import json
from collections import Counter
from pathlib import Path

from scripts.prepare_semantic_review import REVIEW_COLUMNS, build_review_artifacts
from scripts.score_semantic_review import score_review


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUBRIC_PATH = PROJECT_ROOT / "evaluation" / "petroleum_agent_heldout_v1_semantic_rubric.json"
BENCHMARK_PATH = PROJECT_ROOT / "evaluation" / "petroleum_agent_heldout_v1.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_semantic_rubric_matches_frozen_benchmark_schema():
    rubric = load(RUBRIC_PATH)
    benchmark = load(BENCHMARK_PATH)
    rubric_by_id = {item["id"]: item for item in rubric["items"]}

    assert len(rubric_by_id) == len(rubric["items"]) == 60
    assert set(rubric_by_id) == {item["id"] for item in benchmark}
    assert Counter(item["domain"] for item in rubric["items"]) == {
        "well_test": 24,
        "reservoir": 24,
        "cross_domain": 12,
    }
    assert Counter(item["task_type"] for item in rubric["items"]) == {
        "concept": 24,
        "false_premise": 12,
        "figure": 10,
        "numeric": 8,
        "citation": 6,
    }
    assert sum(item["false_premise_required"] for item in rubric["items"]) == 12
    assert sum(item["figure_criterion"] is not None for item in rubric["items"]) == 10
    assert sum(item["numeric_criterion"] is not None for item in rubric["items"]) == 8
    assert sum(item["citation_criterion"] is not None for item in rubric["items"]) == 6

    benchmark_by_id = {item["id"]: item for item in benchmark}
    for item_id, item in rubric_by_id.items():
        assert item["question"] == benchmark_by_id[item_id]["question"]
        assert 2 <= len(item["required_claims"]) <= 4
        assert [claim["claim_id"] for claim in item["required_claims"]] == [
            f"C{index}" for index in range(1, len(item["required_claims"]) + 1)
        ]
        assert all(claim["description"].strip() for claim in item["required_claims"])
        assert "final_answer" not in item
        if item["numeric_criterion"]:
            for check in item["numeric_criterion"]["checks"]:
                assert {"expected_value", "expected_values", "tolerance", "unit"} <= set(check)
        if item["figure_criterion"]:
            assert {
                "axis_claim_ids",
                "series_claim_ids",
                "figure_element_claim_ids",
                "engineering_interpretation_claim_ids",
            } <= set(item["figure_criterion"])


def test_blind_packet_and_model_neutral_aggregation():
    rubric = load(RUBRIC_PATH)
    answers = [{"id": item["id"], "final_answer": f"answer {item['id']}"} for item in rubric["items"]]
    packet, rows = build_review_artifacts(rubric, answers)

    assert len(packet["items"]) == len(rows) == 60
    assert set(packet["items"][0]) == {
        "anonymous_answer_id",
        "question",
        "answer",
        "rubric_atomic_claims",
    }
    assert not ({"model", "run_id", "strict_pass", "strict_answer_accuracy"} & set(packet["items"][0]))

    for row, item in zip(rows, rubric["items"]):
        row.update(
            {
                "evaluation_condition": "same_evidence",
                "contradiction_present": "0",
                "safe_refusal": "0",
                "hallucination_present": "0",
                "overall_score_0_1_2": "2",
            }
        )
        for index in range(1, len(item["required_claims"]) + 1):
            row[f"claim_{index}"] = "1"
        if item["false_premise_required"]:
            row["false_premise_recognized"] = "1"
            row["false_premise_corrected"] = "1"
        if item["numeric_criterion"]:
            row["numeric_correct"] = "1"
        if item["citation_criterion"]:
            row["citation_correct"] = "1"
        if item["figure_criterion"]:
            row["figure_correct"] = "1"
            if item["figure_criterion"]["axis_claim_ids"]:
                row["axis_correct"] = "1"
            if item["figure_criterion"]["series_claim_ids"]:
                row["series_correct"] = "1"
            row["figure_interpretation_correct"] = "1"
        assert set(row) == set(REVIEW_COLUMNS)

    result = score_review(rubric, rows, strict_answer_accuracy=0.13333333333333333)
    assert result["evaluation_condition"] == "same_evidence"
    assert result["strict_answer_accuracy"] == 0.13333333333333333
    assert result["semantic_answer_accuracy"] == 1.0
    assert result["semantic_partial_or_better"] == 1.0
    assert result["mean_claim_coverage"] == 1.0
    assert result["false_premise_total"] == 12
    assert result["false_premise_recognition_rate"] == 1.0
    assert result["false_premise_correction_rate"] == 1.0
    assert result["numeric_accuracy"] == 1.0
    assert result["figure_semantic_accuracy"] == 1.0
    assert result["citation_accuracy"] == 1.0
