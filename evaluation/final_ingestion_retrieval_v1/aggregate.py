"""Predeclared scoring and retrieval denominators for the locked evaluation."""

from __future__ import annotations

import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
CALC_TYPES = {"calculation", "goal_style_multi_step"}
SOURCE_TYPES = {"KB_TEXT", "KB_EQUATION_OR_TEXT", "KB_FORMULA_AND_VALIDATED_CALC",
                "KB_FORMULA_AND_VALIDATED_SIMULATION", "FIG", "TWO_KB_DOCUMENTS"}
CITE_RE = re.compile(r"\[(KB\d+|FIG\d+|CALC\d+)\]")


def load_jsonl(name: str, key=lambda row: row["question_id"]) -> dict:
    path = HERE / name
    if not path.exists():
        return {}
    return {key(row): row for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() for row in [json.loads(line)]}


def mean(items: list[float | bool]) -> float | None:
    return round(statistics.mean(items), 4) if items else None


def expected_sources(task: dict) -> list[tuple[str, int]]:
    if not task.get("document"):
        return []
    docs = task["document"].split("; ")
    pages = task["page"] if isinstance(task["page"], list) else [task["page"]]
    return list(zip(docs, pages))


def source_ranks(task: dict, evidence: list[dict]) -> list[int | None]:
    return [next((rank for rank, item in enumerate(evidence, 1)
                  if item.get("document") == doc and item.get("page") == page), None)
            for doc, page in expected_sources(task)]


def classify_failure(task: dict, score: dict, agent: dict, probe: dict) -> str:
    if agent.get("error") or (agent.get("response") or {}).get("run_status") == "failed":
        return "runtime/tool failure"
    if score["accuracy"]:
        return "none"
    if score["over_refusal"]:
        return "over-refusal"
    response = agent.get("response") or {}
    if task["task_type"] == "figure_understanding":
        gold = expected_sources(task)
        if not any((item.get("document"), item.get("page")) in gold for item in response.get("figures", [])):
            return "Figure grounding failure"
    if task["answerable"] and expected_sources(task):
        selected = source_ranks(task, response.get("internal_sources", []))
        if any(rank is None for rank in selected):
            raw = (probe.get("response") or {}).get("internal_sources", [])
            return "evidence selection failure" if all(source_ranks(task, raw)) else "retrieval miss"
    if task.get("acceptable_equation") and score["equation_accuracy"] is False:
        return "equation selection failure"
    if task["task_type"] in CALC_TYPES and score["calculation_accuracy"] is False:
        return "calculation failure"
    if score["hallucination"]:
        return "hallucination"
    return "synthesis failure"


def main() -> None:
    tasks = json.loads((HERE / "rubric.json").read_text(encoding="utf-8"))["tasks"]
    agent = load_jsonl("agent_raw.jsonl")
    baseline = load_jsonl("baseline_raw.jsonl")
    probes = load_jsonl("retrieval_probe_raw.jsonl")
    reviews = load_jsonl("semantic_review_raw.jsonl", lambda row: (row["system"], row["question_id"]))
    scores: list[dict] = []
    retrieval: list[dict] = []
    failures: list[dict] = []
    for task in tasks:
        task_id = task["question_id"]
        source_gold = expected_sources(task)
        probe = probes.get(task_id, {})
        probe_sources = (probe.get("response") or {}).get("internal_sources", [])
        ranks = source_ranks(task, probe_sources)
        if source_gold:
            rank_complete = max(ranks) if ranks and all(ranks) else None
            retrieval.append({
                "question_id": task_id, "task_type": task["task_type"],
                "query_policy": "verbatim_question_top10_probe_not_agent_planner_query",
                "gold_document_pages": source_gold, "gold_ranks": ranks,
                "hit_at_1": bool(rank_complete and rank_complete <= 1),
                "hit_at_3": bool(rank_complete and rank_complete <= 3),
                "hit_at_5": bool(rank_complete and rank_complete <= 5),
                "hit_at_10": bool(rank_complete and rank_complete <= 10),
                "strict_reciprocal_rank": round(1 / rank_complete, 4) if rank_complete else 0.0,
                "retrieval_mode": (probe.get("response") or {}).get("retrieval_mode"),
                "top10": [{"evidence_id": item.get("evidence_id"), "document": item.get("document"),
                           "page": item.get("page"), "chunk_id": item.get("chunk_id"),
                           "score": item.get("score")}
                          for item in probe_sources[:10]],
            })
        for system, raw in (("agent", agent.get(task_id, {})), ("baseline", baseline.get(task_id, {}))):
            reviewer = reviews.get((system, task_id), {})
            verdict = (reviewer.get("review") or {}).get("parsed") or {}
            checks = verdict.get("claim_checks") or []
            by_index = {item.get("index"): item for item in checks if isinstance(item, dict)}
            claims = [by_index.get(index, {}) for index in range(len(task["required_claims"]))]
            complete_claims = all(item.get("answer_present") is True and
                                  item.get("answer_correct") is True for item in claims)
            numeric = verdict.get("numeric_and_units_correct") if task["required_values"] else None
            equation = verdict.get("equation_correct") if task.get("acceptable_equation") else None
            figure = verdict.get("figure_correct") if task["task_type"] == "figure_understanding" else None
            calculation = verdict.get("calculation_correct") if task["task_type"] in CALC_TYPES else None
            refusal = verdict.get("refusal") is True
            hallucination = (verdict.get("unsupported_new_claims") or 0) > 0
            explicit_correction = verdict.get("explicit_premise_correction") is True
            if task["answerable"]:
                accuracy = bool(complete_claims and not refusal and not hallucination and
                                (numeric is not False) and (equation is not False) and
                                (figure is not False) and (calculation is not False) and
                                (task["task_type"] != "false_premise" or explicit_correction))
            else:
                accuracy = bool(refusal and not hallucination and complete_claims)
            response = raw.get("response") or {}
            valid_calcs = sum(item.get("validation_passed") is True for item in response.get("computations", []))
            support_fraction = (sum(item.get("evidence_support") is True for item in claims) / len(claims)
                                if claims else None)
            citation_fraction = (sum(item.get("citation_support") is True for item in claims) / len(claims)
                                 if claims else None)
            valid_ids = {item.get("evidence_id") for item in response.get("internal_sources", []) + response.get("figures", [])}
            valid_ids |= {item.get("computation_id") for item in response.get("computations", [])}
            cited = CITE_RE.findall(response.get("final_answer", ""))
            citation_ids_correct = all(item in valid_ids for item in cited) if cited else None
            if system == "agent" and task["answerable"]:
                calc_required = task["required_evidence_type"] in {
                    "KB_FORMULA_AND_VALIDATED_CALC", "KB_FORMULA_AND_VALIDATED_SIMULATION",
                    "USER_FACT_AND_VALIDATED_CALC"}
                grounded = bool(accuracy and support_fraction == 1 and
                                (citation_fraction == 1 or task["required_evidence_type"] == "USER_FACT_AND_VALIDATED_CALC")
                                and (not calc_required or valid_calcs > 0))
            else:
                grounded = None
            score = {
                "question_id": task_id, "system": system, "category": task["task_type"],
                "domain": task["domain"], "answerable": task["answerable"],
                "accuracy": accuracy, "grounded_accuracy": grounded,
                "claim_coverage": mean([item.get("answer_present") is True and
                                        item.get("answer_correct") is True for item in claims]),
                "evidence_coverage": support_fraction if system == "agent" else None,
                "citation_semantic_support": citation_fraction if system == "agent" else None,
                "citation_id_correctness": citation_ids_correct if system == "agent" else None,
                "numeric_accuracy": numeric, "equation_accuracy": equation,
                "figure_accuracy": figure, "calculation_accuracy": calculation,
                "task_completed": verdict.get("task_completed") is True,
                "correct_refusal": bool(refusal and accuracy) if not task["answerable"] else None,
                "over_refusal": bool(refusal) if system == "agent" and task["answerable"] else None,
                "hallucination": hallucination, "unsupported_new_claim_count": verdict.get("unsupported_new_claims"),
                "false_premise_corrected": explicit_correction if task["task_type"] == "false_premise" else None,
                "run_id": response.get("run_id"), "run_status": response.get("run_status"),
                "agent_self_status": response.get("status"), "iterations": response.get("iterations_completed"),
                "goal_coverage_percent": response.get("goal_coverage_percent"), "validated_calculations": valid_calcs,
                "python_calls": response.get("python_calls_total"), "latency_seconds": raw.get("elapsed_seconds"),
                "reviewer_error": reviewer.get("error"), "reviewer_reason": verdict.get("brief_reason"),
            }
            scores.append(score)
            if system == "agent" and not accuracy:
                failures.append({"question_id": task_id, "category": task["task_type"],
                                 "primary_cause": classify_failure(task, score, raw, probe),
                                 "reviewer_reason": verdict.get("brief_reason"),
                                 "run_status": response.get("run_status"),
                                 "gold_page_ranks": ranks})
    systems = {}
    for system in ("agent", "baseline"):
        rows = [row for row in scores if row["system"] == system]
        def avg(key: str) -> float | None:
            return mean([row[key] for row in rows if row[key] is not None])
        latency = sorted(row["latency_seconds"] for row in rows if row["latency_seconds"] is not None)
        systems[system] = {
            "n": len(rows), "answer_accuracy": avg("accuracy"),
            "grounded_answer_rate_answerable_only": mean([row["grounded_accuracy"] for row in rows
                                                         if row["grounded_accuracy"] is not None]),
            "claim_coverage": avg("claim_coverage"), "evidence_coverage": avg("evidence_coverage"),
            "citation_semantic_support": avg("citation_semantic_support"),
            "citation_id_correctness": avg("citation_id_correctness"),
            "numeric_accuracy": avg("numeric_accuracy"), "equation_accuracy": avg("equation_accuracy"),
            "figure_accuracy": avg("figure_accuracy"), "calculation_accuracy": avg("calculation_accuracy"),
            "correct_refusal_rate": avg("correct_refusal"), "over_refusal_rate": avg("over_refusal"),
            "hallucination_rate": avg("hallucination"),
            "goal_task_completion_rate": mean([row["task_completed"] for row in rows
                                                if row["category"] == "goal_style_multi_step"]),
            "average_iterations": avg("iterations"), "average_goal_coverage_percent": avg("goal_coverage_percent"),
            "median_goal_coverage_percent": (statistics.median(row["goal_coverage_percent"] for row in rows
                                            if row["goal_coverage_percent"] is not None)
                                            if system == "agent" else None),
            "mean_latency_seconds": mean(latency),
            "median_latency_seconds": round(statistics.median(latency), 3) if latency else None,
            "p95_latency_seconds": latency[min(len(latency)-1, int(0.95*len(latency)))] if latency else None,
            "reviewer_error_count": sum(bool(row["reviewer_error"]) for row in rows),
        }
    retrieval_metrics = {
        "denominator": len(retrieval), "definition": "strict all-gold-document/page present in verbatim-question top-10 probe; not the autonomous planner query",
        **{f"hit_at_{k}": mean([row[f"hit_at_{k}"] for row in retrieval]) for k in (1,3,5,10)},
        "mrr_strict": mean([row["strict_reciprocal_rank"] for row in retrieval]),
        "rows": retrieval,
    }
    categories = {}
    for category in sorted({task["task_type"] for task in tasks}):
        category_rows = [row for row in scores if row["category"] == category]
        categories[category] = {system: {"n": len(part),
            "answer_accuracy": mean([row["accuracy"] for row in part]),
            "grounded_accuracy": mean([row["grounded_accuracy"] for row in part
                                        if row["grounded_accuracy"] is not None]),
            "refusal_count": sum(row["over_refusal"] is True for row in part),
            "hit_at_5": mean([item["hit_at_5"] for item in retrieval if item["task_type"] == category])
                        if system == "agent" else None}
            for system in ("agent", "baseline") for part in [[row for row in category_rows if row["system"] == system]]}
    failure_counts = Counter(row["primary_cause"] for row in failures)
    outputs = {
        "answer_metrics.json": {"systems": systems, "scoring_policy": "See SCORING_POLICY.md", "rows": scores},
        "retrieval_metrics.json": retrieval_metrics,
        "category_metrics.json": categories,
        "failure_analysis.json": {"failure_count": len(failures), "cause_counts": dict(failure_counts),
                                  "rows": failures},
    }
    for name, payload in outputs.items():
        (HERE / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if scores:
        with (HERE / "final_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(scores[0]))
            writer.writeheader()
            writer.writerows(scores)
    poster_rows = [{"Metric": metric, "Petroleum Agent": systems["agent"][key],
                    "ChatGPT closed-book": systems["baseline"][key]}
                   for metric, key in (("Answer Accuracy", "answer_accuracy"),
                                       ("Numeric Accuracy", "numeric_accuracy"),
                                       ("Equation Accuracy", "equation_accuracy"),
                                       ("Correct Refusal", "correct_refusal_rate"),
                                       ("Hallucination Rate", "hallucination_rate"),
                                       ("Median Latency (s)", "median_latency_seconds"))]
    with (HERE / "poster_metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(poster_rows[0]))
        writer.writeheader()
        writer.writerows(poster_rows)
    print(json.dumps({"systems": systems, "retrieval": {k:v for k,v in retrieval_metrics.items() if k!="rows"},
                      "failure_counts": dict(failure_counts)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
