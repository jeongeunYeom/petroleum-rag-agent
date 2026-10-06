"""Scorer and runner gates use fixtures, never held-out Agent outputs."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
import run_python_tool_heldout_v5 as runner  # noqa: E402
import score_python_tool_heldout_v5 as scorer  # noqa: E402
import review_python_tool_heldout_v5 as reviewer  # noqa: E402

TASK = json.loads((ROOT / "evaluation/python_tool_heldout_v5.json").read_text(encoding="utf-8"))["tasks"][0]
REF = json.loads((ROOT / "evaluation/reference/python_tool_heldout_v5_reference_outputs.json").read_text(encoding="utf-8"))[TASK["task_id"]]
SOURCE = scorer.CATALOG_DATA[TASK["ground_truth"]["source_ids"][0]]


def mini_task() -> dict:
    target = {"semantic_name": "A_K", "target_id": "T1", "target_type": "numeric", "value": 2.5,
              "unit": "dimensionless", "abs_tolerance": .01, "scenario_id": "A"}
    return {"topic": "fixture", "python_expected": "required", "ground_truth": {
        "canonical_targets": [target], "numeric_targets": [target], "typed_targets": [],
        "ranking_targets": [], "source_ids": [], "formula_sources": [], "expected_bindings": {},
        "expected_user_facts": [], "expected_evidence_facts": []}}


def mini_contract(value: float = 2.5) -> tuple[dict, dict]:
    task = mini_task()
    spec = {"output_id": "OUT_A_K", "name": "A_K", "semantic_type": "numeric",
            "unit": "dimensionless", "scenario_id": "A"}
    calc = {"computation_id": "CALC1", "validation_passed": True, "contract_validation_passed": True,
            "output_manifest": {"OUT_A_K": {**spec, "value": value}}, "used_input_ids": []}
    response = {"final_answer": "A K = 2.5 dimensionless [CALC1]", "computations": [calc],
                "iterations": [{"python_trace": {"assumption_guard_passed": True,
                                                  "calc_grounding_validation_passed": True,
                                                  "calculation_contract": {"required_outputs": [spec]}}}]}
    return task, response


def test_runner_frozen_asset_hashes_and_product_identity(monkeypatch):
    # The runner checks Git ancestry against the freeze commit in a full checkout.
    # CI uses checkout@v4's shallow clone, so test portable hashes here instead.
    benchmark = runner.load(runner.BENCHMARK)
    manifest = runner.load(runner.MANIFEST)
    assert manifest["product_code_sha"] == benchmark["product_code_sha"]
    assert all(runner.digest(path) == manifest[label + "_sha256"] for label, path in runner.FILES.items())
    original = runner.load
    monkeypatch.setattr(runner, "load", lambda path: {**original(path), "product_code_sha": "wrong"}
                        if path == runner.MANIFEST else original(path))
    with pytest.raises(ValueError, match="Product SHA"):
        runner.load_frozen()


def test_external_source_completeness_requires_the_frozen_chunk_and_formula():
    good = {"internal_sources": [{"evidence_id": "KB1", "chunk_id": SOURCE["chunk_id"],
                                   "document": SOURCE["document"], "page": SOURCE["page"],
                                   "excerpt": "Equilibrium Ratio K=y/x"}]}
    assert scorer.source_audit(TASK, good, scorer.CATALOG_DATA, REF)["source_complete_external"]
    bad = copy.deepcopy(good)
    bad["internal_sources"][0]["chunk_id"] = "wrong"
    assert not scorer.source_audit(TASK, bad, scorer.CATALOG_DATA, REF)["source_complete_external"]


def test_binding_correct_id_and_scenario_required():
    task = mini_task()
    task["ground_truth"]["expected_bindings"] = {"A": {"x": "A_x"}}
    source = {"matched_user_fact_ids": {"A_x": "USERF1"}, "matched_evidence_fact_ids": {}}
    response = {"iterations": [{"python_trace": {"requirement_graph": {"formula_variables": [
        {"variable_name": "x", "scenario_id": "A", "status": "bound", "bound_fact_id": "USERF1"}]}}}]}
    assert scorer.binding_audit(task, response, source)["binding_complete"]
    assert scorer.binding_audit(task, response, source)["userf_runtime_bound"] == 1
    response["iterations"][0]["python_trace"]["requirement_graph"]["formula_variables"][0]["scenario_id"] = "B"
    assert not scorer.binding_audit(task, response, source)["binding_complete"]


def test_recovery_gain_is_external_not_self_reported():
    task = mini_task()
    task["ground_truth"]["source_ids"] = ["R13_K"]
    task["ground_truth"]["formula_sources"] = [["R13_K", "K=y/x"]]
    response = {"internal_sources": [{"evidence_id": "KB1", "chunk_id": SOURCE["chunk_id"],
                                      "document": SOURCE["document"], "page": SOURCE["page"],
                                      "excerpt": "K=y/x"}],
                "iterations": [{"evidence_added": ["KB1"], "python_trace": {"recovery_triggered": True,
                    "recovery_rounds": [{"round": 1, "required_gain": False,
                                         "new_source_ids": ["KB1"], "query": "equilibrium ratio"}]}}]}
    audit = scorer.recovery_audit(task, response, scorer.CATALOG_DATA,
                                  {"evidence_inputs": {}, "inputs": []})
    assert audit["recovery_round_1_required_gain"]
    assert audit["recovery_source_complete_gain"]


def test_checklist_and_contract_external_output_completeness():
    task = mini_task()
    spec = {"output_id": "OUT_A_K", "name": "A_K", "semantic_type": "numeric",
            "unit": "dimensionless", "scenario_id": "A"}
    response = {"iterations": [{"python_trace": {"required_output_checklist": [
        {"semantic_name": "per_case", "scenario_id": "A"}],
        "calculation_contract": {"required_outputs": [spec]}, "contract_complete": True}}]}
    assert scorer.checklist_audit(task, response)["checklist_output_recall"] == 1
    assert scorer.contract_audit(task, response)["external_contract_complete"]
    spec["unit"] = "psi"
    assert not scorer.contract_audit(task, response)["external_contract_complete"]


def test_assumption_guard_false_negative():
    task = mini_task()
    response = {"computations": [{"computation_id": "CALC1", "code_record": "porosity = 0.31"}],
                "iterations": [{"python_trace": {"assumption_guard_passed": True}}]}
    audit = scorer.assumption_audit(task, response, {"inputs": [], "evidence_inputs": {}})
    assert audit["assumption_guard_false_negative"]


def test_calc_gt_correct_and_grounded_adoption_are_separate():
    task, response = mini_contract()
    source = {"matched_user_fact_ids": {}, "matched_evidence_fact_ids": {}, "source_complete_external": True}
    binding = {"binding_required": 0, "binding_complete": None}
    contract = scorer.contract_audit(task, response)
    assumption = scorer.assumption_audit(task, response, {"inputs": [], "evidence_inputs": {}})
    final = scorer.final_targets(task, response["final_answer"])
    audit = scorer.calc_audit(task, response, source, binding, contract, assumption, final)
    assert audit["gt_correct_calc"] and audit["grounded_adoption"]
    response["final_answer"] = "A K = 2.5 dimensionless"
    final = scorer.final_targets(task, response["final_answer"])
    audit = scorer.calc_audit(task, response, source, binding, contract, assumption, final)
    assert audit["gt_correct_calc"] and not audit["grounded_adoption"]


def test_final_numeric_requires_the_right_scenario_and_unit():
    task = mini_task()
    assert scorer.final_targets(task, "B K = 2.5 dimensionless")["numeric_correct"] == 0
    result = scorer.final_targets(task, "A K = 2.5")
    assert result["numeric_correct"] == 1 and result["unit_correct"] == 0
    assert scorer.final_targets(task, "A K = 2.5 dimensionless")["target_complete"]


def test_typed_targets_need_explicit_ranking_and_leader():
    rank, leader = TASK["ground_truth"]["typed_targets"]
    assert not scorer.typed_match("A K=2.5; B K=2; C K=1.75; D K=1.25", rank)
    assert scorer.typed_match("K ranking: A > B > C > D", rank)
    assert not scorer.typed_match("A K=2.5", leader)
    assert scorer.typed_match("A is the highest-K leader", leader)


def test_strong_benefit_vs_weak_unattributed_improvement():
    off = {"criterion_pass_preliminary": {"C2": False}, "numeric_correct": 0}
    on = {"criterion_pass_preliminary": {"C2": True}, "numeric_correct": 1,
          "gt_correct_calc": True, "grounded_adoption": True}
    assert scorer.strong_benefit(off, on)
    assert not scorer.weak_numeric_improvement(off, on)
    on["gt_correct_calc"] = False
    assert not scorer.strong_benefit(off, on)
    assert scorer.weak_numeric_improvement(off, on)


def test_furthest_stage_and_trace_integrity_error():
    response = {"iterations": [{"python_trace": {"source_complete": True,
                       "requirement_graph": {"missing_variables": ["x"]},
                       "tool_selected": True, "subprocess_reached": True}}]}
    recovery = {"initial_source_complete_external": False, "recovery_success": False,
                "post_recovery_source_complete_external": False}
    audit = scorer.stage_audit(response, recovery, {"binding_complete": False},
                               {"checklist_built": False}, {"contract_generated": False,
                               "external_contract_complete": False}, {"assumption_guard_pass": False},
                               {"product_validated_calc": False, "externally_valid_calc": False,
                                "gt_correct_calc": False, "grounded_adoption": False})
    assert audit["furthest_stage"] == 16
    assert "source_complete_with_missing_variables" in audit["trace_integrity_errors"]


def test_paired_bootstrap_reproducible():
    values = [(0, 1), (1, 0), (0, 0)]
    assert scorer.paired_bootstrap(values) == scorer.paired_bootstrap(values)
    assert scorer.paired_bootstrap(values)["samples"] == 10000


def test_blind_packet_removes_tool_condition_and_trace():
    response = {"final_answer": "Python calculated 2.5 [CALC1].",
                "internal_sources": [], "python_calls_total": 1,
                "iterations": [{"python_trace": {"recovery_triggered": True}}],
                "condition": "python_on"}
    packet = reviewer.blind_packet(TASK, response, "BR-001")
    assert reviewer.no_condition_leakage(packet)
    assert "Python" not in json.dumps(packet)
    assert "CALC1" not in json.dumps(packet)
    assert "python_trace" not in json.dumps(packet)
