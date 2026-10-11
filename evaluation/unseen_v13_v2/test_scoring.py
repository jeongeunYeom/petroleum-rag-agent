"""Small synthetic checks for pre-registered scoring guards; no product run."""

from score_eval import DATASET, decision, names_specific_missing_inputs, numbers_match, rejects_premise, score_row
from collections import Counter


def test_expected_numeric_and_percent_match() -> None:
    kf = next(t for t in DATASET["tasks"] if t["id"] == "KF01")
    assert numbers_match(kf, "The verified result is 17% porosity.")
    assert not numbers_match(kf, "The result is 22% porosity.")


def test_lucky_number_without_validated_calc_is_not_success() -> None:
    task = next(t for t in DATASET["tasks"] if t["id"] == "DC02")
    raw = {"wall_seconds": 1.0, "result": {"run_id": "synthetic", "run_status": "completed",
           "status": "achieved", "final_answer": "The drop is 315 psi.", "computations": [],
           "action_history": [], "internal_sources": []}}
    review = {"estimated_cost_usd": 0, "verdict": {
        "claim_supported": [True], "material_hallucination": False,
        "unsupported_claim_count": 0, "engineering_contradiction_count": 0,
        "numeric_correct": True, "unit_correct": True, "operand_binding_correct": True,
        "safe_refusal": None, "false_premise_corrected": None,
        "citation_semantic_supported": None, "unnecessary_refusal": False,
        "failure_note": "Correct prose number but no execution."}}
    row = score_row(task, raw, review)
    assert not row["goal_success"]
    assert not row["validated_calc"]
    assert "routing" in row["failure_labels"]


def test_decision_gate_is_pre_registered() -> None:
    metrics = {"goal_success_pct": 72, "hallucination_pct": 8,
               "citation_semantic_support_pct": 82, "unanswerable_safe_handling_pct": 100}
    assert decision(metrics, Counter()) == "PASS"
    assert decision({**metrics, "goal_success_pct": 49}, Counter()) == "FAIL"


def test_reviewer_cannot_credit_missing_citation() -> None:
    task = next(t for t in DATASET["tasks"] if t["id"] == "SF01")
    raw = {"wall_seconds": 1.0, "result": {"run_id": "synthetic", "run_status": "completed",
           "status": "achieved", "final_answer": "Relative permeability is effective divided by absolute.",
           "internal_sources": [], "computations": []}}
    review = {"estimated_cost_usd": 0, "verdict": {
        "claim_supported": [True], "material_hallucination": False,
        "unsupported_claim_count": 0, "engineering_contradiction_count": 0,
        "numeric_correct": None, "unit_correct": None, "operand_binding_correct": None,
        "safe_refusal": None, "false_premise_corrected": None,
        "citation_semantic_supported": True, "unnecessary_refusal": False,
        "failure_note": "Reviewer saw the gold, but no cited evidence exists."}}
    row = score_row(task, raw, review)
    assert row["reviewer_semantic_judgment"]
    assert not row["citation_semantic_supported"]
    assert not row["goal_success"]


def test_explicit_korean_rejection_and_specific_clarification() -> None:
    assert rejects_premise("그 전제는 맞지 않습니다. 압력 차이는 계면을 가로지릅니다.")
    assert not names_specific_missing_inputs(
        "The supplied values did not establish a complete calculation. Please check the missing input, unit, or operation.")
    assert names_specific_missing_inputs(
        "I need reservoir area, net thickness and hydrocarbon saturation to calculate the volume.")


def test_generic_unanswerable_refusal_gets_no_missing_input_claim() -> None:
    task = next(t for t in DATASET["tasks"] if t["id"] == "UA04")
    raw = {"wall_seconds": 1.0, "result": {"run_id": "synthetic", "run_status": "stopped",
           "status": "stopped", "final_answer": "Please check the missing input, unit, or operation.",
           "internal_sources": [], "computations": []}}
    review = {"estimated_cost_usd": 0, "verdict": {
        "claim_supported": [True, True], "material_hallucination": False,
        "unsupported_claim_count": 0, "engineering_contradiction_count": 0,
        "numeric_correct": None, "unit_correct": None, "operand_binding_correct": None,
        "safe_refusal": True, "false_premise_corrected": None,
        "citation_semantic_supported": None, "unnecessary_refusal": False,
        "failure_note": "Reviewer credited a generic notice."}}
    row = score_row(task, raw, review)
    assert row["claim_coverage"] == 0.5
    assert not row["safe_unanswerable"]
