"""Apply the V18 frozen score functions to V20.1 and pair with immutable old rows."""

from __future__ import annotations

import math
import random
import re
import statistics

from common import (JUDGE_MODEL, ROOT, assert_frozen, old_json, read_json, save_json)
from frozen_score_results import (CITATION, NUMERIC_CATEGORIES, SOURCE_CATEGORIES,
                                  agent_diag, bootstrap, numeric_score, percentile, write_csv)


TASKS = read_json(ROOT / "benchmark.json")["tasks"]
SYSTEMS = ("qwen_closed_book", "v18_agent", "v20_1_agent")
ALL_SYSTEMS = (*SYSTEMS, "gpt_reference")
FIELDS = ("goal_success", "claim_coverage", "hallucination_free", "numerical_accuracy")


def score_new(task: dict, judge: dict, raw: dict) -> dict:
    label = next(k for k, system in judge["anonymous_labels"].items() if system == "v20_1_agent")
    verdict = judge["verdict"]["responses"][label]
    claims = verdict["claim_scores"]
    if len(claims) != len(task["required_claims"]) or any(x not in (0, 0.5, 1) for x in claims):
        raise RuntimeError(f"{task['task_id']}: invalid frozen claim scores")
    answer = raw.get("answer", "")
    numeric = numeric_score(task, answer) if task["category"] in NUMERIC_CATEGORIES else {}
    diag = agent_diag(task, raw["run"])
    goal = bool(verdict["goal_success"])
    if task["category"] in NUMERIC_CATEGORIES:
        goal = goal and numeric["final_numeric_correct"] and diag["route_correct"] and diag["calculation_validated"]
        if task["category"] == "kb_formula":
            goal = goal and diag["formula_source_verified"] and diag["formula_source_correct"]
    if task["category"] in SOURCE_CATEGORIES:
        goal = goal and verdict.get("citation_semantic_support") is True
    material_error_labels = {"fabricated_fact", "unsupported_claim", "wrong_calculation", "wrong_unit",
                             "wrong_formula", "wrong_formula_provenance"}
    hallucination_free = bool(verdict["hallucination_free"]) and not bool(
        material_error_labels.intersection(verdict.get("error_labels", []))
    )
    if task["category"] in NUMERIC_CATEGORIES and numeric["numeric_value_correct"] is False and verdict.get("final_numeric_outputs"):
        hallucination_free = False
    waiting_on_supplied = bool(task["answerable"] and raw.get("run_status") == "waiting_for_user_input")
    error_labels = list(verdict.get("error_labels", []))
    if waiting_on_supplied and "incorrect_refusal" not in error_labels:
        error_labels.append("incorrect_refusal")
    return {
        "goal_success": bool(goal), "claim_coverage": statistics.fmean(claims), "claim_scores": claims,
        "hallucination_free": hallucination_free, "error_labels": error_labels,
        "unnecessary_refusal": (bool(verdict.get("unnecessary_refusal")) or waiting_on_supplied)
                                if task["answerable"] else False,
        "unnecessary_refusal_basis": ("frozen_policy_waiting_on_answerable_task" if waiting_on_supplied
                                      else "semantic_reviewer" if verdict.get("unnecessary_refusal") else None),
        "citation_semantic_support": verdict.get("citation_semantic_support"),
        "relevant_evidence_retrieved": verdict.get("relevant_evidence_retrieved"),
        "latency_seconds": raw.get("latency_seconds"), "answer": answer,
        "run_id": raw.get("run_id"), "run_status": raw.get("run_status"),
        "numeric": numeric, "diagnostics": diag,
        "judge_rationale": verdict.get("brief_rationale", ""),
    }


def numeric_bootstrap(rows: list[dict], base: str) -> dict:
    numeric = [r for r in rows if r["numeric"]]
    delta = [float(r["v20_1_agent"]["numeric"]["final_numeric_correct"])
             - float(r[base]["numeric"]["final_numeric_correct"]) for r in numeric]
    rng = random.Random(20261012)
    samples = [statistics.fmean(delta[rng.randrange(len(delta))] for _ in delta) for _ in range(10000)]
    return {"difference": statistics.fmean(delta), "ci95_low": percentile(samples, 0.025),
            "ci95_high": percentile(samples, 0.975), "n": 10, "resamples": 10000, "seed": 20261012}


def main() -> None:
    assert_frozen()
    old_rows = old_json("scored_rows.json")
    old_metrics = old_json("final_metrics.json")
    if len(old_rows) != 24 or len(TASKS) != 24 or sum(t["category"] in NUMERIC_CATEGORIES for t in TASKS) != 10:
        raise RuntimeError("frozen denominator changed")
    for system, expected in {"qwen_closed_book": (0.375, 0.9), "v18_agent": (0.25, 0.3)}.items():
        metrics = old_metrics["systems"][system]
        if not (math.isclose(metrics["goal_success"], expected[0])
                and math.isclose(metrics["numerical_accuracy"], expected[1])):
            raise RuntimeError(f"{system}: reference metrics changed")
    rows = []
    for task, old in zip(TASKS, old_rows, strict=True):
        task_id = task["task_id"]
        if old["task_id"] != task_id:
            raise RuntimeError("reference row order differs from frozen task order")
        raw = read_json(ROOT / "raw" / "v20_1_agent" / f"{task_id}.json")
        judge = read_json(ROOT / "raw" / "judge" / f"{task_id}.json")
        if raw.get("status") != "completed" or raw.get("attempt_count") != 1 or not raw.get("run"):
            raise RuntimeError(f"{task_id}: incomplete or repeated product run")
        if raw.get("question") != task["question"]:
            raise RuntimeError(f"{task_id}: question changed")
        if judge.get("status") != "completed" or judge.get("attempt_count") != 1 or judge.get("actual_model") != JUDGE_MODEL:
            raise RuntimeError(f"{task_id}: frozen judge incomplete or substituted")
        if set(judge["anonymous_labels"].values()) != {"qwen_closed_book", "v18_agent", "v20_1_agent", "gpt_reference"}:
            raise RuntimeError(f"{task_id}: blinded reviewer systems differ")
        row = dict(old)
        row["v20_1_agent"] = score_new(task, judge, raw)
        rows.append(row)
    save_json(ROOT / "scored_rows.json", rows)
    vals = [r["v20_1_agent"] for r in rows]
    nums = [r["v20_1_agent"]["numeric"]["final_numeric_correct"] for r in rows if r["numeric"]]
    latencies = [v["latency_seconds"] for v in vals]
    if any(value is None for value in latencies):
        raise RuntimeError("one or more wall-clock latencies are unavailable")
    metrics = dict(old_metrics["systems"])
    metrics["v20_1_agent"] = {
        "task_count": 24, "goal_success": statistics.fmean(v["goal_success"] for v in vals),
        "claim_coverage": statistics.fmean(v["claim_coverage"] for v in vals),
        "hallucination_free": statistics.fmean(v["hallucination_free"] for v in vals),
        "numerical_accuracy": statistics.fmean(nums), "numeric_task_count": len(nums),
        "latency_mean_seconds": statistics.fmean(latencies),
        "latency_median_seconds": statistics.median(latencies),
        "latency_p95_seconds": percentile(latencies, 0.95),
    }
    comparisons = {}
    for base, name in (("v18_agent", "v20_1_minus_v18"), ("qwen_closed_book", "v20_1_minus_qwen")):
        comparisons[name] = {field: bootstrap(rows, base, "v20_1_agent", field) for field in FIELDS[:-1]}
        comparisons[name]["numerical_accuracy"] = numeric_bootstrap(rows, base)
    save_json(ROOT / "final_metrics.json", {"systems": metrics, "comparisons": comparisons,
                                           "FINALIZED": False, "status": "awaiting_integrity_finalization"})
    flat = []
    for row in rows:
        for system in ALL_SYSTEMS:
            value = row[system]
            flat.append({"task_id": row["task_id"], "category": row["category"], "domain": row["domain"],
                         "system": system, "goal_success": value["goal_success"],
                         "claim_coverage": value["claim_coverage"], "hallucination_free": value["hallucination_free"],
                         "numeric_value_correct": value["numeric"].get("numeric_value_correct"),
                         "unit_correct": value["numeric"].get("unit_correct"),
                         "final_numeric_correct": value["numeric"].get("final_numeric_correct"),
                         "unnecessary_refusal": value["unnecessary_refusal"],
                         "latency_seconds": value["latency_seconds"]})
    write_csv("final_results.csv", flat)
    write_csv("poster_metrics.csv", [{"System": system,
        "Goal Success %": 100*metrics[system]["goal_success"],
        "Claim Coverage %": 100*metrics[system]["claim_coverage"],
        "Hallucination-free %": 100*metrics[system]["hallucination_free"],
        "Numerical Accuracy %": 100*metrics[system]["numerical_accuracy"],
        "Median Latency (s)": metrics[system]["latency_median_seconds"]} for system in SYSTEMS])
    for base, name, file in (("v18_agent", "v20_1_minus_v18", "poster_v20_1_vs_v18.csv"),
                             ("qwen_closed_book", "v20_1_minus_qwen", "poster_v20_1_vs_qwen.csv")):
        write_csv(file, [{"metric": field, "base_percent": 100*metrics[base][field],
            "v20_1_percent": 100*metrics["v20_1_agent"][field],
            "difference_pp": 100*comparisons[name][field]["difference"],
            "ci95_low_pp": 100*comparisons[name][field]["ci95_low"],
            "ci95_high_pp": 100*comparisons[name][field]["ci95_high"]} for field in FIELDS])
    groups = {"Knowledge": {"knowledge_qa"}, "Reasoning": {"multi_claim_reasoning"},
              "Calculation": NUMERIC_CATEGORIES, "Safety": {"false_premise", "unanswerable"}}
    write_csv("poster_category_metrics.csv", [{"category": group, "system": system, "n": len(subset),
        "goal_success": statistics.fmean(r[system]["goal_success"] for r in subset)}
        for group, categories in groups.items() for subset in [[r for r in rows if r["category"] in categories]]
        for system in SYSTEMS])
    write_csv("poster_numeric_pipeline.csv", [{"task_id": r["task_id"],
        **{k: v for k, v in r["v20_1_agent"]["diagnostics"].items() if k not in ("timing", "action_sequence")},
        **r["v20_1_agent"]["numeric"]} for r in rows if r["numeric"]])
    write_csv("poster_kb_formula_pipeline.csv", [{"task_id": r["task_id"],
        **{k: r["v20_1_agent"]["diagnostics"].get(k) for k in (
            "retrieval_success", "correct_source_page_retrieved", "correct_formula_span_retrieved",
            "formula_candidate_selected", "formula_source_verified", "formula_source_correct",
            "variables_bound", "calculation_executed", "calculation_validated", "route_correct")},
        "numeric_correct": r["v20_1_agent"]["numeric"].get("final_numeric_correct")}
        for r in rows if r["category"] == "kb_formula"])
    write_csv("poster_refusal_analysis.csv", [{"task_id": r["task_id"], "answerable": r["answerable"],
        "v18_unnecessary_refusal": r["v18_agent"]["unnecessary_refusal"],
        "v20_1_unnecessary_refusal": r["v20_1_agent"]["unnecessary_refusal"],
        "v18_relevant_evidence": r["v18_agent"]["relevant_evidence_retrieved"],
        "v20_1_relevant_evidence": r["v20_1_agent"]["relevant_evidence_retrieved"],
        "v18_goal_success": r["v18_agent"]["goal_success"],
        "v20_1_goal_success": r["v20_1_agent"]["goal_success"]} for r in rows])
    write_csv("poster_cross_language.csv", [{"task_id": r["task_id"],
        "v18_goal_success": r["v18_agent"]["goal_success"],
        "v20_1_goal_success": r["v20_1_agent"]["goal_success"],
        "v18_unnecessary_refusal": r["v18_agent"]["unnecessary_refusal"],
        "v20_1_unnecessary_refusal": r["v20_1_agent"]["unnecessary_refusal"],
        "v20_1_support_checked": r["v20_1_agent"]["diagnostics"].get("claim_support_checked"),
        "v20_1_exact_span_passed": r["v20_1_agent"]["diagnostics"].get("exact_span_validation_passed")}
        for r in rows if r["cross_language"]])
    write_csv("poster_citation_support.csv", [{"system": system, "task_id": r["task_id"],
        "citation_links": len(CITATION.findall(r[system]["answer"])),
        "citation_semantic_support": r[system]["citation_semantic_support"],
        "exact_span_validation_passed": r[system]["diagnostics"].get("exact_span_validation_passed")}
        for r in rows for system in ("v18_agent", "v20_1_agent")])
    print({"tasks": len(rows), "v20_1": metrics["v20_1_agent"], "comparisons": comparisons})


if __name__ == "__main__":
    assert numeric_score({"numeric_gold": [{"value": 4.5, "unit": "kW", "tolerance": 0.01}]},
                         "P = 4.5 kW")["final_numeric_correct"]
    main()
