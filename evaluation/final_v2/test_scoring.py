"""Evaluation-only regression checks; no product or frozen benchmark mutation."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from review_semantic import review_input
from score_deterministic import action_metrics, grade, provenance
from summarize import score_row


class FrozenV2ScoringTests(unittest.TestCase):
    def test_empty_answer_never_hallucinates_or_covers_claims(self) -> None:
        task = {"category": "clarification", "expected_claims": ["A", "B"],
                "expected_after_resume": {"result": 2}, "expected_units": {"result": "psi"},
                "expected_source_ids": []}
        review = {"claim_verdicts": [True, True], "partial_or_better": True,
                  "hallucination": True, "unsupported_claim_count": 1,
                  "engineering_contradiction_count": 1, "numeric_accuracy": True,
                  "unit_accuracy": True, "formula_accuracy": True,
                  "false_premise_handled": None, "safe_refusal_correct": None,
                  "citation_semantic_support": None, "note": "misattributed content"}
        row = {"answer": "", "track": "agent", "citation_ids": [],
               "calculation_provenance_completeness": False}
        scored = score_row(row, review, task)
        self.assertEqual(scored["claim_verdicts"], [False, False])
        self.assertFalse(scored["hallucination"])
        self.assertFalse(scored["numeric_accuracy"])
        self.assertFalse(scored["unit_accuracy"])

    def test_applicable_null_numeric_is_failure(self) -> None:
        task = {"category": "direct_calculation", "expected_claims": ["result"],
                "required_numeric_result": {"result": 5}}
        review = {"claim_verdicts": [True], "partial_or_better": True,
                  "hallucination": False, "unsupported_claim_count": 0,
                  "engineering_contradiction_count": 0, "numeric_accuracy": None,
                  "unit_accuracy": None, "formula_accuracy": None,
                  "false_premise_handled": None, "safe_refusal_correct": None,
                  "citation_semantic_support": None, "note": ""}
        row = {"answer": "result is 5", "track": "qwen_closed_book", "citation_ids": []}
        self.assertFalse(score_row(row, review, task)["numeric_accuracy"])

    def test_formula_source_only_applicable_to_kb_or_clarification(self) -> None:
        direct = {"category": "direct_calculation"}
        kb = {"category": "kb_calculation", "expected_formula": "x=a+b"}
        self.assertIsNone(provenance(direct, {}, {})[1])
        self.assertFalse(provenance(kb, {}, {})[1])

    def test_validated_sweep_extrema_satisfy_analysis_action(self) -> None:
        task = {"category": "simulation", "expected_actions": ["SIMULATE", "ANALYZE", "VERIFY"]}
        response = {"action_history": [{"action_type": "simulate"}, {"action_type": "verify"}],
                    "computations": [{"validation_passed": True,
                                      "output_manifest": {"OUT_BEST_PARAMETER": {}, "OUT_BEST_RESULT": {}}}]}
        self.assertTrue(action_metrics(task, {}, response)["correct_action_selection"])

    def test_no_source_no_citation_is_not_citation_failure(self) -> None:
        task = {"task_id": "X", "category": "literature", "domain": "test", "expected_source_ids": []}
        payload = {"model_id": "qwen3:8b", "wall_seconds": 1,
                   "response": {"final_answer": "no citation needed", "action_history": []}}
        self.assertIsNone(grade(task, "agent", payload, {}, set())["citation_id_correctness"])

    def test_reviewer_sees_follow_up_input(self) -> None:
        task = {"task_id": "X-NONBENCH", "category": "clarification", "question": "Need pressure",
                "continuation": "Pressure is 30 psi", "expected_claims": ["pressure known"],
                "expected_source_ids": []}
        item, _ = review_input(task, {})
        self.assertEqual(item["user_continuation_after_clarification"], task["continuation"])


if __name__ == "__main__":
    unittest.main()
