"""Evaluation-only contract checks; no Agent, model, retrieval, or KB runtime."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.evidence_fact_registry import EvidenceFactRegistry
from app.services.formula_source_registry import FormulaSourceRegistry, normalize_formula
from app.services.user_fact_registry import UserFactRegistry
from scripts.preflight_python_tool_heldout_v3r1 import CATALOG, BENCHMARK, EXCLUSIONS, can_freeze, matched


def test_unsupported_user_unit_fails_contract() -> None:
    assert not matched(["API", 33, "degAPI"], UserFactRegistry.from_topic("API=33 degAPI").records)


def test_header_only_evidence_unit_fails_contract() -> None:
    records = EvidenceFactRegistry.from_evidence([{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": "Permeability (mD)\nA 80\nB 90"
    }]).records
    assert not matched(["A_permeability", 80, "mD"], records)


def test_unparseable_specialist_formula_fails_contract() -> None:
    records = FormulaSourceRegistry.from_evidence([{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": "PI = q / ΔP"
    }]).records
    assert not any(row.expression_candidate for row in records)


def test_valid_user_evidence_and_formula_pass_contract() -> None:
    assert matched(["phi", 0.21, ""], UserFactRegistry.from_topic("phi=0.21").records)
    facts = EvidenceFactRegistry.from_evidence([{
        "evidence_id": "KB1", "source_type": "knowledge_base",
        "text": "Layer A: thickness=12 ft, permeability=85 mD"
    }]).records
    assert matched(["Layer_A_thickness", 12, "ft"], facts)
    assert matched(["Layer_A_permeability", 85, "mD"], facts)
    formulas = FormulaSourceRegistry.from_evidence([{
        "evidence_id": "KB2", "source_type": "knowledge_base", "text": "A = kh/kv"
    }]).records
    assert any(row.expression_candidate and normalize_formula(row.raw_span) == "a=kh/kv" for row in formulas)


def test_required_recall_is_hard_gate_and_failed_preflight_cannot_freeze() -> None:
    facts = UserFactRegistry.from_topic("k=10 mD").records
    assert not all(matched(x, facts) for x in [["k", 10, "mD"], ["h", 20, "ft"]])
    assert not can_freeze({"status": "FAIL", "llm_calls": 0, "tasks": [{"status": "FAIL"}]})
    assert not can_freeze({"status": "PASS", "llm_calls": 1, "tasks": [{"status": "PASS"}]})


def test_twelve_task_distribution_and_source_exclusion() -> None:
    tasks = json.loads(BENCHMARK.read_text(encoding="utf-8"))["tasks"]
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    exclusions = json.loads(EXCLUSIONS.read_text(encoding="utf-8"))["excluded_pages"]
    assert len(tasks) == 12
    assert [sum(t["python_expected"] == kind for t in tasks) for kind in
            ("required", "optional", "not_needed")] == [8, 2, 2]
    assert [sum(t["evaluation_stratum"] == kind for t in tasks) for kind in
            ("pipeline", "end_to_end")] == [6, 2]
    assert all(source["page"] not in exclusions.get(source["document"], []) for source in catalog.values())
