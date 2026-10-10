"""Produce the frozen-v2 report and descriptive figures from scored outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from run_experiment import HERE, MODELS, load_benchmark
from summarize import SYSTEM_NAMES


def f(value: float | None, suffix: str = "") -> str:
    return "N/A" if value is None else f"{value:.2f}{suffix}"


def table(headers: list[str], rows: list[list[str]]) -> str:
    return "| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" + "\n".join(
        "| " + " | ".join(str(value) for value in row) + " |" for row in rows)


def chart(metrics: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    groups = (("End-to-End", ("agent", "qwen_closed_book", "openai_closed_book")),
              ("Same-Evidence", ("agent", "qwen_same_evidence", "openai_same_evidence")))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    for axis, (title, tracks) in zip(axes, groups):
        values = [metrics["tracks"][name]["goal_success"] for name in tracks]
        axis.bar(range(len(tracks)), values, color=["#6d56c5", "#7da7c7", "#e09a69"])
        axis.set_xticks(range(len(tracks)), ["Agent", "Qwen", "OpenAI"])
        axis.set_title(title)
        axis.set_ylim(0, 100)
        for index, value in enumerate(values):
            axis.text(index, value + 2, f"{value:.1f}%", ha="center", fontsize=9)
    axes[0].set_ylabel("Goal Success (%)")
    fig.suptitle("Frozen v2: goal success (valid tasks only)")
    fig.tight_layout()
    folder = HERE / "figures"
    folder.mkdir(parents=True, exist_ok=True)
    fig.savefig(folder / "goal_success.png", dpi=160)
    plt.close(fig)


def main() -> None:
    benchmark = load_benchmark()
    metrics = json.loads((HERE / "final_metrics.json").read_text(encoding="utf-8"))
    statistical = json.loads((HERE / "statistical_analysis.json").read_text(encoding="utf-8"))
    with (HERE / "final_results.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    chart(metrics)
    tracks = metrics["tracks"]
    main_tracks = ("agent", "qwen_closed_book", "openai_closed_book")
    same_tracks = ("agent", "qwen_same_evidence", "openai_same_evidence")
    columns = ("System", "Goal Success", "Exact Accuracy", "Claim Coverage", "Hallucination",
               "Numeric Accuracy", "Median s", "p95 s")
    def comparison(names: tuple[str, ...]) -> str:
        return table(list(columns), [[SYSTEM_NAMES[name], *[f(tracks[name][key], "%") for key in
                     ("goal_success", "exact_accuracy", "claim_coverage", "hallucination", "numeric_accuracy")],
                     f(tracks[name]["median_latency_seconds"]), f(tracks[name]["p95_latency_seconds"])]
                    for name in names])
    agent = tracks["agent"]
    category_rows = [[name, str(item["tasks"]), f(item["goal_success"], "%"),
                      f(item["exact_accuracy"], "%"), f(item["hallucination"], "%")]
                     for name, item in metrics["categories"]["agent"].items()]
    reliability = [("Formula Source Correctness", "formula_source_correctness"),
                   ("Calculation Provenance Completeness", "calculation_provenance_completeness"),
                   ("False-premise Handling", "false_premise_handling"),
                   ("Python/Simulation Execution Success", "python_simulation_execution_success"),
                   ("Correct Action Selection", "correct_action_selection"),
                   ("Same-run Resume", "same_run_resume_success"),
                   ("Citation ID Correctness", "citation_id_correctness"),
                   ("Citation Semantic Support", "citation_semantic_support"),
                   ("Document Recall@K", "document_recall_at_k"),
                   ("Page Recall@K", "page_recall_at_k"),
                   ("Figure Retrieval Accuracy", "figure_retrieval_accuracy"),
                   ("Validated CALC Adoption", "validated_calc_adoption")]
    reliability_table = table(["Agent measure", "Value", "Denominator"],
                              [[name, f(agent[key], "%"), str(agent[key + "_denominator"])] for name, key in reliability])
    failures = [row for row in rows if row["track"] == "agent" and row["goal_success"] == "False"]
    failure_table = table(["Task", "Category", "Exact", "Source page recall", "Action", "Note"],
                          [[row["task_id"], row["category"], row["exact_accuracy"],
                            row.get("page_recall_at_k") or "N/A", row.get("correct_action_selection") or "N/A",
                            str(row.get("review_note") or "").replace("|", "/")[:150]] for row in failures]) if failures else "All valid Agent tasks passed."
    ci = statistical["systems"]
    ci_table = table(["System", "Goal Success 95% CI", "Exact Accuracy 95% CI", "Hallucination 95% CI"],
                     [[SYSTEM_NAMES[name], *[f"{f(ci[name][key]['lower'])}–{f(ci[name][key]['upper'])}%"
                                             if ci[name][key] else "N/A" for key in
                                             ("goal_success", "exact_accuracy", "hallucination")]]
                      for name in main_tracks])
    observed = lambda key: agent[key] if agent[key] is not None else 0
    qwen = tracks["qwen_closed_book"]
    same_qwen = tracks["qwen_same_evidence"]
    same_openai = tracks["openai_same_evidence"]
    contrasts = statistical["paired_differences_percentage_points"]
    c = contrasts["agent_minus_qwen_closed_book"]["hallucination"]
    hallucination_sentence = (f"Agent hallucination {f(agent['hallucination'], '%')} versus Qwen closed-book {f(qwen['hallucination'], '%')} "
                             f"(paired difference 95% CI {f(c['lower'])} to {f(c['upper'])} percentage points).")
    source_sentence = (f"Exact formula-span correctness was {f(agent['formula_source_correctness'], '%')} "
                       f"among {agent['formula_source_correctness_denominator']} applicable KB/clarification tasks; "
                       f"complete calculation provenance was {f(agent['calculation_provenance_completeness'], '%')} "
                       f"among {agent['calculation_provenance_completeness_denominator']} applicable tasks.")
    gap_sentence = (f"Goal success was Agent {f(agent['goal_success'], '%')}, same-evidence Qwen "
                    f"{f(same_qwen['goal_success'], '%')}, and same-evidence OpenAI "
                    f"{f(same_openai['goal_success'], '%')}; the differences describe this frozen task set, not causal attribution.")
    text = f"""# Agent reliability v9 — frozen unseen final benchmark v2

## Design and freeze

- Product SHA: `{benchmark['evaluated_product_sha']}`; evaluation branch is not merged into main.
- Benchmark freeze commit: `{json.loads((HERE.parent / 'final_benchmark_v2_manifest.json').read_text(encoding='utf-8'))['freeze_commit']}`.
- Frozen tasks: {metrics['frozen_tasks']}; valid: {metrics['valid_tasks']}; invalid: {len(metrics['invalid_tasks'])}.
- The 60 tasks were written and deduplicated against v1 and old heldout before the freeze. No v1 or heldout task was rerun, copied, translated, number-swapped, or paraphrased for this test. Page-level source distribution and similarity audit are in the manifest/preflight files.
- Agent: local `{MODELS['qwen']}`, hybrid retrieval, web off, existing 12-document/18,976-chunk ChromaDB, autonomous Python/simulation enabled. OpenAI baseline: `{MODELS['openai']}`. Qwen/OpenAI baselines have no retrieval, tools, Python or web. Same-evidence baselines receive only the exact KB/FIG text captured from the Agent run; no extra retrieval or tools.
- Three-layer scoring: deterministic checks, structured expected-claim comparison, and **single-reviewer AI-assisted semantic adjudication** by local `{metrics['model_ids']['semantic_reviewer']}`. This is not human review. Agent calculation Goal Success additionally requires validated CALC, correct formula span when applicable, full provenance, units and action sequence. Benchmarks are not independent clinical-grade ground truth. An earlier OpenAI reviewer completed 50 tasks then hit `credit_balance_exhausted`; those partial records and two F03 HTTP 429 errors are preserved under `review/` but excluded from every final metric. An initial local formatting preflight produced extra claim verdicts on one task; those partial records are also preserved and excluded. The final local reviewer independently re-adjudicated all 60 tasks with one fixed JSON schema and model, never mixing reviewer models or prompt variants.

## Track A — End-to-End Product Comparison

{comparison(main_tracks)}

## Track B — Same-Evidence Comparison

The Agent row is the **identical** Track A output; only the two baselines are rerun with captured evidence.

{comparison(same_tracks)}

![Goal Success comparison](figures/goal_success.png)

## Agent reliability detail

{reliability_table}

Mean repeated/no-progress action rate: {f(agent['repeated_no_progress_action_rate'], '%')}. Mean stage times (seconds): retrieval {f(agent['mean_retrieval_seconds'])}, LLM generation {f(agent['mean_llm_generation_seconds'])}, calculation/simulation {f(agent['mean_calculation_simulation_seconds'])}, verification {f(agent['mean_verification_seconds'])}. These telemetry fields may overlap or omit overhead and do not sum to wall latency.

## Agent categories

{table(['Category', 'N', 'Goal Success', 'Exact Accuracy', 'Hallucination'], category_rows)}

## Paired bootstrap uncertainty

Percentile paired bootstrap by task ID, {statistical['iterations']} resamples, 95% CI. Numeric accuracy CIs use applicable numeric tasks only. Full point estimates and paired differences are in `statistical_analysis.json`.

{ci_table}

## Agent tasks without Goal Success

{failure_table}

## Interpretation and limitations

{source_sentence} These denominators are small and must be shown alongside rates.

{hallucination_sentence} A confidence interval spanning zero does not establish a difference.

{gap_sentence} Same-evidence systems did not execute Python, so their answer correctness and the Agent's operational chain are distinct measures.

Agent median latency was {f(agent['median_latency_seconds'])} s versus closed-book Qwen {f(qwen['median_latency_seconds'])} s; this reflects retrieval, planning, computation and verification cost. The 4 false-premise and 4 figure tasks have wide uncertainty. Source-gold labels were prepared from existing PDFs/Chroma before freeze; semantic review is one model, not a panel of humans. v1 became a development diagnostic set and is **not** compared as same-test final performance. Gemini was not run.

## Poster-safe conclusions

1. {source_sentence}
2. {hallucination_sentence}
3. {gap_sentence} Agent median latency was {f(agent['median_latency_seconds'])} s, a visible trade-off against closed-book speed.
"""
    (HERE / "final_evaluation_report.md").write_text(text, encoding="utf-8")
    print(f"report={HERE / 'final_evaluation_report.md'} failures={len(failures)}")


if __name__ == "__main__":
    main()
