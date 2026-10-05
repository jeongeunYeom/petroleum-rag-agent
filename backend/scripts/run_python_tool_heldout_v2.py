"""Frozen, one-pass A/B evaluation of the unchanged GoalResearchAgent v3."""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import hashlib
import importlib.util
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
EVAL = ROOT / "evaluation"
BENCHMARK = EVAL / "python_tool_heldout_v2.json"
MANIFEST = EVAL / "python_tool_heldout_v2_manifest.json"
RUBRIC = EVAL / "python_tool_heldout_v2_rubric.json"
REFERENCE = EVAL / "reference/python_tool_heldout_v2_ground_truth.py"
POLICY = EVAL / "PYTHON_TOOL_HELDOUT_V2_POLICY.md"
LOCK = EVAL / "python_tool_heldout_v2_frozen_assets.sha256"
CONDITIONS = ("python_off", "python_on")
TIMING = contextvars.ContextVar("heldout_v2_tool_timing", default=None)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reference():
    spec = importlib.util.spec_from_file_location("python_tool_heldout_v2_ground_truth", REFERENCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_and_validate(*, require_lock: bool = True) -> tuple[dict, dict]:
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rubric = json.loads(RUBRIC.read_text(encoding="utf-8"))
    for path, key in ((BENCHMARK, "benchmark_sha256"), (RUBRIC, "rubric_sha256"),
                      (REFERENCE, "reference_sha256"), (POLICY, "policy_sha256")):
        if sha256(path) != manifest[key]:
            raise ValueError(f"Frozen checksum mismatch: {path.name}")
    if require_lock:
        locked = {name: digest for digest, name in (line.split("  ", 1) for line in LOCK.read_text(encoding="utf-8").splitlines())}
        if locked.get("manifest") != sha256(MANIFEST):
            raise ValueError("Frozen manifest checksum mismatch")
    tasks = benchmark["tasks"]
    if benchmark["benchmark_id"] != rubric["rubric_id"].removesuffix("_rubric"):
        raise ValueError("Benchmark/rubric mismatch")
    if len(tasks) != manifest["task_count"] or len({t["task_id"] for t in tasks}) != len(tasks):
        raise ValueError("Task count or duplicate IDs")
    if Counter(t["domain"] for t in tasks) != manifest["domain_count"]:
        raise ValueError("Domain distribution")
    if Counter(t["python_expected"] for t in tasks) != manifest["python_expected_count"]:
        raise ValueError("Python class distribution")
    ref = _reference()
    user_required = kb_required = target_count = required_targets = fact_count = 0
    sources = benchmark["source_catalog"]
    for task in tasks:
        gt = task["ground_truth"]
        criteria = task["success_criteria"]
        ids = {item["criterion_id"] for item in criteria}
        if not 3 <= len(criteria) <= 5 or len(ids) != len(criteria):
            raise ValueError(f"{task['task_id']}: criteria")
        mapped = set()
        for claim in gt["required_claims"]:
            mapped.add(claim["criterion_id"])
            if not set(claim["source_ids"]) <= sources.keys():
                raise ValueError(f"{task['task_id']}: claim source")
        expected = ref.derive(task)
        for target in gt["numeric_targets"]:
            mapped.add(target["criterion_id"])
            if not target["unit"] or target.get("abs_tolerance", 0) <= 0:
                raise ValueError(f"{task['task_id']}: target unit/tolerance")
            rounding_epsilon = max(1e-4, abs(target["value"]) * 1e-10)
            if target["name"] not in expected or abs(expected[target["name"]] - target["value"]) > rounding_epsilon:
                raise ValueError(f"{task['task_id']}: independent GT mismatch: {target['name']}")
        if mapped != ids or not set(gt["formula_sources"] + gt["acceptable_evidence"]) <= sources.keys():
            raise ValueError(f"{task['task_id']}: uncovered criterion or source")
        if gt["expected_user_facts"] != ref.expected_user_facts(task):
            raise ValueError(f"{task['task_id']}: USER fact GT mismatch")
        if gt["expected_tool_behavior"]["class"] != task["python_expected"]:
            raise ValueError(f"{task['task_id']}: expected tool class")
        if task["python_expected"] == "not_needed" and (gt["numeric_targets"] or any(
                word in c["description"].lower() for c in criteria for word in ("calculate", "compute"))):
            raise ValueError(f"{task['task_id']}: quantitative not-needed criterion")
        if task["python_expected"] == "required":
            required_targets += len(gt["numeric_targets"])
            user_required += task["input_provenance_expected"] == "user_fact_plus_kb_formula"
            kb_required += task["input_provenance_expected"] == "kb_numeric"
            if len(gt["numeric_targets"]) < 3:
                raise ValueError(f"{task['task_id']}: insufficient numeric targets")
        target_count += len(gt["numeric_targets"])
        fact_count += len(gt["expected_user_facts"])
    if (user_required, kb_required, target_count, required_targets, fact_count) != tuple(manifest[k] for k in (
            "user_fact_required_count", "kb_numeric_required_count", "numeric_target_count",
            "required_numeric_target_count", "expected_user_fact_count")):
        raise ValueError("Manifest task counts mismatch")
    if len(sources) != manifest["source_locator_count"] or required_targets < 35 or user_required < 6 or kb_required < 2:
        raise ValueError("Insufficient frozen coverage")
    return benchmark, manifest


def make_request(task: dict, condition: str, settings: dict):
    from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest

    if condition not in CONDITIONS:
        raise ValueError(condition)
    python_on = condition == "python_on"
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
        allow_python_execution=python_on, python_execution_approved=python_on,
        deliverables=[], include_generated_charts=False,
    )


def _save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _assert_product_unchanged(manifest: dict) -> None:
    base = manifest["product_code_sha"]
    diff = subprocess.check_output(["git", "diff", "--name-only", base, "--", "backend/app", "frontend"], cwd=ROOT, text=True)
    if diff.strip():
        raise ValueError(f"Product code changed from frozen SHA: {diff.strip()}")
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "backend/app", "frontend"], cwd=ROOT, text=True)
    if dirty.strip():
        raise ValueError(f"Uncommitted product changes: {dirty.strip()}")


def preflight_kb_and_models(benchmark: dict, manifest: dict) -> None:
    from app.core.config import get_settings
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    settings = get_settings()
    kb = manifest["kb"]
    if settings.data_dir.resolve() != Path(kb["data_dir"]).resolve() or settings.vector_db_dir.resolve() != Path(kb["vector_db_dir"]).resolve():
        raise ValueError("DATA_DIR/vector DB differs from frozen manifest")
    if settings.retrieval_mode != kb["retrieval_mode"]:
        raise ValueError("RETRIEVAL_MODE differs from product default")
    collection = chromadb.PersistentClient(
        path=str(settings.vector_db_dir), settings=ChromaSettings(anonymized_telemetry=settings.anonymized_telemetry)
    ).get_collection(kb["collection"])
    if collection.count() != kb["chunks"]:
        raise ValueError("Real KB chunk count mismatch")
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    if len({m.get("document") for m in metadatas if m and m.get("document")}) != kb["documents"]:
        raise ValueError("Real KB document count mismatch")
    catalog = benchmark["source_catalog"]
    found = collection.get(ids=[s["chunk_id"] for s in catalog.values()], include=["documents", "metadatas"])
    actual = {key: (meta, text) for key, meta, text in zip(found["ids"], found["metadatas"], found["documents"])}
    for key, source in catalog.items():
        entry = actual.get(source["chunk_id"])
        if not entry or entry[0].get("document") != source["document"] or entry[0].get("page") != source["page"] or source["excerpt_check"] not in entry[1]:
            raise ValueError(f"KB source locator mismatch: {key}")
    # Numeric GT rows must exist in the actual source, not just in the frozen fixture.
    for task in benchmark["tasks"]:
        if task["input_provenance_expected"] == "kb_numeric":
            source = catalog[task["ground_truth"]["acceptable_evidence"][0]]
            content = actual[source["chunk_id"]][1]
            for rows in task["ground_truth"]["input_values"].values():
                for row in rows:
                    for value in row.values():
                        if str(value) not in content:
                            raise ValueError(f"KB numeric source lacks {value}: {task['task_id']}")
    with urlopen(settings.ollama_base_url.rstrip("/") + "/api/tags", timeout=10) as handle:
        tags = json.load(handle)
    available = {x.get("name") for x in tags.get("models", [])}
    if not {manifest["model_settings"]["research_model"], manifest["model_settings"]["semantic_reviewer_model"]} <= available:
        raise ValueError("Frozen local model unavailable")


async def run_one(task: dict, condition: str, settings: dict, agent, run_id: str) -> dict:
    request = make_request(task, condition, settings)
    timing = {name: 0.0 for name in ("decision", "plan", "verification", "code_generation", "subprocess")}
    token = TIMING.set(timing)
    started = time.perf_counter()
    try:
        response = await agent.run(f"{run_id}-{task['task_id']}-{condition}", request)
    finally:
        TIMING.reset(token)
    return {"task_id": task["task_id"], "condition": condition,
            "request": request.model_dump(mode="json"), "response": response.model_dump(mode="json"),
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "tool_timing_seconds": {key: round(value, 6) for key, value in timing.items()}}


def install_timing_instrumentation() -> None:
    """Observe stage times without changing tool arguments, results, or product files."""
    from app.services.goal_python_analysis import GoalPythonAnalysis
    from app.services.goal_tool_planner import GoalToolPlanner
    from app.tools.python_tools import PythonTools

    structured = GoalToolPlanner._structured
    async def timed_structured(self, messages, schema, model, request):
        started = time.perf_counter()
        try:
            return await structured(self, messages, schema, model, request)
        finally:
            timing = TIMING.get()
            if timing is not None:
                timing["decision" if model.__name__ == "ToolNeedDecision" else "plan"] += time.perf_counter() - started
    GoalToolPlanner._structured = timed_structured

    verify = GoalPythonAnalysis.verification_failure_detail
    def timed_verify(plan, evidence):
        started = time.perf_counter()
        try:
            return verify(plan, evidence)
        finally:
            timing = TIMING.get()
            if timing is not None:
                timing["verification"] += time.perf_counter() - started
    GoalPythonAnalysis.verification_failure_detail = staticmethod(timed_verify)

    generate = GoalPythonAnalysis._generate_code
    async def timed_generate(self, request, plan, outputs, error):
        started = time.perf_counter()
        try:
            return await generate(self, request, plan, outputs, error)
        finally:
            timing = TIMING.get()
            if timing is not None:
                timing["code_generation"] += time.perf_counter() - started
    GoalPythonAnalysis._generate_code = timed_generate

    subprocess_run = PythonTools.run_python
    def timed_subprocess(self, code, *, task_id):
        started = time.perf_counter()
        try:
            return subprocess_run(self, code, task_id=task_id)
        finally:
            timing = TIMING.get()
            if timing is not None:
                timing["subprocess"] += time.perf_counter() - started
    PythonTools.run_python = timed_subprocess


async def run_full(benchmark: dict, manifest: dict, output: Path, run_id: str) -> None:
    from app.api.goal_research_routes import cached_goal_research_service

    install_timing_instrumentation()
    agent = cached_goal_research_service().controller
    for condition in CONDITIONS:
        path = output / f"{condition}.json"
        payload = {"run_id": run_id, "condition": condition, "benchmark_sha256": manifest["benchmark_sha256"],
                   "manifest_sha256": sha256(MANIFEST), "product_code_sha": manifest["product_code_sha"],
                   "complete": False, "results": []}
        _save(path, payload)
        for index, task in enumerate(benchmark["tasks"], 1):
            print(f"{condition} {index}/12 {task['task_id']}", flush=True)
            row = await run_one(task, condition, manifest["model_settings"], agent, run_id)
            payload["results"].append(row)
            _save(path, payload)
        payload["complete"] = True
        _save(path, payload)


async def run_smoke(manifest: dict, output: Path) -> None:
    """A distinct trivial fixture; never sends one of the held-out tasks."""
    from app.api.goal_research_routes import cached_goal_research_service
    from score_python_tool_heldout_v2 import aggregate_iterations

    task = {"task_id": "SYNTHETIC-SMOKE", "topic": "Synthetic arithmetic check: x=7, y=5.",
            "goal": "Add x and y and state that no petroleum-engineering inference follows from this toy example.",
            "expected_result": None,
            "success_criteria": [{"criterion_id": "C1", "description": "Give the arithmetic sum", "required": True},
                                 {"criterion_id": "C2", "description": "Do not infer petroleum properties", "required": True}]}
    settings = {**manifest["model_settings"], "max_iterations": 1}
    agent = cached_goal_research_service().controller
    rows = []
    for condition in CONDITIONS:
        row = await run_one(task, condition, settings, agent, "python-heldout-v2-synthetic-smoke")
        row["parsed_trace"] = aggregate_iterations(row["response"])
        rows.append(row)
    _save(output, {"fixture": "synthetic-not-heldout", "results": rows})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path(r"D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v2\raw"))
    args = parser.parse_args()
    benchmark, manifest = load_and_validate()
    _assert_product_unchanged(manifest)
    if args.validate_only:
        print(f"validated {len(benchmark['tasks'])} frozen tasks; manifest={sha256(MANIFEST)}")
        return 0
    if not args.smoke and args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError("A full run already exists; this benchmark cannot be rerun")
    os.environ["DATA_DIR"] = manifest["kb"]["data_dir"]
    if os.getenv("RETRIEVAL_MODE", "legacy") != manifest["kb"]["retrieval_mode"]:
        raise ValueError("Set RETRIEVAL_MODE to frozen product default")
    os.environ["AGENT_WORKSPACE_DIR"] = str(args.output_dir.parent / "workspace")
    preflight_kb_and_models(benchmark, manifest)
    if args.smoke:
        smoke_path = args.output_dir.parent / "synthetic_smoke.json"
        if smoke_path.exists():
            raise FileExistsError("Synthetic smoke already exists")
        asyncio.run(run_smoke(manifest, smoke_path))
        print(f"synthetic_smoke={smoke_path}", flush=True)
        return 0
    run_id = "python-heldout-v2-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir / run_id
    if output.exists():
        raise FileExistsError(output)
    print(f"run_id={run_id} output={output}", flush=True)
    try:
        asyncio.run(run_full(benchmark, manifest, output, run_id))
    except BaseException as exc:
        _save(output / "incomplete.json", {"run_id": run_id, "error_type": type(exc).__name__,
                                           "message": str(exc), "incomplete": True})
        raise
    print(f"completed={run_id}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
