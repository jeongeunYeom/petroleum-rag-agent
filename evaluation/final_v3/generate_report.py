"""Generate the frozen-v3 human-readable report and a compact comparison figure."""

from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_experiment import HERE, load_benchmark


TRACK_ORDER = ("agent", "qwen_closed_book", "openai_closed_book",
               "qwen_same_evidence", "openai_same_evidence")
LABELS = {"agent": "Petroleum-RAG-Agent v10", "qwen_closed_book": "Qwen3:8b closed-book",
          "openai_closed_book": "OpenAI closed-book", "qwen_same_evidence": "Qwen3:8b same-evidence",
          "openai_same_evidence": "OpenAI same-evidence"}


def pct(value: object) -> str:
    return "—" if value is None else f"{float(value):.2f}%"


def number(value: object, suffix: str = "") -> str:
    return "—" if value is None else f"{float(value):.2f}{suffix}"


def comparison_table(metrics: dict, tracks: tuple[str, ...]) -> str:
    columns = ("System", "Goal Success", "Exact Accuracy", "Claim Coverage", "Hallucination",
               "Numeric Accuracy", "Median latency")
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for track in tracks:
        row = metrics["tracks"][track]
        lines.append("| " + " | ".join((LABELS[track], pct(row["goal_success"]),
                     pct(row["exact_accuracy"]), pct(row["claim_coverage"]),
                     pct(row["hallucination"]), pct(row["numeric_accuracy"]),
                     number(row["median_latency_seconds"], " s"))) + " |")
    return "\n".join(lines)


def reliability_table(agent: dict) -> str:
    fields = (
        ("Intent routing", "intent_routing_accuracy"),
        ("Source requirement", "source_requirement_accuracy"),
        ("Document recall@K", "document_recall_at_k"),
        ("Page recall@K", "page_recall_at_k"),
        ("Exact formula span recall", "exact_formula_span_recall"),
        ("Formula source correctness", "formula_source_correctness"),
        ("Formula → CALCULATE", "formula_to_calculate_success"),
        ("Formula → CALCULATE given span", "formula_to_calculate_given_span"),
        ("Calculation provenance completeness", "calculation_provenance_completeness"),
        ("Python/simulation execution", "python_simulation_execution_success"),
        ("Validated CALC adoption", "validated_calc_adoption"),
        ("Correct action selection", "correct_action_selection"),
        ("False-premise handling", "false_premise_handling"),
        ("Clarification success", "clarification_success"),
        ("Same-run resume", "same_run_resume_success"),
        ("Figure retrieval", "figure_retrieval_accuracy"),
        ("Citation ID correctness", "citation_id_correctness"),
        ("Citation semantic support", "citation_semantic_support"),
        ("Empty final answer", "empty_final_answer"),
        ("Repeated/no-progress actions", "repeated_no_progress_action_rate"),
    )
    lines = ["| Agent diagnostic | Result | Denominator |", "|---|---:|---:|"]
    for label, key in fields:
        lines.append(f"| {label} | {pct(agent.get(key))} | {agent.get(key + '_denominator', 0)} |")
    return "\n".join(lines)


def ci_table(statistical: dict) -> str:
    metrics = ("goal_success", "exact_accuracy", "claim_coverage", "hallucination", "numeric_accuracy")
    lines = ["| Paired contrast, percentage points | Metric | 95% CI |", "|---|---|---:|"]
    for name in ("agent_minus_qwen_closed_book", "agent_minus_openai_closed_book",
                 "qwen_same_evidence_minus_qwen_closed_book",
                 "openai_same_evidence_minus_openai_closed_book"):
        for metric in metrics:
            bounds = statistical["paired_differences_percentage_points"][name][metric]
            interval = "—" if bounds is None else f"[{bounds['lower']:.2f}, {bounds['upper']:.2f}]"
            lines.append(f"| {name} | {metric} | {interval} |")
    return "\n".join(lines)


def category_table(metrics: dict) -> str:
    categories = metrics["categories"]["agent"]
    lines = ["| Category | n | Agent Goal Success | Agent Exact Accuracy |", "|---|---:|---:|---:|"]
    for category, row in categories.items():
        lines.append(f"| {category} | {row['tasks']} | {pct(row['goal_success'])} | {pct(row['exact_accuracy'])} |")
    return "\n".join(lines)


def make_figure(metrics: dict) -> None:
    tracks = metrics["tracks"]
    names = ["Agent", "Qwen closed", "OpenAI closed", "Qwen + evidence", "OpenAI + evidence"]
    values = [tracks[key]["goal_success"] for key in TRACK_ORDER]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    bars = ax.barh(names[::-1], values[::-1], color=["#b7addb", "#a8b4ce", "#b5becb", "#bec9dc", "#51428e"][::-1])
    ax.set_xlim(0, max(100, max(values) + 8))
    ax.set_xlabel("Goal Success (%)")
    ax.set_title("Frozen v3: 60 unseen tasks (valid denominator shown in report)")
    for bar, value in zip(bars, values[::-1]):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{value:.1f}%", va="center", fontsize=9)
    fig.tight_layout()
    folder = HERE / "figures"
    folder.mkdir(exist_ok=True)
    fig.savefig(folder / "goal_success.png", dpi=180)
    plt.close(fig)


def main() -> None:
    benchmark = load_benchmark()
    metrics = json.loads((HERE / "final_metrics.json").read_text(encoding="utf-8"))
    statistical = json.loads((HERE / "statistical_analysis.json").read_text(encoding="utf-8"))
    preflight = json.loads((HERE / "benchmark_preflight.json").read_text(encoding="utf-8"))
    manifest = json.loads((HERE.parent / "final_benchmark_v3_manifest.json").read_text(encoding="utf-8"))
    with (HERE / "final_results.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    agent_rows = [row for row in rows if row["track"] == "agent"]
    agent = metrics["tracks"]["agent"]
    statuses = Counter(row["run_status"] for row in agent_rows)
    direct_rows = [row for row in agent_rows if row["category"] == "direct_calculation"]
    direct_without_retrieval = sum(row["retrieval_action_count"] == "0" for row in direct_rows)
    formula_task_ids = {task["task_id"] for task in benchmark["tasks"]
                        if task["expected_source_requirement"] == "KB_FORMULA"}
    formula_rows = [row for row in agent_rows if row["task_id"] in formula_task_ids]
    span_found = sum(row["exact_formula_span_recall"] == "True" for row in formula_rows)
    transitioned = sum(row["formula_to_calculate_success"] == "True" for row in formula_rows)
    category_counts = preflight["category_distribution"]
    domain_counts = preflight["domain_distribution"]
    errors = sum((HERE / folder / f"{task['task_id']}.json").exists() is False
                 for folder in ("raw/agent", "raw/qwen", "raw/openai", "same_evidence/qwen", "same_evidence/openai")
                 for task in benchmark["tasks"])
    make_figure(metrics)
    report = f"""# Final unseen benchmark v3 — Agent reliability v10

## Evaluation integrity

- Evaluated product: `feature/agent-reliability-v10` at `{benchmark['evaluated_product_sha']}`. Product code was not edited during this evaluation.
- Evaluation branch: `evaluation/final-benchmark-v3`. Freeze commit: `{manifest['freeze_commit']}`. Frozen benchmark SHA-256: `{preflight['benchmark_sha256']}`.
- {metrics['frozen_tasks']} frozen, {metrics['valid_tasks']} valid, {len(metrics['invalid_tasks'])} invalid tasks. The same valid tasks feed all five tracks; zero missing raw records ({errors} absent files).
- Existing Chroma collection `petroleum_knowledge`: 12 documents / 18,976 chunks. Agent used `hybrid` retrieval, local Qwen3:8b, web OFF, and its normal autonomous Python/simulation policies. No reindex or PDF re-extraction.
- Actual model IDs: Agent and local baselines `{metrics['model_ids']['qwen']}`; OpenAI `{metrics['model_ids']['openai']}`; reviewer `{metrics['model_ids']['semantic_reviewer']}`. Gemini was not used.
- Benchmark composition: {', '.join(f'{key} {value}' for key, value in category_counts.items())}. Domains: {', '.join(f'{key} {value}' for key, value in domain_counts.items())}.
- Pre-freeze dedup compared {preflight['old_question_count']} questions from v1, v2, older heldouts, well-test and development prompts using semantic and numeric-masked similarity. See `benchmark_preflight.json` and the frozen manifest for maxima and source/page checks. v1/v2 results were not rerun.

## Protocol and scoring

Track A is end-to-end Agent versus tool-free, retrieval-free Qwen and OpenAI closed-book. Track B gives the Agent's **actual retrieved KB/FIG excerpts** to separate tool-free Qwen and OpenAI baselines, with no additional retrieval, Python, tools, or web. Agent's Track A row is reused, not rerun.

Three layers were used: deterministic evaluator, structured expected-claim comparison, and **single-reviewer AI-assisted semantic adjudication** by local `gemma4:latest`. The reviewer receives anonymized A–E answers, frozen expected claims and source text, then scores factual support and numeric/unit/formula correctness. Its initial citation-score format failure was preserved in `review/local_gemma_schema`; a clarified fraction-scale protocol scored every valid task uniformly in `review/local_gemma_schema_v2`. Frozen questions, answers, raw system results, and product code remained unchanged.

For machine-verifiable Agent calculations, validated formula AST, bound-input provenance, execution hash, CALC citation, final numeric value and unit take precedence over an AI reviewer's missed arithmetic/formula label. For user-formula calculation tasks, the frozen operational claim that the supplied expression was used is likewise proven by that complete chain. Semantic engineering/citation judgments remain with the single reviewer. A numerical answer with no numeric expression cannot pass numeric accuracy merely because the reviewer says it does.

Agent Goal Success is stricter than answer-only Exact Accuracy: intent route, source requirement, action sequence, actual evidence/citation support and, for calculations, validated Python/CALC adoption, normalized formula provenance, correct formula span/source, numeric value and unit must also pass. Direct calculations cannot have unnecessary RETRIEVE. A retrieved KB formula without CALCULATE fails its transition gate. Thus an answer may be exact but fail Goal Success.

## Track A — End-to-End

{comparison_table(metrics, TRACK_ORDER[:3])}

## Track B — Same-Evidence

{comparison_table(metrics, ("agent", *TRACK_ORDER[3:]))}

The same-evidence rows are tool-free answer generation over the Agent's retrieved excerpts; they do not inherit the Agent's Python/validation workflow. Hence Goal Success is scored as response correctness for those baselines, not as Agent operational compliance.

## Agent reliability diagnostics

{reliability_table(agent)}

Agent run statuses: {', '.join(f'{key} {value}' for key, value in sorted(statuses.items()))}. The denominator of each diagnostic is shown explicitly. `Formula → CALCULATE given span` conditions on tasks where the correct formula span was retrieved; all other formula-transition rows use the full KB-formula denominator.

Direct calculations with zero RETRIEVE actions: {direct_without_retrieval}/{len(direct_rows)}. Among tasks requiring KB formulas, exact formula span found: {span_found}/{len(formula_rows)}; subsequent formula→CALCULATE transition: {transitioned}/{len(formula_rows)}. Routing errors are shown separately above.

### Category outcomes

{category_table(metrics)}

### Latency

| Track | Mean | Median | p95 |
|---|---:|---:|---:|
"""
    for track in TRACK_ORDER:
        result = metrics["tracks"][track]
        report += f"| {LABELS[track]} | {number(result['mean_latency_seconds'], ' s')} | {number(result['median_latency_seconds'], ' s')} | {number(result['p95_latency_seconds'], ' s')} |\n"
    report += f"""
Agent mean stage timings (telemetry, not guaranteed additive): retrieval {number(agent.get('mean_retrieval_seconds'), ' s')}; planning {number(agent.get('mean_planning_seconds'), ' s')}; LLM generation {number(agent.get('mean_llm_generation_seconds'), ' s')}; Python {number(agent.get('mean_python_seconds'), ' s')}; calculation/simulation {number(agent.get('mean_calculation_simulation_seconds'), ' s')}; verification {number(agent.get('mean_verification_seconds'), ' s')}. Latency includes actual model and infrastructure time; same-evidence excludes the preceding Agent retrieval time.

## Uncertainty

Paired task-ID bootstrap, {statistical['iterations']} resamples, seed {statistical['seed']}, percentile 95% confidence intervals. These describe sampling uncertainty on this 60-task frozen set, not uncertainty from the single AI reviewer or source selection.

{ci_table(statistical)}

Full per-system intervals and paired contrasts are in `statistical_analysis.json`.

## Limitations

- Sixty curated tasks over existing local course PDFs are not representative of all petroleum engineering requests, all document quality, or all future user inputs.
- A single local semantic reviewer may misjudge nuanced engineering meaning and citation support. Deterministic provenance and action gates reduce, but do not eliminate, that risk.
- The denominator for formula, figure, false-premise, and clarification subgroups is small; their percentages can shift sharply with one task.
- Same-evidence baselines have no Python/tools and receive only the Agent's actual evidence; this isolates answer generation but is not a full parity comparison of capabilities or cost.
- v2 was used diagnostically to design v10; it is not an independent same-test comparator. No numerical v2→v3 improvement claim is made.

## Poster-safe conclusions

"""
    report += f"1. Agent Goal Success was {pct(agent['goal_success'])}, below Qwen closed-book {pct(metrics['tracks']['qwen_closed_book']['goal_success'])} and OpenAI closed-book {pct(metrics['tracks']['openai_closed_book']['goal_success'])}; the paired intervals above exclude zero for these deficits. v10 did not generalize sufficiently on this unseen set.\n"
    report += f"2. Routing/execution remains the central failure: intent routing {pct(agent['intent_routing_accuracy'])}, direct calculations with zero retrieval {direct_without_retrieval}/{len(direct_rows)}, formula-span recall {pct(agent['exact_formula_span_recall'])}, but formula→CALCULATE {pct(agent['formula_to_calculate_success'])}. Correct source availability alone did not produce reliable calculation.\n"
    report += f"3. Calculation provenance completeness was {pct(agent['calculation_provenance_completeness'])}, false-premise handling {pct(agent['false_premise_handling'])}, and same-run resume {pct(agent['same_run_resume_success'])}. These subgroup results do not substantiate a general reliability claim.\n"
    report += f"4. Agent Hallucination was {pct(agent['hallucination'])}, versus Qwen closed-book {pct(metrics['tracks']['qwen_closed_book']['hallucination'])}; however {statuses.get('stopped', 0)} stopped and {statuses.get('waiting_for_user_input', 0)} waiting runs suppressed answer production. Lower hallucination must not be presented as better task performance.\n"
    report += f"5. Same-evidence Qwen Goal Success was {pct(metrics['tracks']['qwen_same_evidence']['goal_success'])} versus {pct(metrics['tracks']['qwen_closed_book']['goal_success'])} closed-book, and same-evidence OpenAI {pct(metrics['tracks']['openai_same_evidence']['goal_success'])} versus {pct(metrics['tracks']['openai_closed_book']['goal_success'])}. Retrieved context helped tool-free answer generation on this set; the Agent's larger gap points to routing/action/verification and finalization, not just missing knowledge.\n"
    report += f"6. Agent median latency was {number(agent['median_latency_seconds'], ' s')} versus Qwen closed-book {number(metrics['tracks']['qwen_closed_book']['median_latency_seconds'], ' s')}; the Agent incurred a substantial latency trade-off without a success advantage here.\n"
    (HERE / "final_evaluation_report.md").write_text(report, encoding="utf-8")
    print(f"report={HERE / 'final_evaluation_report.md'} figure={HERE / 'figures/goal_success.png'}")


if __name__ == "__main__":
    main()
