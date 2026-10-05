"""One immutable OFF-then-ON run against the frozen v4 product."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
MANIFEST = ROOT / "evaluation/python_tool_heldout_v3r1_manifest.json"
BENCHMARK = ROOT / "evaluation/python_tool_heldout_v3r1.json"
RUBRIC = ROOT / "evaluation/python_tool_heldout_v3r1_rubric.json"
CATALOG = ROOT / "evaluation/python_tool_heldout_v3r1_source_catalog.json"
PREFLIGHT = ROOT / "evaluation/review/python_tool_heldout_v3r1_preflight.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen() -> tuple[dict, dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    for label, path in (("benchmark", BENCHMARK), ("rubric", RUBRIC), ("source_catalog", CATALOG), ("preflight", PREFLIGHT)):
        if digest(path) != manifest[label + "_sha256"]:
            raise ValueError(f"Frozen {label} hash mismatch")
    if manifest["preflight_status"] != "PASS" or manifest["preflight_llm_calls"] != 0 or preflight["status"] != "PASS":
        raise ValueError("Pre-freeze contract audit did not pass without LLM")
    if preflight["hashes"]["benchmark_draft_sha256"] != manifest["benchmark_sha256"]:
        raise ValueError("Audited benchmark differs from frozen benchmark")
    tasks = benchmark["tasks"]
    if len(tasks) != manifest["task_count"] or len({t["task_id"] for t in tasks}) != len(tasks):
        raise ValueError("Frozen task identity mismatch")
    if Counter(t["python_expected"] for t in tasks) != manifest["python_need_count"]:
        raise ValueError("Python-need distribution mismatch")
    if Counter(t["domain"] for t in tasks) != manifest["domain_count"]:
        raise ValueError("Domain distribution mismatch")
    return benchmark, manifest


def make_request(task: dict, condition: dict, settings: dict):
    from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest

    return GoalResearchRequest(
        topic=task["topic"], goal=task["goal"], expected_result=task["expected_result"],
        success_criteria=[GoalCriterion.model_validate(c) for c in task["success_criteria"]],
        use_internal=settings["use_internal"], use_external=settings["use_external"],
        engineering_validation=settings["engineering_validation"], model=settings["research_model"],
        internal_top_k=settings["internal_top_k"], external_top_k=settings["external_top_k"],
        temperature=settings["temperature"], seed=settings["seed"],
        max_iterations=settings["max_iterations"], no_progress_patience=settings["no_progress_patience"],
        max_python_calls=settings["max_python_calls"],
        max_python_attempts_per_call=settings["max_python_attempts_per_call"],
        allow_python_execution=condition["allow_python_execution"],
        python_execution_approved=condition["python_execution_approved"],
        deliverables=[], include_generated_charts=False,
    )


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def check_environment(manifest: dict) -> None:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    from app.core.config import get_settings

    configured = get_settings()
    kb = manifest["kb"]
    if configured.data_dir != Path(kb["data_dir"]) or configured.retrieval_mode != kb["retrieval_mode"]:
        raise ValueError("DATA_DIR or RETRIEVAL_MODE differs from frozen condition")
    db = configured.vector_db_dir / "chroma.sqlite3"
    if not db.is_file():
        raise FileNotFoundError(f"Real Chroma DB missing: {db}")
    collection = chromadb.PersistentClient(
        path=str(configured.vector_db_dir),
        settings=ChromaSettings(anonymized_telemetry=configured.anonymized_telemetry),
    ).get_collection(kb["collection"])
    if collection.count() != kb["chunks"]:
        raise ValueError("Real collection count mismatch")
    actual_documents = collection.get(include=["metadatas"])["metadatas"]
    if len({m.get("document") for m in actual_documents if m and m.get("document")}) != kb["documents"]:
        raise ValueError("Real document count mismatch")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    located = collection.get(ids=[s["chunk_id"] for s in catalog.values()], include=["metadatas"])
    by_id = dict(zip(located["ids"], located["metadatas"]))
    if any(by_id.get(s["chunk_id"], {}).get("document") != s["document"] or
           by_id.get(s["chunk_id"], {}).get("page") != s["page"] for s in catalog.values()):
        raise ValueError("Frozen source locator changed")
    with urlopen(configured.ollama_base_url.rstrip("/") + "/api/tags", timeout=10) as handle:
        models = json.load(handle).get("models", [])
    if not any(item.get("name") == manifest["model_settings"]["research_model"] for item in models):
        raise ValueError("qwen3:8b unavailable")


async def run_full(benchmark: dict, manifest: dict, output: Path) -> None:
    from app.api.goal_research_routes import cached_goal_research_service

    controller = cached_goal_research_service().controller
    run_id = "python-tool-v3r1-first-ab-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for condition in manifest["conditions"]:  # frozen order: all OFF, then all ON
        name = condition["name"]
        path = output / f"{name}.json"
        payload = {"run_id": run_id, "condition": name, "benchmark_sha256": manifest["benchmark_sha256"],
                   "product_code_sha": manifest["product_code_sha"], "freeze_commit_sha": manifest["freeze_commit_sha"],
                   "complete": False, "results": []}
        save(path, payload)
        for index, task in enumerate(benchmark["tasks"], 1):
            print(f"{name} {index}/12 {task['task_id']}", flush=True)
            request = make_request(task, condition, manifest["model_settings"])
            started = time.perf_counter()
            row = {"task_id": task["task_id"], "condition": name, "request": request.model_dump(mode="json")}
            try:
                response = await controller.run(f"{run_id}-{task['task_id']}-{name}", request)
                row["response"] = response.model_dump(mode="json")
                row["product_exception"] = None
            except Exception as exc:  # Product exceptions remain scored; never selectively rerun.
                row["response"] = None
                row["product_exception"] = f"{type(exc).__name__}: {exc}"
            row["elapsed_seconds"] = round(time.perf_counter() - started, 6)
            payload["results"].append(row)
            save(path, payload)
        payload["complete"] = True
        save(path, payload)
    print(f"COMPLETED {run_id}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(r"D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v3r1\first_full_ab"))
    args = parser.parse_args()
    benchmark, manifest = load_frozen()
    for condition in manifest["conditions"]:
        for task in benchmark["tasks"]:
            make_request(task, condition, manifest["model_settings"])
    if args.validate_only:
        print("Frozen 12+12 requests validated; no Agent call")
        return 0
    os.environ["DATA_DIR"] = manifest["kb"]["data_dir"]
    os.environ["RETRIEVAL_MODE"] = manifest["kb"]["retrieval_mode"]
    check_environment(manifest)
    if args.output_dir.exists():
        raise FileExistsError(f"One complete run only; output already exists: {args.output_dir}")
    args.output_dir.mkdir(parents=True)
    print(f"OUTPUT {args.output_dir}", flush=True)
    asyncio.run(run_full(benchmark, manifest, args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
