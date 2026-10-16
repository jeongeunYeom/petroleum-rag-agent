"""Synthetic checks for the post-freeze evaluator error corrections."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aggregate_corrected import citation_supported, equation_constants_match, score_row, value_match


def task(**kwargs):
    base = {"question_id": "SYN", "task_type": "calculation", "domain": "synthetic",
            "answerable": True, "required_claims": ["computed result"],
            "required_values": [{"value": 20, "tolerance": 0.01}],
            "acceptable_equation": None, "required_evidence_type": "KB_FORMULA_AND_VALIDATED_CALC"}
    return base | kwargs


def review():
    return {"review": {"parsed": {"claim_checks": [{"index": 0, "answer_present": True,
        "answer_correct": True, "evidence_support": True, "citation_support": "KB1"}],
        "numeric_and_units_correct": True, "calculation_correct": True, "refusal": False,
        "unsupported_new_claims": 0}}}


def test_empty_final_answer_cannot_pass_from_gold_or_evidence():
    row = score_row(task(), "agent", {"response": {"final_answer": "", "computations": []}}, review())
    assert row["accuracy"] is False
    assert row["claim_coverage"] == 0
    assert row["grounded_accuracy"] is False


def test_generic_safe_stop_cannot_pass_calculation():
    answer = "근거 자료에서 필요한 관계식이나 입력값을 확인하지 못해 수치 결과를 계산하거나 추정하지 않았습니다."
    row = score_row(task(), "agent", {"response": {"final_answer": answer, "computations": []}}, review())
    assert row["accuracy"] is False
    assert row["calculation_accuracy"] is False


def test_numeric_range_and_coefficient_gates():
    assert value_match("30,000–40,000 mg/L", [{"min": 30000, "max": 40000}])
    assert not value_match("20,000 mg/L", [{"min": 30000, "max": 40000}])
    assert not equation_constants_match("v = 0.32083 q/A", "v = 0.32086 q/A")


def test_citation_ids_must_appear_in_answer_and_sources():
    assert citation_supported("KB1", "Answer [KB1]", {"KB1"})
    assert not citation_supported("KB1", "Answer", {"KB1"})
    assert not citation_supported("KB2", "Answer [KB2]", {"KB1"})


def test_enumerated_functions_do_not_require_a_literal_count_digit():
    sample = task(task_type="document_specific_fact", required_evidence_type="KB_TEXT",
                  required_claims=["support", "seal", "access", "connect"],
                  required_values=[{"value": 4, "tolerance": 0}])
    verdict = review()
    verdict["review"]["parsed"]["claim_checks"] = [
        {"index": index, "answer_present": True, "answer_correct": True,
         "evidence_support": True, "citation_support": True} for index in range(4)]
    verdict["review"]["parsed"]["numeric_and_units_correct"] = None
    raw = {"response": {"final_answer": "Support [KB1]. Seal [KB1]. Access [KB1]. Connect [KB1].",
                        "internal_sources": [{"evidence_id": "KB1"}]}}
    row = score_row(sample, "agent", raw, verdict)
    assert row["numeric_accuracy"] is True
    assert row["accuracy"] is True
