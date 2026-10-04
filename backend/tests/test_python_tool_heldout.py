"""Evaluation-only regressions; no held-out model calls or product changes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from scripts import run_python_tool_heldout as runner
from scripts import score_python_tool_heldout as scorer


BENCHMARK, MANIFEST = runner.load_and_validate()
TASKS = BENCHMARK["tasks"]
SETTINGS = MANIFEST["model_settings"]


def test_frozen_schema_and_independent_ground_truth():
    assert len(TASKS) == 10
    assert sum(len(t["ground_truth"]["numeric_targets"]) for t in TASKS) == 32
    assert MANIFEST["user_fact_required_count"] == 5


def test_a_b_requests_differ_only_in_python_permission():
    task = TASKS[0]
    a = runner.make_request(task, "python_off", SETTINGS).model_dump()
    b = runner.make_request(task, "python_on", SETTINGS).model_dump()
    assert (a.pop("allow_python_execution"), a.pop("python_execution_approved")) == (False, False)
    assert (b.pop("allow_python_execution"), b.pop("python_execution_approved")) == (True, True)
    assert a == b
    assert a["use_internal"] and not a["use_external"]
    assert a["model"] == "qwen3:8b" and a["temperature"] == 0 and a["seed"] == 42
    assert a["max_iterations"] == 4 and a["no_progress_patience"] == 2


def test_fake_controller_full_a_b_persists_without_leakage(tmp_path, monkeypatch):
    class FakeResponse:
        def model_dump(self, **_kwargs):
            return {"final_answer": "fixture", "iterations": [], "computations": []}

    class FakeController:
        def __init__(self):
            self.calls = []

        async def run(self, run_id, request):
            self.calls.append((run_id, request.model_dump()))
            return FakeResponse()

    fake = FakeController()
    from app.api import goal_research_routes
    monkeypatch.setattr(goal_research_routes, "cached_goal_research_service", lambda: SimpleNamespace(controller=fake))
    asyncio.run(runner.run_full(BENCHMARK, MANIFEST, tmp_path, "python-heldout-v1-fixture"))
    assert len(fake.calls) == 20
    for condition in ("python_off", "python_on"):
        saved = json.loads((tmp_path / f"{condition}.json").read_text(encoding="utf-8"))
        assert saved["complete"] and len(saved["results"]) == 10
        assert all(row["condition"] == condition for row in saved["results"])
        assert all(row["request"]["allow_python_execution"] == (condition == "python_on") for row in saved["results"])
        assert all("/" not in run_id and "\\" not in run_id for run_id, _ in fake.calls)
    assert json.loads((tmp_path / "raw/frozen_assets_before.json").read_text()) == json.loads((tmp_path / "raw/frozen_assets_after.json").read_text())


def test_numeric_tolerance_unit_and_missing_scenario():
    target = {"name": "k_effective", "value": 121.5, "unit": "mD", "abs_tolerance": 0.1}
    assert scorer.numeric_hits("The effective permeability is 121.48 mD.", target)["passed"]
    assert not scorer.numeric_hits("The effective permeability is 121.48 ft.", target)["passed"]
    assert not scorer.numeric_hits("The effective permeability is 121.8 mD.", target)["passed"]
    assert not scorer.numeric_hits("No result for the low-phi case.", TASKS[3]["ground_truth"]["numeric_targets"][2])["passed"]


def test_funnel_selection_and_optional_exclusion():
    rows = []
    for condition in ("python_off", "python_on"):
        for task in TASKS:
            selected = condition == "python_on" and task["python_expected"] in ("required", "optional")
            rows.append({"task_id": task["task_id"], "condition": condition,
                         "python_expected": task["python_expected"], "goal_success": True,
                         "external_coverage": 1.0, "numeric_passed": 1, "numeric_total": 1,
                         "numeric_accuracy": 1.0, "unit_accuracy": 1.0,
                         "hallucination": False, "engineering_contradiction": False,
                         "latency_seconds": 1.0, "python_seconds": 0.0, "python_calls": 0,
                         "python_attempts": 0, "tool_selected": selected, "plan_present": selected,
                         "permission_passed": selected, "facts_verified": selected,
                         "call_boundary_reached": selected, "code_generated": selected,
                         "sandbox_validation_passed": selected, "subprocess_reached": selected,
                         "result_validation_passed": selected, "calc_id": "CALC1" if selected else None,
                         "failure_attribution": None})
    summary = scorer.aggregate(TASKS, rows)
    assert summary["selection"] == {"true_positive": 6, "false_positive_not_needed": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert summary["overuse"]["optional"]["selected"] == 2
    assert summary["overuse"]["not_needed"]["executed"] == 0
    assert summary["funnel"]["subprocess_reached"] == 6


def test_calc_json_and_user_formula_provenance(tmp_path):
    task = TASKS[0]
    output = Path("results/goal-research/example/analysis/analysis_001.json")
    path = tmp_path / "workspace" / output
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"result": {"k_effective": 121.5}, "inputs": {"k": 35}, "summary": "k effective 121.5 mD"}), encoding="utf-8")
    source = BENCHMARK["source_catalog"]["R314"]
    row = {"response": {"final_answer": "Effective permeability is 121.5 mD [CALC1] [USER1] [KB1]",
                        "internal_sources": [{"evidence_id": "KB1", **source}],
                        "computations": [{"validation_passed": True, "output_files": [output.as_posix()],
                                          "source_input_ids": ["USER1"], "source_evidence_ids": [],
                                          "formula_evidence_ids": ["KB1"]}]}}
    final, calc = scorer.numeric_and_calc(task, row, tmp_path)
    assert final["k_effective"]["passed"] and calc["k_effective"]
    prov = scorer.provenance(task, row)
    assert prov["user_fact_provenance_correct"] and prov["formula_provenance_correct"]
    row["response"]["computations"][0]["formula_evidence_ids"] = ["USER1"]
    assert not scorer.provenance(task, row)["formula_provenance_correct"]


def test_failure_attribution_and_paired_bootstrap_are_deterministic():
    row = {"tool_selected": True, "plan_present": True, "permission_passed": True,
           "blocked_stage": "input_fact_verification_failed", "code_generated": False,
           "sandbox_validation_passed": False, "subprocess_reached": False,
           "result_validation_passed": False, "calc_id": None, "goal_success": False}
    assert scorer.failure_attribution(row) == "input_fact_failure"
    first = scorer.bootstrap([0, 1, 0], [1, 1, 0])
    assert first == scorer.bootstrap([0, 1, 0], [1, 1, 0])
    assert first["delta"] == 1 / 3
