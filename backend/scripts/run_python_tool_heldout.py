"""Run the frozen Python-tool A-all/B-all held-out comparison exactly once."""

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
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evaluation" / "reference"))
from python_tool_heldout_v1_ground_truth import derive  # noqa: E402


BENCHMARK = ROOT / "evaluation/python_tool_heldout_v1.json"
MANIFEST = ROOT / "evaluation/python_tool_heldout_v1_manifest.json"
POLICY = ROOT / "evaluation/PYTHON_TOOL_HELDOUT_POLICY.md"
CONDITIONS = ("python_off", "python_on")
DEFAULT_OUTPUT = Path(r"D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v1")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_files() -> list[Path]:
    """Previously frozen evaluation files, including retained raw v1 output."""
    files = [*ROOT.glob("evaluation/*heldout*"), *ROOT.glob("evaluation/HELDOUT_POLICY.md"),
             *ROOT.glob("evaluation/AGENTIC_HELDOUT_POLICY.md"),
             *ROOT.glob("evaluation/review/agentic_heldout*"),
             *ROOT.glob("evaluation/review/petroleum_agent*"),
             *ROOT.glob("evaluation/dev/python_tool_execution_diagnostic_v1.json"),
             *Path(r"D:\petroleum-rag-agent\data\evaluation\agentic").glob("agentic-v1-20261004T075903Z/*.json")]
    return sorted({p.resolve() for p in files if p.is_file() and "python_tool_heldout_v1" not in p.name})


def frozen_snapshot() -> dict[str, str]:
    return {str(path): sha256(path) for path in frozen_files()}


def load_and_validate() -> tuple[dict, dict]:
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if sha256(BENCHMARK) != manifest["benchmark_sha256"] or sha256(POLICY) != manifest["rubric_sha256"]:
        raise ValueError("Frozen benchmark or scoring policy checksum mismatch")
    tasks = benchmark["tasks"]
    if len(tasks) != 10 or len({task["task_id"] for task in tasks}) != 10:
        raise ValueError("Expected ten unique tasks")
    if Counter(t["python_expected"] for t in tasks) != {"required": 6, "optional": 2, "not_needed": 2}:
        raise ValueError("Expected 6/2/2 Python categories")
    if Counter(t["domain"] for t in tasks) != manifest["domain_count"]:
        raise ValueError("Domain distribution mismatch")
    if sum(len(t["ground_truth"]["numeric_targets"]) for t in tasks) != manifest["numeric_target_count"]:
        raise ValueError("Numeric target count mismatch")
    if sum(t["python_expected"] == "required" and t["input_origin"] == "user_fact" for t in tasks) != manifest["user_fact_required_count"]:
        raise ValueError("USER_FACT task count mismatch")
    from app.core.run_ids import validate_workspace_run_id
    from app.models.goal_research_schemas import GoalCriterion

    for task in tasks:
        validate_workspace_run_id(f"python-heldout-v1-{task['task_id']}-python_on")
        criteria = [GoalCriterion.model_validate(c) for c in task["success_criteria"]]
        if not 3 <= len(criteria) <= 5 or len({c.criterion_id for c in criteria}) != len(criteria):
            raise ValueError(f"{task['task_id']}: invalid criteria")
        gt = task["ground_truth"]
        if not gt["formula_sources"] or not set(gt["formula_sources"]) <= benchmark["source_catalog"].keys():
            raise ValueError(f"{task['task_id']}: formula evidence unavailable")
        if not set(gt["acceptable_evidence"]) <= benchmark["source_catalog"].keys():
            raise ValueError(f"{task['task_id']}: unknown evidence")
        covered = {claim["criterion_id"] for claim in gt["required_claims"]}
        covered.update(n["criterion_id"] for n in gt["numeric_targets"])
        if {c.criterion_id for c in criteria} != covered:
            raise ValueError(f"{task['task_id']}: unmapped criterion")
        if task["python_expected"] == "not_needed" and gt["numeric_targets"]:
            raise ValueError(f"{task['task_id']}: conceptual task has numeric targets")
        if task["input_origin"] == "user_fact" and not any(ch.isdigit() for ch in task["topic"]):
            raise ValueError(f"{task['task_id']}: missing explicit user numeric inputs")
        computed = derive(task)
        for target in gt["numeric_targets"]:
            if not target["unit"] or target["abs_tolerance"] <= 0:
                raise ValueError(f"{task['task_id']}: missing unit/tolerance")
            if abs(computed[target["name"]] - target["value"]) > target["abs_tolerance"]:
                raise ValueError(f"{task['task_id']}: ground truth mismatch")
    return benchmark, manifest


def make_request(task: dict, condition: str, settings: dict):
    from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest
    if condition not in CONDITIONS:
        raise ValueError(condition)
    on = condition == "python_on"
    return GoalResearchRequest(
        topic=task["topic"], goal=task["goal"], expected_result=task["expected_result"],
        success_criteria=[GoalCriterion.model_validate(c) for c in task["success_criteria"]],
        use_internal=settings["use_internal"], use_external=False,
        engineering_validation=settings["engineering_validation"], model=settings["research_model"],
        temperature=settings["temperature"], seed=settings["seed"],
        internal_top_k=settings["internal_top_k"], external_top_k=settings["external_top_k"],
        max_iterations=settings["max_iterations"], no_progress_patience=settings["no_progress_patience"],
        max_python_calls=settings["max_python_calls"],
        max_python_attempts_per_call=settings["max_python_attempts_per_call"],
        allow_python_execution=on, python_execution_approved=on, deliverables=[],
    )


def _save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


async def run_one(task: dict, condition: str, settings: dict, controller, run_id: str) -> dict:
    request = make_request(task, condition, settings)
    started = time.perf_counter()
    response = await controller.run(f"{run_id}-{task['task_id']}-{condition}", request)
    return {"task_id": task["task_id"], "condition": condition,
            "request": request.model_dump(mode="json"), "response": response.model_dump(mode="json"),
            "elapsed_seconds": round(time.perf_counter() - started, 6)}


def preflight_kb(manifest: dict, benchmark: dict) -> None:
    from app.core.config import get_settings
    settings = get_settings()
    kb = manifest["kb"]
    if settings.data_dir != Path(kb["data_dir"]) or settings.retrieval_mode != kb["retrieval_mode"]:
        raise ValueError("DATA_DIR/retrieval mode does not match frozen production setting")
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    collection = chromadb.PersistentClient(
        path=str(settings.vector_db_dir),
        settings=ChromaSettings(anonymized_telemetry=settings.anonymized_telemetry),
    ).get_collection(kb["collection"])
    if collection.count() != kb["chunks"]:
        raise ValueError("Real KB chunk count mismatch")
    metadata = collection.get(include=["metadatas"])["metadatas"]
    if len({m.get("document") for m in metadata if m and m.get("document")}) != kb["documents"]:
        raise ValueError("Real KB document count mismatch")
    sources = benchmark["source_catalog"]
    located = collection.get(ids=[s["chunk_id"] for s in sources.values()], include=["metadatas", "documents"])
    actual = dict(zip(located["ids"], zip(located["metadatas"], located["documents"])))
    for source_id, source in sources.items():
        item = actual.get(source["chunk_id"])
        if not item or item[0].get("document") != source["document"] or item[0].get("page") != source["page"]:
            raise ValueError(f"KB locator mismatch: {source_id}")
    rft = benchmark["tasks"][4]["ground_truth"]["input_values"]
    rft_text = actual[sources["W81"]["chunk_id"]][1]
    if any(str(value) not in rft_text for column in rft.values() for value in column):
        raise ValueError("RFT numeric facts not present in cited KB page")
    with urlopen(settings.ollama_base_url.rstrip("/") + "/api/tags", timeout=10) as handle:
        names = {item["name"] for item in json.load(handle).get("models", [])}
    if not {manifest["model_settings"]["research_model"], manifest["model_settings"]["semantic_reviewer_model"]} <= names:
        raise ValueError("Required local model unavailable")


async def run_full(benchmark: dict, manifest: dict, output: Path, run_id: str) -> None:
    from app.api.goal_research_routes import cached_goal_research_service
    controller = cached_goal_research_service().controller
    before = frozen_snapshot()
    _save(output / "raw/frozen_assets_before.json", before)
    for condition in CONDITIONS:
        path = output / f"{condition}.json"
        payload = {"run_id": run_id, "condition": condition, "benchmark_sha256": manifest["benchmark_sha256"],
                   "manifest_sha256": sha256(MANIFEST), "rubric_sha256": manifest["rubric_sha256"],
                   "product_code_sha": manifest["product_code_sha"], "evaluation_commit_sha": subprocess.check_output(
                       ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                   "complete": False, "results": []}
        _save(path, payload)
        for index, task in enumerate(benchmark["tasks"], 1):
            print(f"{condition} {index}/10 {task['task_id']}", flush=True)
            row = await run_one(task, condition, manifest["model_settings"], controller, run_id)
            payload["results"].append(row)
            _save(path, payload)
        payload["complete"] = True
        _save(path, payload)
    after = frozen_snapshot()
    _save(output / "raw/frozen_assets_after.json", after)
    if before != after:
        raise RuntimeError("A previously frozen evaluation asset changed during this run")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    benchmark, manifest = load_and_validate()
    os.environ.setdefault("DATA_DIR", manifest["kb"]["data_dir"])
    os.environ.setdefault("RETRIEVAL_MODE", manifest["kb"]["retrieval_mode"])
    if args.validate_only:
        preflight_kb(manifest, benchmark)
        print(f"validated tasks={len(benchmark['tasks'])} targets={manifest['numeric_target_count']} mode={manifest['kb']['retrieval_mode']}")
        return 0
    run_id = "python-heldout-v1-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir / "raw" / run_id
    if output.exists():
        raise FileExistsError(output)
    os.environ["AGENT_WORKSPACE_DIR"] = str(output / "workspace")
    preflight_kb(manifest, benchmark)
    print(f"run_id={run_id} output={output}", flush=True)
    try:
        asyncio.run(run_full(benchmark, manifest, output, run_id))
    except Exception as exc:
        _save(output / "abort.json", {"run_id": run_id, "error_type": type(exc).__name__, "reason": str(exc),
                                     "timestamp": datetime.now(timezone.utc).isoformat()})
        raise
    print(f"completed={run_id}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
