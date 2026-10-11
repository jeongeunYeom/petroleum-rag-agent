"""Build the v4 evaluation report and a compact goal-success chart."""

from __future__ import annotations

from collections import Counter
import csv
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_experiment import HERE, MANIFEST, load_benchmark


TRACKS = ("agent", "qwen_closed_book", "openai_closed_book",
          "qwen_same_evidence", "openai_same_evidence")
LABELS = {"agent": "Petroleum-RAG-Agent v11.1", "qwen_closed_book": "Qwen3:8b closed-book",
          "openai_closed_book": "OpenAI closed-book", "qwen_same_evidence": "Qwen3:8b same-evidence",
          "openai_same_evidence": "OpenAI same-evidence"}
DIAGNOSTICS = (
    ("Natural-language fact extraction recall (count proxy)", "natural_language_fact_extraction_recall"),
    ("Unit normalization (canonical-unit record proxy)", "unit_normalization_accuracy"),
    ("Intent routing", "intent_routing_accuracy"),
    ("Source requirement", "source_requirement_accuracy"),
    ("Document recall@K", "document_recall_at_k"),
    ("Page recall@K", "page_recall_at_k"),
    ("Domain-matched document recall@K", "domain_matched_document_recall_at_k"),
    ("Relevant gold-span chunk@K", "relevant_chunk_at_k"),
    ("Top-3 gold-span precision", "top3_relevant_precision"),
    ("Wrong-domain dominance", "wrong_domain_dominance_rate"),
    ("Refined retrieval triggered (probe tasks)", "refined_retrieval_triggered"),
    ("Refined retrieval recovery (probe tasks)", "refined_retrieval_recovery_rate"),
    ("Exact formula span recall", "exact_formula_span_recall"),
    ("Formula candidate selection", "formula_candidate_selection_success"),
    ("Formula → CALCULATE", "formula_to_calculate_success"),
    ("Formula → CALCULATE given span", "formula_to_calculate_given_span"),
    ("Formula source correctness", "formula_source_correctness"),
    ("Variable binding", "variable_binding_success"),
    ("Calculation provenance completeness", "calculation_provenance_completeness"),
    ("Python/simulation execution", "python_simulation_execution_success"),
    ("Validated CALC adoption", "validated_calc_adoption"),
    ("Correct action selection", "correct_action_selection"),
    ("Premise relevant-source retrieval", "premise_relevant_source_retrieval"),
    ("False-premise handling", "false_premise_handling"),
    ("Clarification success", "clarification_success"),
    ("Same-run ID", "same_run_id_success"),
    ("Resume fact ingestion", "resume_fact_ingestion_success"),
    ("Resume completion", "resume_completion_success"),
    ("Figure retrieval", "figure_retrieval_accuracy"),
    ("Citation ID correctness", "citation_id_correctness"),
    ("Citation semantic support", "citation_semantic_support"),
    ("Empty final answer", "empty_final_answer"),
    ("Repeated/no-progress actions", "repeated_no_progress_action_rate"),
)


def pct(value: object) -> str:
    return "—" if value is None else f"{float(value):.2f}%"


def seconds(value: object) -> str:
    return "—" if value is None else f"{float(value):.2f} s"


def comparison_table(metrics: dict, keys: tuple[str, ...]) -> str:
    lines = ["| System | Goal Success | Exact Accuracy | Claim Coverage | Hallucination | Numeric Accuracy | Median latency |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for key in keys:
        row = metrics["tracks"][key]
        lines.append(f"| {LABELS[key]} | {pct(row['goal_success'])} | {pct(row['exact_accuracy'])} | "
                     f"{pct(row['claim_coverage'])} | {pct(row['hallucination'])} | "
                     f"{pct(row['numeric_accuracy'])} | {seconds(row['median_latency_seconds'])} |")
    return "\n".join(lines)


def reliability_table(agent: dict) -> str:
    lines = ["| Agent diagnostic | Result | Denominator |", "|---|---:|---:|"]
    for label, key in DIAGNOSTICS:
        lines.append(f"| {label} | {pct(agent.get(key))} | {agent.get(key + '_denominator', 0)} |")
    return "\n".join(lines)


def ci_table(statistical: dict) -> str:
    names = ("agent_minus_qwen_closed_book", "agent_minus_openai_closed_book",
             "qwen_same_evidence_minus_qwen_closed_book",
             "openai_same_evidence_minus_openai_closed_book")
    keys = ("goal_success", "exact_accuracy", "claim_coverage", "hallucination", "numeric_accuracy")
    lines = ["| Paired contrast (percentage points) | Metric | 95% CI |", "|---|---|---:|"]
    for name in names:
        for key in keys:
            bounds = statistical["paired_differences_percentage_points"][name][key]
            interval = "—" if bounds is None else f"[{bounds['lower']:.2f}, {bounds['upper']:.2f}]"
            lines.append(f"| {name} | {key} | {interval} |")
    return "\n".join(lines)


def draw_goal_chart(metrics: dict) -> None:
    values = [metrics["tracks"][key]["goal_success"] for key in TRACKS]
    names = ["Agent", "Qwen closed", "OpenAI closed", "Qwen + evidence", "OpenAI + evidence"]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    bars = ax.barh(names[::-1], values[::-1], color=["#b7addb", "#a8b4ce", "#b5becb", "#bec9dc", "#51428e"][::-1])
    ax.set_xlim(0, 110)
    ax.set_xlabel("Goal Success (%)")
    ax.set_title("Frozen v4 unseen benchmark")
    for bar, value in zip(bars, values[::-1]):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{value:.1f}%", va="center", fontsize=9)
    fig.tight_layout()
    folder = HERE / "figures"
    folder.mkdir(parents=True, exist_ok=True)
    fig.savefig(folder / "goal_success.png", dpi=180)
    plt.close(fig)


def main() -> None:
    benchmark = load_benchmark()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    preflight = json.loads((HERE / "benchmark_preflight.json").read_text(encoding="utf-8"))
    metrics = json.loads((HERE / "final_metrics.json").read_text(encoding="utf-8"))
    statistical = json.loads((HERE / "statistical_analysis.json").read_text(encoding="utf-8"))
    with (HERE / "final_results.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    agent_rows = [row for row in rows if row["track"] == "agent"]
    agent = metrics["tracks"]["agent"]
    statuses = Counter(row["run_status"] for row in agent_rows)
    direct = [row for row in agent_rows if row["category"] == "direct_calculation"]
    no_retrieval = sum(row["retrieval_action_count"] == "0" for row in direct)
    direct_calculated = sum('"CALCULATE"' in row["action_sequence"] for row in direct)
    formula = [row for row in agent_rows if row["category"] == "kb_calculation"]
    ambiguous_formula_tasks = sum(bool(task.get("formula_ambiguity")) for task in benchmark["tasks"])
    spans = sum(row["exact_formula_span_recall"] == "True" for row in formula)
    transitions = sum(row["formula_to_calculate_success"] == "True" for row in formula)
    probe_confidences = []
    for task in benchmark["tasks"]:
        if task.get("refined_probe"):
            payload = json.loads((HERE / "raw/agent" / f"{task['task_id']}.json").read_text(encoding="utf-8"))
            history = ((payload["response"].get("telemetry") or {}).get("retrieval_rerank_history") or [])
            probe_confidences.append(f"{task['task_id']}={history[0].get('confidence', 'unrecorded') if history else 'unrecorded'}")
    draw_goal_chart(metrics)
    categories = ["| Category | n | Agent Goal Success | Agent Exact Accuracy |", "|---|---:|---:|---:|"]
    for category, record in metrics["categories"]["agent"].items():
        categories.append(f"| {category} | {record['tasks']} | {pct(record['goal_success'])} | {pct(record['exact_accuracy'])} |")
    latency = ["| Track | Mean | Median | p95 |", "|---|---:|---:|---:|"]
    for key in TRACKS:
        record = metrics["tracks"][key]
        latency.append(f"| {LABELS[key]} | {seconds(record['mean_latency_seconds'])} | "
                       f"{seconds(record['median_latency_seconds'])} | {seconds(record['p95_latency_seconds'])} |")
    conclusions = [
        f"Agent Goal Success was {pct(agent['goal_success'])}; closed-book Qwen and OpenAI were "
        f"{pct(metrics['tracks']['qwen_closed_book']['goal_success'])} and "
        f"{pct(metrics['tracks']['openai_closed_book']['goal_success'])}. Paired Agent-minus-Qwen "
        f"95% CI was [{statistical['paired_differences_percentage_points']['agent_minus_qwen_closed_book']['goal_success']['lower']:.2f}, "
        f"{statistical['paired_differences_percentage_points']['agent_minus_qwen_closed_book']['goal_success']['upper']:.2f}] "
        "percentage points. This is a frozen-v4 finding, not a v3→v4 same-test improvement claim.",
        f"Among {len(formula)} KB-formula tasks, exact spans were retrieved in {spans} and the "
        f"formula→CALCULATE transition occurred in {transitions}. Formula source correctness was "
        f"{pct(agent['formula_source_correctness'])}; calculation provenance completeness was "
        f"{pct(agent['calculation_provenance_completeness'])} on its applicable subset.",
        f"Direct calculations avoided retrieval in {no_retrieval}/{len(direct)} cases, but actually "
        f"entered CALCULATE in {direct_calculated}/{len(direct)}. "
        f"False-premise handling was {pct(agent['false_premise_handling'])}; "
        f"same-run completion was {pct(agent['resume_completion_success'])}. Small subgroup denominators limit precision.",
        f"Figure retrieval reached {pct(agent['figure_retrieval_accuracy'])} across three tasks, "
        f"but figure Exact Accuracy was {pct(metrics['categories']['agent']['figure']['exact_accuracy'])}. "
        "Retrieving the figure note did not ensure a correct supported visual interpretation.",
        f"Agent hallucination was {pct(agent['hallucination'])}, versus closed-book Qwen "
        f"{pct(metrics['tracks']['qwen_closed_book']['hallucination'])}; their paired difference 95% CI was "
        f"[{statistical['paired_differences_percentage_points']['agent_minus_qwen_closed_book']['hallucination']['lower']:.2f}, "
        f"{statistical['paired_differences_percentage_points']['agent_minus_qwen_closed_book']['hallucination']['upper']:.2f}] "
        "points. Refusals and empty answers "
        "must be considered alongside this rate; lower hallucination alone does not imply better task completion.",
        f"Same-evidence Qwen/OpenAI Goal Success was "
        f"{pct(metrics['tracks']['qwen_same_evidence']['goal_success'])}/"
        f"{pct(metrics['tracks']['openai_same_evidence']['goal_success'])}, compared with their closed-book "
        f"{pct(metrics['tracks']['qwen_closed_book']['goal_success'])}/"
        f"{pct(metrics['tracks']['openai_closed_book']['goal_success'])}. The baselines had no retrieval or tools. "
        "Differences are conditional on the Agent's actual captured evidence.",
        f"Agent median/p95 latency was {seconds(agent['median_latency_seconds'])}/"
        f"{seconds(agent['p95_latency_seconds'])}; Qwen closed-book was "
        f"{seconds(metrics['tracks']['qwen_closed_book']['median_latency_seconds'])}/"
        f"{seconds(metrics['tracks']['qwen_closed_book']['p95_latency_seconds'])}."
    ]
    report = f"""# Final unseen benchmark v4 — Agent reliability v11.1

## Evaluation integrity

- Evaluated product: `feature/agent-reliability-v11-1` at `{benchmark['evaluated_product_sha']}`; product code, ChromaDB, and frozen benchmarks were not modified.
- Evaluation branch: `evaluation/final-benchmark-v4`; freeze commit `{manifest['freeze_commit']}`; committed benchmark SHA-256 `{manifest['benchmark_sha256']}`.
- {metrics['frozen_tasks']} frozen, {metrics['valid_tasks']} valid, {len(metrics['invalid_tasks'])} INVALID. The same valid tasks are used in all five rows.
- Agent: local `{metrics['model_ids']['agent']}`, `hybrid` retrieval, existing 12-document/18,976-chunk ChromaDB, web OFF, autonomous Python/simulation enabled. Qwen baseline: `{metrics['model_ids']['qwen']}`; OpenAI baseline: `{metrics['model_ids']['openai']}`; independent reviewer: `{metrics['model_ids']['semantic_reviewer']}`. Gemini was not used.
- Categories: {', '.join(f'{key} {value}' for key, value in preflight['category_distribution'].items())}. Domains: {', '.join(f'{key} {value}' for key, value in preflight['domain_distribution'].items())}.
- Formula ambiguity was explicitly tagged on {ambiguous_formula_tasks} KB-formula tasks; it is part of the frozen set, not post-hoc filtering.
- Pre-freeze audit compared {preflight['old_question_count']} prior questions/dev prompts, including semantic, normalized, numeric-masked and equation-structure similarity plus source-page overlap. Flagged near duplicates: {len(preflight['flagged_near_duplicates'])}; old source-page overlap: {len(preflight['prior_source_page_overlap'])}. Generic equation-shape matches ({len(preflight['equation_structure_matches'])}) were manually reviewed rather than equated with duplicate tasks. See `benchmark_preflight.json` for thresholds and results. v3 was used diagnostically, not as an independent final comparator.

## Protocol and scoring

Track A compares end-to-end Agent with Qwen and OpenAI closed-book (no retrieval, tools, Python or web). Track B gives tool-free Qwen/OpenAI **only the KB/FIG text actually captured by the Agent**, without further retrieval; no figure pixels. The Agent row is reused, not rerun.

For four frozen clarification tasks, the same follow-up message was provided to each baseline after its initial response whether or not it asked the correct question. Agent operational scoring additionally requires an appropriate clarification and a successful same-run resume.

The three scoring layers are deterministic operational/numeric checks, structured expected-claim comparison, and **single-reviewer AI-assisted semantic adjudication**. The reviewer sees anonymized A–E answers, frozen gold claims/spans and each answer's actual cited evidence. It does not repair answers. Raw reviews, model IDs and per-task scores are retained.

An initial reviewer request returned HTTP 400 because JSON mode required an explicit JSON instruction in the input message. Its error record is preserved in `review/error_history`; the request format was corrected before any semantic score was produced. Product outputs and gold were unchanged.

Agent Goal Success has stricter operational gates than baseline answer-only Goal Success: correct intent/source route and action sequence, evidence and citation semantic support, plus validated CALC/provenance/formula binding/source and numeric/unit adoption when relevant. Thus the Agent can have an accurate final text but fail its end-to-end goal. Exact Accuracy, Claim Coverage and Hallucination are reported separately to expose this asymmetry.

False-premise correction is counted only when the answer explicitly rejects and corrects the premise without additional unsupported or contradictory claims; the Agent must also have a valid, semantically supporting citation. A reviewer-level correction verdict alone does not suffice.

## Track A — End-to-End

{comparison_table(metrics, TRACKS[:3])}

## Track B — Same-Evidence

{comparison_table(metrics, ("agent", *TRACKS[3:]))}

Descriptive exact-accuracy gaps relative to the Agent: Qwen same-evidence {metrics['tracks']['qwen_same_evidence']['exact_accuracy'] - agent['exact_accuracy']:+.2f} percentage points; OpenAI same-evidence {metrics['tracks']['openai_same_evidence']['exact_accuracy'] - agent['exact_accuracy']:+.2f} points. These are not a pure causal estimate of orchestration because model capabilities and operational gates differ.

## Agent reliability diagnostics

{reliability_table(agent)}

Agent run status counts: {', '.join(f'{key} {value}' for key, value in sorted(statuses.items()))}. Direct calculations with no retrieval: {no_retrieval}/{len(direct)}; entered CALCULATE: {direct_calculated}/{len(direct)}. KB-formula exact spans: {spans}/{len(formula)}; subsequent formula→CALCULATE: {transitions}/{len(formula)}. Predesignated refined-retrieval probes' initial confidence: {', '.join(probe_confidences)}.

The formula-source diagnostic denominator is 13 rather than 12 because one clarification task also requires a KB formula. An exact formula span without a subsequent validated calculation is not counted as formula-source correctness.

`Domain-Matched Document Recall` uses the domain/source document set in the frozen catalog. `Relevant Chunk@K` and `Top-3 Relevant Precision` require a frozen gold page plus ≥60% lexical overlap with its gold span. These are conservative proxies, not exhaustive semantic relevance labels; alternate valid passages can be scored as misses. `Fact Extraction Recall` counts observable extracted versus digit-form inputs, capped at 1; `Unit Normalization` checks recorded canonical-unit fields. Neither proxy proves correct semantic variable binding, which is scored separately. `Refined Retrieval Recovery` applies only to the two predesignated probe tasks and requires a gold-page hit after a triggered refinement when the initial candidate set lacked it. If neither probe triggers refinement, recovery is not estimable rather than 0%.

### Category outcomes

{chr(10).join(categories)}

The three unsupported tasks were all judged correct safe refusals on final-text Exact Accuracy, but none passed the Agent's expected unsupported-intent/source-route gate. This explains the 100% versus 0% contrast rather than treating safe refusal as a content failure.

### Latency

{chr(10).join(latency)}

Agent mean stage timings (telemetry, overlapping/non-additive): parsing {seconds(agent.get('mean_message_parsing_seconds'))}, planning {seconds(agent.get('mean_planning_seconds'))}, retrieval {seconds(agent.get('mean_retrieval_seconds'))}, LLM generation {seconds(agent.get('mean_llm_generation_seconds'))}, calculation/simulation {seconds(agent.get('mean_calculation_simulation_seconds'))}, Python {seconds(agent.get('mean_python_seconds'))}, verification {seconds(agent.get('mean_verification_seconds'))}, evaluation {seconds(agent.get('mean_evaluation_seconds'))}, synthesis {seconds(agent.get('mean_synthesis_seconds'))}. Reranking and premise-grounding are not separately timed by the product telemetry and are included in overlapping retrieval/verification stages. Same-evidence latency excludes prior Agent retrieval.

## Statistical uncertainty

Paired bootstrap by valid task ID, {statistical['iterations']} resamples, seed {statistical['seed']}, percentile 95% confidence intervals. The intervals reflect task sampling only, not uncertainty from one AI reviewer or corpus selection. Small-category percentages are exploratory.

{ci_table(statistical)}

Full per-system intervals and contrasts: `statistical_analysis.json`.

## Limitations

- Sixty curated tasks over an existing 12-PDF corpus (gold spans in {len(manifest['source_document_task_counts'])} documents) do not represent all petroleum-engineering use cases or document quality.
- One AI reviewer can misclassify nuanced engineering/citation meaning; deterministic checks complement but do not eliminate this limitation.
- Figure baselines received text notes, not image pixels. Figure gold was visually inspected before freeze, but the semantic reviewer judged text claims/notes rather than raw image pixels; visual interpretation parity is limited.
- Formula, clarification, premise, figure, and refined-retrieval subgroups are small; one task changes percentages materially.
- Agent and baselines have intentionally different operational capabilities and Goal Success gates. Compare Exact Accuracy and Coverage alongside Goal Success.
- v3 exposed failure modes that informed v11/v11.1 development. v3 and v4 are not a same-test before/after comparison.

## Poster-safe conclusions

{chr(10).join(f'{index}. {item}' for index, item in enumerate(conclusions, 1))}
"""
    (HERE / "final_evaluation_report.md").write_text(report, encoding="utf-8")
    print(f"report={HERE / 'final_evaluation_report.md'}")


if __name__ == "__main__":
    main()
