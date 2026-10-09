from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path

from scripts.run_agentic_heldout import (
    BENCHMARK,
    MANIFEST,
    RUBRIC,
    _save,
    load_and_validate,
    make_request,
    run_one,
    sha256,
)
from scripts.prepare_agentic_review import prepare
from scripts.review_agentic_heldout import _final_schema
from scripts.score_agentic_review import _write_csv, paired_bootstrap, score_final, score_numeric, score_process


class FakeResponse:
    def model_dump(self, **_kwargs):
        return {"answer": "fixture"}


class FakeResearchAgent:
    def __init__(self):
        self.calls = []

    async def research(self, request):
        self.calls.append(request)
        return FakeResponse()


class FakeGoalAgent:
    def __init__(self):
        self.calls = []

    async def run(self, run_id, request):
        self.calls.append((run_id, request))
        return FakeResponse()


def test_benchmark_schema_and_freeze():
    data = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert len(data["tasks"]) == 18
    assert len({t["task_id"] for t in data["tasks"]}) == 18
    assert sum(len(t["success_criteria"]) for t in data["tasks"]) == 54
    assert sha256(BENCHMARK) == manifest["benchmark_sha256"]
    assert sha256(RUBRIC) == manifest["rubric_sha256"]
    for task in data["tasks"]:
        gt = task["ground_truth"]
        covered = {cid for claim in gt["claims"] for cid in claim["criterion_ids"]}
        covered.update(n["criterion_id"] for n in gt["numeric_targets"])
        assert {c["criterion_id"] for c in task["success_criteria"]} <= covered
        assert all(n["abs_tolerance"] > 0 for n in gt["numeric_targets"])
        assert all(set(c["source_ids"]) <= data["source_catalog"].keys() for c in gt["claims"])


def test_figure_mapping_manifest():
    data = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    figures = [f for task in data["tasks"] for f in ([task["ground_truth"]["figure"]] if "figure" in task["ground_truth"] else task["ground_truth"].get("figures", []))]
    assert len(figures) == 3
    assert {(f["page"], f["figure_number"], f["image_index"]) for f in figures} == {(440, "2", 2), (441, "4", 2), (441, "5", 3)}
    assert {f["image_file"] for f in figures} == {f["image_file"] for f in manifest["figure_assets"]}
    for f in manifest["figure_assets"]:
        if Path(f["image_file"]).exists():
            assert sha256(Path(f["image_file"])) == f["sha256"]


def test_condition_permissions_web_and_single_call(tmp_path):
    settings = json.loads(MANIFEST.read_text(encoding="utf-8"))["model_settings"]
    task = {"task_id": "SYNTHETIC", "topic": "Synthetic porous media", "goal": "Summarize the fixture", "expected_result": None, "success_criteria": [{"criterion_id": "C1", "description": "State the fixture result", "required": True}]}
    research = FakeResearchAgent()
    goal = FakeGoalAgent()

    async def run():
        return [await run_one(task, condition, settings, research, goal, "SYNTHETIC") for condition in ("single_shot", "goal_agent", "full_agent")]

    rows = asyncio.run(run())
    assert len(research.calls) == 1
    assert len(goal.calls) == 2
    assert all(not r["request"]["use_external"] and r["request"]["use_internal"] for r in rows)
    assert all(r["request"]["model"] == "qwen3:8b" and r["request"]["seed"] == 42 and r["request"]["temperature"] == 0 for r in rows)
    assert all(r["request"]["internal_top_k"] == 5 for r in rows)
    assert rows[0]["request"]["query"].count("C1:") == 1
    assert rows[1]["request"]["allow_python_execution"] is False
    assert rows[1]["request"]["python_execution_approved"] is False
    assert rows[1]["request"]["max_iterations"] == rows[2]["request"]["max_iterations"] == 4
    assert rows[1]["request"]["no_progress_patience"] == rows[2]["request"]["no_progress_patience"] == 2
    assert rows[2]["request"]["allow_python_execution"] is True
    assert rows[2]["request"]["python_execution_approved"] is True
    path = tmp_path / "synthetic.json"
    _save(path, {"complete": True, "results": rows})
    assert len(json.loads(path.read_text(encoding="utf-8"))["results"]) == 3


def test_blind_packet_has_no_condition_names():
    benchmark = {"benchmark_id": "synthetic_fixture", "source_catalog": {}, "tasks": [{"task_id": "SYNTHETIC", "topic": "Synthetic porous media", "goal": "Summarize the fixture", "expected_result": None, "success_criteria": [{"criterion_id": "C1", "description": "State the fixture result", "required": True}], "ground_truth": {"claims": [], "numeric_targets": [], "goal_feasibility": "achievable", "expected_hypothesis_status": "not_provided"}}]}
    raws = {}
    for condition in ("single_shot", "goal_agent", "full_agent"):
        raws[condition] = {"complete": True, "results": [
            {"task_id": task["task_id"], "condition": condition, "response": {"answer": "synthetic answer", "final_answer": "synthetic answer", "iterations": [], "internal_sources": [], "figures": []}}
            for task in benchmark["tasks"]
        ]}
    final, process, mapping = prepare(benchmark, raws)
    assert len(final["items"]) == 3
    assert len(process["items"]) == 2
    text = json.dumps((final, process), ensure_ascii=False)
    assert all(name not in text for name in ("single_shot", "goal_agent", "full_agent"))
    assert len(mapping["final"]) == 3 and len(mapping["process"]) == 2


def test_numeric_tolerance_and_unit():
    target = {"target_id": "K", "value": 89.2857, "unit": "mD", "abs_tolerance": 0.3}
    answer = "Series effective permeability is 89.29 mD."
    item = {"target_id": "K", "value": 89.29, "unit": "mD", "quote": "89.29 mD"}
    assert score_numeric(answer, [target], [item])["K"]["passed"]
    assert score_numeric(answer, [target], [{**item, "value": 89.28571429, "quote": "89.28571429 mD"}])["K"]["passed"]
    assert not score_numeric("Series effective permeability is 89.29 psi.", [target], [item])["K"]["passed"]
    assert not score_numeric("Series effective permeability is 133 mD.", [target], [item])["K"]["passed"]
    volume = {"target_id": "V", "value": 2_700_000, "unit": "stock-tank m^3", "abs_tolerance": 10_000}
    text = "OOIP is 2.7 million stock-tank m^3."
    extraction = {"target_id": "V", "value": 2.7, "unit": "stock-tank m^3", "quote": "2.7 million stock-tank m^3"}
    assert score_numeric(text, [volume], [extraction])["V"]["passed"]
    change = {"target_id": "P", "value": -6.67, "unit": "%", "abs_tolerance": 0.1}
    assert score_numeric("A 6.67% reduction", [change], [{"target_id": "P", "value": -6.67, "unit": "%", "quote": "6.67% reduction"}])["P"]["passed"]


def test_strict_review_requires_per_criterion_quotes():
    item = {"criteria": [{"criterion_id": "C1"}], "ground_truth": {"claims": []}}
    schema = _final_schema(item, strict=True)
    assert "criterion_quotes" in schema["required"]
    assert "contradiction_quote" in schema["required"]
    assert schema["properties"]["criterion_quotes"]["required"] == ["C1"]


def test_old_evidence_cannot_count_as_new_replan():
    task = {"task_id": "SYNTHETIC", "python_expected": "not_needed", "success_criteria": [{"criterion_id": "C1", "required": True}]}
    row = {"condition": "goal_agent", "request": {}, "response": {
        "iterations": [
            {"iteration": 1, "evidence_added": ["KB1"], "computation_ids": [], "python_requested": False},
            {"iteration": 2, "evidence_added": ["KB2"], "computation_ids": [], "python_requested": False},
        ],
        "goal_coverage": 1.0, "stop_reason": "max_iterations", "status": "achieved",
        "python_calls_total": 0, "python_attempts_total": 0, "python_failures": 0,
        "computations": [], "final_answer": "answer",
    }}
    review = {"iteration_reviews": [
        {"criterion_scores": {"C1": 2}, "relevant_new_evidence_ids": ["KB1"], "engineering_error": False},
        {"criterion_scores": {"C1": 2}, "relevant_new_evidence_ids": ["KB1"], "engineering_error": False},
    ], "reviewer_notes": "old evidence repeated"}
    final = {"criterion_scores": {"C1": 2}, "external_goal_coverage": 1.0, "goal_success": 1, "engineering_contradiction": False}
    process = score_process(task, row, review, final)
    assert process["new_evidence_replans"] == 0
    assert process["useful_replans"] == 0
    assert "reviewer_named_old_evidence_as_new" in process["qa_flags"]


def test_paired_bootstrap_reproducible():
    left = [0, 1, 0, 1, 0, 0]
    right = [1, 1, 0, 1, 1, 0]
    first = paired_bootstrap(left, right)
    assert first == paired_bootstrap(left, right)
    assert first["delta"] == 2 / 6
    assert first["ci95_low"] <= first["delta"] <= first["ci95_high"]


def test_aggregate_csv_persists_numeric_values(tmp_path):
    path = tmp_path / "synthetic.csv"
    _write_csv(path, [{"condition": "synthetic", "goal_success": 0.5, "latency_mean_seconds": 2.3}])
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [{"condition": "synthetic", "goal_success": "0.5", "latency_mean_seconds": "2.3"}]


def test_external_goal_success_requires_numeric_and_hypothesis_handling():
    task = {
        "task_id": "SYNTHETIC",
        "success_criteria": [{"criterion_id": "C1", "required": True}],
        "ground_truth": {
            "claims": [{"claim_id": "GT1"}],
            "numeric_targets": [{"target_id": "N1", "criterion_id": "C1", "value": 5.0, "unit": "mD", "abs_tolerance": 0.1, "critical": True}],
            "expected_hypothesis_status": "contradicted",
            "goal_feasibility": "conflicts_with_evidence",
        },
    }
    row = {"condition": "single_shot", "elapsed_seconds": 1.0, "response": {"answer": "The target is false; measured value is 5.0 mD."}}
    judgment = {
        "criterion_scores": {"C1": 2}, "claim_results": {"GT1": True}, "hallucination": False,
        "engineering_contradiction": False, "evidence_grounding": 1.0,
        "hypothesis_handling_correct": True, "insufficient_evidence_handling_correct": None,
        "numeric_extractions": [{"target_id": "N1", "value": 5.0, "unit": "mD", "quote": "5.0 mD"}],
    }
    assert score_final(task, row, judgment)["goal_success"] == 1
    assert score_final(task, row, {**judgment, "hypothesis_handling_correct": False})["goal_success"] == 0
    assert score_final(task, row, {**judgment, "numeric_extractions": []})["goal_success"] == 1
    missing = {**row, "response": {"answer": "The target is false; the measurement is unavailable."}}
    assert score_final(task, missing, {**judgment, "numeric_extractions": []})["goal_success"] == 0
