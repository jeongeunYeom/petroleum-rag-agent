"""Evaluation-only diagnostic tests; no frozen agentic task is rerun."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.config import Settings
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_tool_planner import PythonAnalysisPlan, ToolDecision
from scripts.diagnose_python_tool_execution import (
    FIXTURE, decision_stage, explain_verified_facts, frozen_posthoc, run_dev_cases,
    write_results,
)


@pytest.fixture(scope="module")
def fixture_cases():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.fixture(scope="module")
def dev_rows(fixture_cases):
    return {row["task_id"]: row for row in asyncio.run(run_dev_cases({"cases": fixture_cases}))}


def test_planner_gate_taxonomy(fixture_cases):
    plan = PythonAnalysisPlan.model_validate(fixture_cases[0]["plan"])
    assert decision_stage(ToolDecision(), True) == "PLANNER_NOT_SELECTED"
    assert decision_stage(ToolDecision(tool_needed=True, tool_type="python_calculation"), True) == "PLANNER_SELECTED_NO_PLAN"
    assert decision_stage(ToolDecision(tool_needed=True, tool_type="python_calculation", plan=plan), False) == "PERMISSION_NOT_APPROVED"
    assert decision_stage(ToolDecision(tool_needed=True, tool_type="python_calculation", plan=plan), True) is None


@pytest.mark.parametrize("case_id", ["D1", "D2", "D3", "D4", "D5", "D6", "D7"])
def test_explainer_equivalent_to_product_predicate(fixture_cases, case_id):
    case = next(item for item in fixture_cases if item["id"] == case_id)
    plan = PythonAnalysisPlan.model_validate(case["plan"])
    explained = explain_verified_facts(plan, case["evidence"])
    actual = GoalPythonAnalysis.verified_facts(plan, case["evidence"])
    assert (explained is None) == actual


@pytest.mark.parametrize("case_id,stage", [
    ("D1", "CALC_VALIDATED"), ("D2", "EVIDENCE_ID_NOT_FOUND"),
    ("D3", "EVIDENCE_ID_NOT_FOUND"), ("D4", "CALC_VALIDATED"),
    ("D5", "UNIT_NOT_IN_EXCERPT"), ("D6", "FORMULA_PROVENANCE_MISSING"),
    ("D7", "PERMISSION_NOT_APPROVED"), ("D8", "CACHE_HIT"),
])
def test_eight_development_diagnostics(dev_rows, case_id, stage):
    row = dev_rows[case_id]
    assert row["tool_selected"] and row["plan_present"]
    assert row["blocked_stage"] == stage
    assert row["subprocess_reached"] is (case_id in {"D1", "D4"})


def test_call_boundary_and_local_sandbox_result(dev_rows):
    for case_id in ("D1", "D4"):
        row = dev_rows[case_id]
        assert row["verified_facts_passed"]
        assert row["call_boundary_reached"] and row["code_generated"]
        assert row["sandbox_validation_passed"] and row["permission_manager_passed"]
        assert row["subprocess_exit_code"] == 0
        assert row["result_validation_passed"] and row["calc_created"]


def test_prompt_only_numbers_do_not_get_provenance(dev_rows):
    for case_id in ("D2", "D3"):
        row = dev_rows[case_id]
        assert not row["verified_facts_passed"]
        assert not row["call_boundary_reached"] and not row["subprocess_reached"]
        assert not row["calc_created"]


def test_unit_formula_and_permission_gates_are_pre_call(dev_rows):
    for case_id in ("D5", "D6", "D7"):
        row = dev_rows[case_id]
        assert not row["call_boundary_reached"]
        assert not row["subprocess_reached"]
    assert dev_rows["D7"]["verified_facts_passed"]
    assert not dev_rows["D7"]["permission_approved"]


def test_cache_reuses_validated_calc_without_second_subprocess(dev_rows):
    first, second = dev_rows["D1"], dev_rows["D8"]
    assert second["python_call_counter_before"] == first["python_call_counter_after"] == 1
    assert second["python_call_counter_after"] == 1
    assert second["calc_created"] and not second["subprocess_reached"]


def test_frozen_classification_from_minimal_synthetic_record():
    raw = {"results": [{"task_id": "T", "request": {"allow_python_execution": True, "python_execution_approved": True}, "response": {
        "run_id": "agentic-v1-T-full_agent", "frozen_criteria": [], "validation": {"python_analysis_error": "Invalid goal research run ID"},
        "python_calls_total": 0, "python_attempts_total": 0, "python_failures": 0, "computations": [],
        "iterations": [{"iteration": 1, "evidence_added": ["KB1"], "python_requested": True,
                        "python_decision_reason": "calculation", "python_executed": False,
                        "python_calls": 0, "computation_ids": [], "criteria": [], "gap_analysis": []}],
    }}]}
    selected, stats = frozen_posthoc(raw)
    assert selected[0]["blocked_stage"] == "RUN_ID_REJECTED"
    assert selected[0]["plan_present"] is True
    assert selected[0]["input_fact_count"] == "unknown"
    assert selected[0]["evidence_ids_available_at_decision"] == ["KB1"]
    assert stats["run_id_rejected_iterations_by_deterministic_code_path"] == 1


def test_frozen_runner_style_id_is_now_accepted_without_altering_frozen_results(tmp_path):
    run_id = "agentic-v1-20261004T075903Z-AG-Q-006-full_agent"
    assert GoalPythonAnalysis(Settings(data_dir=tmp_path), object(), run_id).run_id == run_id


def test_explainer_detects_missing_and_duplicate_inputs(fixture_cases):
    case = fixture_cases[0]
    plan = PythonAnalysisPlan.model_validate(case["plan"])
    assert explain_verified_facts(plan.model_copy(update={"input_facts": []}), case["evidence"]) == "INPUT_FACTS_EMPTY"
    assert explain_verified_facts(plan.model_copy(update={"input_facts": plan.input_facts[:1]}), case["evidence"]) == "INPUT_FACT_COUNT_TOO_LOW"
    duplicate = plan.model_copy(update={"input_facts": [plan.input_facts[0], plan.input_facts[0]]})
    assert explain_verified_facts(duplicate, case["evidence"]) == "DUPLICATE_INPUT_NAME"


def test_machine_readable_json_and_csv_include_all_development_rows(tmp_path, dev_rows):
    rows = list(dev_rows.values())
    write_results(tmp_path, {"dev_cases": rows})
    assert len(json.loads((tmp_path / "python_tool_execution_diagnostic_v1.json").read_text(encoding="utf-8"))["dev_cases"]) == 8
    import csv
    with (tmp_path / "python_tool_execution_diagnostic_v1.csv").open(encoding="utf-8-sig", newline="") as handle:
        saved = list(csv.DictReader(handle))
    assert len(saved) == 8
    assert saved[0]["blocked_stage"] == "CALC_VALIDATED"
    assert saved[-1]["blocked_stage"] == "CACHE_HIT"
