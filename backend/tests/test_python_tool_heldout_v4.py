"""Evaluation-only regression checks; no LLM or live KB is needed in CI."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend/scripts"), str(ROOT / "evaluation/reference")]

from preflight_python_tool_heldout_v4 import can_freeze  # noqa: E402
from python_tool_heldout_v4_ground_truth import expected_outputs  # noqa: E402
from score_python_tool_heldout_v4 import (  # noqa: E402
    aggregate_stages, calc_score, citation_mapping, contract_score, furthest_stage,
    numeric_match, paired_bootstrap, score, strong_benefit, trace_integrity, typed_match,
    weak_numeric_improvement,
)
from review_python_tool_heldout_v4 import blind_packet, no_condition_leakage  # noqa: E402

BENCHMARK = json.loads((ROOT / "evaluation/python_tool_heldout_v4.json").read_text(encoding="utf-8"))
CATALOG = json.loads((ROOT / "evaluation/python_tool_heldout_v4_source_catalog.json").read_text(encoding="utf-8"))
EXCLUSIONS = json.loads((ROOT / "evaluation/python_tool_heldout_v4_source_exclusions.json").read_text(encoding="utf-8"))
PREFLIGHT = json.loads((ROOT / "evaluation/review/python_tool_heldout_v4_preflight.json").read_text(encoding="utf-8"))


def task(task_id: str) -> dict:
    return next(row for row in BENCHMARK["tasks"] if row["task_id"] == task_id)


def test_frozen_schema_and_balance():
    tasks = BENCHMARK["tasks"]
    assert len(tasks) == 12 == len({row["task_id"] for row in tasks})
    assert Counter(row["python_expected"] for row in tasks) == {"required": 8, "optional": 2, "not_needed": 2}
    assert Counter(row["evaluation_stratum"] for row in tasks if row["python_expected"] == "required") == {
        "pipeline": 6, "end_to_end": 2
    }
    assert sum(row["domain"] == "reservoir_engineering" for row in tasks) == 6
    assert sum(row["domain"] in {"well_test", "formation_evaluation"} for row in tasks) == 6
    assert sum(len(row["ground_truth"]["expected_contract_outputs"]) for row in tasks
               if row["python_expected"] == "required") >= 50
    assert sum(len(row["ground_truth"]["expected_contract_outputs"]) for row in tasks
               if row["evaluation_stratum"] == "pipeline") >= 38


def test_preflight_is_complete_and_llm_free():
    assert can_freeze(PREFLIGHT)
    assert PREFLIGHT["llm_calls"] == PREFLIGHT["agent_calls"] == PREFLIGHT["planner_calls"] == 0
    assert PREFLIGHT["summary"]["expected_user"] == PREFLIGHT["summary"]["matched_user"]
    assert PREFLIGHT["summary"]["expected_evidence"] == PREFLIGHT["summary"]["matched_evidence"]
    assert PREFLIGHT["summary"]["expected_formula"] == PREFLIGHT["summary"]["matched_formula"]


@pytest.mark.parametrize("key", ["user", "evidence", "formula"])
def test_preflight_missing_registry_fact_blocks_freeze(key):
    report = copy.deepcopy(PREFLIGHT)
    row = next(item for item in report["tasks"] if item[f"expected_{key}"] > 0)
    row[f"matched_{key}"] -= 1
    assert not can_freeze(report)


def test_no_old_exact_source_overlap():
    old = EXCLUSIONS["old_sources"]
    assert not [
        key for key, source in CATALOG.items()
        if any(row["chunk_id"] == source["chunk_id"] or
               (row["document"], row["page"]) == (source["document"], source["page"]) for row in old)
    ]


def test_independent_reference_matches_frozen_numeric_gt():
    for row in BENCHMARK["tasks"]:
        actual = expected_outputs(row["task_id"])
        targets = {item["semantic_name"]: item for item in row["ground_truth"]["numeric_targets"]}
        assert actual.keys() == targets.keys()
        assert all(abs(value - targets[name]["value"]) <= targets[name]["abs_tolerance"] / 10
                   for name, value in actual.items())


def test_frozen_typed_targets_follow_independent_arithmetic():
    values = expected_outputs("PT4-RE-P1")
    assert task("PT4-RE-P1")["ground_truth"]["typed_targets"][0]["value"] == [
        key.split("_")[0] for key, value in values.items() if key.startswith("C") and value == values["max_Pc"]
    ]
    saturation = expected_outputs("PT4-FE-P3")
    ranking = [key.split("_")[0] for key in sorted(
        (key for key in saturation if key.startswith("Z")), key=lambda key: saturation[key], reverse=True
    )]
    assert task("PT4-FE-P3")["ground_truth"]["ranking_targets"][0]["value"] == ranking


@pytest.mark.xfail(strict=True, reason="Frozen v4 P2 GT says C4; independent minimum is C5. Benchmark invalid.")
def test_frozen_p2_lowest_cell_matches_reference():
    porosity = expected_outputs("PT4-RE-P2")
    cells = {key.split("_")[0]: value for key, value in porosity.items() if key.startswith("C")}
    assert task("PT4-RE-P2")["ground_truth"]["typed_targets"][0]["value"] == max(cells, key=cells.get)
    assert task("PT4-RE-P2")["ground_truth"]["typed_targets"][1]["value"] == min(cells, key=cells.get)


def test_numeric_tolerance_and_unit_scoring():
    target = {"semantic_name": "C1_Pc", "value": 26, "unit": "psi", "abs_tolerance": .05}
    assert numeric_match("C1 Pc = 26.01 psi", target)["unit"]
    assert not numeric_match("C1 Pc = 26.2 psi", target)["value"]
    assert numeric_match("C1 Pc = 26.01 mD", target)["value"]
    assert not numeric_match("C1 Pc = 26.01 mD", target)["unit"]
    percent = {"semantic_name": "Z1_Sw", "value": .5, "unit": "dimensionless", "abs_tolerance": .001}
    assert numeric_match("Z1 Sw = 50%", percent)["unit"]


def test_typed_and_ranking_scoring():
    label = {"semantic_name": "highest", "type": "label", "value": "T8"}
    ranking = {"semantic_name": "rank", "type": "ranking", "value": ["Z8", "Z4", "Z6"]}
    assert typed_match("Highest: T8.", label)
    assert typed_match("Z8 > Z4 > Z6", ranking)
    assert not typed_match("Z4 > Z8 > Z6", ranking)


def test_contract_output_recall_and_completeness():
    row = task("PT4-RE-O1")
    calc = {"computation_id": "CALC1", "output_manifest": {
        "OUT_PC": {"name": "Pc", "value": 24, "unit": "psi", "semantic_type": "numeric"}
    }}
    scored = contract_score(row, {"computations": [calc]})
    assert scored["contract_output_recall_observable"] == 1
    assert scored["contract_output_precision_observable"] == 1
    assert scored["contract_unit_accuracy_observable"] == 1
    assert scored["contract_external_complete_observable"]
    calc["output_manifest"]["OUT_PC"]["unit"] = "mD"
    assert contract_score(row, {"computations": [calc]})["contract_unit_accuracy_observable"] == 0


def test_calc_complete_and_gt_correct_are_distinct():
    row = task("PT4-RE-O1")
    calc = {"computation_id": "CALC1", "validation_passed": True, "contract_validation_passed": True,
            "output_manifest": {"OUT_PC": {"name": "Pc", "value": 23, "unit": "psi"}}}
    scored = calc_score(row, {"computations": [calc]})
    assert scored["calc_created"] and scored["contract_complete_calc"]
    assert not scored["gt_correct_calc"]
    calc["output_manifest"]["OUT_PC"]["value"] = 24
    assert calc_score(row, {"computations": [calc]})["gt_correct_calc"]


def test_recovery_aggregation_furthest_stage_and_integrity():
    response = {"iterations": [
        {"python_trace": {"tool_selected": True, "recovery_triggered": True,
                          "recovery_query_count": 1}},
        {"python_trace": {"plan_present": True, "recovery_materialization_success": True,
                          "code_generated": True, "subprocess_reached": True}},
    ]}
    calc = {"calc_created": False, "contract_complete_calc": False, "gt_correct_calc": False}
    stages = aggregate_stages(response, calc, "")
    assert stages["tool_selected"] and stages["recovery_triggered"] and stages["recovery_success"]
    assert stages["subprocess"] and furthest_stage(stages) == 11
    bad = {**stages, "validated_calc": True, "subprocess": False}
    assert "calc_without_subprocess" in trace_integrity(bad, [])
    assert "contract_complete_with_missing_outputs" in trace_integrity(stages, [
        {"contract_complete": True, "missing_output_ids": ["OUT_X"]}
    ])


def test_pair_hashing_and_strong_benefit():
    response = {"final_answer": "Value 2 [CALC1] [KB2]", "internal_sources": [
        {"evidence_id": "KB2", "document": "x.pdf", "page": 3, "chunk_id": "c"}
    ], "computations": [{"computation_id": "CALC1", "source_evidence_ids": ["KB2"]}]}
    mapping = citation_mapping(response)
    assert mapping["[KB2]"] == ["x.pdf", 3, "c"]
    assert "[CALC1]" in mapping
    off = {"goal_success_preliminary": False}
    on = {"goal_success_preliminary": True, "gt_correct_calc": True, "grounded_adoption": True}
    assert strong_benefit(off, on)
    on["grounded_adoption"] = False
    assert not strong_benefit(off, on)
    assert weak_numeric_improvement({"numeric_correct": 1}, {
        "numeric_correct": 2, "gt_correct_calc": False, "grounded_adoption": False
    })


def test_paired_bootstrap_reproducible():
    pairs = [(0, 1), (1, 1), (1, 0), (0, 1)]
    assert paired_bootstrap(pairs) == paired_bootstrap(pairs)
    assert paired_bootstrap(pairs)["samples"] == 10000


def test_blind_packet_hides_condition_and_calc_state():
    packet = blind_packet(task("PT4-RE-P1"), {
        "final_answer": "Python result 26 psi [CALC1] from [USERF1]",
        "internal_sources": [],
    }, "BR-001")
    assert no_condition_leakage(packet)
    text = json.dumps(packet)
    assert "[CALC1]" not in text and "[USERF1]" not in text
    assert "python_off" not in text and "python_on" not in text


def test_scorer_smoke_all_24_rows(tmp_path):
    from run_python_tool_heldout_v4 import load_frozen
    _, manifest = load_frozen()
    run_dir = tmp_path / "raw"
    run_dir.mkdir()
    for condition in ("python_off", "python_on"):
        payload = {
            "run_id": "synthetic-evaluation-test", "condition": condition,
            "benchmark_sha256": manifest["benchmark_sha256"], "complete": True,
            "results": [{"task_id": item["task_id"], "elapsed_seconds": 1.0,
                         "response": {"final_answer": "", "iterations": [], "internal_sources": [],
                                      "computations": [], "web_sources": []}}
                        for item in BENCHMARK["tasks"]],
        }
        (run_dir / f"{condition}.json").write_text(json.dumps(payload), encoding="utf-8")
    result = score(run_dir, tmp_path / "review")
    assert len(result["rows"]) == 24
    assert result["populations"]["required_8"]["python_on"]["n"] == 8
    assert result["funnel"]["pipeline_6"]["subprocess"] == 0


def test_frozen_preflight_hash_is_portable_across_checkout_line_endings(tmp_path):
    from run_python_tool_heldout_v4 import digest
    manifest = json.loads((ROOT / "evaluation/python_tool_heldout_v4_manifest.json").read_text(encoding="utf-8"))
    lf_blob = subprocess.check_output([
        "git", "show", "213231fd5c4f6bc29cefebd37f98fc9656c488cb:evaluation/review/python_tool_heldout_v4_preflight.json"
    ], cwd=ROOT)
    path = tmp_path / "preflight.json"
    path.write_bytes(lf_blob)
    assert digest(path, preflight_report=True) == manifest["preflight_sha256"]


def test_invalidated_benchmark_cannot_be_rerun():
    from run_python_tool_heldout_v4 import main
    invalidation = json.loads((ROOT / "evaluation/review/python_tool_heldout_v4_invalidated.json").read_text(encoding="utf-8"))
    assert invalidation["status"] == "INVALIDATED_BEFORE_COMPLETE_AB"
    assert invalidation["issue"]["independent_reference"] == "C5"
    with pytest.raises(RuntimeError, match="invalidated"):
        main()
