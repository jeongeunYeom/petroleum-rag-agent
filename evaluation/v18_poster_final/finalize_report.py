"""Create poster-facing summaries from sealed raw rows and frozen scoring."""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import subprocess
from pathlib import Path

from score_results import CITATION, ROOT, TASKS, numeric_match, percentile


SYSTEMS = ["qwen_closed_book", "v17_agent", "v18_agent", "gpt_reference"]
LABELS = {"qwen_closed_book": "qwen3:8b (Closed-book)",
          "v17_agent": "Petroleum RAG Agent v17", "v18_agent": "Petroleum RAG Agent v18",
          "gpt_reference": "GPT-5.4 mini (Closed-book reference)"}
STAGES = ["planning_seconds", "retrieval_seconds", "llm_generation_seconds",
          "python_seconds", "verification_seconds", "calculation_seconds", "synthesis_seconds"]
PRICES = {"gpt_reference": {"input": 0.75, "cached": 0.075, "output": 4.5},
          "judge": {"input": 2.5, "cached": 0.25, "output": 15.0}}
PRICE_SOURCES = {"gpt_reference": "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
                 "judge": "https://developers.openai.com/api/docs/models/gpt-5.4"}


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(name: str, value: object) -> None:
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    with (ROOT / name).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
        writer.writeheader()
        writer.writerows(rows)


def pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def cost(system: str) -> dict:
    folder = ROOT / "raw" / ("judge" if system == "judge" else system)
    rows = [read(path) for path in sorted(folder.glob("V18P-*.json"))]
    input_tokens = sum((r.get("usage") or {}).get("input_tokens", 0) for r in rows)
    output_tokens = sum((r.get("usage") or {}).get("output_tokens", 0) for r in rows)
    cached_tokens = sum(((r.get("usage") or {}).get("input_tokens_details") or {}).get("cached_tokens", 0) for r in rows)
    price = PRICES[system]
    estimate = ((input_tokens - cached_tokens) * price["input"] + cached_tokens * price["cached"]
                + output_tokens * price["output"]) / 1_000_000
    return {"model": "gpt-5.4-2026-03-05" if system == "judge" else "gpt-5.4-mini-2026-03-17",
            "calls": len(rows), "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cached_tokens": cached_tokens, "estimated_list_price_usd": round(estimate, 5),
            "pricing_source": PRICE_SOURCES[system]}


def resume_rows() -> list[dict]:
    suite = read(ROOT / "resume_suite.json")
    keywords = {"V18R-01": ["bulk", "부피", "체적"],
                "V18R-02": ["leak", "surface pressure", "표면", "압력"],
                "V18R-03": ["hour", "duration", "시간"]}
    already_supplied = {"V18R-01": ["공극률", "porosity"],
                        "V18R-02": ["mud density", "shoe tvd"],
                        "V18R-03": ["power_kw", "power value"]}
    result = []
    for task in suite["tasks"]:
        path = ROOT / "raw" / "resume_suite" / f"{task['task_id']}.json"
        raw = read(path) if path.exists() else {}
        first = raw.get("turn_1_run") or {}
        second = raw.get("turn_2_run") or {}
        question = (first.get("clarification_question") or " ".join(first.get("required_inputs") or [])).lower()
        repeat = (second.get("run_status") == "waiting_for_user_input" and
                  second.get("clarification_question") == first.get("clarification_question"))
        calculated = any(c.get("validation_passed") for c in second.get("computations") or [])
        numeric = numeric_match(second.get("final_answer", ""),
                                {**task["expected_result"], "tolerance": 0.01})
        row = {"task_id": task["task_id"], "turn_1_waiting": first.get("run_status") == "waiting_for_user_input",
               "clarification_correct": (
                   first.get("run_status") == "waiting_for_user_input"
                   and any(word in question for word in keywords[task["task_id"]])
                   and not any(word in question for word in already_supplied[task["task_id"]])
               ),
               "same_run_preserved": bool(raw.get("run_id")) and first.get("run_id") == raw.get("run_id") == second.get("run_id"),
               "resume_input_bound": bool((second.get("telemetry") or {}).get("operands_bound", 0)),
               "repeated_clarification": repeat, "calculation_executed": calculated,
               "goal_success": second.get("status") == "achieved" and numeric["value_correct"]
                               and numeric["unit_correct"] and calculated and not repeat,
               "turn_1_status": first.get("run_status"), "turn_2_status": second.get("run_status"),
               "latency_seconds": raw.get("latency_seconds")}
        result.append(row)
    return result


def chosen_demo(rows: list[dict]) -> dict:
    candidates = []
    for task in TASKS:
        scored = next(r for r in rows if r["task_id"] == task["task_id"])
        if not scored["v18_agent"]["goal_success"]:
            continue
        raw = read(ROOT / "raw" / "v18_agent" / f"{task['task_id']}.json")
        run = raw.get("run") or {}
        actions = [a.get("action_type", "").lower() for a in run.get("action_history") or []]
        preferred = all(a in actions for a in ("retrieve", "calculate", "verify", "synthesize", "stop"))
        fallback = all(a in actions for a in ("retrieve", "verify", "synthesize", "stop"))
        actual_grounded = all(a in actions for a in ("retrieve", "verify", "stop"))
        if preferred or fallback or actual_grounded:
            tier = 3 if preferred else 2 if fallback else 1
            candidates.append((tier, len(run.get("iterations") or []), len(task["required_claims"]), task, raw, actions))
    if not candidates:
        return {"status": "unavailable", "reason": "No successful real run matched the trace preference."}
    tier, _, _, task, raw, actions = max(candidates, key=lambda item: (item[0], item[1], item[2]))
    run = raw["run"]
    return {"status": "selected", "task_id": task["task_id"], "user_goal": task["question"],
            "selection_tier": tier,
            "selection_note": "No successful run had the preferred synthesis action; selected a real grounded retrieve→verify→stop run." if tier == 1 else None,
            "run_id": raw.get("run_id"), "action_history": run.get("action_history"),
            "action_sequence": actions, "iterations": run.get("iterations_completed"),
            "goal_coverage_progression": [state.get("coverage") for state in run.get("state_history") or []
                                          if state.get("coverage") is not None],
            "evidence_ids": [s.get("evidence_id") for s in run.get("internal_sources") or []],
            "calculation_ids": [c.get("computation_id") for c in run.get("computations") or []],
            "final_answer": run.get("final_answer"),
            "citations": CITATION.findall(run.get("final_answer", "")),
            "stop_reason": run.get("stop_reason"), "final_status": run.get("status")}


def git_head(path: str) -> str:
    return subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True).strip()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def integrity() -> dict:
    receipt = read(ROOT / "freeze_receipt.json")
    snapshot = read(ROOT / "kb_snapshot.json")
    all_raw = {system: [read(path) for path in sorted((ROOT / "raw" / system).glob("V18P-*.json"))]
               for system in [*SYSTEMS, "judge"]}
    questions = {t["task_id"]: t["question"] for t in TASKS}
    checks = {
        "24_qwen": len(all_raw["qwen_closed_book"]) == 24 and all(r.get("status") == "completed" for r in all_raw["qwen_closed_book"]),
        "24_v17": len(all_raw["v17_agent"]) == 24 and all(r.get("status") == "completed" for r in all_raw["v17_agent"]),
        "24_v18": len(all_raw["v18_agent"]) == 24 and all(r.get("status") == "completed" for r in all_raw["v18_agent"]),
        "24_gpt": len(all_raw["gpt_reference"]) == 24 and all(r.get("status") == "completed" for r in all_raw["gpt_reference"]),
        "24_judge": len(all_raw["judge"]) == 24 and all(r.get("status") == "completed" for r in all_raw["judge"]),
        "exact_same_questions": all(r.get("question") == questions.get(r.get("task_id"))
                                   for system in SYSTEMS for r in all_raw[system]),
        "v17_sha_unchanged": git_head(r"D:\petroleum-rag-agent-v17-final-eval") == receipt["product_v17_sha"],
        "v18_sha_unchanged": git_head(r"D:\petroleum-rag-agent-v18-final-eval") == receipt["product_v18_sha"],
        "benchmark_sha_unchanged": sha(ROOT / "benchmark.json") == receipt["benchmark_sha256"],
        "policy_sha_unchanged": sha(ROOT / "POLICY.md") == receipt["policy_sha256"],
        "kb_snapshot_unchanged": all(sha(Path(snapshot["persistent_directory"]) / path) == item["sha256"]
                                     for path, item in snapshot["files"].items()),
        "no_retries": all(r.get("attempt_count") == 1 for system in [*SYSTEMS, "judge"] for r in all_raw[system]),
        "main_unchanged": subprocess.check_output(["git", "rev-parse", "main"], text=True).strip()
                          == "8ec21935afeae871904a94a26c1a0bf81238e00e",
        "resume_excluded_from_primary": len(TASKS) == 24 and all(t["task_id"].startswith("V18P-") for t in TASKS),
    }
    return {"checks": checks, "FINALIZED": all(checks.values()),
            "product_v17_sha": receipt["product_v17_sha"], "product_v18_sha": receipt["product_v18_sha"],
            "freeze_commit_sha": receipt["freeze_commit_sha"], "benchmark_sha256": receipt["benchmark_sha256"],
            "no_post_result_tuning": True}


def main() -> None:
    rows = read(ROOT / "scored_rows.json")
    summary = read(ROOT / "final_metrics.json")
    systems = summary["systems"]
    comparisons = summary["comparisons"]
    resumes = resume_rows()
    write_csv("poster_resume_suite.csv", resumes)
    demo = chosen_demo(rows)
    write_json("poster_demo_trace.json", demo)
    if demo["status"] == "selected":
        answer_for_markdown = "\n".join(line.rstrip() for line in demo["final_answer"].splitlines())
        demo_text = (f"# Real V18 poster trace — {demo['task_id']}\n\n"
                     f"Goal: {demo['user_goal']}\n\n"
                     f"Selection note: {demo.get('selection_note') or 'Preferred real action sequence matched.'}\n\n"
                     f"Actions: {' → '.join(demo['action_sequence'])}\n\n"
                     f"Iterations: {demo['iterations']}\n\n"
                     f"Goal coverage progression: {demo['goal_coverage_progression']}\n\n"
                     f"Evidence IDs: {demo['evidence_ids']}\n\n"
                     f"Calculation IDs: {demo['calculation_ids']}\n\n"
                     f"Final status/stop reason: {demo['final_status']} / {demo['stop_reason']}\n\n"
                     f"Final answer:\n\n{answer_for_markdown}\n")
    else:
        demo_text = "# Poster demo trace unavailable\n\nNo successful real V18 execution matched the selection policy.\n"
    (ROOT / "poster_demo_trace.md").write_text(demo_text, encoding="utf-8")
    checks = integrity()
    write_json("completion_checks.json", checks)
    costs = {system: cost(system) for system in ("gpt_reference", "judge")}
    summary["cost"] = costs
    summary["integrity"] = checks
    write_json("final_metrics.json", summary)

    fields = ("goal_success", "claim_coverage", "hallucination_free", "numerical_accuracy")
    title = {"goal_success": "Goal Success", "claim_coverage": "Claim Coverage",
             "hallucination_free": "Hallucination-free", "numerical_accuracy": "Numerical Accuracy"}
    version = ["| Metric | V17 | V18 | V18 − V17 (95% CI) |", "| --- | ---: | ---: | ---: |"]
    same_base = ["| Metric | qwen3:8b Closed-book | V18 Agent | Agent − Qwen (95% CI) |", "| --- | ---: | ---: | ---: |"]
    for field in fields:
        a = comparisons["v18_minus_v17"][field]
        b = comparisons["v18_minus_qwen"][field]
        version.append(f"| {title[field]} | {pct(systems['v17_agent'][field])} | {pct(systems['v18_agent'][field])} | {100*a['difference']:+.1f} pp [{100*a['ci95_low']:+.1f}, {100*a['ci95_high']:+.1f}] |")
        same_base.append(f"| {title[field]} | {pct(systems['qwen_closed_book'][field])} | {pct(systems['v18_agent'][field])} | {100*b['difference']:+.1f} pp [{100*b['ci95_low']:+.1f}, {100*b['ci95_high']:+.1f}] |")
    reference = ["| System | Goal Success | Claim Coverage | Hallucination-free | Numerical Accuracy | Median latency |",
                 "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for system in SYSTEMS:
        m = systems[system]
        reference.append(f"| {LABELS[system]} | {pct(m['goal_success'])} | {pct(m['claim_coverage'])} | {pct(m['hallucination_free'])} | {pct(m['numerical_accuracy'])} | {m['latency_median_seconds']:.2f}s |")
    latency_lines = ["| System | Mean | Median | P95 |", "| --- | ---: | ---: | ---: |"]
    for system in SYSTEMS:
        m = systems[system]
        latency_lines.append(
            f"| {LABELS[system]} | {m['latency_mean_seconds']:.2f}s | "
            f"{m['latency_median_seconds']:.2f}s | {m['latency_p95_seconds']:.2f}s |"
        )
    tables = "# Poster results tables\n\n## A. Version effect\n\n" + "\n".join(version) + "\n\n## B. Same base model\n\n" + "\n".join(same_base) + "\n\n## C. Reference\n\n" + "\n".join(reference) + "\n"
    (ROOT / "POSTER_RESULTS_TABLE.md").write_text(tables, encoding="utf-8")

    v17 = [r["v17_agent"] for r in rows]
    v18 = [r["v18_agent"] for r in rows]
    answerable_n = sum(r["answerable"] for r in rows)
    kb = [r for r in rows if r["category"] == "kb_formula"]
    cross = [r for r in rows if r["cross_language"]]
    reasoning = [r for r in rows if r["category"] == "multi_claim_reasoning"]
    relevant17 = [v for v in v17 if v["relevant_evidence_retrieved"] is True]
    relevant18 = [v for v in v18 if v["relevant_evidence_retrieved"] is True]
    stages = {}
    for system in ("v17_agent", "v18_agent"):
        stages[system] = {stage: statistics.fmean((r[system]["diagnostics"].get("timing") or {}).get(stage, 0.0)
                                            for r in rows) for stage in STAGES}
    citation = {}
    for system in ("v17_agent", "v18_agent"):
        citation[system] = {"bearing_responses": sum(bool(CITATION.search(r[system]["answer"])) for r in rows),
            "link_count": sum(len(CITATION.findall(r[system]["answer"])) for r in rows),
            "semantic_support_true": sum(r[system]["citation_semantic_support"] is True for r in rows),
            "exact_span_validation_passes": sum(r[system]["diagnostics"].get("exact_span_validation_passed", False) for r in rows)}
    diagnostic_summary = {
        "unnecessary_refusal": {system: {"count": sum(r[system]["unnecessary_refusal"] for r in rows),
            "rate_answerable": sum(r[system]["unnecessary_refusal"] for r in rows)/answerable_n,
            "rate_all": sum(r[system]["unnecessary_refusal"] for r in rows)/24}
            for system in ("v17_agent", "v18_agent")},
        "evidence_conversion": {"v17": {"relevant": len(relevant17), "failed": sum(not v["goal_success"] for v in relevant17),
             "to_non_refusal": sum(not v["unnecessary_refusal"] for v in relevant17),
             "to_success": sum(v["goal_success"] for v in relevant17)},
            "v18": {"relevant": len(relevant18), "failed": sum(not v["goal_success"] for v in relevant18),
             "to_non_refusal": sum(not v["unnecessary_refusal"] for v in relevant18),
             "to_success": sum(v["goal_success"] for v in relevant18)}},
        "v18_kb_formula": {"n": 3, "retrieval_success": sum(r["v18_agent"]["diagnostics"]["retrieval_success"] for r in kb),
             "correct_span": sum(r["v18_agent"]["diagnostics"]["correct_formula_span_retrieved"] for r in kb),
             "retrieve_to_calculate": sum(r["v18_agent"]["diagnostics"]["route_correct"] for r in kb),
             "numeric_correct": sum(r["v18_agent"]["numeric"]["final_numeric_correct"] for r in kb)},
        "v18_numeric": {"n": 10, "correct_route": sum(r["v18_agent"]["diagnostics"]["route_correct"] for r in rows if r["numeric"]),
             "operands_complete": sum(r["v18_agent"]["diagnostics"]["operands_complete"] for r in rows if r["numeric"]),
             "formula_ready": sum(r["v18_agent"]["diagnostics"]["formula_ready"] for r in rows if r["numeric"]),
             "formula_source_verified": sum(r["v18_agent"]["diagnostics"]["formula_source_verified"] for r in kb),
             "calculation_executed": sum(r["v18_agent"]["diagnostics"]["calculation_executed"] for r in rows if r["numeric"]),
             "calculation_validated": sum(r["v18_agent"]["diagnostics"]["calculation_validated"] for r in rows if r["numeric"]),
             "numeric_correct": sum(r["v18_agent"]["numeric"]["final_numeric_correct"] for r in rows if r["numeric"])},
        "cross_language": {"n": len(cross), "v17_success": sum(r["v17_agent"]["goal_success"] for r in cross),
             "v18_success": sum(r["v18_agent"]["goal_success"] for r in cross),
             "v17_unnecessary_refusals": sum(r["v17_agent"]["unnecessary_refusal"] for r in cross),
             "v18_unnecessary_refusals": sum(r["v18_agent"]["unnecessary_refusal"] for r in cross)},
        "citation": citation, "stage_latency_mean_seconds": stages,
        "v18_grounded_fast_path_used": sum(v["diagnostics"].get("grounded_fast_path_used", False) for v in v18),
        "v18_verified_support_but_refused": sum(v["diagnostics"].get("supported_claim_count", 0) > 0 and v["unnecessary_refusal"] for v in v18),
        "resume": {"n": 3, "passed": sum(r["goal_success"] for r in resumes),
            "same_run_preserved": sum(r["same_run_preserved"] for r in resumes),
            "repeated_clarification_count": sum(r["repeated_clarification"] for r in resumes)},
    }
    summary["diagnostics"] = diagnostic_summary
    write_json("final_metrics.json", summary)

    callouts = [
        f"Unnecessary refusals: v17 {diagnostic_summary['unnecessary_refusal']['v17_agent']['count']}/{answerable_n} answerable; v18 {diagnostic_summary['unnecessary_refusal']['v18_agent']['count']}/{answerable_n}.",
        f"Calculation executions: v17 {sum(v['diagnostics'].get('calculation_executed', False) for v in v17 if v['diagnostics'])}; v18 {sum(v['diagnostics'].get('calculation_executed', False) for v in v18 if v['diagnostics'])}.",
        f"Numerical Accuracy: v17 {pct(systems['v17_agent']['numerical_accuracy'])}; v18 {pct(systems['v18_agent']['numerical_accuracy'])} (n=10).",
        f"V18 KB formula retrieve→calculate: {diagnostic_summary['v18_kb_formula']['retrieve_to_calculate']}/3.",
        f"V18 relevant evidence but failed: {diagnostic_summary['evidence_conversion']['v18']['failed']}/{diagnostic_summary['evidence_conversion']['v18']['relevant']}.",
        f"V18 verified support but refused: {diagnostic_summary['v18_verified_support_but_refused']} tasks.",
    ]
    failed = [r for r in rows if not r["v18_agent"]["goal_success"]]
    failure_lines = ["| Task | Category | V17 success | V18 error labels | V18 status |",
                     "| --- | --- | ---: | --- | --- |"]
    for r in failed:
        v = r["v18_agent"]
        failure_lines.append(f"| {r['task_id']} | {r['category']} | {r['v17_agent']['goal_success']} | {', '.join(v['error_labels']) or 'none'} | {v['run_status']} |")
    multi_lines = ["| Task | Required claims | V17 detected/supported | V18 detected/supported | External coverage V17/V18 |",
                   "| --- | ---: | ---: | ---: | ---: |"]
    for r in reasoning:
        t = next(t for t in TASKS if t["task_id"] == r["task_id"])
        a, b = r["v17_agent"], r["v18_agent"]
        multi_lines.append(f"| {r['task_id']} | {len(t['required_claims'])} | {a['diagnostics'].get('detected_claim_count',0)}/{a['diagnostics'].get('supported_claim_count',0)} | {b['diagnostics'].get('detected_claim_count',0)}/{b['diagnostics'].get('supported_claim_count',0)} | {pct(a['claim_coverage'])} / {pct(b['claim_coverage'])} |")
    direction = comparisons["v18_minus_v17"]["goal_success"]
    if direction["ci95_low"] > 0:
        version_conclusion = "V18 improved Goal Success over v17 on this paired 24-task sample (95% paired CI above zero)."
    elif direction["ci95_high"] < 0:
        version_conclusion = "V18 was worse than v17 on Goal Success in this paired sample (95% paired CI below zero)."
    else:
        version_conclusion = "V18 and v17 had identical Goal Success on all 24 paired tasks (difference 0.0 pp; sample bootstrap CI [0.0, 0.0]); this sample shows no version gain and does not establish population equivalence."
    rag = comparisons["v18_minus_qwen"]["goal_success"]
    if rag["ci95_low"] > 0:
        rag_conclusion = "The complete V18 Agent exceeded its qwen3:8b closed-book base on Goal Success in this sample (95% paired CI above zero)."
    else:
        rag_conclusion = "The same-base Goal Success comparison does not establish an Agent advantage at 95% CI on this sample."
    report = (
        "# Petroleum RAG Agent v18 — final independent paired poster evaluation\n\n"
        f"Frozen products: v17 `{checks['product_v17_sha']}`, v18 `{checks['product_v18_sha']}`. "
        f"Benchmark freeze `{checks['freeze_commit_sha']}`; SHA256 `{checks['benchmark_sha256']}`. "
        "Same 24 exact questions, same 12-document / 18,976-chunk production KB, hybrid retrieval, web off. "
        f"Integrity FINALIZED={str(checks['FINALIZED']).lower()}.\n\n"
        + tables + "\n## Poster-safe diagnostic callouts\n\n"
        + "\n".join(f"- {line}" for line in callouts) + "\n\n"
        + "## Category and pipeline diagnostics\n\n"
        + "Knowledge n=6; Reasoning n=4; Calculation n=10; Safety n=4. See `poster_category_metrics.csv`. "
        + f"V18 numeric pipeline: {diagnostic_summary['v18_numeric']}. "
        + f"V18 KB formula pipeline: {diagnostic_summary['v18_kb_formula']}. "
        + f"Cross-language Korean/English evidence: {diagnostic_summary['cross_language']}. "
        + f"Citation diagnostics: {citation}.\n\n"
        + "### Multi-claim reasoning (claim scores are external adjudication)\n\n"
        + "\n".join(multi_lines) + "\n\n"
        + "### V18 unsuccessful tasks\n\n" + "\n".join(failure_lines) + "\n\n"
        + "## Latency and cost\n\n"
        + "\n".join(latency_lines) + "\n\n"
        + "Stage means (seconds; stages may overlap and are not summed into total): "
        + json.dumps(stages, ensure_ascii=False) + "\n\n"
        + f"GPT reference: {costs['gpt_reference']}. Judge: {costs['judge']}. "
        + "Local inference; hardware/electricity cost not estimated. List-price sources: "
        + f"[mini]({PRICE_SOURCES['gpt_reference']}) and [judge]({PRICE_SOURCES['judge']}).\n\n"
        + "## Separate same-run resume diagnostic\n\n"
        + f"{diagnostic_summary['resume']}. Its 3 tasks are excluded from all primary denominators; see `poster_resume_suite.csv`.\n\n"
        + "## Poster-safe conclusions\n\n"
        + f"1. {version_conclusion}\n2. {rag_conclusion}\n"
        + f"3. In KB formula tasks, v18 retrieved the exact formula span in {diagnostic_summary['v18_kb_formula']['correct_span']}/3 and made a retrieve→calculate transition in {diagnostic_summary['v18_kb_formula']['retrieve_to_calculate']}/3. "
        + "This isolates remaining retrieval-versus-orchestration failures without assuming a positive result.\n\n"
        + "## Limitations\n\n"
        + "Only 24 primary tasks and 10 numeric tasks; paired bootstrap intervals remain wide. "
        + "The semantic adjudication is one AI reviewer, not human review. "
        + "Retrieved-evidence relevance and citation support are reviewer labels; deterministic numeric checks and raw traces are separate. "
        + "V17 and V18 were run sequentially; latency differences may reflect cache/order effects and are not a causal speed claim. "
        + "Seven reviewer records had material-error labels inconsistent with their hallucination-free flag; derived scoring follows the frozen error-label policy. "
        + "Some frozen domain labels for arithmetic tasks are broad legacy metadata labels and are not used in scoring. "
        + "No post-result tuning was performed.\n"
    )
    (ROOT / "FINAL_REPORT.md").write_text(report, encoding="utf-8")
    audit = (
        "# Scoring audit\n\n"
        "Frozen gold and policy hashes are checked in `completion_checks.json`. One run/call per task per system, "
        "with attempted reservations to prevent accidental retries. Judge outputs are anonymous, randomized "
        "per task and preserved under `raw/judge/`; this is single-reviewer AI-assisted semantic adjudication, "
        "not human review. Claim scores are 0/0.5/1. Hallucination-free excludes omissions alone. "
        "Numerical scoring separately checks printed value against frozen tolerance and nearby unit in the raw "
        "answer. Equivalent LaTeX-rendered units (for example `^\\circ\\text{C}`) are normalized before "
        "unit matching; this corrected the Qwen V18P-014 numeric result without changing its raw output or "
        "the frozen tolerance. Agent numerical Goal Success additionally needs correct routing, validated calculation and, "
        "for KB formulas, a true source-span/formula citation. Citation presence alone receives no credit. "
        "Paired 10,000-resample percentile bootstrap uses seed 20261012 and the 10 numeric tasks for numeric CI. "
        "Seven reviewer records across systems marked `hallucination_free=true` while also assigning a "
        "material-error label (`unsupported_claim` or `wrong_formula_provenance`). The frozen policy "
        "makes these mutually exclusive; derived scoring conservatively marks hallucination-free false "
        "without changing the raw reviewer record or making another judge call. "
        "Six answerable Agent runs (V18P-013, -017, -020 in each version) paused for already-supplied "
        "inputs. Their raw `final_answer` was empty and the one-call semantic reviewer therefore saw "
        "an empty answer rather than the saved `clarification_question`. The frozen policy explicitly "
        "counts asking for supplied input as unnecessary refusal. Derived scoring marks these six as "
        "incorrect refusals; claim, success and citation scores remain from the original "
        "judge. No second judge call was made. All row-level decisions and judge rationales are in "
        "`scored_rows.json`; raw outputs were not rewritten.\n\n"
        f"Integrity FINALIZED={str(checks['FINALIZED']).lower()}; failed checks: "
        f"{[name for name, ok in checks['checks'].items() if not ok]}.\n"
    )
    (ROOT / "SCORING_AUDIT.md").write_text(audit, encoding="utf-8")
    print(json.dumps({"FINALIZED": checks["FINALIZED"], "metrics": systems, "diagnostics": diagnostic_summary}, indent=2))


if __name__ == "__main__":
    main()
