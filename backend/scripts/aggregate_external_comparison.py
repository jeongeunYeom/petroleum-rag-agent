from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from run_external_baseline import PROJECT_ROOT, base_condition, latency_summary, load_json
from score_semantic_review import score_review


DEFAULT_REVIEW = PROJECT_ROOT / "evaluation" / "review" / "external_baseline_semantic_review.csv"
DEFAULT_KEY = PROJECT_ROOT / "evaluation" / "review" / "external_baseline_answer_key.json"
DEFAULT_RUBRIC = PROJECT_ROOT / "evaluation" / "petroleum_agent_heldout_v1_semantic_rubric.json"
PETROLEUM_REVIEW = PROJECT_ROOT / "evaluation" / "review" / "qwen_semantic_review.csv"
PETROLEUM_RESULT = PROJECT_ROOT / "data" / "evaluation" / "petroleum_agent_heldout_v1_20261002T024117Z.json"
OUTPUT_JSON = PROJECT_ROOT / "data" / "evaluation" / "petroleum_external_model_comparison_v1.json"
OUTPUT_CSV = PROJECT_ROOT / "data" / "evaluation" / "petroleum_external_model_comparison_v1.csv"
POSTER_CSV = PROJECT_ROOT / "data" / "evaluation" / "poster_model_comparison.csv"
OUTPUT_MD = PROJECT_ROOT / "evaluation" / "review" / "external_model_comparison_summary.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def subset_rubric(rubric: dict[str, Any], ids: set[str]) -> dict[str, Any]:
    return {**rubric, "items": [item for item in rubric["items"] if item["id"] in ids]}


def latency_from_run(run: dict[str, Any], ids: set[str] | None = None) -> dict[str, float | None]:
    rows = [row for row in run["results"] if ids is None or row["question_id"] in ids]
    return latency_summary(rows)


def petroleum_latency(payload: dict[str, Any], ids: set[str]) -> dict[str, float | None]:
    rows = [
        {"latency_seconds": row["total_seconds"], "error": None}
        for row in payload["results"] if row["id"] in ids and row.get("total_seconds") is not None
    ]
    return latency_summary(rows)


def row_coverage(row: dict[str, str], claim_count: int) -> float:
    return sum(row[f"claim_{index}"] == "1" for index in range(1, claim_count + 1)) / claim_count


def paired_delta(
    petroleum_rows: list[dict[str, str]], external_rows: list[dict[str, str]], rubric: dict[str, Any]
) -> dict[str, Any]:
    claims = {item["id"]: len(item["required_claims"]) for item in rubric["items"]}
    left = {row["question_id"]: row for row in petroleum_rows}
    right = {row["question_id"]: row for row in external_rows}
    ids = sorted(set(left) & set(right))
    exact_deltas = [int(right[qid]["overall_score_0_1_2"] == "2") - int(left[qid]["overall_score_0_1_2"] == "2") for qid in ids]
    coverage_deltas = [row_coverage(right[qid], claims[qid]) - row_coverage(left[qid], claims[qid]) for qid in ids]

    def interval(values: list[float]) -> list[float] | None:
        if not values:
            return None
        rng = random.Random(20261002)
        samples = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(5000))
        return [samples[124], samples[4874]]

    return {
        "questions": len(ids),
        "external_minus_petroleum_exact": statistics.fmean(exact_deltas),
        "external_minus_petroleum_exact_bootstrap_95_ci": interval(exact_deltas),
        "external_minus_petroleum_claim_coverage": statistics.fmean(coverage_deltas),
        "external_minus_petroleum_claim_coverage_bootstrap_95_ci": interval(coverage_deltas),
    }


def metric_row(system: str, condition: str, metrics: dict[str, Any], latency: dict[str, Any], cost: float | None, status: str = "complete") -> dict[str, Any]:
    return {
        "System": system, "Condition": condition, "Status": status,
        "N": metrics.get("questions_reviewed", 0),
        "Semantic Exact": metrics.get("semantic_exact_accuracy"),
        "Partial+": metrics.get("semantic_partial_or_better"),
        "Claim Coverage": metrics.get("mean_claim_coverage"),
        "Hallucination": metrics.get("hallucination_rate"),
        "Engineering Error": metrics.get("engineering_contradiction_rate"),
        "Safe Refusal": metrics.get("safe_refusal_rate"),
        "False-Premise Recognition": metrics.get("false_premise_recognition_rate"),
        "False-Premise Correction": metrics.get("false_premise_correction_rate"),
        "Numeric Accuracy": metrics.get("numeric_accuracy"),
        "Citation Accuracy": metrics.get("citation_accuracy"),
        "Figure Accuracy": metrics.get("figure_semantic_accuracy"),
        "Axis Accuracy": metrics.get("axis_accuracy"),
        "Series Accuracy": metrics.get("series_accuracy"),
        "Figure Element Accuracy": metrics.get("figure_element_accuracy"),
        "Interpretation Accuracy": metrics.get("figure_interpretation_accuracy"),
        "Mean Latency": latency.get("mean"), "Median Latency": latency.get("median"),
        "P95 Latency": latency.get("p95"), "Estimated Cost": cost,
    }


def pct(value: Any) -> str:
    return "N/A" if value is None else f"{100 * value:.2f}%"


def poster_pct(value: Any) -> float | str:
    return "N/A" if value is None else round(100 * value, 2)


def error_type(error: str) -> str:
    status = re.search(r"HTTP Error (\d+)", error)
    return f"HTTP_{status.group(1)}" if status else error.split(":", 1)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge blind review scores with model keys and aggregate results.")
    parser.add_argument("--review", nargs="+", default=[str(DEFAULT_REVIEW)])
    parser.add_argument("--key", nargs="+", default=[str(DEFAULT_KEY)])
    parser.add_argument("--runs", nargs="+", required=True)
    args = parser.parse_args()

    rubric = load_json(DEFAULT_RUBRIC)
    review_rows = [row for path in args.review for row in read_csv(Path(path))]
    answer_key: dict[str, Any] = {}
    for path in args.key:
        incoming = load_json(Path(path))["answers"]
        overlap = set(answer_key) & set(incoming)
        if overlap:
            raise ValueError(f"Duplicate anonymous IDs across answer keys: {sorted(overlap)}")
        answer_key.update(incoming)
    if {row["anonymous_answer_id"] for row in review_rows} != set(answer_key):
        raise ValueError("Completed blind review does not match the separate answer key")
    runs = [load_json(Path(path)) for path in args.runs]

    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in review_rows:
        key = answer_key[row["anonymous_answer_id"]]
        grouped[(key["provider"], key["model"], base_condition(key["condition"]))].append(row)

    rows: list[dict[str, Any]] = []
    semantic: dict[str, Any] = {}
    external_text_rows: dict[str, list[dict[str, str]]] = {}
    for (provider, model, condition), scored_rows in sorted(grouped.items()):
        ids = {row["question_id"] for row in scored_rows}
        metrics = score_review(subset_rubric(rubric, ids), scored_rows, evaluation_condition=condition)
        run = next(run for run in runs if run["metadata"]["provider"] == provider and base_condition(run["metadata"]["condition"]) == condition)
        name = f"{model} ({provider})"
        errors = [row["error"] for row in run["results"] if row.get("error")]
        expected_figure_miss = condition == "figure" and errors == ["figure image unavailable"]
        status = "complete_usable_subset" if expected_figure_miss else "partial_api_errors" if errors else "complete"
        rows.append(metric_row(name, condition, metrics, latency_from_run(run, ids), run["metadata"]["estimated_cost_usd"], status))
        semantic[f"{provider}_{condition}"] = metrics
        if condition in {"closed_book", "same_evidence"}:
            external_text_rows[f"{provider}_{condition}"] = scored_rows

    petroleum_rows = read_csv(PETROLEUM_REVIEW)
    petroleum_payload = load_json(PETROLEUM_RESULT)
    figure_success_ids = {
        row["question_id"] for run in runs if base_condition(run["metadata"]["condition"]) == "figure"
        for row in run["results"] if row["error"] is None
    }
    for label, ids in (
        ("text50", {item["id"] for item in rubric["items"] if item["task_type"] != "figure"}),
        ("figure_usable", figure_success_ids),
    ):
        selected = [row for row in petroleum_rows if row["question_id"] in ids]
        metrics = score_review(subset_rubric(rubric, ids), selected, evaluation_condition="petroleum_agent")
        condition = "petroleum_agent_text50" if label == "text50" else "petroleum_agent_figure_usable"
        rows.append(metric_row("Petroleum Agent", condition, metrics, petroleum_latency(petroleum_payload, ids), 0.0))
        semantic[condition] = metrics

    completed = {(provider, condition) for provider, _model, condition in grouped}
    for provider, model in (("openai", "gpt-6.1-sol"), ("gemini", "gemini-3.8-flash")):
        for condition in ("closed_book", "same_evidence", "figure"):
            if (provider, condition) not in completed:
                key_present = bool(os.environ.get("OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY"))
                status = "not_run_rate_limit_or_quota" if key_present else "not_run_missing_api_key"
                rows.append(metric_row(f"{model} ({provider})", condition, {}, {}, None, status))

    text_ids = {item["id"] for item in rubric["items"] if item["task_type"] != "figure"}
    petroleum_text = [row for row in petroleum_rows if row["question_id"] in text_ids]
    paired = {name: paired_delta(petroleum_text, scored, subset_rubric(rubric, text_ids)) for name, scored in external_text_rows.items()}
    run_metrics = {}
    for run in runs:
        provider = run["metadata"]["provider"]
        condition = base_condition(run["metadata"]["condition"])
        errors = [row["error"] for row in run["results"] if row.get("error")]
        run_metrics[f"{provider}_{condition}"] = {
            "requested": len(run["results"]),
            "succeeded": sum(row.get("error") is None for row in run["results"]),
            "errors": len(errors),
            "error_types": dict(sorted(Counter(error_type(error) for error in errors).items())),
            "estimated_cost_usd": run["metadata"].get("estimated_cost_usd"),
        }
    missing_conditions = [
        f"{provider}/{condition}"
        for provider in ("openai", "gemini")
        for condition in ("closed_book", "same_evidence", "figure")
        if (provider, condition) not in completed
    ]
    comparison = {
        "metadata": {
            "benchmark": "petroleum_agent_heldout_v1", "reviewer": "single AI-assisted semantic reviewer",
            "petroleum_agent_reexecuted": False, "pricing_date": "2026-10-02",
            "latency_interpretation": "end-to-end user-perceived latency; local and cloud hardware are not directly comparable",
            "api_availability": {
                "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
                "GEMINI_API_KEY": bool(os.environ.get("GEMINI_API_KEY")),
            },
        },
        "models": ["Petroleum Agent", "qwen3:8b", "qwen2.5vl:7b", "gpt-6.1-sol", "gemini-3.8-flash"],
        "conditions": ["closed_book", "same_evidence", "figure"],
        "sample_counts": {"text": 50, "figure_total": 10, "figure_usable": len(figure_success_ids)},
        "semantic_metrics": semantic,
        "latency_metrics": {f"{row['System']}::{row['Condition']}": {"mean": row["Mean Latency"], "median": row["Median Latency"], "p95": row["P95 Latency"]} for row in rows},
        "cost_metrics": {f"{row['System']}::{row['Condition']}": row["Estimated Cost"] for row in rows},
        "run_metrics": run_metrics,
        "figure_metrics": {key: value for key, value in semantic.items() if "figure" in key},
        "paired_comparisons": paired,
        "limitations": [
            f"Unavailable provider conditions: {', '.join(missing_conditions) if missing_conditions else 'none'}.",
            "Petroleum Agent is a system-level baseline with retrieval, validation, and repair; direct closed-book models use only their internal knowledge.",
            "Same-evidence results compare generation and reasoning with retrieval differences removed.",
            "Semantic grading used one AI-assisted reviewer, not a human panel.",
            "Petroleum Agent figure answers may include retrieved text and validator/repair context; the direct vision run used only question plus image.",
            "Latency compares local RTX 3090 execution with remote APIs only when cloud runs are available and is not pure inference latency.",
            "Configured API models are gpt-6.1-sol and gemini-3.8-flash; evaluation date is 2026-10-02.",
        ],
        "rows": rows,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    poster_rows = [
        {
            "System": row["System"], "Condition": row["Condition"], "N": row["N"],
            "Exact %": poster_pct(row["Semantic Exact"]), "Partial+ %": poster_pct(row["Partial+"]),
            "Claim Coverage %": poster_pct(row["Claim Coverage"]),
            "Hallucination %": poster_pct(row["Hallucination"]),
            "Engineering Error %": poster_pct(row["Engineering Error"]),
            "False-Premise Correction %": poster_pct(row["False-Premise Correction"]),
            "Numeric Accuracy %": poster_pct(row["Numeric Accuracy"]),
            "Figure Accuracy %": poster_pct(row["Figure Accuracy"]),
            "Median Latency": row["Median Latency"] if row["Median Latency"] is not None else "N/A",
            "P95 Latency": row["P95 Latency"] if row["P95 Latency"] is not None else "N/A",
            "Estimated Cost USD": row["Estimated Cost"] if row["Estimated Cost"] is not None else "N/A",
        }
        for row in rows
    ]
    with POSTER_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(poster_rows[0]))
        writer.writeheader()
        writer.writerows(poster_rows)

    lines = [
        "# External model comparison summary", "",
        "Semantic results were produced by a **single AI-assisted semantic reviewer** using the frozen rubric.",
        "The Petroleum Agent was not re-run. Qwen ran locally on the RTX 3090; completed GPT/Gemini conditions used remote APIs.", "",
        "| System | Condition | N | Exact | Partial+ | Coverage | Hallucination | Eng. error | Median s | P95 s | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['System']} | {row['Condition']} | {row['N']} | {pct(row['Semantic Exact'])} | "
            f"{pct(row['Partial+'])} | {pct(row['Claim Coverage'])} | {pct(row['Hallucination'])} | "
            f"{pct(row['Engineering Error'])} | {row['Median Latency'] if row['Median Latency'] is not None else 'N/A'} | "
            f"{row['P95 Latency'] if row['P95 Latency'] is not None else 'N/A'} | {row['Status']} |"
        )
    by_system_condition = {(row["System"], row["Condition"]): row for row in rows}
    petroleum = by_system_condition[("Petroleum Agent", "petroleum_agent_text50")]

    def delta(left: dict[str, Any] | None, right: dict[str, Any] | None, field: str) -> str:
        if not left or not right or left[field] is None or right[field] is None:
            return "N/A"
        return f"{100 * (left[field] - right[field]):+.2f} percentage points"

    lines += ["", "## Key deltas", ""]
    for system in ("qwen3:8b (qwen)", "gpt-6.1-sol (openai)", "gemini-3.8-flash (gemini)"):
        closed = by_system_condition.get((system, "closed_book"))
        same = by_system_condition.get((system, "same_evidence"))
        lines.append(f"- Petroleum Agent minus {system} closed-book exact: {delta(petroleum, closed, 'Semantic Exact')}")
        lines.append(f"- {system} same-evidence minus closed-book exact: {delta(same, closed, 'Semantic Exact')}")
    lines += ["", "## Interpretation limits", ""] + [f"- {item}" for item in comparison["limitations"]]
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"json={OUTPUT_JSON.resolve()}")
    print(f"csv={OUTPUT_CSV.resolve()}")
    print(f"poster={POSTER_CSV.resolve()}")
    print(f"summary={OUTPUT_MD.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
