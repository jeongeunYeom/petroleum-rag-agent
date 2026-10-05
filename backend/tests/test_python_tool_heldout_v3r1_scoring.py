from __future__ import annotations

import json

from scripts.review_python_tool_heldout_v3r1 import blind_packet, no_condition_leakage
from scripts.adjudicate_python_tool_heldout_v3r1 import numeric_criteria
from scripts.score_python_tool_heldout_v3r1 import (
    adoption, attribution, calc_score, funnel, numeric_match, paired_bootstrap, scoring_targets,
)


def test_numeric_matching_requires_case_and_accepts_fraction_percent() -> None:
    assert numeric_match("A ED = 85.4%", ["A_ED", 0.854, "fraction", 0.005]) == (True, True)
    assert numeric_match("B Bo = 1.2 dimensionless", ["A_Bo", 1.2, "ratio", 0.005]) == (False, False)
    assert numeric_match("R4: 4 psi", ["R4_abs", 4, "psi", 0.01]) == (True, True)
    assert numeric_match("The gap is three percentage points.",
                         ["gap_pp", 3, "percentage points", 0.01]) == (True, True)


def test_explicit_re03_mean_is_derived_from_frozen_case_targets() -> None:
    task = {"task_id": "PY3R1-RE-03", "ground_truth": {"numeric_targets": [
        [f"{case}_Fpvg", value, "fraction", 0.005] for case, value in
        zip("ABCDE", (0.1, 0.2, 0.3, 0.4, 0.5))]}}
    assert scoring_targets(task)[-1] == ["mean_Fpvg", 0.3, "fraction", 0.005]


def test_funnel_aggregates_across_iterations() -> None:
    task = {"ground_truth": {"required_user_facts": [], "required_evidence_facts": [], "formula_sources": []}}
    response = {"iterations": [{"python_trace": {"planner_decision_status": "selected", "tool_selected": True,
                   "plan_present": True, "planner_plan_status": "materialized", "facts_verified": True,
                   "formula_verified": True, "call_boundary_reached": True, "code_generated": True,
                   "sandbox_validation_passed": True, "subprocess_reached": True,
                   "result_validation_passed": True}}],
                "computations": [{"validation_passed": True}]}
    registry = {"user_registry_recall": None, "evidence_registry_recall": None,
                "formula_registry_recall": None, "expected_user_ids": [], "expected_evidence_ids": [],
                "selected_fact_ids": [], "formula_selection_accuracy": None}
    stages = funnel(task, response, registry)
    assert stages["tool_selected"] and stages["plan_materialized"]
    assert stages["subprocess"] and stages["calc_created"]


def test_calc_scorer_and_adoption(tmp_path) -> None:
    relative = "results/one/result.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"A_total_We": 88626, "unit": "bbl", "summary": "A total 88626 bbl"}), encoding="utf-8")
    task = {"ground_truth": {"numeric_targets": [["A_total_We", 88626, "bbl", 1]],
                              "required_user_facts": [["A_We2", 21600, "bbl"]],
                              "formula_sources": [["R710", "We=We1+We2+We3"]]}}
    response = {"computations": [{"computation_id": "CALC1", "validation_passed": True,
                                   "output_files": [relative]}],
                "final_answer": "A total 88626 bbl [CALC1] from hypothetical user increments [USERF1] and the source [KB2]."}
    calc = calc_score(task, response, tmp_path)
    assert calc["calc_complete"] and calc["calc_numeric_correct"] == 1
    numeric = {"numeric_complete": True}
    registry = {"evidence_source_map": {"R710": "KB2"}}
    assert adoption(task, response, numeric, calc, registry)["calc_adopted"]


def test_calc_scorer_never_counts_inputs_as_outputs(tmp_path) -> None:
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"inputs": {"R1_first": 1, "R1_repeat": 2},
                                "result": {"difference": 1}, "summary": "difference=1"}), encoding="utf-8")
    task = {"ground_truth": {"numeric_targets": [["R1_abs", 1, "psi", 0.01]]}}
    response = {"computations": [{"validation_passed": True, "output_files": ["result.json"]}]}
    assert calc_score(task, response, tmp_path)["calc_numeric_correct"] == 0

    path.write_text(json.dumps({"inputs": {"R1_first": 100},
                                "result": {"R1_abs": {"value": 1, "unit": "psi"}}}), encoding="utf-8")
    assert calc_score(task, response, tmp_path)["calc_target_matches"]["R1_abs"] == {"value": True, "unit": True}


def test_runtime_retrieval_missing_is_not_preflight_failure() -> None:
    task = {"python_expected": "required"}
    registry = {"retrieved_source_ids": {"W376": False}, "evidence_registry_recall": None,
                "formula_registry_recall": 0}
    assert attribution(task, {}, registry, {"tool_selected": False, "plan_materialized": False,
                        "calc_created": False}, {"calc_complete": None}, {"numeric_complete": False}) == ["retrieval_source_missing"]


def test_disabled_off_condition_is_not_counted_as_planner_failure() -> None:
    registry = {"retrieved_source_ids": {}, "evidence_registry_recall": None,
                "formula_registry_recall": None}
    result = attribution({"python_expected": "required"}, {}, registry,
                         {"tool_selected": False, "plan_materialized": False, "calc_created": False},
                         {"calc_complete": None}, {"numeric_complete": False}, "python_off")
    assert result == ["python_disabled_by_condition"]


def test_validated_stage_is_not_a_failure_label() -> None:
    result = attribution({"python_expected": "required"},
                         {"iterations": [{"python_trace": {"blocked_stage": "validated"}}]},
                         {"retrieved_source_ids": {}, "evidence_registry_recall": None,
                          "formula_registry_recall": None},
                         {"tool_selected": True, "plan_materialized": True, "calc_created": True},
                         {"calc_complete": True}, {"numeric_complete": True})
    assert result == []


def test_paired_bootstrap_deterministic() -> None:
    a = paired_bootstrap([(0, 1), (1, 1)], samples=10000, seed=42)
    b = paired_bootstrap([(0, 1), (1, 1)], samples=10000, seed=42)
    assert a == b and a["delta"] == 0.5 and a["ci95"] == [0.0, 1.0]


def test_blind_packet_removes_condition_and_calc_state() -> None:
    task = {"task_id": "PY3R1-RE-01", "topic": "Reference", "goal": "Explain", "python_expected": "required",
            "success_criteria": [{"criterion_id": "C1", "description": "Cite"},
                                 {"criterion_id": "C2", "description": "Compute"}]}
    packet = blind_packet(task, {"final_answer": "Python output [CALC1] from [USERF2] [KB1]"}, "BR-001")
    assert no_condition_leakage(packet)
    assert "CALC1" not in json.dumps(packet)
    assert "Python output" not in json.dumps(packet)
    assert [c["criterion_id"] for c in packet["question"]["qualitative_criteria"]] == ["C1"]


def test_numeric_criteria_cannot_be_replaced_by_semantic_review() -> None:
    required = {"task_id": "PY3R1-RE-01", "python_expected": "required"}
    row = {"target_matches": {"A_Bo": {"value": True, "unit": True},
                              "B_Bo": {"value": False, "unit": True}}}
    assert numeric_criteria(required, row) == {"C2": False}
    optional = {"task_id": "PY3R1-RE-09", "python_expected": "optional"}
    row = {"target_matches": {"gap_pp": {"value": True, "unit": True},
                              "relative_gap": {"value": False, "unit": True}}}
    assert numeric_criteria(optional, row) == {"C1": True, "C2": False}
