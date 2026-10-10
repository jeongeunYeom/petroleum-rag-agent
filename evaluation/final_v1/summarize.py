"""Combine deterministic and semantic grades, bootstrap pairs, and write report data.

CSV files are authored from these JSON rows by export_csv.mjs via artifact-tool.
"""

from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
import random
import statistics

from run_experiment import HERE, MODELS, load_benchmark
from score_deterministic import TRACKS


BOOTSTRAP_SEED = 20261009
BOOTSTRAP_REPLICATES = 4000
METRIC_KEYS = ["goal_success", "exact_accuracy", "partial_or_better", "claim_coverage",
               "hallucination", "unsupported_claim", "engineering_contradiction",
               "numeric_accuracy", "unit_accuracy", "formula_accuracy", "safe_refusal_accuracy",
               "false_premise_handling", "citation_correctness", "citation_semantic_support",
               "document_recall_at_k", "page_recall_at_k", "figure_retrieval_accuracy",
               "formula_source_correctness", "calculation_provenance_accuracy",
               "correct_action_selection", "clarification_success", "same_run_resume_success",
               "python_simulation_execution_success", "validated_calc_adoption",
               "repeated_no_progress_action_rate", "wall_seconds", "retrieval_seconds",
               "llm_generation_seconds", "calculation_simulation_seconds", "verification_seconds"]
POSTER_COLUMNS = ["Goal Success %", "Exact Accuracy %", "Partial-or-better %",
                  "Claim Coverage %", "Hallucination %", "Engineering Contradiction %",
                  "Numeric Accuracy %", "Citation ID Validity %",
                  "Citation Semantic Support %", "Median Latency (s)"]


def mean(values: list[float | bool | None]) -> float | None:
    available = [float(value) for value in values if value is not None]
    return statistics.mean(available) if available else None


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * p
    low = int(pos)
    high = min(low + 1, len(values) - 1)
    return values[low] * (high - pos) + values[high] * (pos - low)


def load_review(task_id: str) -> dict:
    path = HERE / "review" / f"{task_id}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def merge_row(base: dict, review: dict, task: dict) -> dict:
    row = {key: value for key, value in base.items() if key != "answer"}
    score = review.get("scores_by_track", {}).get(base["track"])
    row["review_available"] = isinstance(score, dict)
    if not row["valid"] or not row["available"] or not row["review_available"]:
        for name in ("goal_success", "exact_accuracy", "partial_or_better", "claim_coverage",
                     "hallucination", "unsupported_claim", "unsupported_claim_count",
                     "engineering_contradiction", "engineering_contradiction_count",
                     "numeric_accuracy", "unit_accuracy", "formula_accuracy", "safe_refusal_accuracy",
                     "false_premise_handling", "citation_correctness", "citation_semantic_support"):
            row[name] = None
        return row
    score = score or {}
    numeric_required = bool(task.get("required_numeric_result") or task.get("expected_after_resume"))
    numeric = None
    if numeric_required:
        numeric = bool(base.get("numeric_accuracy_deterministic") and score.get("numeric_accuracy"))
    source_required = bool(task["expected_source_ids"])
    citation = base.get("citation_correctness_deterministic")
    semantic_support = score.get("citation_semantic_support")
    citation_support_ok = (not source_required or
                           (citation is True and semantic_support is not None and
                            float(semantic_support) >= 0.5))
    exact = bool(score.get("exact_correct") and (not numeric_required or numeric))
    safe_refusal = score.get("safe_refusal_correct") if task["safe_refusal_expected"] else None
    false_premise = score.get("false_premise_handled") if task["category"] == "false_premise" else None
    goal = exact
    if task["safe_refusal_expected"]:
        goal = bool(safe_refusal and base.get("python_calls", 0) == 0) if base["track"] == "agent" else bool(safe_refusal)
    if task["clarification_required"]:
        if base["track"] == "agent":
            goal = bool(goal and base.get("clarification_success") and
                        base.get("same_run_resume_success"))
        else:
            # A one-shot baseline can ask for information, but cannot actually resume.
            goal = False
    if base["track"] == "agent":
        if source_required:
            goal = goal and citation_support_ok
        if task["calculation_required"]:
            goal = goal and bool(base.get("python_simulation_execution_success"))
        if not task["safe_refusal_expected"]:
            goal = goal and base.get("agent_self_status") == "achieved"
    if base["track"].endswith("same_evidence") and source_required:
        goal = goal and citation_support_ok
    row.update({
        "goal_success": bool(goal), "exact_accuracy": exact,
        "partial_or_better": bool(score.get("partial_or_better")),
        "claim_coverage": float(score.get("claim_coverage") or 0),
        "hallucination": bool(score.get("hallucination")),
        "unsupported_claim": int(score.get("unsupported_claim_count") or 0) > 0,
        "unsupported_claim_count": int(score.get("unsupported_claim_count") or 0),
        "engineering_contradiction": int(score.get("engineering_contradiction_count") or 0) > 0,
        "engineering_contradiction_count": int(score.get("engineering_contradiction_count") or 0),
        "numeric_accuracy": numeric,
        "unit_accuracy": base.get("unit_accuracy_deterministic") if numeric_required else None,
        "formula_accuracy": score.get("formula_accuracy") if task["calculation_required"] else None,
        "safe_refusal_accuracy": safe_refusal,
        "false_premise_handling": false_premise,
        "citation_correctness": citation,
        "citation_semantic_support": semantic_support,
        "review_note": str(score.get("note", ""))[:500],
    })
    return row


def track_metrics(rows: list[dict]) -> dict:
    valid = [row for row in rows if row["valid"]]
    available = [row for row in valid if row["available"] and row["review_available"]]
    result = {"valid_tasks": len(valid), "available_reviewed": len(available),
              "blocked_or_unreviewed": len(valid) - len(available)}
    for key in METRIC_KEYS:
        values = [row.get(key) for row in available]
        result[key] = mean(values)
        result[key + "_n"] = sum(value is not None for value in values)
    latency = [float(row["wall_seconds"]) for row in available if row.get("wall_seconds") is not None]
    result["median_latency_seconds"] = statistics.median(latency) if latency else None
    result["p95_latency_seconds"] = percentile(latency, 0.95)
    return result


def paired_bootstrap(rows: list[dict], metric: str, comparator: str) -> dict:
    by_key = {(row["task_id"], row["track"]): row for row in rows if row["valid"]}
    pairs = []
    for task_id, track in by_key:
        if track != "agent":
            continue
        a = by_key[(task_id, "agent")].get(metric)
        b = by_key.get((task_id, comparator), {}).get(metric)
        if a is not None and b is not None:
            pairs.append((float(a), float(b)))
    if not pairs:
        return {"paired_n": 0, "difference": None, "ci95": None}
    observed = statistics.mean(a - b for a, b in pairs)
    rng = random.Random(BOOTSTRAP_SEED + sum(map(ord, metric + comparator)))
    draws = []
    for _ in range(BOOTSTRAP_REPLICATES):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        draws.append(statistics.mean(a - b for a, b in sample))
    return {"paired_n": len(pairs), "difference": observed,
            "ci95": [percentile(draws, 0.025), percentile(draws, 0.975)]}


def fmt(value: float | None, *, percent: bool = True) -> str:
    if value is None:
        return "N/A"
    return f"{100 * value:.1f}%" if percent else f"{value:.2f}"


def markdown_table(metrics: dict, tracks: list[str]) -> str:
    lines = ["| System | N | Goal success | Exact | Claim coverage | Hallucination | Numeric | Citation ID | Median s |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for track in tracks:
        value = metrics[track]
        lines.append("| " + " | ".join([
            track, str(value["available_reviewed"]), fmt(value["goal_success"]),
            fmt(value["exact_accuracy"]), fmt(value["claim_coverage"]),
            fmt(value["hallucination"]), fmt(value["numeric_accuracy"]),
            fmt(value["citation_correctness"]),
            fmt(value["median_latency_seconds"], percent=False),
        ]) + " |")
    return "\n".join(lines)


def supplementary_gemini() -> dict:
    records = [json.loads(path.read_text(encoding="utf-8"))
               for path in (HERE / "raw/gemini").glob("*.json")]
    completed = [item for item in records if not item.get("error")]
    errors = [item for item in records if item.get("error")]
    return {
        "status": "EXTERNAL_PROVIDER_BLOCKED",
        "attempted_unique_tasks": len(records),
        "completed_unique_tasks": len(completed),
        "model_ids_observed": sorted({item["model_id"] for item in completed if item.get("model_id")}),
        "http_429_observed": any("HTTP 429" in item.get("error", "") for item in errors),
        "excluded_from_main_denominator": True,
    }


def write_report(benchmark: dict, rows: list[dict], metrics: dict, stats: dict,
                 invalid: list[dict], model_ids: dict, gemini: dict) -> None:
    by_cat = defaultdict(list)
    for row in rows:
        if row["valid"] and row["track"] == "agent":
            by_cat[row["category"]].append(row)
    category_lines = ["| Category | N | Goal success | Exact | Mean latency s |", "|---|---:|---:|---:|---:|"]
    for category, data in sorted(by_cat.items()):
        category_lines.append(f"| {category} | {len(data)} | {fmt(mean([x.get('goal_success') for x in data]))} "
                              f"| {fmt(mean([x.get('exact_accuracy') for x in data]))} "
                              f"| {fmt(mean([x.get('wall_seconds') for x in data]), percent=False)} |")
    acceptance = [row for row in rows if row["track"] == "agent" and row["category"] in
                  {"petrophysics", "direct_calculation", "kb_calculation", "simulation",
                   "clarification", "unsupported_formula", "figure"}]
    key_categories = ["petrophysics", "direct_calculation", "kb_calculation", "simulation",
                      "clarification", "unsupported_formula", "figure"]
    acceptance_lines = ["| Function | Example task | Actual action sequence | Goal success |", "|---|---|---|---:|"]
    for category in key_categories:
        row = next((item for item in acceptance if item["category"] == category), None)
        if row:
            acceptance_lines.append(f"| {category} | {row['task_id']} | "
                                    f"{' → '.join(row.get('action_sequence') or []) or 'none'} | "
                                    f"{fmt(float(row['goal_success']) if row.get('goal_success') is not None else None)} |")
    agent = metrics["agent"]
    other = [(name, metrics[name]) for name in ("qwen_closed_book", "openai_closed_book")]
    best_baseline = max(other, key=lambda pair: pair[1].get("goal_success") or -1)
    main_sha = json.loads((HERE.parent / "final_benchmark_v1_manifest.json").read_text(encoding="utf-8"))["evaluated_product_main_sha"]
    category_table = "\n".join(category_lines)
    acceptance_table = "\n".join(acceptance_lines)
    ci_lines = ["| Comparison (Agent minus baseline) | Metric | Paired N | Difference | Bootstrap 95% CI |",
                "|---|---|---:|---:|---:|"]
    for baseline, by_metric in stats["differences"].items():
        for metric, estimate in by_metric.items():
            interval = estimate["ci95"]
            ci_text = (f"[{fmt(interval[0])}, {fmt(interval[1])}]" if interval else "N/A")
            ci_lines.append(f"| {baseline} | {metric} | {estimate['paired_n']} | "
                            f"{fmt(estimate['difference'])} | {ci_text} |")
    ci_table = "\n".join(ci_lines)
    secondary_lines = ["| System | Unsupported claims | Contradictions | Safe refusal | False premise | Unit | Formula | Citation semantic | Mean s | p95 s |",
                       "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for track, value in metrics.items():
        secondary_lines.append("| " + " | ".join([
            track, fmt(value["unsupported_claim"]), fmt(value["engineering_contradiction"]),
            fmt(value["safe_refusal_accuracy"]), fmt(value["false_premise_handling"]),
            fmt(value["unit_accuracy"]), fmt(value["formula_accuracy"]),
            fmt(value["citation_semantic_support"]), fmt(value["wall_seconds"], percent=False),
            fmt(value["p95_latency_seconds"], percent=False)]) + " |")
    secondary_table = "\n".join(secondary_lines)
    text = f"""# Final Petroleum-RAG-Agent evaluation, frozen v1

## Provenance and design

- Evaluated product: merged `main` at `{main_sha}`; evaluation branch only, product code unchanged.
- Frozen benchmark SHA-256: `{json.loads((HERE.parent / 'final_benchmark_v1_manifest.json').read_text(encoding='utf-8'))['benchmark_sha256']}`; freeze commit `a88fdc4a8e57e46c9f4775e8a3e07fcbb5360f2c`.
- Frozen tasks: {len(benchmark['tasks'])}; invalid: {len(invalid)}; valid: {len(benchmark['tasks'])-len(invalid)}. Invalid records are preserved in `invalid_tasks.json`, not silently revised.
- Actual main models: Agent and local closed-book `{model_ids.get('qwen')}`; OpenAI `{', '.join(model_ids.get('openai', []))}`; semantic reviewer `{', '.join(model_ids.get('reviewer', []))}`.
- Agent used autonomous `POST /api/research/goal-runs/from-message`, local Qwen3:8b, `hybrid` retrieval, 12-document/18,976-chunk ChromaDB, web disabled, Python as product policy allows. Four clarification tasks had one prewritten reply and same-run resume attempted.
- All baselines were one-shot, no tools or web. Track A closed-book models saw only the question. Track B received the *Agent's captured KB/FIG text evidence* for each identical question; this does not independently evaluate their retrieval. Figure pixels were not supplied to the text baselines, only retrieved figure notes.
- Temperature was zero where accepted; Qwen additionally used seed 42. Runs were sequential by system, not randomized in time. No output-driven product or benchmark tuning.
- Scoring combines deterministic numeric/unit/action/provenance checks, structured expected claims, and **single-reviewer AI-assisted semantic adjudication** (`{', '.join(model_ids.get('reviewer', []))}`, prompt `{stats['reviewer_prompt_version']}`). This is not human review. The reviewer saw anonymized system labels and source spans; all raw reviews are retained.

## Track A — End-to-End Product Comparison

{markdown_table(metrics, ['agent','qwen_closed_book','openai_closed_book'])}

These are *not equal-information conditions*: only the Agent had retrieval and tools. Closed-book citation/retrieval metrics are N/A, not zero.

## Track B — Same-Evidence Comparison

{markdown_table(metrics, ['agent','qwen_same_evidence','openai_same_evidence'])}

The Agent row is the identical product output from Track A, not a second Agent run. The supplied evidence is whatever the Agent actually retrieved, including retrieval misses.

## Supplementary Gemini evaluation — incomplete due to provider rate limiting

- Status: `{gemini['status']}`; model ID: `{', '.join(gemini['model_ids_observed'])}`.
- Attempted unique tasks: {gemini['attempted_unique_tasks']}/50; completed unique tasks: {gemini['completed_unique_tasks']}/50.
- The earlier blocked snapshot had 20 completed tasks; 21 additional tasks were captured before the next 429. All 41 successful files remain untouched.
- HTTP 429 observed: {gemini['http_429_observed']}. Earlier successful raw responses and error history are preserved.
- Gemini is excluded from the 49-task main denominator, all performance tables, bootstrap comparisons, and ranking. No Gemini performance rate is calculated.

## Secondary quality and latency measures

{secondary_table}

## Agent engineering and workflow diagnostics

- Document Recall@K: {fmt(agent['document_recall_at_k'])} (N={agent['document_recall_at_k_n']}); Page Recall@K: {fmt(agent['page_recall_at_k'])} (N={agent['page_recall_at_k_n']}).
- Figure retrieval accuracy: {fmt(agent['figure_retrieval_accuracy'])} (N={agent['figure_retrieval_accuracy_n']}); formula source correctness: {fmt(agent['formula_source_correctness'])}.
- Correct action selection: {fmt(agent['correct_action_selection'])}; clarification trigger: {fmt(agent['clarification_success'])}; same-run resume: {fmt(agent['same_run_resume_success'])}.
- Validated Python/simulation execution: {fmt(agent['python_simulation_execution_success'])}; validated CALC adoption: {fmt(agent['validated_calc_adoption'])}; repeated/no-progress action fraction: {fmt(agent['repeated_no_progress_action_rate'])}.
- Safe-refusal accuracy: {fmt(agent['safe_refusal_accuracy'])}; false-premise handling: {fmt(agent['false_premise_handling'])}; citation semantic support: {fmt(agent['citation_semantic_support'])}.
- Agent latency: mean {fmt(agent['wall_seconds'], percent=False)} s, median {fmt(agent['median_latency_seconds'], percent=False)} s, p95 {fmt(agent['p95_latency_seconds'], percent=False)} s. Mean retrieval {fmt(agent['retrieval_seconds'], percent=False)} s; LLM generation {fmt(agent['llm_generation_seconds'], percent=False)} s; calculate/simulate {fmt(agent['calculation_simulation_seconds'], percent=False)} s; verification {fmt(agent['verification_seconds'], percent=False)} s.

## Category performance (Agent)

{category_table}

## Final Agent acceptance, independent of earlier T1–T7

{acceptance_table}

Example tasks are the first frozen-order item in each category, not selected successes.

## Statistical analysis

Task-paired, nonparametric bootstrap percentile 95% intervals use {BOOTSTRAP_REPLICATES} resamples and seed {BOOTSTRAP_SEED}. Full differences and denominators are in `statistical_analysis.json`. With about 49 valid tasks, category subsets and rare behaviors (especially four clarifications and four figures) are too small for strong significance claims. Intervals are exploratory uncertainty summaries, not independent repeated-system measurements.

{ci_table}

## Invalid tasks and limitations

{'; '.join(item['task_id']+': '+item['reason'] for item in invalid)}

- The source catalog consists of KB text spans and selected figure notes. Four figure items cannot establish full visual-understanding capability; figure-note quality is a further limitation.
- Direct-calculation inputs overlap answer values in some tasks; numeric scoring therefore requires both deterministic tolerance matching and reviewer verification of output/value association.
- The same-evidence track fixes evidence to the Agent's retrieval output and inherits its omissions. It cannot isolate generation from a perfect-retrieval counterfactual.
- One AI reviewer is not an independent panel or blinded human assessment. Structured raw responses permit later human audit.
- Baseline models differ in size, training, cost and provider; comparisons do not control those factors. API service and local hardware can affect latency.
- Missing or blocked outputs are reported separately, never converted into success.

## Poster-safe conclusions

1. Agent goal success was {fmt(agent['goal_success'])} on valid tasks, below {best_baseline[0]} at {fmt(best_baseline[1]['goal_success'])}. This unequal-information end-to-end comparison does not establish a retrieval benefit.
2. With the Agent's retrieved text evidence supplied to both systems, Agent goal success remained {fmt(agent['goal_success'])} versus {fmt(metrics['openai_same_evidence']['goal_success'])} for OpenAI. This is a generation/orchestration gap conditional on the captured evidence, not a causal isolation of either component.
3. Agent median response time was {fmt(agent['median_latency_seconds'], percent=False)} s. Local-versus-remote latency is not a controlled hardware comparison; the 49-task, single-reviewer results need independent replication.

All per-task grades are in `final_results.csv`; raw responses, traces, source IDs, citations, calculations, latency, and reviews are under `raw/`, `same_evidence/`, and `review/`.
"""
    (HERE / "final_evaluation_report.md").write_text(text, encoding="utf-8")


def main() -> None:
    benchmark = load_benchmark()
    base = json.loads((HERE / "metrics/deterministic_rows.json").read_text(encoding="utf-8"))
    if len(base) != len(benchmark["tasks"]) * len(TRACKS):
        raise RuntimeError("Deterministic scoring is incomplete")
    by_task = {task["task_id"]: task for task in benchmark["tasks"]}
    reviews = {task_id: load_review(task_id) for task_id in by_task}
    rows = [merge_row(item, reviews[item["task_id"]], by_task[item["task_id"]]) for item in base]
    incomplete = [row for row in rows if row["valid"] and (not row["available"] or not row["review_available"])]
    if incomplete:
        raise RuntimeError(f"Cannot publish full final metrics: {len(incomplete)} valid task-track rows unavailable/unreviewed")
    metrics = {track: track_metrics([row for row in rows if row["track"] == track]) for track in TRACKS}
    invalid = json.loads((HERE / "invalid_tasks.json").read_text(encoding="utf-8"))["invalid"]
    model_ids = {"qwen": MODELS["qwen"]}
    for provider in ("openai",):
        ids = {json.loads(path.read_text(encoding="utf-8")).get("model_id")
               for path in (HERE / f"raw/{provider}").glob("*.json")}
        model_ids[provider] = sorted(str(value) for value in ids if value)
    reviewer_ids = {item.get("reviewer_model_id") for item in reviews.values()}
    model_ids["reviewer"] = sorted(str(value) for value in reviewer_ids if value)
    gemini = supplementary_gemini()
    final = {"benchmark_sha256": json.loads((HERE.parent / "final_benchmark_v1_manifest.json").read_text(encoding="utf-8"))["benchmark_sha256"],
             "frozen_tasks": len(benchmark["tasks"]), "valid_tasks": len(benchmark["tasks"])-len(invalid),
             "invalid_tasks": invalid, "model_ids_observed": model_ids,
             "supplementary_gemini": gemini,
             "definitions": {"hallucination": "AI-reviewer flagged fabricated claim, not missing citation alone",
                             "unsupported_claim": "fraction of answers with at least one unsupported specific engineering assertion",
                             "goal_success": "correct complete goal with deterministic numeric and applicable tool/provenance/clarification gates",
                             "citation_correctness": "citation IDs resolve to supplied KB/FIG evidence; semantic support separately adjudicated",
                             "latency": "client wall-clock seconds per task, including polling for Agent"},
             "tracks": metrics}
    (HERE / "final_metrics.json").write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    comparisons = {baseline: {metric: paired_bootstrap(rows, metric, baseline)
                              for metric in ("goal_success", "exact_accuracy", "claim_coverage",
                                             "hallucination", "numeric_accuracy")}
                   for baseline in TRACKS if baseline != "agent"}
    stats = {"method": "task-paired percentile bootstrap", "seed": BOOTSTRAP_SEED,
             "replicates": BOOTSTRAP_REPLICATES, "reviewer_prompt_version": "final-v1-reviewer-1",
             "differences": comparisons,
             "warning": "Small category samples; exploratory intervals, not claims of significance."}
    (HERE / "statistical_analysis.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = ["task_id", "track", "category", "difficulty", "valid", "available", "model_id",
               "run_id", "run_status", "agent_self_status", "action_sequence", "python_calls",
               "validated_calculations", "goal_success", "exact_accuracy", "partial_or_better",
               "claim_coverage", "hallucination", "unsupported_claim", "unsupported_claim_count",
               "engineering_contradiction", "engineering_contradiction_count", "numeric_accuracy",
               "unit_accuracy", "formula_accuracy", "safe_refusal_accuracy", "false_premise_handling",
               "document_recall_at_k", "page_recall_at_k", "figure_retrieval_accuracy",
               "citation_correctness", "citation_semantic_support", "formula_source_correctness",
               "calculation_provenance_accuracy", "correct_action_selection", "clarification_success",
               "same_run_resume_success", "python_simulation_execution_success", "validated_calc_adoption",
               "repeated_no_progress_action_rate", "retrieval_seconds", "llm_generation_seconds",
               "calculation_simulation_seconds", "verification_seconds", "wall_seconds", "review_note", "error"]
    csv_rows = [{key: (" → ".join(row[key]) if key == "action_sequence" and row.get(key) else row.get(key))
                 for key in columns} for row in rows]
    poster = []
    for track, value in metrics.items():
        poster.append({"Track": "A End-to-End" if track.endswith("closed_book") or track == "agent" else "B Same-Evidence",
                       "System": track, "Valid N": value["valid_tasks"],
                       **{name: (round(100 * value[key], 3) if value.get(key) is not None else None)
                          for name, key in zip(POSTER_COLUMNS[:-1], ["goal_success", "exact_accuracy",
                                                             "partial_or_better", "claim_coverage",
                                                             "hallucination", "engineering_contradiction",
                                                             "numeric_accuracy", "citation_correctness",
                                                             "citation_semantic_support"])},
                       "Median Latency (s)": round(value["median_latency_seconds"], 3)
                       if value["median_latency_seconds"] is not None else None})
    agent_same_evidence = dict(poster[0])
    agent_same_evidence["Track"] = "B Same-Evidence"
    poster.insert(3, agent_same_evidence)
    (HERE / "metrics/csv_input.json").write_text(json.dumps({"final_results": {"columns": columns, "rows": csv_rows},
                                                               "poster_metrics": {"columns": list(poster[0]), "rows": poster}},
                                                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(benchmark, rows, metrics, stats, invalid, model_ids, gemini)
    print(f"valid_tasks={final['valid_tasks']} output_rows={len(rows)}")


if __name__ == "__main__":
    main()
