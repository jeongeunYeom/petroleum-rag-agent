"""Combine immutable numeric scoring, blinded local review, and explicit 24/24 QA."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score_python_tool_heldout_v3r1 import ROOT, paired_bootstrap, summary, write_csv
from run_python_tool_heldout_v3r1 import load_frozen

REVIEW = ROOT / "evaluation/review"
DET = REVIEW / "python_tool_heldout_v3r1_deterministic.json"
BLIND = REVIEW / "python_tool_heldout_v3r1_reviewer_raw.json"
MAPPING = REVIEW / "python_tool_heldout_v3r1_blind_mapping.json"
MANUAL = REVIEW / "python_tool_heldout_v3r1_manual_qa.json"
NUMERIC_QUALIFIERS = {
    "PY3R1-RE-01": {"C2": "Correct extrema for the five cases are identified."},
    "PY3R1-RE-02": {"C2": "Correct extrema for the five cases are identified."},
    "PY3R1-RE-03": {"C2": "Correct extrema for the five cases are identified."},
    "PY3R1-WT-04": {"C2": "The five cases are ranked correctly."},
    "PY3R1-WT-05": {"C2": "The closest variant to the KB reference is identified."},
    "PY3R1-WT-06": {"C2": "The tied maxima are identified correctly."},
    "PY3R1-RE-07": {"C2": "The four hypothetical totals are ranked correctly."},
}


def numeric_criteria(task: dict, row: dict) -> dict[str, bool]:
    matches = row["target_matches"]
    if task["python_expected"] == "required":
        return {"C2": all(item["value"] and item["unit"] for item in matches.values())}
    if task["task_id"] == "PY3R1-RE-09":
        return {"C1": matches["gap_pp"]["value"] and matches["gap_pp"]["unit"],
                "C2": matches["relative_gap"]["value"] and matches["relative_gap"]["unit"]}
    if task["task_id"] == "PY3R1-WT-10":
        return {"C1": matches["increase"]["value"] and matches["increase"]["unit"]}
    return {}


def prepare_manual_template() -> Path:
    if MANUAL.exists():
        raise FileExistsError(MANUAL)
    benchmark, _ = load_frozen()
    tasks = {t["task_id"]: t for t in benchmark["tasks"]}
    det = json.loads(DET.read_text(encoding="utf-8"))
    if len(det["rows"]) != 24:
        raise ValueError("Manual QA template requires all 24 results")
    rows = []
    for row in det["rows"]:
        task = tasks[row["task_id"]]
        numeric_ids = numeric_criteria(task, row).keys()
        rows.append({"task_id":row["task_id"], "condition":row["condition"],
                     "answer_sha256":row["answer_sha256"], "reviewed":False,
                     "qualitative_criterion_pass":{c["criterion_id"]:False for c in task["success_criteria"]
                                                   if c["criterion_id"] not in numeric_ids},
                     "numeric_qualifier_pass":{key:False for key in NUMERIC_QUALIFIERS.get(row["task_id"], {})},
                     "unsupported_claim_count":0, "engineering_contradiction_count":0,
                     "user_input_as_kb_count":0, "note":""})
    MANUAL.write_text(json.dumps({"status":"PENDING_MANUAL_QA", "rows":rows},ensure_ascii=False,indent=2)+"\n",
                      encoding="utf-8")
    return MANUAL


def score_final() -> dict:
    benchmark, manifest = load_frozen()
    tasks = {t["task_id"]: t for t in benchmark["tasks"]}
    det = json.loads(DET.read_text(encoding="utf-8"))
    reviewer = json.loads(BLIND.read_text(encoding="utf-8"))
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    manual = json.loads(MANUAL.read_text(encoding="utf-8"))
    if not reviewer.get("complete") or len(reviewer["results"]) != 24 or len(mapping) != 24 or len(manual["rows"]) != 24 or len(det["rows"]) != 24:
        raise ValueError("Complete 24/24 deterministic, blind and manual evidence required")
    if reviewer["model"] != manifest["model_settings"]["review_model"]:
        raise ValueError("Unexpected semantic reviewer model")
    by_blind = {r["blind_id"]: r for r in reviewer["results"]}
    blind_by_pair = {(r["task_id"], r["condition"]): r["blind_id"] for r in mapping}
    manual_by_pair = {(r["task_id"], r["condition"]): r for r in manual["rows"]}
    if any(len(obj) != 24 for obj in (by_blind, blind_by_pair, manual_by_pair)):
        raise ValueError("Duplicate review identities")
    rows = []
    disagreements = []
    for original in det["rows"]:
        pair = (original["task_id"], original["condition"])
        task = tasks[pair[0]]
        qa = manual_by_pair[pair]
        blind_id = blind_by_pair[pair]
        model = by_blind[blind_id].get("parsed") or {}
        if qa.get("answer_sha256") != original["answer_sha256"] or not qa.get("reviewed"):
            raise ValueError(f"Manual QA missing or answer changed: {pair}")
        numeric = numeric_criteria(task, original)
        qualifiers = qa.get("numeric_qualifier_pass", {})
        if set(qualifiers) != set(NUMERIC_QUALIFIERS.get(pair[0], {})) or any(
                not isinstance(value, bool) for value in qualifiers.values()):
            raise ValueError(f"Manual numeric qualifier missing: {pair}")
        numeric = {key: value and qualifiers.get(key, True) for key, value in numeric.items()}
        qualitative = qa["qualitative_criterion_pass"]
        expected_qualitative = {c["criterion_id"] for c in task["success_criteria"]} - numeric.keys()
        if set(qualitative) != expected_qualitative or any(not isinstance(value, bool) for value in qualitative.values()):
            raise ValueError(f"Manual QA criteria missing: {pair}")
        criterion = {**numeric, **qualitative}
        if task["python_expected"] == "not_needed" and original["subprocess"]:
            criterion["C3"] = False
        if len(criterion) != len(task["success_criteria"]):
            raise ValueError(f"Incomplete criterion score: {pair}")
        model_qualitative = model.get("criterion_pass") or {}
        for criterion_id in expected_qualitative:
            if criterion_id in model_qualitative and bool(model_qualitative[criterion_id]) != qualitative[criterion_id]:
                disagreements.append({"task_id": pair[0], "condition": pair[1], "criterion_id": criterion_id,
                                      "reviewer": bool(model_qualitative[criterion_id]),
                                      "manual": qualitative[criterion_id], "reason": qa["note"]})
        unsupported = int(qa["unsupported_claim_count"])
        engineering = int(qa["engineering_contradiction_count"])
        leakage = int(qa["user_input_as_kb_count"])
        coverage = sum(criterion.values()) / len(criterion)
        final = dict(original)
        final.update({"blind_id": blind_id, "criterion_pass": criterion,
                      "external_coverage": coverage,
                      "goal_success": coverage == 1 and unsupported == 0 and engineering == 0 and leakage == 0,
                      "unsupported_claim_count": unsupported,
                      "engineering_contradiction_count_manual": engineering,
                      "user_input_as_kb_count": leakage,
                      "manual_qa_note": qa["note"],
                      "reviewer_criterion_pass": model_qualitative,
                      "reviewer_unsupported_claim_count": model.get("unsupported_claim_count"),
                      "reviewer_engineering_contradiction_count": model.get("engineering_contradiction_count")})
        rows.append(final)
    pairs = list(zip(rows[:12], rows[12:]))
    if any(a["task_id"] != b["task_id"] or a["condition"] != "python_off" or b["condition"] != "python_on" for a,b in pairs):
        raise ValueError("A/B pairing differs from frozen task order")
    populations = {"all_12": lambda r: True,
                   "required_8": lambda r: r["python_expected"] == "required",
                   "pipeline_6": lambda r: r["evaluation_stratum"] == "pipeline",
                   "end_to_end_2": lambda r: r["evaluation_stratum"] == "end_to_end"}
    comparison = {"benchmark_id": benchmark["benchmark_id"], "run_id": det["run_id"],
                  "product_code_sha": manifest["product_code_sha"],
                  "freeze_commit_sha": manifest["freeze_commit_sha"],
                  "status": "STRICT_ADJUDICATED_V1_1", "manual_qa_count": 24,
                  "reviewer_model": reviewer["model"], "reviewer_disagreements": disagreements,
                  "populations": {}, "bootstrap": {}, "funnel": det["funnel"], "rows": rows}
    for name, include in populations.items():
        selected = [(a,b) for a,b in pairs if include(a)]
        comparison["populations"][name] = {"python_off": summary([a for a,_ in selected]),
                                           "python_on": summary([b for _,b in selected])}
        comparison["bootstrap"][name] = {
            "goal_success": paired_bootstrap([(float(a["goal_success"]),float(b["goal_success"])) for a,b in selected]),
            "external_coverage": paired_bootstrap([(a["external_coverage"],b["external_coverage"]) for a,b in selected]),
            "numeric_accuracy": paired_bootstrap([(a["numeric_correct"]/a["numeric_total"] if a["numeric_total"] else 0,
                                                    b["numeric_correct"]/b["numeric_total"] if b["numeric_total"] else 0) for a,b in selected]),
            "unit_accuracy": paired_bootstrap([(a["unit_correct"]/a["numeric_total"] if a["numeric_total"] else 0,
                                                 b["unit_correct"]/b["numeric_total"] if b["numeric_total"] else 0) for a,b in selected])}
    required = [(a,b) for a,b in pairs if a["python_expected"] == "required"]
    comparison["required_benefit"] = dict(Counter(
        "benefit" if b["external_coverage"] > a["external_coverage"] else
        "harm" if b["external_coverage"] < a["external_coverage"] else "neutral" for a,b in required))
    comparison["strong_python_benefit"] = sum(not a["numeric_complete"] and b["calc_created"] and
                                            b["numeric_complete"] for a,b in required)
    comparison["exact_pair_identity"] = {"answer_hash_equal": sum(a["answer_sha256"] == b["answer_sha256"] for a,b in pairs),
                                         "citation_mapping_hash_equal": sum(a["citation_mapping_sha256"] == b["citation_mapping_sha256"] for a,b in pairs)}
    comparison["selection"] = {"required_selected": sum(b["tool_selected"] for a,b in required),
                               "required_total": 8,
                               "not_needed_selected": sum(b["tool_selected"] for a,b in pairs if a["python_expected"] == "not_needed"),
                               "not_needed_executed": sum(b["subprocess"] for a,b in pairs if a["python_expected"] == "not_needed"),
                               "not_needed_calc": sum(b["calc_created"] for a,b in pairs if a["python_expected"] == "not_needed"),
                               "optional_selected": sum(b["tool_selected"] for a,b in pairs if a["python_expected"] == "optional"),
                               "optional_executed": sum(b["subprocess"] for a,b in pairs if a["python_expected"] == "optional")}
    selected = comparison["selection"]
    selected["precision"] = (selected["required_selected"] /
                             (selected["required_selected"] + selected["not_needed_selected"])) if (
                                 selected["required_selected"] + selected["not_needed_selected"]) else 0.0
    selected["recall"] = selected["required_selected"] / 8
    selected["f1"] = (2 * selected["precision"] * selected["recall"] /
                      (selected["precision"] + selected["recall"])) if (
                          selected["precision"] + selected["recall"]) else 0.0
    on_required = [b for _, b in required]
    comparison["runtime_registry"] = {}
    for label, fact_key, registry_key, selection_key in (
        ("user", "required_user_facts", "user_registry_recall", "user_selection_recall"),
        ("evidence", "required_evidence_facts", "evidence_registry_recall", "evidence_selection_recall"),
        ("formula", "formula_sources", "formula_registry_recall", "formula_selection_accuracy"),
    ):
        denominator = sum(len(tasks[row["task_id"]]["ground_truth"][fact_key]) for row in on_required)
        available = sum((row[registry_key] or 0) * len(tasks[row["task_id"]]["ground_truth"][fact_key])
                        for row in on_required)
        chosen = sum(((float(row[selection_key] or 0) if selection_key == "formula_selection_accuracy" else
                       row[selection_key]) or 0) * len(tasks[row["task_id"]]["ground_truth"][fact_key])
                     for row in on_required)
        comparison["runtime_registry"][label] = {
            "expected": denominator, "available": available, "selected": chosen,
            "recall": available / denominator if denominator else None,
            "selection_recall": chosen / denominator if denominator else None,
        }
    comparison["calc_correctness"] = det["calc_correctness"]
    comparison["hallucination"] = {condition: {"unsupported_claims": sum(r["unsupported_claim_count"] for r in rows if r["condition"] == condition),
                                            "engineering_contradictions": sum(r["engineering_contradiction_count_manual"] for r in rows if r["condition"] == condition),
                                            "user_input_as_kb": sum(r["user_input_as_kb_count"] for r in rows if r["condition"] == condition)}
                                 for condition in ("python_off","python_on")}
    comparison["failure_attribution"] = {condition: dict(Counter(label for r in rows if r["condition"] == condition
                                                                 for label in r["failure_attribution"]))
                                         for condition in ("python_off","python_on")}
    comparison["timing_limitations"] = "Per-stage decision/plan/materialization/verification/codegen/subprocess times are not exposed by frozen v4; only iteration python_seconds and end-to-end elapsed_seconds are measured."
    return comparison


def markdown_report(result: dict) -> str:
    lines = ["# Python-tool held-out v3r1: strict adjudication", "",
             f"Product: `{result['product_code_sha']}` · freeze: `{result['freeze_commit_sha']}` · run: `{result['run_id']}`", "",
             "Prior v3 was invalidated before any Agent run; it has no performance score. This v3r1 run is independent.", "",
             "## OFF vs ON", "",
             "| Population | n | Goal OFF | Goal ON | Coverage OFF | Coverage ON | Numeric OFF | Numeric ON | Unit OFF | Unit ON |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    def fmt(value):
        return "N/A" if value is None else f"{100*value:.1f}%"
    for label, by_condition in result["populations"].items():
        off, on = by_condition["python_off"], by_condition["python_on"]
        lines.append(f"| {label} | {off['n']} | {fmt(off['goal_success'])} | {fmt(on['goal_success'])} | "
                     f"{fmt(off['external_coverage'])} | {fmt(on['external_coverage'])} | "
                     f"{fmt(off['numeric_accuracy'])} | {fmt(on['numeric_accuracy'])} | "
                     f"{fmt(off['unit_accuracy'])} | {fmt(on['unit_accuracy'])} |")
    lines.extend(["", "## Required Python funnel (ON)", "",
                  "| Stage | Pipeline 6 | End-to-end 2 |", "|---|---:|---:|"])
    for stage in result["funnel"]["pipeline_6"]:
        lines.append(f"| {stage} | {result['funnel']['pipeline_6'][stage]}/6 | {result['funnel']['end_to_end_2'][stage]}/2 |")
    lines.extend(["", "## Paired task outcomes", "",
                  "| Task | OFF criteria | ON criteria | OFF numeric | ON numeric | ON CALC | ON attribution |",
                  "|---|---:|---:|---:|---:|---|---|"])
    for off, on in zip(result["rows"][:12], result["rows"][12:]):
        lines.append(f"| {off['task_id']} | {sum(off['criterion_pass'].values())}/3 | "
                     f"{sum(on['criterion_pass'].values())}/3 | {off['numeric_correct']}/{off['numeric_total']} | "
                     f"{on['numeric_correct']}/{on['numeric_total']} | {'yes' if on['calc_created'] else 'no'} | "
                     f"{', '.join(on['failure_attribution']) or 'none'} |")
    lines.extend(["", f"Manual QA: {result['manual_qa_count']}/24. Blinded reviewer: {result['reviewer_model']}; "
                  f"disagreements with strict adjudication: {len(result['reviewer_disagreements'])}.",
                  f"Strong Python benefit: {result['strong_python_benefit']}/8 required.",
                  "Paired confidence intervals use 10,000 bootstrap resamples (seed 42); the small sample is not a population-level performance guarantee.",
                  "", "## Instrumentation limits", "", result["timing_limitations"], "",
                  "Raw run and computation outputs are retained under `D:\\petroleum-rag-agent\\data\\evaluation\\python_tool_heldout_v3r1\\first_full_ab` and the product workspace."])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-manual", action="store_true")
    args = parser.parse_args()
    if args.prepare_manual:
        print(prepare_manual_template())
        return 0
    result = score_final()
    path = REVIEW / "python_tool_heldout_v3r1_strict_adjudicated_v1_1.json"
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(REVIEW / "python_tool_heldout_v3r1_strict_adjudicated_v1_1.csv", result["rows"])
    (REVIEW / "python_tool_heldout_v3r1_summary.md").write_text(markdown_report(result), encoding="utf-8")
    print(json.dumps({key:value for key,value in result.items() if key not in {"rows","reviewer_disagreements"}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
