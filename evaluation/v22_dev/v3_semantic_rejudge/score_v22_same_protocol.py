"""Score preserved V22 answers with the original V3 deterministic rules."""

from __future__ import annotations

import argparse
import math
import random
import statistics
import sys
from pathlib import Path

from prepare_v22_raw import HERE, OBSERVED, read_json, verify


def score(original: Path) -> None:
    original = original.resolve()
    observed, benchmark = verify(original)
    sys.path.insert(0, str(original))
    from common import write_json
    from score import agent_provenance, average, numeric_present, percentile, summarize

    model = "gpt-5.4-2026-03-05"
    judges = HERE / "judge" / "v22_agent"
    raw_dir = HERE / "raw" / "v22_agent"
    tasks = benchmark["primary_tasks"]
    if len(list(judges.glob("*.json"))) != 36 or len(list(raw_dir.glob("*.json"))) != 36:
        raise RuntimeError("All 36 saved answers and judgments are required")
    qwen_rows = [row for row in read_json(original / "scored_rows.json")
                 if row["system"] == "qwen_closed_book"]
    original_metrics = read_json(original / "metrics.json")["systems"]["qwen_closed_book"]
    if len(qwen_rows) != 36:
        raise RuntimeError("Original Qwen scored-row count mismatch")
    for key in ("goal_success", "claim_coverage", "hallucination_free", "numeric_accuracy"):
        if not math.isclose(summarize(qwen_rows)[key], original_metrics[key], abs_tol=1e-12):
            raise RuntimeError(f"Original finalized Qwen {key} does not match scored rows")

    v22_rows = []
    for task in tasks:
        task_id = task["task_id"]
        raw = read_json(raw_dir / f"{task_id}.json")
        judged = read_json(judges / f"{task_id}.json")
        if (judged.get("status") != "completed" or judged.get("judge_model") != model
                or judged.get("attempt_count") != 1
                or judged.get("response_meta", {}).get("model_returned") != model):
            raise RuntimeError(f"Exact one-call semantic judgment is incomplete: {task_id}")
        judgment = judged["judgment"]
        if len(judgment["claim_scores"]) != len(task["required_claims"]):
            raise RuntimeError(f"Claim-score count mismatched frozen rubric: {task_id}")
        if raw["technical_failure"] or raw["system"] != "v22_agent":
            raise RuntimeError(f"Saved V22 raw outcome changed or is missing: {task_id}")
        coverage = statistics.mean(judgment["claim_scores"])
        numeric = bool(task["numeric_targets"])
        numeric_correct = bool(numeric and judgment["numeric_accuracy"] and judgment["unit_accuracy"]
                               and all(numeric_present(raw["answer_text"], target)
                                       for target in task["numeric_targets"]))
        run = raw["run"]
        provenance = agent_provenance(task, run)
        goal = bool(judgment["all_required_goals_met"]
                    and all(value == 1 for value in judgment["claim_scores"]))
        if task["category"] == "false_premise":
            goal = goal and judgment["false_premise_explicitly_corrected"]
            goal = goal and provenance["citation_id_correct"] and judgment["citation_semantic_support"]
        if task["category"] == "unanswerable":
            goal = goal and judgment["unanswerable_specific_missing_identified"]
        if numeric:
            goal = goal and numeric_correct and provenance["calculation_validated"]
        if task["category"] == "kb_formula":
            goal = goal and provenance["formula_provenance_correct"]
        if task["citation_required_for_agent"] and task["category"] != "unanswerable":
            goal = goal and provenance["citation_id_correct"] and judgment["citation_semantic_support"]
        v22_rows.append({
            "task_id": task_id, "category": task["category"], "domain": task["domain"],
            "question_language": task["question_language"], "multi_goal": task["multi_goal"],
            "answerable": task["answerable"], "system": "v22_agent",
            "response_status": raw["response_status"], "technical_failure": False,
            "goal_success": bool(goal), "claim_coverage": coverage,
            "hallucination_free": not judgment["hallucination"],
            "hallucination": bool(judgment["hallucination"]),
            "numeric_correct": numeric_correct if numeric else None,
            "unnecessary_refusal": bool(judgment["unnecessary_refusal"]),
            "citation_semantic_support": bool(judgment["citation_semantic_support"]
                                              and provenance["citation_id_correct"]),
            "latency_seconds": raw["latency_seconds"],
            "run_status": run.get("run_status"), "final_status": run.get("status"),
            "python_calls": run.get("python_calls_total", 0), **provenance,
        })
    write_json(HERE / "scored_rows.json", qwen_rows + v22_rows)
    qwen = {row["task_id"]: row for row in qwen_rows}
    v22 = {row["task_id"]: row for row in v22_rows}
    paired = {}
    for metric in ("goal_success", "claim_coverage", "hallucination_free", "numeric_correct"):
        ids = [task["task_id"] for task in tasks if metric != "numeric_correct" or task["numeric_targets"]]
        if len(ids) != (16 if metric == "numeric_correct" else 36):
            raise RuntimeError("Frozen paired denominator mismatch")
        differences = [float(v22[task_id][metric]) - float(qwen[task_id][metric]) for task_id in ids]
        rng = random.Random(20261013)
        samples = [average([differences[rng.randrange(len(differences))] for _ in differences])
                   for _ in range(10000)]
        paired[metric] = {
            "delta": average(differences), "ci95_low": percentile(samples, 0.025),
            "ci95_high": percentile(samples, 0.975), "n": len(ids),
            "resamples": 10000, "seed": 20261013,
        }
    categories = {}
    for category in sorted({task["category"] for task in tasks}):
        categories[category] = {
            "qwen_closed_book": average([float(row["goal_success"]) for row in qwen_rows
                                         if row["category"] == category]),
            "v22_agent": average([float(row["goal_success"]) for row in v22_rows
                                  if row["category"] == category]),
        }
    group_map = {
        "Knowledge": ("knowledge_qa",),
        "Reasoning": ("multi_claim_reasoning",),
        "Calculation": ("direct_calculation", "user_formula", "kb_formula"),
        "Safety": ("false_premise", "unanswerable"),
    }
    groups = {
        name: {system: average([float(row["goal_success"]) for row in rows
                                if row["category"] in categories_in_group])
               for system, rows in (("qwen_closed_book", qwen_rows), ("v22_agent", v22_rows))}
        for name, categories_in_group in group_map.items()
    }
    numeric_rows = [row for row in v22_rows if row["numeric_correct"] is not None]
    kb_rows = [row for row in v22_rows if row["category"] == "kb_formula"]
    source_rows = [row for row in v22_rows
                   if row["category"] not in {"direct_calculation", "user_formula"}]
    diagnostics = {
        "calculation_executed_16": sum(row["calculation_executed"] for row in numeric_rows),
        "calculation_validated_16": sum(row["calculation_validated"] for row in numeric_rows),
        "calculation_provenance_complete_16": sum(row["calculation_provenance_complete"] for row in numeric_rows),
        "numeric_correct_16": sum(row["numeric_correct"] for row in numeric_rows),
        "gold_page_retrieved_6": sum(row["gold_page_retrieved"] for row in kb_rows),
        "formula_span_retrieved_6": sum(row["formula_span_retrieved"] for row in kb_rows),
        "retrieve_then_calculate_6": sum(row["retrieve_then_calculate"] for row in kb_rows),
        "kb_formula_numeric_correct_6": sum(row["numeric_correct"] for row in kb_rows),
        "kb_formula_provenance_correct_6": sum(row["formula_provenance_correct"] for row in kb_rows),
        "citation_semantic_support_source_tasks": sum(row["citation_semantic_support"] for row in source_rows),
        "citation_semantic_support_denominator": len(source_rows),
        "unnecessary_refusals": sum(row["unnecessary_refusal"] for row in v22_rows),
        "cross_language_goal_success_12": sum(row["goal_success"] for row in v22_rows
                                              if row["question_language"] == "ko"),
        "multi_goal_success_6": sum(row["goal_success"] for row in v22_rows if row["multi_goal"]),
        "resume_final_completion_4": sum(bool(row.get("final_completion"))
                                         for row in observed["resume_probes"]),
    }
    if len(numeric_rows) != 16 or len(kb_rows) != 6 or len(source_rows) != 26:
        raise RuntimeError("Frozen diagnostic denominator mismatch")
    if len([row for row in v22_rows if row["question_language"] == "ko"]) != 12:
        raise RuntimeError("Frozen Korean-task denominator mismatch")
    if len([row for row in v22_rows if row["multi_goal"]]) != 6:
        raise RuntimeError("Frozen multi-goal denominator mismatch")
    write_json(HERE / "metrics.json", {
        "label": "V22 observed V3 same-protocol semantic comparison; not unseen final evaluation",
        "v22_product_sha": observed["product_sha"], "judge_model": model,
        "judge_completed": 36, "primary_denominator": 36, "numeric_denominator": 16,
        "systems": {"qwen_closed_book": original_metrics, "v22_agent": summarize(v22_rows)},
        "v22_diagnostics": diagnostics,
    })
    write_json(HERE / "comparison_qwen_v22.json", {
        "paired_v22_minus_qwen": paired, "category_goal_success": categories,
        "poster_grouping": group_map, "grouped_goal_success": groups,
    })
    print("same-protocol scoring complete: 36 V22 rows, 36 unchanged Qwen rows", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    score(parser.parse_args().original)
