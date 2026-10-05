"""Evaluation-only contracts; the synthetic smoke never invokes a held-out goal."""

from __future__ import annotations

import json
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_python_tool_heldout_v2 as runner
import score_python_tool_heldout_v2 as scorer


@pytest.fixture(scope="module")
def frozen():
    return runner.load_and_validate()


def test_schema_distribution_and_criteria(frozen):
    benchmark, manifest = frozen
    assert len(benchmark["tasks"]) == 12
    assert manifest["python_expected_count"] == {"required": 8, "optional": 2, "not_needed": 2}
    assert manifest["domain_count"] == {"reservoir_engineering": 6, "well_test": 6}
    assert sum(len(t["ground_truth"]["numeric_targets"]) for t in benchmark["tasks"]) == 50
    assert all(3 <= len(t["success_criteria"]) <= 5 for t in benchmark["tasks"])


def test_user_fact_mapping_and_numeric_tolerances(frozen):
    benchmark, _ = frozen
    assert sum(t["input_provenance_expected"] == "user_fact_plus_kb_formula" for t in benchmark["tasks"] if t["python_expected"] == "required") == 6
    assert sum(t["input_provenance_expected"] == "kb_numeric" for t in benchmark["tasks"] if t["python_expected"] == "required") == 2
    assert all(n["unit"] and n["abs_tolerance"] > 0 for t in benchmark["tasks"] for n in t["ground_truth"]["numeric_targets"])


def test_formula_locators(frozen):
    benchmark, _ = frozen
    sources = benchmark["source_catalog"]
    assert all(s["chunk_id"] and s["document"] and s["page"] and s["excerpt_check"] for s in sources.values())
    assert all(set(t["ground_truth"]["formula_sources"]) <= sources.keys() for t in benchmark["tasks"])


@pytest.mark.parametrize("condition,allowed", [("python_off", False), ("python_on", True)])
def test_synthetic_smoke_request_flags(frozen, condition, allowed):
    _, manifest = frozen
    synthetic = {"topic": "Synthetic arithmetic smoke: x=7", "goal": "State x", "expected_result": None,
                 "success_criteria": [{"criterion_id": "C1", "description": "State the given value", "required": True}]}
    req = runner.make_request(synthetic, condition, manifest["model_settings"])
    assert req.allow_python_execution is allowed
    assert req.python_execution_approved is allowed
    assert req.max_iterations == 4 and req.no_progress_patience == 2
    assert req.seed == 42 and req.temperature == 0 and not req.use_external


def test_synthetic_smoke_raw_trace_persistence(frozen):
    class FakeResponse:
        def model_dump(self, **_):
            return {"iterations": [{"iteration": 1, "python_trace": {"tool_selected": True, "subprocess_reached": True}}]}
    class FakeAgent:
        async def run(self, run_id, request):
            assert "Synthetic" in request.topic
            return FakeResponse()
    _, manifest = frozen
    task = {"task_id": "SYNTHETIC", "topic": "Synthetic x=7", "goal": "State x", "expected_result": None,
            "success_criteria": [{"criterion_id": "C1", "description": "State given x", "required": True}]}
    row = asyncio.run(runner.run_one(task, "python_on", manifest["model_settings"], FakeAgent(), "synthetic-smoke"))
    assert row["response"]["iterations"][0]["python_trace"]["subprocess_reached"]
    assert row["request"]["allow_python_execution"]


def test_iteration_aggregation_uses_earlier_selected_iteration():
    response = {"iterations": [
        {"python_trace": {"planner_decision_attempts": 1, "planner_decision_status": "selected",
                          "tool_selected": True, "plan_present": True, "planner_plan_status": "materialized",
                          "facts_verified": True, "subprocess_reached": True, "result_validation_passed": True,
                          "computation_id": "CALC1"}},
        {"python_trace": {"planner_decision_attempts": 1, "planner_decision_status": "legitimate_not_selected",
                          "blocked_stage": "planner_not_selected"}}],
        "computations": [{"computation_id": "CALC1", "validation_passed": True}]}
    aggregate = scorer.aggregate_iterations(response)
    assert aggregate["ever_selected"] and aggregate["calc_created"]
    assert aggregate["furthest_stage"] == 12
    assert not aggregate["trace_integrity_error"]


def test_decision_parse_failure_distinct_from_nonselection():
    a = scorer.aggregate_iterations({"iterations": [{"python_trace": {"planner_decision_status": "planner_decision_parse_failed", "blocked_stage": "planner_decision_parse_failed"}}]})
    b = scorer.aggregate_iterations({"iterations": [{"python_trace": {"planner_decision_status": "legitimate_not_selected", "blocked_stage": "planner_not_selected"}}]})
    assert a["failure_attribution"] == ["planner_decision_parse_failure"]
    assert b["failure_attribution"] == ["planner_not_selected"]


def test_plan_parse_failure_and_furthest_stage():
    a = scorer.aggregate_iterations({"iterations": [{"python_trace": {"planner_decision_status": "selected", "tool_selected": True,
                                                         "planner_plan_status": "planner_plan_parse_failed", "blocked_stage": "planner_plan_parse_failed"}}]})
    assert a["furthest_stage"] == 2
    assert a["failure_attribution"] == ["planner_plan_parse_failure"]


def test_registry_and_selection_recall(frozen):
    task = frozen[0]["tasks"][0]
    a = scorer.registry_score(task, {"selected_user_fact_ids": ["USERF1", "USERF2", "USERF999"]})
    assert a["registry_recall"] == 1
    assert a["selection_recall"] == 2 / 12
    assert a["unknown_user_fact_count"] == 1


def test_calc_numeric_and_units(tmp_path):
    output = tmp_path / "analysis.json"
    output.write_text(json.dumps({"result": "effective permeability 120 mD"}), encoding="utf-8")
    task = {"ground_truth": {"numeric_targets": [{"name": "keff", "value": 120, "unit": "mD", "abs_tolerance": 0.1}]}}
    response = {"computations": [{"validation_passed": True, "output_files": ["analysis.json"]}]}
    result = scorer.calc_score(task, response, tmp_path)
    assert (result["calc_numeric_correct"], result["calc_unit_correct"], result["calc_complete"]) == (1, 1, True)


def test_trace_integrity_flag():
    result = scorer.aggregate_iterations({"iterations": [{"python_trace": {"computation_id": "CALC1", "result_validation_passed": True}}],
                                          "computations": [{"computation_id": "CALC1", "validation_passed": True}]})
    assert result["trace_integrity_error"]


def test_optional_excluded_from_precision_recall():
    rows = [{"python_expected": "required", "ever_selected": True},
            {"python_expected": "not_needed", "ever_selected": False},
            {"python_expected": "optional", "ever_selected": True}]
    assert scorer.selection_metrics(rows) == {"precision": 1, "recall": 1, "f1": 1}


def test_paired_bootstrap_deterministic():
    pairs = [(0, 1), (0, 0), (1, 0)]
    assert scorer.paired_bootstrap(pairs, samples=10000, seed=42) == scorer.paired_bootstrap(pairs, samples=10000, seed=42)
    assert scorer.paired_bootstrap(pairs)["delta"] == 0


def test_blind_packet_hides_condition_tool_provenance(frozen):
    task = frozen[0]["tasks"][0]
    packet = scorer.blind_packet(task, {"final_answer": "Python tool [CALC1] [USERF1] produced 120 mD", "internal_sources": []}, "BR-001")
    text = json.dumps(packet)
    assert "python_off" not in text and "python_on" not in text
    assert "CALC1" not in text and "USERF1" not in text
