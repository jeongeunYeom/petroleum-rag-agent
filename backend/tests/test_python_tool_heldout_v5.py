"""Evaluation-only gates; product execution is intentionally absent."""

from __future__ import annotations

import ast
import copy
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend/scripts"), str(ROOT / "evaluation/reference")]
import freeze_python_tool_heldout_v5 as freeze  # noqa: E402
import preflight_python_tool_heldout_v5 as preflight  # noqa: E402
from python_tool_heldout_v5_ground_truth import reference_outputs  # noqa: E402

BASE = ROOT / "evaluation"
BENCHMARK = json.loads((BASE / "python_tool_heldout_v5.json").read_text(encoding="utf-8"))
REFERENCES = json.loads((BASE / "reference/python_tool_heldout_v5_reference_outputs.json").read_text(encoding="utf-8"))
TASKS = BENCHMARK["tasks"]


def test_distribution_and_unique_new_ids():
    assert len(TASKS) == len({t["task_id"] for t in TASKS}) == 12
    assert Counter(t["python_expected"] for t in TASKS) == {"required": 8, "optional": 2, "not_needed": 2}
    assert Counter(t["evaluation_stratum"] for t in TASKS if t["python_expected"] == "required") == {
        "pipeline_direct": 4, "pipeline_recovery_challenge": 2, "end_to_end": 2}
    assert Counter(t["domain"] for t in TASKS) == {"reservoir_engineering": 5, "well_test": 4, "formation_evaluation": 3}
    assert all(t["task_id"].startswith("PT5-") for t in TASKS)


def test_old_scenario_source_and_smoke_contamination_zero():
    report = json.loads((BASE / "review/python_tool_heldout_v5_preflight.json").read_text(encoding="utf-8"))
    assert report["old_task_overlap"] == report["old_source_overlap"] == report["synthetic_smoke_reuse"] == 0
    assert all(row["old_source_overlap"] is False for row in
               json.loads((BASE / "python_tool_heldout_v5_source_catalog.json").read_text(encoding="utf-8")).values())


def test_user_evidence_formula_representability():
    report, audit = preflight.audit()
    assert report["status"] == audit["status"] == "PASS"
    assert report["representability"] == {"user": {"expected": 47, "matched": 47},
                                           "evidence": {"expected": 7, "matched": 7},
                                           "formula": {"expected": 8, "matched": 8}}
    assert report["required_canonical_targets"] >= 60
    assert report["required_numeric_targets"] >= 50
    assert report["kb_collection_count"] == 18976
    assert all(value == 0 for value in report["calls"].values())
    assert audit["conflict_count"] == 0


def test_preflight_has_no_forbidden_product_calls():
    tree = ast.parse((ROOT / "backend/scripts/preflight_python_tool_heldout_v5.py").read_text(encoding="utf-8"))
    forbidden = {"GoalResearchAgent", "GoalToolPlanner", "build_requirement_graph", "required_output_checklist",
                 "CalculationContractBuilder", "GoalPythonAnalysis", "research", "query"}
    invoked = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not invoked & forbidden


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t["task_id"])
def test_reference_reproducible_and_all_projections_consistent(task):
    reference = REFERENCES[task["task_id"]]
    fresh = reference_outputs(task["task_id"], {name: value for name, value, _ in reference["inputs"]},
                              {key: row[2] for key, row in reference["evidence_inputs"].items()})
    assert [r["value"] for r in fresh] == [r["value"] for r in reference["raw_reference_calculation"]]
    assert not preflight.validate_ground_truth_consistency(task, reference)


@pytest.mark.parametrize("kind,field,value,code", [
    ("numeric", "value", -999, "NUMERIC"),
    ("numeric", "unit", "wrong_unit", "UNIT"),
    ("ranking", "value", ["WRONG"], "RANKING"),
    ("ranking", "ranking_of", {"WRONG": "missing"}, "ORPHAN"),
    ("numeric", "scenario_id", "WRONG", "SCENARIO"),
])
def test_gt_conflicts_block_freeze(kind, field, value, code):
    task = copy.deepcopy(TASKS[0])
    if kind == "ranking":
        target = next(row for row in task["ground_truth"]["canonical_targets"] if row["target_type"] == "ranking")
    else:
        target = next(row for row in task["ground_truth"]["canonical_targets"] if row["target_type"] == "numeric")
    target[field] = value
    errors = preflight.validate_ground_truth_consistency(task, REFERENCES[task["task_id"]])
    assert any(code in error for error in errors)


def test_typed_and_required_missing_conflicts():
    task = copy.deepcopy(TASKS[0])
    label = next(row for row in task["ground_truth"]["canonical_targets"] if row["target_type"] == "label")
    label["value"] = "WRONG"
    assert any("TYPED" in error or "ARGMAX" in error for error in
               preflight.validate_ground_truth_consistency(task, REFERENCES[task["task_id"]]))
    task = copy.deepcopy(TASKS[0])
    task["ground_truth"]["numeric_targets"].pop()
    assert any("REQUIRED_TARGET_MISSING" in error for error in
               preflight.validate_ground_truth_consistency(task, REFERENCES[task["task_id"]]))


def test_freeze_blocked_on_failed_preflight(monkeypatch):
    original = freeze.load
    def failed(p):
        row = original(p)
        if p == freeze.FILES["preflight"]:
            row["status"] = "FAIL"
        return row
    monkeypatch.setattr(freeze, "load", failed)
    with pytest.raises(ValueError, match="Freeze blocked"):
        freeze.frozen_manifest()


def test_unit_convention_and_required_targets():
    for task in TASKS:
        targets = task["ground_truth"]["canonical_targets"]
        assert all(row["required"] for row in targets)
        assert all(row["unit"] for row in targets if row["target_type"] == "numeric")
        assert all(row["unit"] is None for row in targets if row["target_type"] != "numeric")
