"""Run one complete, frozen A/B/C agentic comparison; never tune product code here."""

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
BENCHMARK = ROOT / "evaluation/agentic_heldout_v1.json"
RUBRIC = ROOT / "evaluation/agentic_heldout_v1_rubric.json"
MANIFEST = ROOT / "evaluation/agentic_heldout_v1_manifest.json"
CONDITIONS = ("single_shot", "goal_agent", "full_agent")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_and_validate() -> tuple[dict, dict]:
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if sha256(BENCHMARK) != manifest["benchmark_sha256"]:
        raise ValueError("Frozen benchmark checksum mismatch")
    if sha256(RUBRIC) != manifest["rubric_sha256"]:
        raise ValueError("Frozen rubric checksum mismatch")
    tasks = benchmark["tasks"]
    if len(tasks) != manifest["task_count"] or len({t["task_id"] for t in tasks}) != len(tasks):
        raise ValueError("Task count or unique IDs mismatch")
    if Counter(t["domain"] for t in tasks) != manifest["domain_count"]:
        raise ValueError("Domain distribution mismatch")
    if Counter(t["task_type"] for t in tasks) != manifest["task_type_count"]:
        raise ValueError("Task type distribution mismatch")
    if sum(len(t["success_criteria"]) for t in tasks) != manifest["criteria_count"]:
        raise ValueError("Criteria count mismatch")
    sources = benchmark["source_catalog"]
    for task in tasks:
        criteria = task["success_criteria"]
        criterion_ids = [c["criterion_id"] for c in criteria]
        if not 3 <= len(criteria) <= 5 or len(set(criterion_ids)) != len(criteria):
            raise ValueError(f"{task['task_id']}: invalid criteria")
        gt = task["ground_truth"]
        covered = set()
        for claim in gt["claims"]:
            if not claim["source_ids"] or not set(claim["source_ids"]) <= sources.keys():
                raise ValueError(f"{task['task_id']}: unlocated GT claim")
            covered.update(claim["criterion_ids"])
        for numeric in gt["numeric_targets"]:
            if numeric["abs_tolerance"] <= 0 or not numeric["unit"] or not numeric["formula"]:
                raise ValueError(f"{task['task_id']}: invalid numeric target")
            covered.add(numeric["criterion_id"])
        if not set(criterion_ids) <= covered:
            raise ValueError(f"{task['task_id']}: criterion without GT")
        if not set(gt["required_evidence"]) <= sources.keys():
            raise ValueError(f"{task['task_id']}: unlocated evidence")
        if task["task_type"] == "figure_integrated":
            figures = [gt["figure"]] if "figure" in gt else gt.get("figures", [])
            if not figures or not all(Path(f["image_file"]).is_file() for f in figures):
                raise ValueError(f"{task['task_id']}: missing figure")
    for figure in manifest["figure_assets"]:
        if sha256(Path(figure["image_file"])) != figure["sha256"]:
            raise ValueError(f"Figure changed: {figure['image_file']}")
    return benchmark, manifest


def single_shot_query(task: dict) -> str:
    criteria = "\n".join(f"{c['criterion_id']}: {c['description']}" for c in task["success_criteria"])
    return (
        f"Research topic: {task['topic']}\n"
        f"Research goal: {task['goal']}\n"
        f"Expected hypothesis: {task['expected_result'] or 'none'}\n"
        f"Required criteria:\n{criteria}\n"
        "Using only available evidence, produce the best supported final research result. "
        "If evidence contradicts the expected hypothesis, state that. "
        "If evidence is insufficient, do not invent a result."
    )


def make_request(task: dict, condition: str, settings: dict):
    from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest
    from app.models.research_schemas import ResearchRequest

    common = dict(
        use_internal=settings["use_internal"],
        use_external=settings["use_external"],
        engineering_validation=settings["engineering_validation"],
        model=settings["research_model"],
        internal_top_k=settings["internal_top_k"],
        external_top_k=settings["external_top_k"],
        temperature=settings["temperature"],
        seed=settings["seed"],
    )
    if condition == "single_shot":
        return ResearchRequest(query=single_shot_query(task), **common)
    if condition not in CONDITIONS:
        raise ValueError(condition)
    python_on = condition == "full_agent"
    return GoalResearchRequest(
        topic=task["topic"],
        goal=task["goal"],
        expected_result=task["expected_result"],
        success_criteria=[GoalCriterion.model_validate(c) for c in task["success_criteria"]],
        max_iterations=settings["max_iterations"],
        no_progress_patience=settings["no_progress_patience"],
        max_python_calls=settings["max_python_calls"],
        max_python_attempts_per_call=settings["max_python_attempts_per_call"],
        allow_python_execution=python_on,
        python_execution_approved=python_on,
        deliverables=[],
        **common,
    )


async def run_one(task: dict, condition: str, settings: dict, research_agent, goal_agent, run_id: str) -> dict:
    request = make_request(task, condition, settings)
    started = time.perf_counter()
    if condition == "single_shot":
        response = await research_agent.research(request)
    else:
        response = await goal_agent.run(f"{run_id}-{task['task_id']}-{condition}", request)
    return {
        "task_id": task["task_id"],
        "condition": condition,
        "request": request.model_dump(mode="json"),
        "response": response.model_dump(mode="json"),
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }


def _save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


async def run_full(benchmark: dict, manifest: dict, output: Path, run_id: str) -> None:
    from app.api.goal_research_routes import cached_goal_research_service
    from app.api.research_routes import cached_research_agent
    from app.core.config import get_settings

    product_settings = get_settings()
    expected = manifest["kb"]
    if product_settings.data_dir != Path(expected["data_dir"]) or product_settings.retrieval_mode != expected["retrieval_mode"]:
        raise ValueError("DATA_DIR or RETRIEVAL_MODE differs from frozen manifest")
    import chromadb

    collection = chromadb.PersistentClient(path=str(product_settings.vector_db_dir)).get_collection(expected["collection"])
    if collection.count() != expected["chunks"]:
        raise ValueError("Real KB chunk count mismatch")
    metadata = collection.get(include=["metadatas"])["metadatas"]
    if len({m.get("document") for m in metadata if m and m.get("document")}) != expected["documents"]:
        raise ValueError("Real KB document count mismatch")
    catalog = benchmark["source_catalog"]
    located = collection.get(ids=[item["chunk_id"] for item in catalog.values()], include=["metadatas"])
    actual = dict(zip(located["ids"], located["metadatas"]))
    for source_id, source in catalog.items():
        item = actual.get(source["chunk_id"])
        if item is None or item.get("document") != source["document"] or item.get("page") != source["page"]:
            raise ValueError(f"KB source locator mismatch: {source_id}")
    with urlopen(product_settings.ollama_base_url.rstrip("/") + "/api/tags", timeout=10) as handle:
        tags = json.load(handle)
    if not any(x.get("name") == manifest["model_settings"]["research_model"] for x in tags.get("models", [])):
        raise ValueError("Frozen research model unavailable")
    research_agent = cached_research_agent()
    goal_agent = cached_goal_research_service().controller
    for condition in CONDITIONS:
        path = output / f"{condition}.json"
        payload = {"run_id": run_id, "condition": condition, "benchmark_sha256": manifest["benchmark_sha256"], "product_code_sha": manifest["product_code_sha"], "complete": False, "results": []}
        _save(path, payload)
        for index, task in enumerate(benchmark["tasks"], 1):
            print(f"{condition} {index}/{len(benchmark['tasks'])} {task['task_id']}", flush=True)
            row = await run_one(task, condition, manifest["model_settings"], research_agent, goal_agent, run_id)
            payload["results"].append(row)
            _save(path, payload)
        payload["complete"] = True
        _save(path, payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path(r"D:\petroleum-rag-agent\data\evaluation\agentic"))
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    benchmark, manifest = load_and_validate()
    if args.validate_only:
        print(f"validated {len(benchmark['tasks'])} frozen tasks")
        return 0
    os.environ.setdefault("DATA_DIR", manifest["kb"]["data_dir"])
    os.environ.setdefault("RETRIEVAL_MODE", manifest["kb"]["retrieval_mode"])
    run_id = "agentic-v1-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir / run_id
    if output.exists():
        raise FileExistsError(output)
    print(f"run_id={run_id} output={output}", flush=True)
    asyncio.run(run_full(benchmark, manifest, output, run_id))
    print(f"completed={run_id}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
