import json
import re
from collections import Counter
from pathlib import Path

import pytest

from app.services.benchmark_suite import (
    BenchmarkSuiteValidationError,
    build_benchmark_manifest,
    materialize_benchmark_items,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_repository_benchmark_has_paper_minimum_and_balanced_types():
    raw = json.loads(
        (PROJECT_ROOT / "evaluation" / "well_test_agent_benchmark.json").read_text(
            encoding="utf-8"
        )
    )

    items = materialize_benchmark_items(raw)
    manifest = build_benchmark_manifest(items)

    assert manifest["question_count"] == 32
    assert manifest["concept_group_count"] == 16
    assert manifest["variant_count"] == 16
    assert manifest["question_type_counts"] == {
        "figure": 12,
        "hallucination": 6,
        "text": 14,
    }


def test_variant_inherits_evaluation_rules_from_base():
    base = {
        "id": "WT-001",
        "category": "flow_regime",
        "question": "base",
        "expected_behavior": "answer",
        "required_patterns": ["radial"],
        "forbidden_patterns": [],
        "preferred_pages": [1],
    }
    variants = [
        {
            "id": f"WT-{index:03d}",
            "variant_of": "WT-001",
            "question": f"variant {index}",
        }
        for index in range(2, 31)
    ]

    items = materialize_benchmark_items([base, *variants])

    assert items[-1]["required_patterns"] == ["radial"]
    assert items[-1]["concept_group"] == "WT-001"
    assert items[-1]["is_variant"] is True


def test_rejects_suite_below_minimum_question_count():
    with pytest.raises(BenchmarkSuiteValidationError, match="최소 30개"):
        materialize_benchmark_items([], minimum_questions=30)


def test_frozen_petroleum_heldout_has_expected_balance():
    raw = json.loads(
        (PROJECT_ROOT / "evaluation" / "petroleum_agent_heldout_v1.json").read_text(
            encoding="utf-8"
        )
    )

    items = materialize_benchmark_items(raw)

    assert len(items) == 60
    assert Counter(item["domain"] for item in items) == {
        "well_test": 24,
        "reservoir": 24,
        "cross_domain": 12,
    }
    assert Counter(item["task_type"] for item in items) == {
        "concept": 24,
        "false_premise": 12,
        "figure": 10,
        "numeric": 8,
        "citation": 6,
    }
    assert Counter(item["question_type"] for item in items) == {
        "text": 38,
        "hallucination": 12,
        "figure": 10,
    }
    assert len({item["question"] for item in items}) == 60
    for item in items:
        for pattern in [*item["required_patterns"], *item["forbidden_patterns"]]:
            re.compile(pattern)


def test_frozen_petroleum_heldout_manifest_matches_without_prompt_leakage():
    raw = json.loads(
        (PROJECT_ROOT / "evaluation" / "petroleum_agent_heldout_v1.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = json.loads(
        (
            PROJECT_ROOT
            / "evaluation"
            / "petroleum_agent_heldout_v1_manifest.json"
        ).read_text(encoding="utf-8")
    )

    benchmark_by_id = {item["id"]: item for item in raw}
    manifest_by_id = {item["id"]: item for item in manifest["items"]}

    assert len(benchmark_by_id) == len(raw) == 60
    assert len(manifest_by_id) == len(manifest["items"]) == 60
    assert benchmark_by_id.keys() == manifest_by_id.keys()
    assert manifest["ground_truth_source"] == {
        "type": "internal_chromadb_only",
        "collection": "petroleum_knowledge",
        "collection_count": 18976,
        "document_count": 12,
        "web_used": False,
        "verified_on": "2026-10-02",
    }

    for item_id, item in benchmark_by_id.items():
        provenance = manifest_by_id[item_id]
        assert "ground_truth_summary" not in item
        assert provenance["ground_truth_summary"].strip()
        assert provenance["source_document"] in item["expected_documents"]
        assert provenance["source_page"] in item["preferred_pages"]
        assert provenance["source_locator"].strip()
