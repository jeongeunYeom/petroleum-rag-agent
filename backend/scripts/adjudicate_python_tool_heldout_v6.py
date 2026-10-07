"""Merge frozen deterministic scores, one blind review, and explicit 24/24 manual QA."""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
from run_python_tool_heldout_v6 import load_frozen  # noqa: E402
from score_python_tool_heldout_v6 import _write_csv, paired_bootstrap  # noqa: E402

REVIEW = ROOT / "evaluation/review"
PREFIX = "python_tool_heldout_v6"
DET = REVIEW / f"{PREFIX}_deterministic.json"
BLIND = REVIEW / f"{PREFIX}_reviewer_raw.json"
MAPPING = REVIEW / f"{PREFIX}_blind_mapping.json"
MANUAL = REVIEW / f"{PREFIX}_manual_qa.json"
FINAL = REVIEW / f"{PREFIX}_strict_adjudicated_v1_1.json"


def manual_template() -> Path:
    if MANUAL.exists():
        raise FileExistsError(MANUAL)
    tasks = {task["task_id"]: task for task in load_frozen()[0]["tasks"]}
    deterministic = json.loads(DET.read_text(encoding="utf-8"))
    if len(deterministic["rows"]) != 24:
        raise ValueError("Manual QA requires 24 deterministic rows")
    rows = []
    for item in deterministic["rows"]:
        criteria = {criterion["criterion_id"]: False for criterion in tasks[item["task_id"]]["success_criteria"]
                    if criterion["criterion_id"] != "C2"}
        rows.append({"task_id": item["task_id"], "condition": item["condition"],
                     "answer_sha256": item["answer_sha256"], "reviewed": False,
                     "qualitative_criterion_pass": criteria,
                     "numeric_target_overrides": {}, "typed_target_overrides": {},
                     "citation_correct": False, "safe_source_incomplete": None,
                     "calc_grounded_adoption_verified": False,
                     "unsupported_claim_count": 0, "engineering_contradiction_count": 0,
                     "python_unsupported_claim_count": 0, "user_input_as_kb_count": 0,
                     "efact_attribution_error_count": 0, "formula_provenance_error_count": 0,
                     "calc_overclaim_count": 0, "note": ""})
    MANUAL.write_text(json.dumps({"status": "PENDING_MANUAL_QA", "rows": rows},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return MANUAL


def _rate(rows: list[dict], key: str) -> float | None:
    return statistics.mean(float(row[key]) for row in rows) if rows else None


def population_summary(rows: list[dict]) -> dict:
    numeric = sum(row["numeric_total"] for row in rows)
    typed = sum(row["typed_total"] for row in rows)
    ranking = sum(row["ranking_total"] for row in rows)
    latencies = sorted(row["elapsed_seconds"] for row in rows)
    return {"n": len(rows), "goal_success": _rate(rows, "goal_success"),
            "external_coverage": _rate(rows, "external_coverage"),
            "numeric_accuracy": sum(row["numeric_correct"] for row in rows) / numeric if numeric else None,
            "unit_accuracy": sum(row["unit_correct"] for row in rows) / numeric if numeric else None,
            "typed_accuracy": sum(row["typed_correct"] for row in rows) / typed if typed else None,
            "ranking_accuracy": sum(row["ranking_correct"] for row in rows) / ranking if ranking else None,
            "scenario_completeness": _rate(rows, "scenario_complete"),
            "citation_correctness": _rate(rows, "citation_correct"),
            "latency_mean": statistics.mean(latencies) if latencies else None,
            "latency_median": statistics.median(latencies) if latencies else None,
            "latency_p95": latencies[max(0, int(.95 * len(latencies) + .999) - 1)] if latencies else None}


def adjudicate() -> dict:
    benchmark, manifest = load_frozen()
    tasks = {task["task_id"]: task for task in benchmark["tasks"]}
    det = json.loads(DET.read_text(encoding="utf-8"))
    reviewer = json.loads(BLIND.read_text(encoding="utf-8"))
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    manual = json.loads(MANUAL.read_text(encoding="utf-8"))
    if not reviewer.get("complete") or reviewer.get("model") != manifest["model_settings"]["review_model"] or (
            any(len(rows) != 24 for rows in (det["rows"], reviewer["results"], mapping, manual["rows"]))):
        raise ValueError("Complete 24/24 deterministic, blind, and manual records required")
    by_blind = {row["blind_id"]: row for row in reviewer["results"]}
    blind_by_pair = {(row["task_id"], row["condition"]): row["blind_id"] for row in mapping}
    qa_by_pair = {(row["task_id"], row["condition"]): row for row in manual["rows"]}
    if any(len(rows) != 24 for rows in (by_blind, blind_by_pair, qa_by_pair)):
        raise ValueError("Duplicate or missing review identities")
    rows, disagreements = [], []
    for original in det["rows"]:
        pair = original["task_id"], original["condition"]
        task, qa = tasks[pair[0]], qa_by_pair[pair]
        if not qa.get("reviewed") or qa.get("answer_sha256") != original["answer_sha256"]:
            raise ValueError(f"Unreviewed or altered answer: {pair}")
        numeric = copy.deepcopy(original["numeric_matches"])
        typed = dict(original["typed_matches"])
        for name, value in qa.get("numeric_target_overrides", {}).items():
            if name not in numeric or set(value) != {"value", "unit"}:
                raise ValueError(f"Invalid numeric override: {pair} {name}")
            numeric[name].update(value=bool(value["value"]), unit=bool(value["unit"]))
        for name, value in qa.get("typed_target_overrides", {}).items():
            if name not in typed:
                raise ValueError(f"Invalid typed override: {pair} {name}")
            typed[name] = bool(value)
        c2 = all(item["value"] and item["unit"] for item in numeric.values()) and all(typed.values())
        criteria = {**qa["qualitative_criterion_pass"], "C2": c2}
        if set(criteria) != {item["criterion_id"] for item in task["success_criteria"]}:
            raise ValueError(f"Incomplete criteria: {pair}")
        parsed = by_blind[blind_by_pair[pair]].get("parsed") or {}
        reviewer_criteria = parsed.get("criterion_pass") or {}
        for key, passed in qa["qualitative_criterion_pass"].items():
            if key in reviewer_criteria and bool(reviewer_criteria[key]) != bool(passed):
                disagreements.append({"task_id": pair[0], "condition": pair[1], "criterion_id": key,
                                      "reviewer": bool(reviewer_criteria[key]), "manual": bool(passed),
                                      "reason": qa.get("note", "")})
        provenance_errors = sum(int(qa.get(key, 0)) for key in ("user_input_as_kb_count", "efact_attribution_error_count",
                                                         "formula_provenance_error_count", "calc_overclaim_count"))
        numeric_count = sum(item["value"] for item in numeric.values())
        unit_count = sum(item["value"] and item["unit"] for item in numeric.values())
        typed_count = sum(typed.values())
        final = {**original, "blind_id": blind_by_pair[pair], "criterion_pass": criteria,
                 "numeric_matches": numeric, "numeric_correct": numeric_count, "unit_correct": unit_count,
                 "typed_matches": typed, "typed_correct": typed_count,
                 "ranking_correct": sum(typed[row["semantic_name"]] for row in task["ground_truth"]["ranking_targets"]),
                 "external_coverage": sum(criteria.values()) / len(criteria),
                 "scenario_complete": c2, "citation_correct": bool(qa.get("citation_correct", False)),
                 "safe_source_incomplete": qa.get("safe_source_incomplete"),
                 "grounded_adoption": bool(original["grounded_adoption"] and qa.get("calc_grounded_adoption_verified", False)),
                 "unsupported_claim_count": int(qa.get("unsupported_claim_count", 0)),
                 "engineering_contradiction_count_manual": int(qa.get("engineering_contradiction_count", 0)),
                 "python_unsupported_claim_count": int(qa.get("python_unsupported_claim_count", 0)),
                 "user_input_as_kb_count": int(qa.get("user_input_as_kb_count", 0)),
                 "efact_attribution_error_count": int(qa.get("efact_attribution_error_count", 0)),
                 "formula_provenance_error_count": int(qa.get("formula_provenance_error_count", 0)),
                 "calc_overclaim_count": int(qa.get("calc_overclaim_count", 0)),
                 "manual_qa_note": qa.get("note", ""), "reviewer_criterion_pass": reviewer_criteria,
                 "reviewer_unsupported_claim_count": parsed.get("unsupported_claim_count"),
                 "reviewer_engineering_contradiction_count": parsed.get("engineering_contradiction_count")}
        final["goal_success"] = bool(all(criteria.values()) and final["citation_correct"] and
                                     final["unsupported_claim_count"] == 0 and
                                     final["engineering_contradiction_count_manual"] == 0 and provenance_errors == 0 and
                                     not (task["python_expected"] == "not_needed" and original["stages"]["16"]))
        rows.append(final)
    pairs = list(zip(rows[:12], rows[12:]))
    if any(off["task_id"] != on["task_id"] or off["condition"] != "python_off" or on["condition"] != "python_on"
           for off, on in pairs):
        raise ValueError("Frozen paired task identity mismatch")
    populations = {
        "all_12": lambda row: True,
        "required_8": lambda row: row["python_expected"] == "required",
        "pipeline_6": lambda row: row["evaluation_stratum"] in {"generic_direct", "specialist_direct", "recovery_challenge"},
        "generic_direct_2": lambda row: row["evaluation_stratum"] == "generic_direct",
        "specialist_direct_3": lambda row: row["evaluation_stratum"] == "specialist_direct",
        "recovery_challenge_1": lambda row: row["evaluation_stratum"] == "recovery_challenge",
        "end_to_end_2": lambda row: row["evaluation_stratum"] == "end_to_end",
        "optional_2": lambda row: row["python_expected"] == "optional",
        "not_needed_2": lambda row: row["python_expected"] == "not_needed",
    }
    result = {"benchmark_id": benchmark["benchmark_id"], "run_id": det["run_id"],
              "product_code_sha": manifest["product_code_sha"], "freeze_commit_sha": manifest["freeze_commit_sha"],
              "status": "STRICT_ADJUDICATED_V1_1", "manual_qa_count": 24, "reviewer_model": reviewer["model"],
              "reviewer_disagreements": disagreements, "populations": {}, "paired_bootstrap": {},
              "funnel": det["funnel"], "rows": rows}
    for name, include in populations.items():
        selected = [(off, on) for off, on in pairs if include(off)]
        result["populations"][name] = {"python_off": population_summary([off for off, _ in selected]),
                                       "python_on": population_summary([on for _, on in selected])}
        if name in {"all_12", "required_8", "pipeline_6"}:
            bootstrap = {
                "goal_success": [(float(off["goal_success"]), float(on["goal_success"])) for off, on in selected],
                "external_coverage": [(off["external_coverage"], on["external_coverage"]) for off, on in selected],
                "numeric_accuracy": [(off["numeric_correct"] / off["numeric_total"] if off["numeric_total"] else 0,
                                      on["numeric_correct"] / on["numeric_total"] if on["numeric_total"] else 0)
                                     for off, on in selected],
            }
            if name == "required_8":
                bootstrap["unit_accuracy"] = [(off["unit_correct"] / off["numeric_total"],
                                                on["unit_correct"] / on["numeric_total"]) for off, on in selected]
            result["paired_bootstrap"][name] = {key: paired_bootstrap(value) for key, value in bootstrap.items()}
    required = [(off, on) for off, on in pairs if off["python_expected"] == "required"]
    result["required_benefit_neutral_harm"] = dict(Counter(
        "benefit" if on["external_coverage"] > off["external_coverage"] else
        "harm" if on["external_coverage"] < off["external_coverage"] else "neutral" for off, on in required))
    result["strong_python_benefit"] = sum(not off["criterion_pass"]["C2"] and on["criterion_pass"]["C2"] and
                                          on["gt_correct_calc"] and on["grounded_adoption"] for off, on in required)
    result["weak_unattributed_numeric_improvement"] = sum(
        on["numeric_correct"] > off["numeric_correct"] and not (on["gt_correct_calc"] and on["grounded_adoption"])
        for off, on in required)
    result["paired_identity"] = {"answer_hash_equal": sum(off["answer_sha256"] == on["answer_sha256"] for off, on in pairs),
                                 "citation_mapping_hash_equal": sum(off["citation_mapping_sha256"] == on["citation_mapping_sha256"]
                                                                      for off, on in pairs)}
    result["failure_attribution"] = {condition: dict(Counter(reason for row in rows if row["condition"] == condition
                                                                  for reason in row["failure_attribution"]))
                                     for condition in ("python_off", "python_on")}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-manual", action="store_true")
    args = parser.parse_args()
    if args.prepare_manual:
        print(manual_template())
        return 0
    if FINAL.exists():
        raise FileExistsError(FINAL)
    result = adjudicate()
    FINAL.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(REVIEW / f"{PREFIX}_strict_adjudicated_v1_1.csv", result["rows"])
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
