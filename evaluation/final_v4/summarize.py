"""Join deterministic and semantic layers; enforce operational success gates."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import random
import statistics

from run_experiment import HERE, MANIFEST, MODELS, load_benchmark
from score_deterministic import NUMBER, SCIENTIFIC, TRACKS


CALC = {"direct_calculation", "kb_calculation", "user_formula_calculation", "user_formula_simulation", "clarification"}
SYSTEM_NAMES = {"agent": "Petroleum-RAG-Agent v11.1", "qwen_closed_book": "Qwen3:8b closed-book",
                "openai_closed_book": "OpenAI closed-book", "qwen_same_evidence": "Qwen3:8b same-evidence",
                "openai_same_evidence": "OpenAI same-evidence"}
METRICS = ("goal_success", "exact_accuracy", "partial_or_better", "claim_coverage",
           "hallucination", "unsupported_claim", "engineering_contradiction",
           "numeric_accuracy", "unit_accuracy", "formula_accuracy", "safe_refusal",
           "false_premise_handling", "wall_seconds")


def mean(rows: list[dict], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return sum(values) / len(values) if values else None


def percent(value: float | None) -> float | None:
    return round(value * 100, 2) if value is not None else None


def score_row(row: dict, review: dict, task: dict) -> dict:
    out = dict(row)
    empty_answer = not str(row.get("answer") or "").strip()
    has_numeric_expression = bool(NUMBER.search(str(row.get("answer") or "")) or
                                  SCIENTIFIC.search(str(row.get("answer") or "")))
    formula_applicable = bool(task.get("expected_formula") or task.get("user_formula"))
    machine_formula_verified = bool(
        row["track"] == "agent" and formula_applicable
        and row.get("formula_accuracy_deterministic") is True
        and row.get("calculation_provenance_completeness") is True
        and row.get("validated_calc_adoption") is True)
    machine_numeric_verified = bool(
        row["track"] == "agent" and row.get("calculation_provenance_completeness") is True
        and row.get("validated_calc_adoption") is True
        and (not formula_applicable or machine_formula_verified)
        and row.get("numeric_accuracy_deterministic") is True
        and row.get("validated_calc_numeric_match") is True)
    claim_verdicts = [False] * len(task["expected_claims"]) if empty_answer else review["claim_verdicts"]
    out["claim_verdicts"] = claim_verdicts
    out["claim_coverage"] = sum(claim_verdicts) / len(claim_verdicts) if claim_verdicts else 0.0
    out["partial_or_better"] = (bool(review["partial_or_better"]) or machine_numeric_verified) and not empty_answer
    out["hallucination"] = bool(review["hallucination"]) and not empty_answer
    out["unsupported_claim_count"] = 0 if empty_answer else int(review["unsupported_claim_count"])
    out["unsupported_claim"] = out["unsupported_claim_count"] > 0
    out["engineering_contradiction_count"] = 0 if empty_answer else int(review["engineering_contradiction_count"])
    out["engineering_contradiction"] = out["engineering_contradiction_count"] > 0
    numeric_applicable = bool(task.get("required_numeric_result") or task.get("expected_after_resume"))
    unit_applicable = any(str(value).casefold() not in {"dimensionless", "fraction"}
                          for value in (task.get("expected_units") or {}).values())
    out["numeric_accuracy"] = ((bool(review["numeric_accuracy"]) and has_numeric_expression) or machine_numeric_verified
                               if numeric_applicable and not empty_answer else (False if numeric_applicable else None))
    out["unit_accuracy"] = (bool(review["unit_accuracy"]) and has_numeric_expression
                            if unit_applicable and not empty_answer else (False if unit_applicable else None))
    out["formula_accuracy"] = (bool(review["formula_accuracy"]) or machine_formula_verified
                               if formula_applicable and not empty_answer else (False if formula_applicable else None))
    out["false_premise_handling"] = None
    if task["category"] == "false_premise":
        corrected = (bool(review["false_premise_handled"]) and not out["hallucination"]
                     and not out["unsupported_claim"] and not out["engineering_contradiction"])
        if row["track"] == "agent":
            corrected = (corrected and row.get("citation_id_correctness") is True
                         and review["citation_semantic_support"] == 1)
        out["false_premise_handling"] = bool(corrected)
    out["safe_refusal"] = bool(review["safe_refusal_correct"]) if task["category"] == "unsupported" else None
    out["citation_semantic_support"] = (float(review["citation_semantic_support"] or 0)
                                        if row.get("citation_ids") else None)
    out["review_note"] = ("Empty final answer; deterministic guard overrides impossible reviewer assertions."
                          if empty_answer else review["note"])
    content_ok = bool(claim_verdicts and all(claim_verdicts) and
                      not out["hallucination"] and not out["unsupported_claim"] and
                      not out["engineering_contradiction"] and
                      (out["numeric_accuracy"] is not False) and (out["unit_accuracy"] is not False) and
                      (out["formula_accuracy"] is not False) and
                      (out["false_premise_handling"] is not False) and (out["safe_refusal"] is not False))
    out["exact_accuracy"] = content_ok
    operational = content_ok
    if row["track"] == "agent":
        if task["category"] != "unsupported":
            operational = operational and row.get("agent_self_status") == "achieved"
        operational = operational and row.get("intent_routing_accuracy") is True
        operational = operational and row.get("source_requirement_accuracy") is True
        operational = operational and row.get("correct_action_selection") is True
        if task["expected_source_ids"]:
            operational = operational and row.get("citation_id_correctness") is True and review["citation_semantic_support"] == 1
        if task["category"] in CALC:
            operational = operational and row.get("calculation_provenance_completeness") is True
            operational = operational and row.get("variable_binding_success") is True
            operational = operational and row.get("python_simulation_execution_success") is True
            operational = operational and row.get("validated_calc_adoption") is True
        if task["expected_source_requirement"] == "KB_FORMULA":
            operational = operational and row.get("formula_source_correctness") is True
            operational = operational and row.get("formula_candidate_selection_success") is True
            operational = operational and row.get("exact_formula_span_recall") is True
            operational = operational and row.get("formula_to_calculate_success") is True
        if task["category"] == "figure":
            operational = operational and row.get("figure_retrieval_accuracy") == 1
        if task["category"] == "clarification":
            operational = (operational and row.get("clarification_success") is True
                           and row.get("same_run_id_success") is True
                           and row.get("resume_fact_ingestion_success") is True
                           and row.get("resume_completion_success") is True)
        if task["category"] == "false_premise":
            operational = (operational and row.get("premise_relevant_source_retrieval") is True
                           and row.get("citation_id_correctness") is True
                           and review["citation_semantic_support"] == 1)
    out["goal_success"] = bool(operational)
    return out


def aggregate(rows: list[dict]) -> dict:
    latency = [float(row["wall_seconds"]) for row in rows if row.get("wall_seconds") is not None]
    result = {"tasks": len(rows)}
    for metric in METRICS[:-1]:
        result[metric] = percent(mean(rows, metric))
        result[metric + "_denominator"] = sum(row.get(metric) is not None for row in rows)
    result["mean_latency_seconds"] = round(statistics.mean(latency), 3) if latency else None
    result["median_latency_seconds"] = round(statistics.median(latency), 3) if latency else None
    result["p95_latency_seconds"] = round(sorted(latency)[math.ceil(0.95 * len(latency)) - 1], 3) if latency else None
    for field in ("intent_routing_accuracy", "source_requirement_accuracy",
                  "exact_formula_span_recall", "formula_to_calculate_success",
                  "formula_to_calculate_given_span", "empty_final_answer",
                  "formula_source_correctness", "formula_candidate_selection_success",
                  "variable_binding_success", "calculation_provenance_completeness",
                  "natural_language_fact_extraction_recall", "unit_normalization_accuracy",
                  "domain_matched_document_recall_at_k", "relevant_chunk_at_k",
                  "top3_relevant_precision", "wrong_domain_dominance_rate",
                  "refined_retrieval_recovery_rate", "refined_retrieval_triggered",
                  "premise_relevant_source_retrieval", "correct_action_selection",
                  "clarification_success", "same_run_id_success", "resume_fact_ingestion_success",
                  "resume_completion_success", "same_run_resume_success",
                  "python_simulation_execution_success", "validated_calc_adoption",
                  "document_recall_at_k", "page_recall_at_k", "figure_retrieval_accuracy",
                  "citation_id_correctness", "citation_semantic_support", "repeated_no_progress_action_rate"):
        result[field] = percent(mean(rows, field))
        result[field + "_denominator"] = sum(row.get(field) is not None for row in rows)
    for field in ("message_parsing_seconds", "retrieval_seconds", "planning_seconds",
                  "llm_generation_seconds", "python_seconds", "calculation_simulation_seconds",
                  "verification_seconds", "evaluation_seconds", "synthesis_seconds"):
        value = mean(rows, field)
        result["mean_" + field] = round(value, 3) if value is not None else None
    result["mean_unsupported_claim_count"] = round(mean(rows, "unsupported_claim_count") or 0, 3)
    result["mean_engineering_contradiction_count"] = round(mean(rows, "engineering_contradiction_count") or 0, 3)
    return result


def quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] * (hi - position) + ordered[hi] * (position - lo) if hi != lo else ordered[lo]


def bootstrap(rows: list[dict], ids: list[str], *, iterations: int = 5000) -> dict:
    by_track = {track: {row["task_id"]: row for row in rows if row["track"] == track} for track in TRACKS}
    tracks = list(TRACKS)
    rng = random.Random(20261011)
    metrics = ("goal_success", "exact_accuracy", "claim_coverage", "hallucination", "numeric_accuracy")
    samples: dict[str, dict[str, list[float]]] = {track: {metric: [] for metric in metrics} for track in tracks}
    pairs = (("agent", "qwen_closed_book"), ("agent", "openai_closed_book"),
             ("qwen_same_evidence", "qwen_closed_book"),
             ("openai_same_evidence", "openai_closed_book"),
             ("agent", "qwen_same_evidence"), ("agent", "openai_same_evidence"))
    contrasts = {f"{a}_minus_{b}": {metric: [] for metric in metrics} for a, b in pairs}
    for _ in range(iterations):
        sampled_ids = rng.choices(ids, k=len(ids))
        current = {track: {metric: mean([by_track[track][key] for key in sampled_ids], metric)
                           for metric in metrics} for track in tracks}
        for track in tracks:
            for metric in metrics:
                value = current[track][metric]
                if value is not None:
                    samples[track][metric].append(value)
        for a, b in pairs:
            for metric in metrics:
                left, right = current[a][metric], current[b][metric]
                if left is not None and right is not None:
                    contrasts[f"{a}_minus_{b}"][metric].append(left - right)
    def summary(series: list[float]) -> dict | None:
        return {"lower": round(100 * quantile(series, 0.025), 2),
                "upper": round(100 * quantile(series, 0.975), 2)} if series else None
    return {"method": "paired bootstrap by valid task ID, percentile 95% CI",
            "iterations": iterations, "seed": 20261011,
            "systems": {track: {metric: summary(series) for metric, series in metrics_dict.items()}
                        for track, metrics_dict in samples.items()},
            "paired_differences_percentage_points": {
                name: {metric: summary(series) for metric, series in metrics_dict.items()}
                for name, metrics_dict in contrasts.items()}}


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(row[key], ensure_ascii=False) if isinstance(row.get(key), (dict, list)) else row.get(key)
                             for key in columns})


def main() -> None:
    benchmark = load_benchmark()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    invalid_file = HERE / "invalid_tasks.json"
    invalid = {row["task_id"] for row in json.loads(invalid_file.read_text(encoding="utf-8")).get("invalid", [])} if invalid_file.exists() else set()
    tasks = {task["task_id"]: task for task in benchmark["tasks"] if task["task_id"] not in invalid}
    deterministic = json.loads((HERE / "metrics/deterministic_rows.json").read_text(encoding="utf-8"))
    rows = []
    for item in deterministic:
        if item["task_id"] not in tasks:
            continue
        if not item["available"]:
            raise RuntimeError(f"Missing raw result: {item['task_id']} {item['track']}")
        review_path = HERE / "review/independent_openai" / f"{item['task_id']}.json"
        if not review_path.exists():
            raise RuntimeError(f"Missing semantic review: {item['task_id']}")
        review = json.loads(review_path.read_text(encoding="utf-8"))
        if review.get("parse_error") or review.get("error") or item["track"] not in review.get("scores_by_track", {}):
            raise RuntimeError(f"Incomplete semantic review: {item['task_id']}")
        rows.append(score_row(item, review["scores_by_track"][item["track"]], tasks[item["task_id"]]))
    if len(rows) != len(tasks) * len(TRACKS):
        raise RuntimeError("Joined rows incomplete")
    by_track = {track: aggregate([row for row in rows if row["track"] == track]) for track in TRACKS}
    by_category = {track: {category: aggregate(group) for category, group in
                           ((category, [row for row in rows if row["track"] == track and row["category"] == category])
                            for category in sorted({task["category"] for task in tasks.values()}))}
                   for track in TRACKS}
    statistical = bootstrap(rows, list(tasks))
    reviewer_ids = {
        json.loads((HERE / "review/independent_openai" / f"{task_id}.json").read_text(encoding="utf-8"))["reviewer_model_id"]
        for task_id in tasks}
    if len(reviewer_ids) != 1:
        raise RuntimeError(f"Mixed or missing semantic reviewer models: {reviewer_ids}")
    reviewer_id = next(iter(reviewer_ids))
    actual_models = {}
    for track in TRACKS:
        observed = {row.get("model_id") for row in rows if row["track"] == track}
        if len(observed) != 1 or None in observed:
            raise RuntimeError(f"Mixed or missing model IDs for {track}: {observed}")
        actual_models[track] = next(iter(observed))
    if actual_models["agent"] != MODELS["qwen"] or actual_models["openai_closed_book"] != MODELS["openai"]:
        raise RuntimeError(f"Unexpected actual model ID: {actual_models}")
    metrics = {"benchmark_id": benchmark["benchmark_id"], "evaluated_product_sha": benchmark["evaluated_product_sha"],
               "benchmark_sha256": manifest["benchmark_sha256"], "freeze_commit": manifest["freeze_commit"],
               "frozen_tasks": len(benchmark["tasks"]), "valid_tasks": len(tasks), "invalid_tasks": sorted(invalid),
               "model_ids": {"agent": actual_models["agent"], "qwen": actual_models["qwen_closed_book"],
                             "openai": actual_models["openai_closed_book"],
                             "semantic_reviewer": reviewer_id, "by_track": actual_models},
               "tracks": by_track, "categories": by_category,
               "agent_run_status_counts": dict(Counter(row.get("run_status") for row in rows if row["track"] == "agent")),
               "agent_empty_final_answers": sum(not str(row.get("answer") or "").strip() for row in rows if row["track"] == "agent"),
               "scoring": "deterministic + structured expected claims + single-reviewer AI-assisted semantic adjudication"}
    (HERE / "final_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (HERE / "statistical_analysis.json").write_text(json.dumps(statistical, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status = {"status": "COMPLETED", "benchmark_id": benchmark["benchmark_id"],
              "frozen_tasks": len(benchmark["tasks"]), "valid_tasks": len(tasks),
              "invalid_tasks": sorted(invalid), "rows_scored": len(rows),
              "raw_completed_by_track": {track: sum(row["track"] == track for row in rows) for track in TRACKS},
              "reviewer_model_id": reviewer_id,
              "product_code_modified": False, "frozen_benchmark_modified": False}
    (HERE / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    write_csv(HERE / "final_results.csv", rows, fields)
    poster = [{"System": SYSTEM_NAMES[track], "Track": "End-to-End" if track in {"agent", "qwen_closed_book", "openai_closed_book"} else "Same-Evidence",
               "Goal Success %": by_track[track]["goal_success"], "Exact Accuracy %": by_track[track]["exact_accuracy"],
               "Claim Coverage %": by_track[track]["claim_coverage"], "Hallucination %": by_track[track]["hallucination"],
               "Numeric Accuracy %": by_track[track]["numeric_accuracy"], "Median Latency": by_track[track]["median_latency_seconds"]}
              for track in TRACKS]
    write_csv(HERE / "poster_metrics.csv", poster, list(poster[0]))
    agent = by_track["agent"]
    reliability = [{"Fact Extraction Recall %": agent["natural_language_fact_extraction_recall"],
                    "Unit Normalization Accuracy %": agent["unit_normalization_accuracy"],
                    "Intent Routing Accuracy %": agent["intent_routing_accuracy"],
                    "Source Requirement Accuracy %": agent["source_requirement_accuracy"],
                    "Document Recall@K %": agent["document_recall_at_k"],
                    "Page Recall@K %": agent["page_recall_at_k"],
                    "Domain Document Recall@K %": agent["domain_matched_document_recall_at_k"],
                    "Relevant Chunk@K %": agent["relevant_chunk_at_k"],
                    "Top-3 Relevant Precision %": agent["top3_relevant_precision"],
                    "Wrong-Domain Dominance %": agent["wrong_domain_dominance_rate"],
                    "Refined Retrieval Recovery Rate %": agent["refined_retrieval_recovery_rate"],
                    "Exact Formula Span Recall %": agent["exact_formula_span_recall"],
                    "Formula Candidate Selection %": agent["formula_candidate_selection_success"],
                    "Formula Source Correctness %": agent["formula_source_correctness"],
                    "Formula-to-CALCULATE %": agent["formula_to_calculate_success"],
                    "Variable Binding Success %": agent["variable_binding_success"],
                    "Calculation Provenance %": agent["calculation_provenance_completeness"],
                    "Premise Relevant-Source Retrieval %": agent["premise_relevant_source_retrieval"],
                    "False-Premise Correction %": agent["false_premise_handling"],
                    "Python/Simulation Execution %": agent["python_simulation_execution_success"],
                    "Correct Action Selection %": agent["correct_action_selection"],
                    "Clarification Success %": agent["clarification_success"],
                    "Same-run ID Success %": agent["same_run_id_success"],
                    "Resume Fact Ingestion Success %": agent["resume_fact_ingestion_success"],
                    "Resume Completion %": agent["resume_completion_success"],
                    "Same-run Resume %": agent["same_run_resume_success"],
                    "Citation ID Correctness %": agent["citation_id_correctness"],
                    "Citation Semantic Support %": agent["citation_semantic_support"],
                    "Empty Final Answer %": agent["empty_final_answer"],
                    "No-progress Action Rate %": agent["repeated_no_progress_action_rate"]}]
    write_csv(HERE / "agent_reliability_metrics.csv", reliability, list(reliability[0]))
    print(f"valid={len(tasks)} rows={len(rows)} agent_goal_success={agent['goal_success']}%")


if __name__ == "__main__":
    main()
