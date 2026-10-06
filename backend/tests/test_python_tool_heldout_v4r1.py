"""Evaluation-only checks. No LLM, Agent, or live KB is needed in CI."""

from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend/scripts"), str(ROOT / "evaluation/reference")]

from freeze_python_tool_heldout_v4r1 import build_manifest, verify_freeze_gate  # noqa: E402
from preflight_python_tool_heldout_v4r1 import (  # noqa: E402
    can_freeze, digest, find_old_source_overlap, validate_ground_truth_consistency,
)
from python_tool_heldout_v4r1_ground_truth import reference_outputs  # noqa: E402
from score_python_tool_heldout_v4r1 import (  # noqa: E402
    aggregate_stages, calc_score, citation_mapping, contract_score, furthest_stage,
    numeric_match, paired_bootstrap, score, strong_benefit, trace_integrity, typed_match,
    weak_numeric_improvement,
)
from review_python_tool_heldout_v4r1 import blind_packet, no_condition_leakage  # noqa: E402

BASE = ROOT / "evaluation"
BENCHMARK = json.loads((BASE / "python_tool_heldout_v4r1.json").read_text(encoding="utf-8"))
CATALOG = json.loads((BASE / "python_tool_heldout_v4r1_source_catalog.json").read_text(encoding="utf-8"))
EXCLUSIONS = json.loads((BASE / "python_tool_heldout_v4r1_source_exclusions.json").read_text(encoding="utf-8"))
REFERENCES = json.loads((BASE / "reference/python_tool_heldout_v4r1_reference_outputs.json").read_text(encoding="utf-8"))
PREFLIGHT = json.loads((BASE / "review/python_tool_heldout_v4r1_preflight.json").read_text(encoding="utf-8"))
GT_AUDIT = json.loads((BASE / "review/python_tool_heldout_v4r1_gt_consistency.json").read_text(encoding="utf-8"))


def task(task_id: str) -> dict:
    return copy.deepcopy(next(row for row in BENCHMARK["tasks"] if row["task_id"] == task_id))


def codes(row: dict) -> set[str]:
    return {error.split(":", 1)[0] for error in validate_ground_truth_consistency(
        row, REFERENCES[row["task_id"]]
    )}


def test_new_schema_and_distribution():
    tasks = BENCHMARK["tasks"]
    assert BENCHMARK["benchmark_id"] == "python_tool_heldout_v4r1"
    assert len(tasks) == 12 == len({row["task_id"] for row in tasks})
    assert all(row["task_id"].startswith("PT4R1-") for row in tasks)
    assert Counter(row["python_expected"] for row in tasks) == {"required": 8, "optional": 2, "not_needed": 2}
    assert Counter(row["evaluation_stratum"] for row in tasks if row["python_expected"] == "required") == {
        "pipeline": 6, "end_to_end": 2
    }
    assert sum(row["domain"] == "reservoir_engineering" for row in tasks) == 6
    assert sum(row["domain"] in {"well_test", "formation_evaluation"} for row in tasks) == 6
    assert sum(len(row["ground_truth"]["canonical_targets"]) for row in tasks
               if row["python_expected"] == "required") >= 55
    assert sum(len(row["ground_truth"]["canonical_targets"]) for row in tasks
               if row["evaluation_stratum"] == "pipeline") >= 40


def test_preflight_phases_pass_without_llm_or_agent_calls():
    assert can_freeze(PREFLIGHT, GT_AUDIT)
    assert PREFLIGHT["llm_calls"] == PREFLIGHT["agent_calls"] == PREFLIGHT["planner_calls"] == 0
    assert PREFLIGHT["summary"]["expected_user"] == PREFLIGHT["summary"]["matched_user"]
    assert PREFLIGHT["summary"]["expected_evidence"] == PREFLIGHT["summary"]["matched_evidence"]
    assert PREFLIGHT["summary"]["expected_formula"] == PREFLIGHT["summary"]["matched_formula"]
    assert GT_AUDIT["conflict_count"] == 0
    assert all(not row["conflicts"] for row in GT_AUDIT["tasks"])


@pytest.mark.parametrize("kind", ["user", "evidence", "formula"])
def test_missing_input_contract_blocks_freeze(kind):
    report = copy.deepcopy(PREFLIGHT)
    row = next(item for item in report["tasks"] if item[f"expected_{kind}"] > 0)
    row[f"matched_{kind}"] -= 1
    assert not can_freeze(report, GT_AUDIT)


def test_gt_failure_blocks_freeze():
    audit = copy.deepcopy(GT_AUDIT)
    audit["tasks"][0]["conflicts"].append("GT_TYPED_VALUE_CONFLICT")
    assert not can_freeze(PREFLIGHT, audit)


def test_source_exclusions_have_no_page_or_chunk_overlap():
    assert EXCLUSIONS["documented_exceptions"] == []
    assert not [key for key, source in CATALOG.items()
                if find_old_source_overlap(source, EXCLUSIONS["old_sources"])]


def test_reference_calculator_is_reproducible_and_canonical_matches():
    for row in BENCHMARK["tasks"]:
        ref = REFERENCES[row["task_id"]]
        inputs = {name: value for name, value, _ in ref["inputs"]}
        evidence = {name: item[2] for name, item in ref["evidence_inputs"].items()}
        assert reference_outputs(row["task_id"], inputs, evidence) == [
            {key: value for key, value in target.items() if key not in {"target_id", "required", "source"}}
            for target in ref["canonical_targets"]
        ]
        assert not validate_ground_truth_consistency(row, ref)


def test_previous_bug_class_typed_duplicate_value_is_hard_failure():
    row = task("PT4R1-WT-P3")
    target = next(x for x in row["ground_truth"]["typed_targets"] if x["semantic_name"] == "lowest_Pwf_well")
    target["value"] = "A"
    assert "GT_TYPED_VALUE_CONFLICT" in codes(row)
    assert "GT_DUPLICATE_SEMANTIC_CONFLICT" in codes(row)


def test_numeric_conflict():
    row = task("PT4R1-RE-P1")
    row["ground_truth"]["canonical_targets"][0]["value"] += 100
    assert "GT_NUMERIC_CONFLICT" in codes(row)


def test_unit_conflict():
    row = task("PT4R1-RE-P1")
    row["ground_truth"]["numeric_targets"][0]["unit"] = "mD"
    assert "GT_UNIT_CONFLICT" in codes(row)


def test_ranking_conflict():
    row = task("PT4R1-RE-P2")
    row["ground_truth"]["ranking_targets"][0]["value"].reverse()
    assert "GT_RANKING_CONFLICT" in codes(row)


def test_tie_conflict():
    row = task("PT4R1-RE-P2")
    target = next(x for x in row["ground_truth"]["canonical_targets"] if x["semantic_name"] == "top_interfaces")
    target["value"] = target["value"][:1]
    assert "GT_TIE_CONFLICT" in codes(row)


def test_argmin_conflict():
    row = task("PT4R1-WT-P3")
    target = next(x for x in row["ground_truth"]["canonical_targets"] if x["semantic_name"] == "lowest_Pwf_well")
    target["value"] = "A"
    assert "GT_ARGMIN_CONFLICT" in codes(row)


def test_argmax_conflict():
    row = task("PT4R1-RE-P1")
    target = next(x for x in row["ground_truth"]["canonical_targets"] if x["semantic_name"] == "max_period")
    target["value"] = "A"
    assert "GT_ARGMAX_CONFLICT" in codes(row)


def test_scenario_mapping_conflict():
    row = task("PT4R1-RE-P1")
    row["ground_truth"]["canonical_targets"][0]["scenario_id"] = "B"
    assert "GT_SCENARIO_MAPPING_CONFLICT" in codes(row)


def test_duplicate_semantic_conflict():
    row = task("PT4R1-RE-P1")
    row["ground_truth"]["canonical_targets"].append(copy.deepcopy(row["ground_truth"]["canonical_targets"][0]))
    assert "GT_DUPLICATE_SEMANTIC_CONFLICT" in codes(row)


def test_orphan_projection_conflict():
    row = task("PT4R1-RE-P1")
    row["ground_truth"]["numeric_targets"].append({
        "target_id": "T_GHOST", "semantic_name": "ghost", "value": 1, "unit": "bbl",
        "abs_tolerance": 0.01, "required": True,
    })
    assert "GT_ORPHAN_TARGET" in codes(row)


def test_required_target_missing_conflict():
    row = task("PT4R1-RE-P1")
    row["ground_truth"]["canonical_targets"].pop(0)
    assert "GT_REQUIRED_TARGET_MISSING" in codes(row)


def test_freeze_gate_rejects_stale_or_failed_artifacts():
    hashes = {
        "benchmark_draft": PREFLIGHT["hashes"]["benchmark_draft_sha256"],
        "source_catalog": PREFLIGHT["hashes"]["source_catalog_sha256"],
        "source_exclusions": PREFLIGHT["hashes"]["source_exclusions_sha256"],
        "reference_calculator": PREFLIGHT["hashes"]["reference_calculator_sha256"],
        "reference_outputs": PREFLIGHT["hashes"]["reference_outputs_sha256"],
    }
    verify_freeze_gate(PREFLIGHT, GT_AUDIT, hashes)
    hashes["benchmark_draft"] = "bad"
    with pytest.raises(ValueError, match="changed"):
        verify_freeze_gate(PREFLIGHT, GT_AUDIT, hashes)
    with pytest.raises(ValueError, match="both PASS"):
        verify_freeze_gate({**PREFLIGHT, "status": "FAIL"}, GT_AUDIT, hashes)


def test_manifest_freeze_and_portable_hash_when_present(tmp_path):
    manifest = BASE / "python_tool_heldout_v4r1_manifest.json"
    if not manifest.exists():
        pytest.skip("Freeze deliberately follows this pre-freeze test run")
    frozen = json.loads(manifest.read_text(encoding="utf-8"))
    assert build_manifest(PREFLIGHT, GT_AUDIT)["benchmark_sha256"] == frozen["benchmark_sha256"]
    from run_python_tool_heldout_v4r1 import load_frozen
    assert len(load_frozen()[0]["tasks"]) == 12
    path = tmp_path / "preflight.json"
    path.write_bytes((BASE / "review/python_tool_heldout_v4r1_preflight.json").read_bytes().replace(b"\r\n", b"\n"))
    assert digest(path) == frozen["preflight_sha256"]
    path.write_bytes(path.read_bytes() + b" ")
    assert digest(path) != frozen["preflight_sha256"]


def test_numeric_tolerance_unit_typed_and_ranking_scoring():
    target = {"semantic_name": "A_F", "value": 1855, "unit": "bbl", "abs_tolerance": .02}
    assert numeric_match("A F = 1855.01 bbl", target)["unit"]
    assert not numeric_match("A F = 1855.2 bbl", target)["value"]
    assert not numeric_match("A F = 1855.01 psi", target)["unit"]
    assert typed_match("Highest: D", {"semantic_name": "max", "type": "label", "value": "D"})
    ranking = {"semantic_name": "rank", "type": "ranking", "value": ["I3", "I4", "I1", "I2"]}
    assert typed_match("I3 > I4 > I1 > I2", ranking)
    assert not typed_match("I4 > I3 > I1 > I2", ranking)


def test_contract_and_calc_scoring_distinguish_completeness_from_gt():
    row = task("PT4R1-RE-O1")
    target = row["ground_truth"]["numeric_targets"][0]
    calc = {"computation_id": "CALC1", "validation_passed": True, "contract_validation_passed": True,
            "output_manifest": {"OUT_F": {"name": "single_F", "value": target["value"] + 1, "unit": "bbl"}}}
    assert contract_score(row, {"computations": [calc]})["contract_output_recall_observable"] == 1
    first = calc_score(row, {"computations": [calc]})
    assert first["calc_created"] and first["contract_complete_calc"] and not first["gt_correct_calc"]
    calc["output_manifest"]["OUT_F"]["value"] = target["value"]
    assert calc_score(row, {"computations": [calc]})["gt_correct_calc"]


def test_iteration_trace_integrity_pair_hash_and_benefit():
    response = {"iterations": [
        {"python_trace": {"tool_selected": True, "recovery_triggered": True, "recovery_query_count": 1}},
        {"python_trace": {"plan_present": True, "recovery_materialization_success": True,
                          "code_generated": True, "subprocess_reached": True}},
    ]}
    calc = {"calc_created": False, "contract_complete_calc": False, "gt_correct_calc": False}
    stages = aggregate_stages(response, calc, "")
    assert stages["tool_selected"] and stages["recovery_success"] and furthest_stage(stages) == 11
    assert "calc_without_subprocess" in trace_integrity({**stages, "validated_calc": True, "subprocess": False}, [])
    mapping = citation_mapping({"final_answer": "x [CALC1] [KB2]", "internal_sources": [
        {"evidence_id": "KB2", "document": "x.pdf", "page": 3, "chunk_id": "c"}],
        "computations": [{"computation_id": "CALC1", "source_evidence_ids": ["KB2"]}]})
    assert mapping["[KB2]"] == ["x.pdf", 3, "c"]
    assert strong_benefit({"goal_success_preliminary": False},
                          {"goal_success_preliminary": True, "gt_correct_calc": True, "grounded_adoption": True})
    assert weak_numeric_improvement({"numeric_correct": 1},
                                    {"numeric_correct": 2, "gt_correct_calc": False, "grounded_adoption": False})


def test_blind_reviewer_and_bootstrap_reproducibility():
    packet = blind_packet(task("PT4R1-RE-P1"), {
        "final_answer": "Python result [CALC1] from [USERF1]", "internal_sources": [],
    }, "BR-001")
    assert no_condition_leakage(packet)
    assert "[CALC1]" not in json.dumps(packet)
    pairs = [(0, 1), (1, 1), (1, 0), (0, 1)]
    assert paired_bootstrap(pairs) == paired_bootstrap(pairs)
    assert paired_bootstrap(pairs)["samples"] == 10000


def test_scorer_smoke_all_24_rows_after_freeze(tmp_path):
    if not (BASE / "python_tool_heldout_v4r1_manifest.json").exists():
        pytest.skip("Freeze deliberately follows this pre-freeze test run")
    from run_python_tool_heldout_v4r1 import load_frozen
    _, manifest = load_frozen()
    run_dir = tmp_path / "raw"
    run_dir.mkdir()
    for condition in ("python_off", "python_on"):
        payload = {"run_id": "synthetic-evaluation-test", "condition": condition,
                   "benchmark_sha256": manifest["benchmark_sha256"], "complete": True,
                   "results": [{"task_id": item["task_id"], "elapsed_seconds": 1.0,
                                "response": {"final_answer": "", "iterations": [], "internal_sources": [],
                                             "computations": [], "web_sources": []}}
                               for item in BENCHMARK["tasks"]]}
        (run_dir / f"{condition}.json").write_text(json.dumps(payload), encoding="utf-8")
    result = score(run_dir, tmp_path / "review")
    assert len(result["rows"]) == 24
    assert result["populations"]["required_8"]["python_on"]["n"] == 8
    assert result["funnel"]["pipeline_6"]["subprocess"] == 0
