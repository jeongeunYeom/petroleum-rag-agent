"""Integrity-gated V20.1 poster tables, diagnostics, and paired interpretation."""

from __future__ import annotations

import hashlib
import json
import re
import statistics

from common import (BENCHMARK_SHA, JUDGE_MODEL, OLD_COMMIT, POLICY_SHA, PRODUCT_SHA,
                    ROOT, assert_frozen, kb_snapshot, old_bytes, old_json,
                    product_unchanged, read_json, save_json)
from frozen_score_results import CITATION, numeric_match, write_csv


TASKS = read_json(ROOT / "benchmark.json")["tasks"]
SYSTEMS = ("qwen_closed_book", "v18_agent", "v20_1_agent")
FIELDS = ("goal_success", "claim_coverage", "hallucination_free", "numerical_accuracy")
TITLES = {"goal_success": "Goal Success", "claim_coverage": "Claim Coverage",
          "hallucination_free": "Hallucination-free", "numerical_accuracy": "Numerical Accuracy"}
STAGES = ("planning_seconds", "retrieval_seconds", "llm_generation_seconds",
          "python_seconds", "verification_seconds", "calculation_seconds", "synthesis_seconds")


def pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def resume_rows() -> list[dict]:
    suite = read_json(ROOT / "resume_suite.json")
    keywords = {"V18R-01": ["bulk", "부피", "체적"],
                "V18R-02": ["leak", "surface pressure", "표면", "압력"],
                "V18R-03": ["hour", "duration", "시간"]}
    already_supplied = {"V18R-01": ["공극률", "porosity"],
                        "V18R-02": ["mud density", "shoe tvd"],
                        "V18R-03": ["power_kw", "power value"]}
    result = []
    for task in suite["tasks"]:
        path = ROOT / "raw" / "resume_suite" / f"{task['task_id']}.json"
        raw = read_json(path) if path.exists() else {}
        first, second = raw.get("turn_1_run") or {}, raw.get("turn_2_run") or {}
        question = (first.get("clarification_question") or " ".join(first.get("required_inputs") or [])).lower()
        repeat = (second.get("run_status") == "waiting_for_user_input" and
                  second.get("clarification_question") == first.get("clarification_question"))
        calculated = any(c.get("validation_passed") for c in second.get("computations") or [])
        numeric = numeric_match(second.get("final_answer", ""), {**task["expected_result"], "tolerance": 0.01})
        result.append({"task_id": task["task_id"],
            "turn_1_waiting": first.get("run_status") == "waiting_for_user_input",
            "clarification_correct": (first.get("run_status") == "waiting_for_user_input"
                and any(word in question for word in keywords[task["task_id"]])
                and not any(word in question for word in already_supplied[task["task_id"]])),
            "same_run_preserved": bool(raw.get("run_id")) and first.get("run_id") == raw.get("run_id") == second.get("run_id"),
            "resume_input_bound": bool((second.get("telemetry") or {}).get("operands_bound", 0)),
            "repeated_clarification": repeat, "calculation_executed": calculated,
            "goal_success": second.get("status") == "achieved" and numeric["value_correct"]
                            and numeric["unit_correct"] and calculated and not repeat,
            "turn_1_status": first.get("run_status"), "turn_2_status": second.get("run_status"),
            "latency_seconds": raw.get("latency_seconds")})
    return result


def integrity() -> dict:
    assert_frozen()
    preflight = read_json(ROOT / "preflight.json")
    receipt = read_json(ROOT / "freeze_receipt.json")
    snapshot = kb_snapshot()
    raw_files = sorted((ROOT / "raw" / "v20_1_agent").glob("V18P-*.json"))
    judge_files = sorted((ROOT / "raw" / "judge").glob("V18P-*.json"))
    raw = [read_json(path) for path in raw_files]
    judges = [read_json(path) for path in judge_files]
    by_id = {t["task_id"]: t for t in TASKS}
    checks = {
        "24_primary_raw_runs": len(raw) == 24 and {r.get("task_id") for r in raw} == set(by_id),
        "one_attempt_per_primary_task": len(raw) == 24 and all(r.get("attempt_count") == 1 and r.get("run_id") and r.get("run") for r in raw),
        "exact_frozen_questions": len(raw) == 24 and all(r.get("question") == by_id[r["task_id"]]["question"] for r in raw),
        "all_terminal_or_waiting": len(raw) == 24 and all(r.get("run_status") in
            {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"} for r in raw),
        "24_single_exact_judges": len(judges) == 24 and all(
            j.get("attempt_count") == 1 and j.get("status") == "completed"
            and j.get("actual_model") == JUDGE_MODEL for j in judges),
        "benchmark_hash_unchanged": preflight["benchmark_sha256"] == BENCHMARK_SHA,
        "policy_hash_unchanged": preflight["policy_sha256"] == POLICY_SHA,
        "kb_snapshot_unchanged": snapshot["all_files_match_frozen"]
                                 and preflight["kb"]["all_files_match_frozen"],
        "product_code_unchanged": product_unchanged() and preflight["evaluated_product_sha"] == PRODUCT_SHA,
        "web_unused": len(raw) == 24 and all(not ((r.get("run") or {}).get("web_sources") or []) for r in raw),
        "correct_model_and_retrieval": preflight["local_model"]["name"] == "qwen3:8b"
                                      and preflight["retrieval_mode"] == "hybrid",
        "old_baselines_immutable": all(hashlib.sha256(old_bytes(name)).hexdigest() == value
            for name, value in preflight["baseline_artifact_sha256"].items())
            and preflight["baseline_source_commit"] == OLD_COMMIT,
        "resume_excluded_from_primary": len(TASKS) == 24 and all(t["task_id"].startswith("V18P-") for t in TASKS),
        "harness_frozen_before_runs": bool(receipt.get("harness_commit_sha"))
                                      and receipt.get("product_sha") == PRODUCT_SHA,
    }
    return {"checks": checks, "FINALIZED": all(checks.values()), "kb_after": snapshot,
            "evaluated_product_sha": PRODUCT_SHA, "harness_commit_sha": receipt["harness_commit_sha"],
            "benchmark_sha256": BENCHMARK_SHA, "policy_sha256": POLICY_SHA,
            "baseline_source_commit": OLD_COMMIT}


def diagnostic_summary(rows: list[dict], resumes: list[dict]) -> dict:
    answerable_n = sum(r["answerable"] for r in rows)
    new = [r["v20_1_agent"] for r in rows]
    relevant = [v for v in new if v["relevant_evidence_retrieved"] is True]
    numeric = [r for r in rows if r["numeric"]]
    kb = [r for r in rows if r["category"] == "kb_formula"]
    cross = [r for r in rows if r["cross_language"]]
    refusal = {system: {"count": sum(r[system]["unnecessary_refusal"] for r in rows),
                         "rate_answerable": sum(r[system]["unnecessary_refusal"] for r in rows)/answerable_n,
                         "rate_all": sum(r[system]["unnecessary_refusal"] for r in rows)/24}
               for system in ("v18_agent", "v20_1_agent")}
    return {
        "unnecessary_refusal": refusal,
        "evidence_conversion": {"relevant": len(relevant), "relevant_but_failed": sum(
            not v["goal_success"] for v in relevant),
            "relevant_to_non_refusal": sum(not v["unnecessary_refusal"] for v in relevant),
            "relevant_to_success": sum(v["goal_success"] for v in relevant),
            "verified_support_but_refused": sum(v["diagnostics"].get("supported_claim_count", 0) > 0
                and v["unnecessary_refusal"] for v in new)},
        "numeric": {"n": 10, "correct_route": sum(r["v20_1_agent"]["diagnostics"]["route_correct"] for r in numeric),
            "operands_complete": sum(r["v20_1_agent"]["diagnostics"]["operands_complete"] for r in numeric),
            "formula_ready": sum(r["v20_1_agent"]["diagnostics"]["formula_ready"] for r in numeric),
            "formula_source_verified": sum(r["v20_1_agent"]["diagnostics"]["formula_source_verified"] for r in kb),
            "calculation_executed": sum(r["v20_1_agent"]["diagnostics"]["calculation_executed"] for r in numeric),
            "calculation_validated": sum(r["v20_1_agent"]["diagnostics"]["calculation_validated"] for r in numeric),
            "numeric_correct": sum(r["v20_1_agent"]["numeric"]["final_numeric_correct"] for r in numeric)},
        "kb_formula": {"n": 3, "retrieval_success": sum(r["v20_1_agent"]["diagnostics"]["retrieval_success"] for r in kb),
            "correct_span": sum(r["v20_1_agent"]["diagnostics"]["correct_formula_span_retrieved"] for r in kb),
            "retrieve_to_calculate": sum(r["v20_1_agent"]["diagnostics"]["route_correct"] for r in kb),
            "numeric_correct": sum(r["v20_1_agent"]["numeric"]["final_numeric_correct"] for r in kb)},
        "cross_language": {"n": len(cross), "success": sum(r["v20_1_agent"]["goal_success"] for r in cross),
            "unnecessary_refusals": sum(r["v20_1_agent"]["unnecessary_refusal"] for r in cross)},
        "citation": {"bearing_responses": sum(bool(CITATION.search(v["answer"])) for v in new),
            "link_count": sum(len(CITATION.findall(v["answer"])) for v in new),
            "semantic_support_true": sum(v["citation_semantic_support"] is True for v in new),
            "exact_span_validation_passes": sum(v["diagnostics"].get("exact_span_validation_passed", False) for v in new)},
        "stage_latency_mean_seconds": {stage: statistics.fmean(
            (v["diagnostics"].get("timing") or {}).get(stage, 0.0) for v in new) for stage in STAGES},
        "resume": {"n": 3, "passed": sum(r["goal_success"] for r in resumes),
            "same_run_preserved": sum(r["same_run_preserved"] for r in resumes),
            "repeated_clarification_count": sum(r["repeated_clarification"] for r in resumes)},
    }


def main() -> None:
    rows = read_json(ROOT / "scored_rows.json")
    summary = read_json(ROOT / "final_metrics.json")
    resumes = resume_rows()
    write_csv("poster_resume_suite.csv", resumes)
    checks = integrity()
    diagnostics = diagnostic_summary(rows, resumes)
    summary["integrity"] = checks
    summary["diagnostics"] = diagnostics
    summary["FINALIZED"] = checks["FINALIZED"]
    summary["status"] = "finalized" if checks["FINALIZED"] else "not_finalized"
    save_json(ROOT / "final_metrics.json", summary)
    save_json(ROOT / "completion_checks.json", checks)
    metrics, comparisons = summary["systems"], summary["comparisons"]
    table = ["| Metric | qwen3:8b Closed-book | V18 Agent | V20.1 Agent |",
             "| --- | ---: | ---: | ---: |"]
    diffs = {}
    for key in ("v20_1_minus_v18", "v20_1_minus_qwen"):
        lines = ["| Metric | Difference | Paired 95% CI |", "| --- | ---: | ---: |"]
        for field in FIELDS:
            x = comparisons[key][field]
            lines.append(f"| {TITLES[field]} | {100*x['difference']:+.1f} pp | [{100*x['ci95_low']:+.1f}, {100*x['ci95_high']:+.1f}] pp |")
        diffs[key] = lines
    for field in FIELDS:
        table.append(f"| {TITLES[field]} | {pct(metrics['qwen_closed_book'][field])} | "
                     f"{pct(metrics['v18_agent'][field])} | {pct(metrics['v20_1_agent'][field])} |")
    poster = ("# Frozen paired poster metrics\n\n" + "\n".join(table) + "\n\n## V20.1 − V18\n\n"
              + "\n".join(diffs["v20_1_minus_v18"]) + "\n\n## V20.1 − Qwen\n\n"
              + "\n".join(diffs["v20_1_minus_qwen"]) + "\n")
    (ROOT / "poster_metrics.md").write_text(poster, encoding="utf-8")
    direction = comparisons["v20_1_minus_v18"]
    goal_gain = direction["goal_success"]["difference"]
    num_gain = direction["numerical_accuracy"]["difference"]
    no_safety_decline = (metrics["v20_1_agent"]["hallucination_free"]
                         >= metrics["v18_agent"]["hallucination_free"])
    poster_decision = ("POSTER METRICS UPDATE RECOMMENDED"
                       if (goal_gain >= 0 and num_gain >= 0 and (goal_gain > 0 or num_gain > 0)
                           and no_safety_decline) else "KEEP EXISTING POSTER METRICS") if checks["FINALIZED"] else "NOT FINALIZED"
    def interpretation(field: str, base: str) -> str:
        x = comparisons[base][field]
        label = "V18" if base == "v20_1_minus_v18" else "Qwen closed-book"
        if x["ci95_low"] > 0:
            return f"{TITLES[field]} exceeded {label} on this paired sample; the 95% CI is above zero."
        if x["ci95_high"] < 0:
            return f"{TITLES[field]} was lower than {label} on this paired sample; the 95% CI is below zero."
        return f"{TITLES[field]} differed from {label} by {100*x['difference']:+.1f} pp, but the paired 95% CI includes zero."
    failed = [r for r in rows if not r["v20_1_agent"]["goal_success"]]
    failures = ["| Task | Category | V18 success | V20.1 status | Error labels |",
                "| --- | --- | ---: | --- | --- |"]
    for row in failed:
        value = row["v20_1_agent"]
        failures.append(f"| {row['task_id']} | {row['category']} | {row['v18_agent']['goal_success']} | "
                        f"{value['run_status']} | {', '.join(value['error_labels']) or 'none'} |")
    latency = ["| System | Mean | Median | P95 |", "| --- | ---: | ---: | ---: |"]
    for system in SYSTEMS:
        m = metrics[system]
        latency.append(f"| {system} | {m['latency_mean_seconds']:.2f}s | {m['latency_median_seconds']:.2f}s | "
                       f"{m['latency_p95_seconds']:.2f}s |")
    report = (
        "# Petroleum RAG Agent V20.1 — frozen paired poster re-evaluation\n\n"
        "V20.1 was evaluated by frozen paired re-evaluation on the same 24-task benchmark previously used for V18. "
        "It is therefore a controlled version comparison, not a new unseen held-out benchmark.\n\n"
        f"Product SHA `{PRODUCT_SHA}`; old frozen benchmark SHA256 `{BENCHMARK_SHA}`; policy SHA256 `{POLICY_SHA}`. "
        f"Exact local qwen3:8b, hybrid retrieval, 12-document/18,976-chunk KB, web off. "
        f"Integrity FINALIZED={str(checks['FINALIZED']).lower()}.\n\n"
        + poster + "\n## Diagnostics\n\n"
        f"Numeric pipeline (n=10): {json.dumps(diagnostics['numeric'])}.\n\n"
        f"KB formula pipeline (n=3): {json.dumps(diagnostics['kb_formula'])}.\n\n"
        f"Unnecessary refusals: {json.dumps(diagnostics['unnecessary_refusal'])}.\n\n"
        f"Relevant evidence and answer conversion: {json.dumps(diagnostics['evidence_conversion'])}.\n\n"
        f"Cross-language: {json.dumps(diagnostics['cross_language'])}. Citation: {json.dumps(diagnostics['citation'])}.\n\n"
        "## V20.1 unsuccessful tasks\n\n" + "\n".join(failures) + "\n\n"
        "## Latency\n\n" + "\n".join(latency) + "\n\n"
        "Stage means (seconds; stages may overlap and are not summed into total): "
        + json.dumps(diagnostics["stage_latency_mean_seconds"]) + "\n\n"
        "## Separate same-run resume diagnostic\n\n"
        + json.dumps(diagnostics["resume"]) + ". Three probes are excluded from all primary denominators.\n\n"
        "## Poster-safe conclusions\n\n"
        f"1. {interpretation('goal_success', 'v20_1_minus_v18')}\n"
        f"2. {interpretation('numerical_accuracy', 'v20_1_minus_v18')}\n"
        f"3. {interpretation('goal_success', 'v20_1_minus_qwen')}\n\n"
        "## Limitations\n\n"
        "This unchanged 24-task set was previously used for V18, so it is not unseen for V20.1. "
        "Numerical Accuracy has only ten tasks and KB formula diagnostics only three. "
        "Semantic adjudication used one AI reviewer, not human review. "
        "Agent runs were sequential; latency may reflect cache/order effects and is not a causal speed claim. "
        "No benchmark, rubric, product, or KB changes were made after results.\n\n"
        f"**{poster_decision}**\n"
    )
    (ROOT / "FINAL_REPORT.md").write_text(report, encoding="utf-8")
    audit = ("# V20.1 scoring audit\n\n"
        f"Frozen benchmark/policy hashes: `{BENCHMARK_SHA}` / `{POLICY_SHA}`. "
        f"Old task-level scores are read from `{OLD_COMMIT}` and are not recomputed. "
        "The V18 frozen numeric matcher, agent diagnostics, score reconciliation, and paired bootstrap are reused. "
        "Claim scores are 0/0.5/1; material error labels override an inconsistent hallucination-free verdict. "
        "A waiting Agent on an answerable task is an unnecessary refusal under the frozen policy. "
        "Numerical Goal Success additionally requires value, unit, route, validated calculation and, for KB formula tasks, "
        "verified correct literal formula-source span. Citation presence alone is insufficient. "
        "The single-reviewer AI-assisted semantic adjudication uses anonymous randomized labels; old baseline scores remain fixed. "
        "Paired percentile bootstrap uses 10,000 resamples, seed 20261012 and only ten numeric tasks for numeric CI. "
        f"FINALIZED={str(checks['FINALIZED']).lower()}; failed integrity checks: "
        f"{[name for name, ok in checks['checks'].items() if not ok]}.\n")
    (ROOT / "SCORING_AUDIT.md").write_text(audit, encoding="utf-8")
    print(json.dumps({"FINALIZED": checks["FINALIZED"], "metrics": metrics["v20_1_agent"],
                      "diagnostics": diagnostics, "poster_decision": poster_decision}, indent=2))


if __name__ == "__main__":
    main()
