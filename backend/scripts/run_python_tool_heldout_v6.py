"""Run exactly one frozen, OFF-all-then-ON-all paired held-out evaluation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/scripts")]
from freeze_python_tool_heldout_v6 import FILES  # noqa: E402
from preflight_python_tool_heldout_v6 import PRODUCT_SHA, digest, load, validate_ground_truth_consistency  # noqa: E402

MANIFEST = ROOT / "evaluation/python_tool_heldout_v6_manifest.json"
BENCHMARK = FILES["benchmark"]
CATALOG = FILES["source_catalog"]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def load_frozen() -> tuple[dict, dict]:
    manifest = load(MANIFEST)
    benchmark = load(BENCHMARK)
    preflight = load(FILES["preflight"])
    audit = load(FILES["gt_consistency"])
    if manifest["product_code_sha"] != PRODUCT_SHA or benchmark["product_code_sha"] != PRODUCT_SHA:
        raise ValueError("Product SHA identity mismatch")
    if manifest["preflight_status"] != "PASS" or preflight["status"] != "PASS" or audit["status"] != "PASS" or audit["conflict_count"]:
        raise ValueError("Frozen preflight or independent GT gate failed")
    if any(preflight["calls"].values()) or preflight["errors"]:
        raise ValueError("Preflight must have zero forbidden calls and errors")
    if preflight["hashes"]["benchmark_draft_sha256"] != manifest["benchmark_sha256"]:
        raise ValueError("Audited benchmark hash mismatch")
    freeze_sha = manifest.get("freeze_commit_sha")
    if not freeze_sha or len(freeze_sha) != 40:
        raise ValueError("Freeze SHA not recorded in manifest")
    if git("rev-parse", f"{freeze_sha}^{{commit}}") != freeze_sha:
        raise ValueError("Freeze commit does not exist")
    subprocess.run(["git", "merge-base", "--is-ancestor", PRODUCT_SHA, "HEAD"], cwd=ROOT, check=True)
    subprocess.run(["git", "merge-base", "--is-ancestor", freeze_sha, "HEAD"], cwd=ROOT, check=True)
    if git("diff", "--name-only", PRODUCT_SHA, "HEAD", "--", "backend/app", "frontend"):
        raise ValueError("Product application files changed after pinned product SHA")
    for label, p in FILES.items():
        if digest(p) != manifest[label + "_sha256"]:
            raise ValueError(f"Frozen {label} hash mismatch")
        relative = p.relative_to(ROOT).as_posix()
        frozen_bytes = subprocess.check_output(["git", "show", f"{freeze_sha}:{relative}"], cwd=ROOT)
        frozen_hash = hashlib.sha256(frozen_bytes.replace(b"\r\n", b"\n")).hexdigest()
        if frozen_hash != manifest[label + "_sha256"]:
            raise ValueError(f"Frozen {label} differs from freeze commit")
    references = load(FILES["reference_outputs"])
    tasks = benchmark["tasks"]
    if len(tasks) != 12 or Counter(t["python_expected"] for t in tasks) != manifest["python_need_count"]:
        raise ValueError("Frozen task count/distribution mismatch")
    if Counter(t["domain"] for t in tasks) != manifest["domain_count"]:
        raise ValueError("Frozen domain count mismatch")
    for task in tasks:
        conflicts = validate_ground_truth_consistency(task, references[task["task_id"]])
        if conflicts:
            raise ValueError(f"GT consistency failed before task 1: {task['task_id']} {conflicts}")
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
        raise FileNotFoundError(f"Real ChromaDB missing: {db}")
    collection = chromadb.PersistentClient(path=str(configured.vector_db_dir), settings=ChromaSettings(anonymized_telemetry=False)).get_collection(kb["collection"])
    if collection.count() != kb["chunks"]:
        raise ValueError("Real collection count mismatch")
    documents = collection.get(include=["metadatas"])["metadatas"]
    if len({m["document"] for m in documents if m and m.get("document")}) != kb["documents"]:
        raise ValueError("Real document count mismatch")
    catalog = load(CATALOG)
    found = collection.get(ids=[s["chunk_id"] for s in catalog.values()], include=["metadatas", "documents"])
    by_id = {key: (meta, text) for key, meta, text in zip(found["ids"], found["metadatas"], found["documents"])}
    for key, source in catalog.items():
        actual = by_id.get(source["chunk_id"])
        if not actual or actual[0].get("document") != source["document"] or actual[0].get("page") != source["page"] or hashlib.sha256(actual[1].encode()).hexdigest() != source["exact_source_excerpt_sha256"]:
            raise ValueError(f"Frozen source moved or changed: {key}")
    with urlopen(configured.ollama_base_url.rstrip("/") + "/api/tags", timeout=10) as handle:
        models = json.load(handle).get("models", [])
    for model in (manifest["model_settings"]["research_model"], manifest["model_settings"]["review_model"]):
        if not any(item.get("name") == model for item in models):
            raise ValueError(f"Required local model unavailable: {model}")


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def infra_error(exc: Exception) -> bool:
    return isinstance(exc, (ConnectionError, TimeoutError, OSError)) or any(
        marker in str(exc).casefold() for marker in ("ollama unavailable", "connection refused", "chroma unavailable", "disk full"))


async def run_full(benchmark: dict, manifest: dict, output: Path) -> None:
    from app.api.goal_research_routes import cached_goal_research_service

    controller = cached_goal_research_service().controller
    run_id = "python-tool-v6-first-ab-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for condition in manifest["conditions"]:
        name = condition["name"]
        target = output / f"{name}.json"
        payload = {"run_id": run_id, "condition": name, "benchmark_sha256": manifest["benchmark_sha256"],
                   "product_code_sha": PRODUCT_SHA, "freeze_commit_sha": manifest["freeze_commit_sha"],
                   "complete": False, "results": []}
        save(target, payload)
        for index, task in enumerate(benchmark["tasks"], 1):
            print(f"{name} {index}/12 {task['task_id']}", flush=True)
            request = make_request(task, condition, manifest["model_settings"])
            started = time.perf_counter()
            row = {"task_id": task["task_id"], "condition": name, "request": request.model_dump(mode="json")}
            try:
                response = await controller.run(f"{run_id}-{task['task_id']}-{name}", request)
                row["response"] = response.model_dump(mode="json")
                row["product_exception"] = None
            except Exception as exc:
                if infra_error(exc):
                    payload["infrastructure_error"] = f"{type(exc).__name__}: {exc}"
                    save(target, payload)
                    raise RuntimeError("Infrastructure failure; partial outputs preserved; no selective rerun") from exc
                row["response"] = None
                row["product_exception"] = f"{type(exc).__name__}: {exc}"
            row["elapsed_seconds"] = round(time.perf_counter() - started, 6)
            payload["results"].append(row)
            save(target, payload)
        payload["complete"] = True
        save(target, payload)
    print(f"COMPLETE {run_id} {output}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    benchmark, manifest = load_frozen()
    for condition in manifest["conditions"]:
        for task in benchmark["tasks"]:
            make_request(task, condition, manifest["model_settings"])
    if args.validate_only:
        print("Frozen 12+12 requests and SHA integrity validated; zero Agent calls")
        return 0
    os.environ["DATA_DIR"] = manifest["kb"]["data_dir"]
    os.environ["RETRIEVAL_MODE"] = manifest["kb"]["retrieval_mode"]
    check_environment(manifest)
    raw_root = Path(manifest["kb"]["data_dir"]) / "evaluation/python_tool_heldout_v6/raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    if any(raw_root.iterdir()):
        raise FileExistsError("First A/B run or partial attempt already exists; no rerun permitted")
    output = raw_root / ("first-ab-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    output.mkdir()
    print(f"OUTPUT {output}", flush=True)
    asyncio.run(run_full(benchmark, manifest, output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
