"""Evaluation-infrastructure checks; these do not run the frozen product."""

from score_eval import generic_abstention, numeric_values_present, score_row, summarize


def sample():
    task = {"id": "T", "category": "single_fact", "difficulty": "easy", "answerable": True,
            "expected_claims": ["Supported claim"], "source_ids": ["R465"], "question": "Q", "reference_answer": "A"}
    result = {"run_id": "r", "run_status": "completed", "status": "achieved", "final_answer": "A [KB1]",
              "internal_sources": [{"evidence_id": "KB1", "document": "Heriot-Watt University - Reservoir Engineering.pdf", "page": 465}],
              "computations": [], "action_history": [], "timing": {}}
    review = {"cost_usd": .001, "verdict": {"claim_supported": [True], "material_hallucination": False,
              "engineering_contradiction_count": 0, "unsupported_claim_count": 0,
              "unnecessary_refusal": False, "citation_semantic_supported": True,
              "numeric_correct": None, "unit_correct": None, "safe_refusal": None,
              "false_premise_corrected": None, "failure_note": "supported"}}
    return task, {"result": result, "wall_seconds": 4}, review


def test_supported_citation_and_goal_succeed():
    task, raw, review = sample()
    row = score_row(task, raw, review)
    assert row["goal_success"] and row["gold_page_hit"]
    assert summarize([row])["goal_success_pct"] == 100


def test_wrong_page_or_semantically_wrong_citation_fails():
    task, raw, review = sample()
    raw["result"]["internal_sources"][0]["page"] = 464
    review["verdict"]["citation_semantic_supported"] = False
    row = score_row(task, raw, review)
    assert not row["goal_success"]
    assert "retrieval_page_miss" in row["failure_labels"]


def test_calc_requires_validation_even_with_correct_answer():
    task, raw, review = sample()
    task.update({"category": "calculation", "source_ids": [], "expected_numeric": {"value": 2}})
    raw["result"]["final_answer"] = "2"
    review["verdict"].update({"numeric_correct": True, "unit_correct": True})
    assert not score_row(task, raw, review)["goal_success"]
    raw["result"]["computations"] = [{"validation_passed": True}]
    assert score_row(task, raw, review)["goal_success"]


def test_unanswerable_requires_safe_refusal():
    task, raw, review = sample()
    task.update({"category": "unanswerable", "source_ids": [], "answerable": False})
    raw["result"]["status"] = "insufficient_evidence"
    raw["result"]["final_answer"] = "Cannot determine without inputs."
    review["verdict"]["safe_refusal"] = True
    assert score_row(task, raw, review)["goal_success"]
    review["verdict"]["safe_refusal"] = False
    assert not score_row(task, raw, review)["goal_success"]


def test_numeric_guard_accepts_equivalent_percent_but_not_wrong_number():
    task = {"expected_numeric": {"fraction": 0.1}, "tolerance": 0.01}
    assert numeric_values_present(task, "The fraction is 10%.")
    assert not numeric_values_present(task, "The fraction is 20%.")


def test_generic_abstention_cannot_satisfy_claims_or_missing_input_explanation():
    task, raw, review = sample()
    raw["result"]["final_answer"] = "The retrieved sources did not directly support an answer."
    assert generic_abstention(raw["result"]["final_answer"])
    row = score_row(task, raw, review)
    assert row["claim_coverage"] == 0 and not row["goal_success"]
    task.update({"category": "unanswerable", "answerable": False, "source_ids": []})
    review["verdict"].update({"safe_refusal": True})
    assert not score_row(task, raw, review)["goal_success"]
