"""Pure evaluator checks; uses synthetic examples, not benchmark outputs."""

import unittest

from score_deterministic import citation_check, numeric_hit, recall, unit_hit


class DeterministicScoringTests(unittest.TestCase):
    def test_numeric_tolerance_and_input_mismatch(self):
        self.assertTrue(numeric_hit("22.64 °API", 22.64, 0.01))
        self.assertFalse(numeric_hit("22.40 °API", 22.64, 0.01))

    def test_unit_check(self):
        self.assertTrue(unit_hit("33.03 °API", "api"))
        self.assertFalse(unit_hit("33.03", "api"))

    def test_citation_id_must_resolve(self):
        task = {"expected_source_ids": ["S"]}
        sources = [{"evidence_id": "KB1"}]
        self.assertEqual(citation_check(task, "Claim [KB1]", sources, applicable=True), (True, 1, 0))
        self.assertEqual(citation_check(task, "Claim [KB2]", sources, applicable=True), (False, 1, 1))

    def test_document_and_page_recall_are_distinct(self):
        task = {"expected_source_ids": ["S"], "figure_requirement": False}
        catalog = {"S": {"document": "doc.pdf", "page": 10}}
        response = {"internal_sources": [{"document": "doc.pdf", "page": 11}], "figures": []}
        self.assertEqual(recall(task, response, catalog), (1.0, 0.0, None))


if __name__ == "__main__":
    unittest.main()
