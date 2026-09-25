import csv
import json

import pytest

from scripts.run_well_test_benchmark import (
    benchmark_evaluation_fields,
    build_summary,
    direct_ollama_answer,
    correct_figure_number_hit,
    figure_retrieval_hit,
    require_nonempty_knowledge_base,
    reevaluate_saved_benchmark,
    write_csv,
    write_json,
)
from app.services.benchmark_evaluator import evaluate_benchmark_answer
from app.services.refusal_policy import NO_EVIDENCE_REFUSAL


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


def test_figure_metrics_are_written_and_summarized(tmp_path):
    row = {
        "id": "WT-009",
        "category": "figure_mixing",
        "question_type": "figure",
        "expected_behavior": "answer",
        "infrastructure_error": None,
        "initial_benchmark_passed": False,
        "final_benchmark_passed": True,
        "initial_answer_passed": False,
        "final_answer_passed": True,
        "hallucination_detected": False,
        "figure_required": True,
        "figure_hit": True,
        "figure_retrieval_hit": True,
        "correct_figure_number_hit": True,
        "correct_figure_page_hit": True,
        "figure_numeric_support_pass": True,
        "figure_citation_correctness": True,
    }
    csv_path = tmp_path / "figures.csv"

    write_csv(csv_path, [row])
    summary = build_summary([row])

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        csv_row = next(csv.DictReader(handle))
    for field in (
        "figure_required",
        "figure_hit",
        "correct_figure_number_hit",
        "correct_figure_page_hit",
        "figure_numeric_support_pass",
        "figure_citation_correctness",
    ):
        assert csv_row[field] == "True"
    assert summary["figure_required_count"] == 1
    assert summary["figure_hit_count"] == 1
    assert summary["correct_figure_number_hit_rate"] == 1.0
    assert summary["correct_figure_page_hit_rate"] == 1.0
    assert summary["figure_numeric_support_pass_rate"] == 1.0
    assert summary["figure_citation_correctness_rate"] == 1.0


def test_correct_figure_number_hit_requires_each_requested_figure():
    item = {
        "question_type": "figure",
        "question": "Compare Figure 2 and Figure 3.",
        "required_concepts": [],
        "required_patterns": [],
    }

    assert correct_figure_number_hit(
        item,
        [
            {"figure_number": "Figure 2"},
            {"figure_number": "Figure 3"},
        ],
    ) is True
    assert correct_figure_number_hit(
        item,
        [{"figure_number": "Figure 2"}],
    ) is False


def test_benchmark_fails_fast_for_empty_knowledge_base(capsys):
    checklist = {
        "checks": {
            "data_dir": {"path": "C:/clone/data"},
            "chroma": {"path": "C:/clone/data/vector_db"},
        },
        "knowledge_base": {"documents": 0, "chunks": 0},
    }

    with pytest.raises(RuntimeError, match="knowledge base collection is empty"):
        require_nonempty_knowledge_base(checklist)

    output = capsys.readouterr().out
    assert "resolved_data_dir=C:/clone/data" in output
    assert "knowledge_base_chunks=0" in output


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


def test_runner_fields_match_benchmark_evaluator():
    item = {
        "expected_behavior": "answer",
        "required_patterns": [],
        "forbidden_patterns": [],
    }
    evaluation = evaluate_benchmark_answer(
        item,
        "Radial flow has a horizontal derivative plateau. [KB1]",
        sources=[
            {
                "evidence_id": "KB1",
                "excerpt": "Radial flow has a horizontal derivative plateau.",
            }
        ],
    )

    row = benchmark_evaluation_fields(evaluation, evaluation)

    assert row["final_answer_passed"] == evaluation.answer_passed
    assert row["final_benchmark_passed"] == evaluation.passed
    assert row["hallucination_detected"] == evaluation.hallucination_detected
    assert row["engineering_contradiction_count"] == 0
    assert row["unsupported_engineering_claim_count"] == 0


def test_saved_benchmark_reevaluation_is_offline_and_preserves_input(
    tmp_path,
    monkeypatch,
):
    benchmark_items = [
        {
            "id": f"WT-{index:03d}",
            "category": "refusal",
            "question": f"unsupported question {index}",
            "expected_behavior": "refuse",
            "preferred_pages": [],
            "required_patterns": [],
            "forbidden_patterns": [],
        }
        for index in range(1, 31)
    ]
    benchmark_path = tmp_path / "benchmark.json"
    write_json(benchmark_path, benchmark_items)
    source = tmp_path / "saved.json"
    rows = [
        {
            "id": item["id"],
            "question": item["question"],
            "category": "refusal",
            "question_type": "hallucination",
            "expected_behavior": "refuse",
            "infrastructure_error": None,
            "initial_answer": NO_EVIDENCE_REFUSAL,
            "final_answer": NO_EVIDENCE_REFUSAL,
            "sources": [],
            "citation_correctness": False,
        }
        for item in benchmark_items
    ]
    write_json(
        source,
        {
            "run_id": "original",
            "condition": "saved",
            "benchmark_file": str(benchmark_path),
            "results": rows,
        },
    )
    original_bytes = source.read_bytes()
    monkeypatch.setattr(
        "scripts.run_well_test_benchmark.http_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("network must not be called")
        ),
    )

    json_path, csv_path, payload = reevaluate_saved_benchmark(
        source,
        run_id="reeval",
    )

    assert source.read_bytes() == original_bytes
    assert json_path != source
    assert json_path.exists() and csv_path.exists()
    assert payload["results"][0]["id"] == rows[0]["id"]
    assert payload["results"][0]["final_answer"] == rows[0]["final_answer"]
    assert payload["results"][0]["sources"] == rows[0]["sources"]
    assert payload["summary"]["answer_accuracy"] == 1.0
    assert payload["summary"]["exact_refusal_rate"] == 1.0
