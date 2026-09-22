import csv
import json

from scripts.run_well_test_benchmark import (
    build_summary,
    direct_ollama_answer,
    figure_retrieval_hit,
    write_csv,
    write_json,
)


def test_summary_exposes_paper_metrics():
    results = [
        {
            "category": "flow_regime",
            "question_type": "text",
            "expected_behavior": "answer",
            "infrastructure_error": None,
            "initial_benchmark_passed": False,
            "final_benchmark_passed": True,
            "initial_validator_passed": False,
            "final_validator_passed": True,
            "initial_answer_passed": False,
            "final_answer_passed": True,
            "hallucination_detected": False,
            "citation_correctness": True,
            "engineering_contradiction_count": 0,
            "false_premise_correction_success": True,
            "unsupported_engineering_claim_count": 0,
            "repair_attempts": 1,
            "engineering_validation_passed": True,
            "rewrite_success": True,
            "expected_document_hit": True,
            "preferred_page_hit": True,
            "figure_retrieval_hit": None,
            "attempts": 2,
            "retrieval_seconds": 1.0,
            "generation_seconds": 2.0,
            "total_seconds": 3.0,
            "final_answer": "answer",
        },
        {
            "category": "refusal",
            "question_type": "hallucination",
            "expected_behavior": "refuse",
            "infrastructure_error": None,
            "initial_benchmark_passed": False,
            "final_benchmark_passed": False,
            "initial_validator_passed": True,
            "final_validator_passed": True,
            "initial_answer_passed": False,
            "final_answer_passed": False,
            "hallucination_detected": True,
            "citation_correctness": False,
            "engineering_contradiction_count": 2,
            "false_premise_correction_success": False,
            "unsupported_engineering_claim_count": 1,
            "repair_attempts": 2,
            "engineering_validation_passed": False,
            "rewrite_success": False,
            "expected_document_hit": None,
            "preferred_page_hit": None,
            "figure_retrieval_hit": None,
            "attempts": 1,
            "retrieval_seconds": 0.5,
            "generation_seconds": 1.0,
            "total_seconds": 1.5,
            "final_answer": "unsupported number",
        },
    ]

    summary = build_summary(results)

    assert summary["answer_accuracy"] == 0.5
    assert summary["initial_answer_accuracy"] == 0.0
    assert summary["hallucination_rate"] == 0.5
    assert summary["citation_correctness_rate"] == 0.5
    assert summary["engineering_contradiction_count"] == 2
    assert summary["false_premise_correction_success_rate"] == 0.5
    assert summary["unsupported_engineering_claim_count"] == 1
    assert summary["average_engineering_contradiction_count"] == 1.0
    assert summary["average_unsupported_engineering_claim_count"] == 0.5
    assert summary["engineering_validation_pass_rate"] == 0.5
    assert summary["average_repair_attempts"] == 1.5
    assert summary["retrieval_document_recall_at_k"] == 1.0
    assert summary["average_retrieval_seconds"] == 0.75
    assert summary["average_total_seconds"] == 2.25
    assert summary["category_metrics"]["flow_regime"]["answer_accuracy"] == 1.0


def test_engineering_metrics_are_written_to_json_and_csv(tmp_path):
    row = {
        "id": "WT-002",
        "engineering_contradiction_count": 1,
        "false_premise_detected": True,
        "false_premise_correction_success": False,
        "unsupported_engineering_claim_count": 2,
        "repair_attempts": 2,
        "engineering_validation_passed": False,
    }
    json_path = tmp_path / "result.json"
    csv_path = tmp_path / "result.csv"

    write_json(json_path, {"results": [row]})
    write_csv(csv_path, [row])

    json_row = json.loads(json_path.read_text(encoding="utf-8"))["results"][0]
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        csv_row = next(csv.DictReader(handle))

    for field in (
        "engineering_contradiction_count",
        "false_premise_detected",
        "false_premise_correction_success",
        "unsupported_engineering_claim_count",
        "repair_attempts",
        "engineering_validation_passed",
    ):
        assert field in json_row
        assert field in csv_row
    assert csv_row["repair_attempts"] == "2"
    assert csv_row["engineering_validation_passed"] == "False"


def test_figure_retrieval_requires_a_preferred_page_hit():
    item = {"question_type": "figure", "preferred_pages": [219]}

    assert figure_retrieval_hit(item, [{"page": 219}]) is True
    assert figure_retrieval_hit(item, [{"page": 220}]) is False
    assert figure_retrieval_hit(item, []) is False
    assert figure_retrieval_hit({"question_type": "text"}, []) is None


def test_direct_ollama_answer_uses_chat_endpoint(monkeypatch):
    captured = {}

    def fake_http_json(method, url, *, payload=None, timeout=0):
        captured.update(
            method=method,
            url=url,
            payload=payload,
            timeout=timeout,
        )
        return {"message": {"content": "direct answer"}}

    monkeypatch.setattr(
        "scripts.run_well_test_benchmark.http_json",
        fake_http_json,
    )

    answer, elapsed = direct_ollama_answer(
        "http://localhost:11434/",
        model="qwen3:8b",
        question="What is radial flow?",
        timeout=12.0,
    )

    assert answer == "direct answer"
    assert elapsed >= 0
    assert captured == {
        "method": "POST",
        "url": "http://localhost:11434/api/chat",
        "payload": {
            "model": "qwen3:8b",
            "stream": False,
            "messages": [
                {"role": "user", "content": "What is radial flow?"}
            ],
        },
        "timeout": 12.0,
    }
