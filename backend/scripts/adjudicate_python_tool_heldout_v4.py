"""Strictly merge deterministic scoring, one blind reviewer, and explicit 24/24 QA."""

from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_python_tool_heldout_v4 import ROOT, load_frozen  # noqa: E402
from score_python_tool_heldout_v4 import paired_bootstrap, write_csv  # noqa: E402

REVIEW = ROOT / "evaluation/review"
DET = REVIEW / "python_tool_heldout_v4_deterministic.json"
BLIND = REVIEW / "python_tool_heldout_v4_reviewer_raw.json"
MAPPING = REVIEW / "python_tool_heldout_v4_blind_mapping.json"
MANUAL = REVIEW / "python_tool_heldout_v4_manual_qa.json"
FINAL = REVIEW / "python_tool_heldout_v4_strict_adjudicated_v1_1.json"


def prepare_manual_template() -> Path:
    if MANUAL.exists():
        raise FileExistsError(MANUAL)
    benchmark, _ = load_frozen()
    tasks = {task["task_id"]: task for task in benchmark["tasks"]}
    deterministic = json.loads(DET.read_text(encoding="utf-8"))
    if len(deterministic["rows"]) != 24:
        raise ValueError("Manual QA requires all 24 answers")
    rows = []
    for row in deterministic["rows"]:
        task = tasks[row["task_id"]]
        numeric = bool(task["ground_truth"]["numeric_targets"])
        rows.append({
            "task_id": row["task_id"], "condition": row["condition"],
            "answer_sha256": row["answer_sha256"], "reviewed": False,
            "qualitative_criterion_pass": {
                item["criterion_id"]: False for item in task["success_criteria"]
                if not (numeric and item["criterion_id"] == "C2")
            },
            "numeric_qa_override": None,
            "typed_qa_override": None,
            "numeric_target_overrides": {},
            "typed_target_overrides": {},
            "unsupported_claim_count": 0, "engineering_contradiction_count": 0,
            "python_unsupported_claim_count": 0, "user_input_as_kb_count": 0,
            "efact_attribution_error_count": 0, "formula_provenance_error_count": 0,
            "calc_overclaim_count": 0, "citation_correct": False,
            "calc_grounded_adoption_verified": False, "note": "",
        })
    MANUAL.write_text(json.dumps({"status": "PENDING_MANUAL_QA", "rows": rows},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return MANUAL


def _rate(rows: list[dict], field: str) -> float | None:
    return statistics.mean(float(row[field]) for row in rows) if rows else None


def population_summary(rows: list[dict]) -> dict:
    total = sum(row["numeric_total"] for row in rows)
    typed_total = sum(row["typed_total"] for row in rows)
    return {
        "n": len(rows), "goal_success": _rate(rows, "goal_success"),
        "external_coverage": _rate(rows, "external_coverage"),
        "numeric_accuracy": sum(row["numeric_correct"] for row in rows) / total if total else None,
        "unit_accuracy": sum(row["unit_correct"] for row in rows) / total if total else None,
        "typed_accuracy": sum(row["typed_correct"] for row in rows) / typed_total if typed_total else None,
        "scenario_completeness": _rate(rows, "scenario_complete"),
        "citation_correctness": _rate(rows, "citation_correct"),
        "latency_mean": statistics.mean(row["elapsed_seconds"] for row in rows) if rows else None,
        "latency_median": statistics.median(row["elapsed_seconds"] for row in rows) if rows else None,
        "latency_p95": sorted(row["elapsed_seconds"] for row in rows)[max(0, int(.95 * len(rows) + .999) - 1)] if rows else None,
    }


def adjudicate() -> dict:
    benchmark, manifest = load_frozen()
    tasks = {task["task_id"]: task for task in benchmark["tasks"]}
    det = json.loads(DET.read_text(encoding="utf-8"))
    reviewer = json.loads(BLIND.read_text(encoding="utf-8"))
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    manual = json.loads(MANUAL.read_text(encoding="utf-8"))
    if not reviewer.get("complete") or any(len(value) != 24 for value in (
        det["rows"], reviewer["results"], mapping, manual["rows"]
    )):
        raise ValueError("Complete 24/24 deterministic, blind, and manual records required")
    if reviewer["model"] != manifest["model_settings"]["review_model"]:
        raise ValueError("Wrong blind reviewer model")
    by_blind = {item["blind_id"]: item for item in reviewer["results"]}
    blind_by_pair = {(item["task_id"], item["condition"]): item["blind_id"] for item in mapping}
    qa_by_pair = {(item["task_id"], item["condition"]): item for item in manual["rows"]}
    if any(len(value) != 24 for value in (by_blind, blind_by_pair, qa_by_pair)):
        raise ValueError("Duplicate or missing review identities")
    rows, disagreements = [], []
    for original in det["rows"]:
        pair = (original["task_id"], original["condition"])
        task = tasks[pair[0]]
        qa = qa_by_pair[pair]
        if not qa.get("reviewed") or qa.get("answer_sha256") != original["answer_sha256"]:
            raise ValueError(f"Unreviewed or altered answer: {pair}")
        numeric = bool(task["ground_truth"]["numeric_targets"])
        numeric_matches = copy.deepcopy(original["numeric_matches"])
        typed_matches = dict(original["typed_matches"])
        for name, override in qa.get("numeric_target_overrides", {}).items():
            if name not in numeric_matches or set(override) != {"value", "unit"}:
                raise ValueError(f"Invalid numeric target override: {pair} {name}")
            numeric_matches[name].update(value=bool(override["value"]), unit=bool(override["unit"]))
        for name, override in qa.get("typed_target_overrides", {}).items():
            if name not in typed_matches:
                raise ValueError(f"Invalid typed target override: {pair} {name}")
            typed_matches[name] = bool(override)
        numeric_pass = all(item["value"] and item["unit"] for item in numeric_matches.values())
        typed_pass = all(typed_matches.values())
        if qa["numeric_qa_override"] is not None:
            numeric_pass = bool(qa["numeric_qa_override"])
        if qa["typed_qa_override"] is not None:
            typed_pass = bool(qa["typed_qa_override"])
        criterion = dict(qa["qualitative_criterion_pass"])
        if numeric:
            criterion["C2"] = numeric_pass and typed_pass
        if task["python_expected"] == "not_needed" and original["subprocess"]:
            criterion["C3"] = False
        if set(criterion) != {item["criterion_id"] for item in task["success_criteria"]}:
            raise ValueError(f"Incomplete criteria: {pair}")
        blind_id = blind_by_pair[pair]
        parsed = by_blind[blind_id].get("parsed") or {}
        model_criteria = parsed.get("criterion_pass") or {}
        for key in qa["qualitative_criterion_pass"]:
            if key in model_criteria and bool(model_criteria[key]) != criterion[key]:
                disagreements.append({
                    "task_id": pair[0], "condition": pair[1], "criterion_id": key,
                    "reviewer": bool(model_criteria[key]), "manual": criterion[key],
                    "reason": qa["note"],
                })
        coverage = sum(criterion.values()) / len(criterion)
        unsupported = int(qa["unsupported_claim_count"])
        engineering = int(qa["engineering_contradiction_count"])
        provenance_errors = sum(int(qa[key]) for key in (
            "user_input_as_kb_count", "efact_attribution_error_count",
            "formula_provenance_error_count", "calc_overclaim_count"
        ))
        final = {
            **original, "blind_id": blind_id, "criterion_pass": criterion,
            "numeric_matches": numeric_matches,
            "numeric_correct": sum(item["value"] for item in numeric_matches.values()),
            "unit_correct": sum(item["value"] and item["unit"] for item in numeric_matches.values()),
            "typed_matches": typed_matches,
            "typed_correct": sum(typed_matches.values()),
            "external_coverage": coverage,
            "goal_success": coverage == 1 and unsupported == engineering == provenance_errors == 0,
            "scenario_complete": numeric_pass and typed_pass,
            "citation_correct": bool(qa["citation_correct"]),
            "grounded_adoption": bool(original["grounded_adoption"] and qa["calc_grounded_adoption_verified"]),
            "unsupported_claim_count": unsupported,
            "engineering_contradiction_count_manual": engineering,
            "python_unsupported_claim_count": int(qa["python_unsupported_claim_count"]),
            "user_input_as_kb_count": int(qa["user_input_as_kb_count"]),
            "efact_attribution_error_count": int(qa["efact_attribution_error_count"]),
            "formula_provenance_error_count": int(qa["formula_provenance_error_count"]),
            "calc_overclaim_count": int(qa["calc_overclaim_count"]),
            "manual_qa_note": qa["note"], "reviewer_criterion_pass": model_criteria,
            "reviewer_unsupported_claim_count": parsed.get("unsupported_claim_count"),
            "reviewer_engineering_contradiction_count": parsed.get("engineering_contradiction_count"),
        }
        rows.append(final)
    pairs = list(zip(rows[:12], rows[12:]))
    if any(off["task_id"] != on["task_id"] or off["condition"] != "python_off" or on["condition"] != "python_on"
           for off, on in pairs):
        raise ValueError("A/B pairing differs from frozen task order")
    populations = {
        "all_12": lambda row: True,
        "required_8": lambda row: row["python_expected"] == "required",
        "pipeline_6": lambda row: row["evaluation_stratum"] == "pipeline",
        "end_to_end_2": lambda row: row["evaluation_stratum"] == "end_to_end",
    }
    result = {
        "benchmark_id": benchmark["benchmark_id"], "run_id": det["run_id"],
        "product_code_sha": manifest["product_code_sha"], "status": "STRICT_ADJUDICATED_V1_1",
        "manual_qa_count": 24, "reviewer_model": reviewer["model"],
        "reviewer_disagreements": disagreements, "populations": {},
        "bootstrap": {}, "funnel": det["funnel"], "rows": rows,
    }
    for name, include in populations.items():
        selected = [(off, on) for off, on in pairs if include(off)]
        result["populations"][name] = {
            "python_off": population_summary([off for off, _ in selected]),
            "python_on": population_summary([on for _, on in selected]),
        }
        result["bootstrap"][name] = {
            "goal_success": paired_bootstrap([(float(off["goal_success"]), float(on["goal_success"])) for off, on in selected]),
            "external_coverage": paired_bootstrap([(off["external_coverage"], on["external_coverage"]) for off, on in selected]),
            "numeric_accuracy": paired_bootstrap([
                (off["numeric_correct"] / off["numeric_total"] if off["numeric_total"] else 0,
                 on["numeric_correct"] / on["numeric_total"] if on["numeric_total"] else 0)
                for off, on in selected
            ]),
        }
        if name == "required_8":
            result["bootstrap"][name]["unit_accuracy"] = paired_bootstrap([
                (off["unit_correct"] / off["numeric_total"], on["unit_correct"] / on["numeric_total"])
                for off, on in selected
            ])
    required = [(off, on) for off, on in pairs if off["python_expected"] == "required"]
    result["required_benefit_neutral_harm"] = dict(Counter(
        "benefit" if on["external_coverage"] > off["external_coverage"] else
        "harm" if on["external_coverage"] < off["external_coverage"] else "neutral"
        for off, on in required
    ))
    result["strong_python_benefit"] = sum(
        not off["criterion_pass"]["C2"] and on["criterion_pass"]["C2"]
        and on["gt_correct_calc"] and on["grounded_adoption"] for off, on in required
    )
    result["weak_unattributed_numeric_improvement"] = sum(
        on["numeric_correct"] > off["numeric_correct"]
        and not (on["gt_correct_calc"] and on["grounded_adoption"]) for off, on in required
    )
    result["paired_identity"] = {
        "answer_hash_equal": sum(off["answer_sha256"] == on["answer_sha256"] for off, on in pairs),
        "citation_mapping_hash_equal": sum(off["citation_mapping_sha256"] == on["citation_mapping_sha256"] for off, on in pairs),
    }
    result["selection"] = {
        "optional_selected": sum(on["tool_selected"] for off, on in pairs if off["python_expected"] == "optional"),
        "optional_executed": sum(on["subprocess"] for off, on in pairs if off["python_expected"] == "optional"),
        "not_needed_selected": sum(on["tool_selected"] for off, on in pairs if off["python_expected"] == "not_needed"),
        "not_needed_executed": sum(on["subprocess"] for off, on in pairs if off["python_expected"] == "not_needed"),
        "not_needed_calc": sum(on["calc_created"] for off, on in pairs if off["python_expected"] == "not_needed"),
    }
    result["hallucination"] = {
        condition: {
            "unsupported_claims": sum(row["unsupported_claim_count"] for row in rows if row["condition"] == condition),
            "engineering_contradictions": sum(row["engineering_contradiction_count_manual"] for row in rows if row["condition"] == condition),
            "python_unsupported_claims": sum(row["python_unsupported_claim_count"] for row in rows if row["condition"] == condition),
            "provenance_errors": sum(row["user_input_as_kb_count"] + row["efact_attribution_error_count"] +
                                     row["formula_provenance_error_count"] + row["calc_overclaim_count"]
                                     for row in rows if row["condition"] == condition),
        }
        for condition in ("python_off", "python_on")
    }
    result["failure_attribution"] = {
        condition: dict(Counter(reason for row in rows if row["condition"] == condition
                                for reason in row["failure_attribution"]))
        for condition in ("python_off", "python_on")
    }
    result["non_executed_python_overhead"] = statistics.mean(
        on["python_seconds"] for off, on in pairs if on["tool_selected"] and not on["subprocess"]
    ) if any(on["tool_selected"] and not on["subprocess"] for off, on in pairs) else None
    return result


def report_markdown(result: dict) -> str:
    def pct(value):
        return "N/A" if value is None else f"{100 * value:.1f}%"
    lines = [
        "# Python Tool Heldout v4 — strict first-run baseline", "",
        f"Product `{result['product_code_sha']}` · run `{result['run_id']}` · manual QA 24/24", "",
        "| Stratum | n | Goal OFF | Goal ON | Coverage OFF | Coverage ON | Numeric OFF | Numeric ON | Unit OFF | Unit ON |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, population in result["populations"].items():
        off, on = population["python_off"], population["python_on"]
        lines.append(f"| {name} | {off['n']} | {pct(off['goal_success'])} | {pct(on['goal_success'])} | "
                     f"{pct(off['external_coverage'])} | {pct(on['external_coverage'])} | "
                     f"{pct(off['numeric_accuracy'])} | {pct(on['numeric_accuracy'])} | "
                     f"{pct(off['unit_accuracy'])} | {pct(on['unit_accuracy'])} |")
    lines.extend(["", "## ON funnel", "",
                  "| Stage | Required 8 | Pipeline 6 | End-to-end 2 |",
                  "|---|---:|---:|---:|"])
    for stage, count in result["funnel"]["required_8"].items():
        lines.append(f"| {stage} | {count}/8 | {result['funnel']['pipeline_6'][stage]}/6 | "
                     f"{result['funnel']['end_to_end_2'][stage]}/2 |")
    lines.extend(["", f"Strong Python benefit: {result['strong_python_benefit']}/8; "
                  f"weak/unattributed numeric improvement: {result['weak_unattributed_numeric_improvement']}/8.",
                  "Bootstrap: 10,000 paired resamples, seed 42; exploratory small-sample intervals only.",
                  "No product tuning or selective reruns. The first completed A/B run is the frozen baseline.",
                  "Full pre-execution contract names and units are not persisted by product v5; contract semantic metrics are observable lower bounds after result creation."])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-manual", action="store_true")
    args = parser.parse_args()
    if args.prepare_manual:
        print(prepare_manual_template())
        return 0
    if FINAL.exists():
        raise FileExistsError(FINAL)
    result = adjudicate()
    FINAL.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(REVIEW / "python_tool_heldout_v4_strict_adjudicated_v1_1.csv", result["rows"])
    (REVIEW / "python_tool_heldout_v4_summary.md").write_text(report_markdown(result), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
