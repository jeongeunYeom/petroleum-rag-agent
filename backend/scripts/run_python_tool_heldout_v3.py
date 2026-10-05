"""One complete frozen Agent v4 Python OFF/ON run; no product mutation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evaluation/reference"))
BENCHMARK = ROOT / "evaluation/python_tool_heldout_v3.json"
CATALOG = ROOT / "evaluation/python_tool_heldout_v3_source_catalog.json"
RUBRIC = ROOT / "evaluation/python_tool_heldout_v3_rubric.json"
REFERENCE = ROOT / "evaluation/reference/python_tool_heldout_v3_ground_truth.py"
POLICY = ROOT / "evaluation/PYTHON_TOOL_HELDOUT_V3_POLICY.md"
EXCLUSIONS = ROOT / "evaluation/review/python_tool_heldout_v3_source_exclusions.json"
MANIFEST = ROOT / "evaluation/python_tool_heldout_v3_manifest.json"
DEFAULT_OUTPUT = Path(r"D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v3\raw")
TIMING: ContextVar[dict[str, float] | None] = ContextVar("heldout_v3_timing", default=None)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_and_validate() -> tuple[dict, dict, dict]:
    from python_tool_heldout_v3_ground_truth import validate

    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for key, path in {
        "benchmark_sha256": BENCHMARK,
        "source_catalog_sha256": CATALOG,
        "rubric_sha256": RUBRIC,
        "reference_sha256": REFERENCE,
        "policy_sha256": POLICY,
        "source_exclusions_sha256": EXCLUSIONS,
    }.items():
        if sha256(path) != manifest[key]:
            raise ValueError(f"Frozen asset checksum mismatch: {path}")
    counts = validate()
    if counts["tasks"] != manifest["task_count"] or counts["required_targets"] != manifest["required_numeric_target_count"]:
        raise ValueError("Frozen task/target count mismatch")
    if Counter(task["domain"] for task in benchmark["tasks"]) != manifest["domain_count"]:
        raise ValueError("Frozen domain distribution mismatch")
    if len(catalog) != manifest["source_locator_count"]:
        raise ValueError("Source catalog count mismatch")
    return benchmark, catalog, manifest


def assert_product_unchanged(manifest: dict) -> None:
    base = manifest["product_code_sha"]
    diff = subprocess.check_output(["git", "diff", "--name-only", base, "--", "backend/app", "frontend"], cwd=ROOT, text=True)
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "backend/app", "frontend"], cwd=ROOT, text=True)
    if diff.strip() or dirty.strip():
        raise ValueError(f"Product changed from frozen SHA: {diff.strip()} {dirty.strip()}")
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch != manifest["evaluation_branch"]:
        raise ValueError(f"Wrong evaluation branch: {branch}")


def audit_input_contract(benchmark: dict, catalog: dict, actual: dict) -> dict[str, tuple[int, int, int, int]]:
    """Reject frozen tasks whose required facts cannot be materialized at all.

    This is a pre-run benchmark validity gate, not FormulaSourceRegistry-based
    case selection and not an Agent answer or a product-code modification.
    """
    from app.services.evidence_fact_registry import EvidenceFactRegistry
    from app.services.user_fact_registry import UserFactRegistry

    audit = {}
    for task in benchmark["tasks"]:
        gt = task["ground_truth"]
        expected_user = gt["expected_user_facts"]
        user = UserFactRegistry.from_topic(task["topic"]).records
        user_found = sum(any(math.isclose(record.value, fact["value"], rel_tol=0, abs_tol=1e-9)
                             and record.unit.casefold() == fact["unit"].casefold() for record in user)
                         for fact in expected_user)
        expected_evidence = gt["expected_evidence_facts"]
        evidence = [
            {"evidence_id": source_id, "source_type": "knowledge_base", "text": actual[catalog[source_id]["chunk_id"]][1]}
            for source_id in {fact["source_id"] for fact in expected_evidence}
        ]
        facts = EvidenceFactRegistry.from_evidence(evidence).records
        evidence_found = sum(any(record.source_id == fact["source_id"]
                                 and math.isclose(record.value, fact["value"], rel_tol=0, abs_tol=1e-9)
                                 and record.unit.casefold() == fact["unit"].casefold() for record in facts)
                             for fact in expected_evidence)
        audit[task["task_id"]] = (user_found, len(expected_user), evidence_found, len(expected_evidence))
    return audit


def preflight(benchmark: dict, catalog: dict, manifest: dict) -> None:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    from app.core.config import get_settings

    settings = get_settings()
    kb = manifest["kb"]
    if settings.data_dir.resolve() != Path(kb["data_dir"]).resolve() or settings.vector_db_dir.resolve() != Path(kb["vector_db_dir"]).resolve():
        raise ValueError("DATA_DIR or vector DB differs from frozen manifest")
    if settings.retrieval_mode != kb["retrieval_mode"]:
        raise ValueError("Retrieval mode differs from Agent v4 product default")
    collection = chromadb.PersistentClient(
        path=str(settings.vector_db_dir), settings=ChromaSettings(anonymized_telemetry=settings.anonymized_telemetry)
    ).get_collection(kb["collection"])
    if collection.count() != kb["chunks"]:
        raise ValueError("Real KB chunk count mismatch")
    document_count = len({m.get("document") for m in collection.get(include=["metadatas"])["metadatas"] if m and m.get("document")})
    if document_count != kb["documents"]:
        raise ValueError("Real KB document count mismatch")
    found = collection.get(ids=[s["chunk_id"] for s in catalog.values()], include=["documents", "metadatas"])
    actual = {ident: (metadata, text) for ident, metadata, text in zip(found["ids"], found["metadatas"], found["documents"])}
    for name, source in catalog.items():
        entry = actual.get(source["chunk_id"])
        if not entry or entry[0].get("document") != source["document"] or entry[0].get("page") != source["page"]:
            raise ValueError(f"Source locator invalid: {name}")
    audit = audit_input_contract(benchmark, catalog, actual)
    invalid = {task_id: counts for task_id, counts in audit.items()
               if task_id in {task["task_id"] for task in benchmark["tasks"] if task["python_expected"] == "required"}
               and (counts[0] < counts[1] or counts[2] < counts[3])}
    if invalid:
        raise ValueError(f"Frozen benchmark required-input contract invalid; no Agent run started: {invalid}")
    with urlopen(settings.ollama_base_url.rstrip("/") + "/api/tags", timeout=10) as handle:
        tags = json.load(handle)
    models = {item.get("name") for item in tags.get("models", [])}
    required = {manifest["model_settings"]["research_model"], manifest["model_settings"]["semantic_reviewer_model"]}
    if not required <= models:
        raise ValueError(f"Local models unavailable: {sorted(required - models)}")


def make_request(task: dict, condition: str, settings: dict):
    from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest

    python_on = condition == "python_on"
    return GoalResearchRequest(
        topic=task["topic"], goal=task["goal"], expected_result=task["expected_result"],
        success_criteria=[GoalCriterion.model_validate(item) for item in task["success_criteria"]],
        use_internal=settings["use_internal"], use_external=settings["use_external"],
        engineering_validation=settings["engineering_validation"], model=settings["research_model"],
        internal_top_k=settings["internal_top_k"], external_top_k=settings["external_top_k"],
        temperature=settings["temperature"], seed=settings["seed"],
        max_iterations=settings["max_iterations"], no_progress_patience=settings["no_progress_patience"],
        max_python_calls=settings["max_python_calls"], max_python_attempts_per_call=settings["max_python_attempts_per_call"],
        allow_python_execution=python_on, python_execution_approved=python_on,
        deliverables=[], include_generated_charts=False,
    )


def install_timing_observers() -> None:
    """Transparent in-memory wrappers; no change to product arguments or results."""
    from app.services.goal_python_analysis import GoalPythonAnalysis
    from app.services.goal_tool_planner import GoalToolPlanner
    from app.tools.python_tools import PythonTools

    decide = GoalToolPlanner.decide
    async def timed_decide(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return await decide(self, *args, **kwargs)
        finally:
            if (timing := TIMING.get()) is not None:
                timing["decision_and_plan_seconds"] += time.perf_counter() - started
    GoalToolPlanner.decide = timed_decide

    structured = GoalToolPlanner._structured
    async def timed_structured(self, messages, schema, model, request):
        started = time.perf_counter()
        try:
            return await structured(self, messages, schema, model, request)
        finally:
            if (timing := TIMING.get()) is not None and model.__name__ == "ToolNeedDecision":
                timing["decision_seconds"] += time.perf_counter() - started
    GoalToolPlanner._structured = timed_structured

    for method_name, metric in (("fact_verification_failure", "fact_verification_seconds"), ("formula_verification_failure", "formula_verification_seconds")):
        method = getattr(GoalPythonAnalysis, method_name)
        def timed(plan, evidence, _method=method, _metric=metric):
            started = time.perf_counter()
            try:
                return _method(plan, evidence)
            finally:
                if (timing := TIMING.get()) is not None:
                    timing[_metric] += time.perf_counter() - started
        setattr(GoalPythonAnalysis, method_name, staticmethod(timed))

    generate = GoalPythonAnalysis._generate_code
    async def timed_generate(self, request, plan, outputs, error):
        started = time.perf_counter()
        try:
            return await generate(self, request, plan, outputs, error)
        finally:
            if (timing := TIMING.get()) is not None:
                timing["code_generation_seconds"] += time.perf_counter() - started
    GoalPythonAnalysis._generate_code = timed_generate

    run_python = PythonTools.run_python
    def timed_subprocess(self, code, *, task_id):
        started = time.perf_counter()
        try:
            return run_python(self, code, task_id=task_id)
        finally:
            if (timing := TIMING.get()) is not None:
                timing["subprocess_seconds"] += time.perf_counter() - started
    PythonTools.run_python = timed_subprocess


def save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


async def run_full(benchmark: dict, manifest: dict, output: Path, run_id: str) -> None:
    from app.api.goal_research_routes import cached_goal_research_service

    install_timing_observers()
    agent = cached_goal_research_service().controller
    for condition in ("python_off", "python_on"):
        path = output / f"{condition}.json"
        payload = {"run_id": run_id, "condition": condition, "benchmark_sha256": manifest["benchmark_sha256"],
                   "manifest_sha256": sha256(MANIFEST), "product_code_sha": manifest["product_code_sha"],
                   "complete": False, "results": []}
        save(path, payload)
        for index, task in enumerate(benchmark["tasks"], 1):
            print(f"{condition} {index}/12 {task['task_id']}", flush=True)
            request = make_request(task, condition, manifest["model_settings"])
            timing = {key: 0.0 for key in ("decision_and_plan_seconds", "decision_seconds", "fact_verification_seconds",
                                           "formula_verification_seconds", "code_generation_seconds", "subprocess_seconds")}
            token = TIMING.set(timing)
            started = time.perf_counter()
            try:
                response = await agent.run(f"{run_id}-{task['task_id']}-{condition}", request)
            finally:
                TIMING.reset(token)
            timing["plan_registry_materialization_seconds"] = max(0, timing["decision_and_plan_seconds"] - timing["decision_seconds"])
            payload["results"].append({"task_id": task["task_id"], "condition": condition,
                                       "request": request.model_dump(mode="json"), "response": response.model_dump(mode="json"),
                                       "elapsed_seconds": round(time.perf_counter() - started, 6),
                                       "tool_timing_seconds": {key: round(value, 6) for key, value in timing.items()}})
            save(path, payload)
        payload["complete"] = True
        save(path, payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    benchmark, catalog, manifest = load_and_validate()
    assert_product_unchanged(manifest)
    os.environ["DATA_DIR"] = manifest["kb"]["data_dir"]
    if os.getenv("RETRIEVAL_MODE", "legacy") != manifest["kb"]["retrieval_mode"]:
        raise ValueError("Set RETRIEVAL_MODE to frozen product default")
    os.environ["AGENT_WORKSPACE_DIR"] = str(args.output_root.parent / "workspace")
    preflight(benchmark, catalog, manifest)
    if args.validate_only:
        print(f"validated {len(benchmark['tasks'])} frozen tasks; real KB and local models ready")
        return 0
    if args.output_root.exists() and any(args.output_root.glob("*/python_on.json")):
        raise FileExistsError("A v3 A/B run already exists; never rerun frozen tasks")
    run_id = "python-heldout-v3-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_root / run_id
    if output.exists():
        raise FileExistsError(output)
    print(f"run_id={run_id} output={output}", flush=True)
    try:
        asyncio.run(run_full(benchmark, manifest, output, run_id))
    except BaseException as exc:
        save(output / "incomplete.json", {"run_id": run_id, "error_type": type(exc).__name__,
                                          "message": str(exc), "incomplete": True})
        raise
    print(f"completed={run_id}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
