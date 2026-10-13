"""Score one observed-set pass with the existing frozen numeric/diagnostic rules."""

from __future__ import annotations

import csv
import json
import math
import statistics
import subprocess
import sys

from judge_once import MODEL, SYSTEMS, V20_ROOT, read_old
from run_once import BENCHMARK_REF, HERE, REPO, save


sys.path.insert(0, str(V20_ROOT))
from frozen_score_results import NUMERIC_CATEGORIES, SOURCE_CATEGORIES, agent_diag, numeric_score  # noqa: E402


def score(task: dict, system: str, judge: dict) -> dict:
    label = next(label for label, name in judge["anonymous_labels"].items() if name == system)
    verdict = judge["verdict"]["responses"][label]
    claims = verdict["claim_scores"]
    if (len(claims) != len(task["required_claims"]) or
            any(value not in (0, 0.5, 1) for value in claims)):
        raise RuntimeError(f"{task['task_id']}: invalid frozen-rubric claim scores")
    raw = read_old(system, task["task_id"])
    answer = raw.get("answer", "")
    numerical = numeric_score(task, answer) if task["category"] in NUMERIC_CATEGORIES else None
    diag = agent_diag(task, raw.get("run") or {}) if system.endswith("_agent") else {}
    success = bool(verdict["goal_success"])
    if numerical:
        success &= numerical["final_numeric_correct"]
        if system.endswith("_agent"):
            success &= bool(diag["route_correct"] and diag["calculation_validated"])
            if task["category"] == "kb_formula":
                success &= bool(diag["formula_source_verified"] and diag["formula_source_correct"])
    if task["category"] in SOURCE_CATEGORIES:
        success &= verdict.get("citation_semantic_support") is True if system.endswith("_agent") else True
    material_errors = {"fabricated_fact", "unsupported_claim", "wrong_calculation", "wrong_unit",
                       "wrong_formula", "wrong_formula_provenance"}
    clean = bool(verdict["hallucination_free"]) and not bool(
        material_errors.intersection(verdict.get("error_labels", [])))
    if numerical and numerical["numeric_value_correct"] is False and verdict.get("final_numeric_outputs"):
        clean = False
    waiting = bool(task["answerable"] and raw.get("run_status") == "waiting_for_user_input")
    return {"goal_success": bool(success), "claim_coverage": statistics.fmean(claims),
            "hallucination_free": clean,
            "numeric_correct": numerical["final_numeric_correct"] if numerical else None,
            "unnecessary_refusal": bool(task["answerable"] and
                                        (verdict.get("unnecessary_refusal") or waiting)),
            "citation_semantic_support": verdict.get("citation_semantic_support"),
            "relevant_evidence_retrieved": verdict.get("relevant_evidence_retrieved"),
            "diagnostics": diag, "numeric": numerical,
            "latency_seconds": raw.get("latency_seconds")}


def percent(values) -> float:
    return round(100 * statistics.fmean(values), 2)


def main() -> None:
    tasks = json.loads(subprocess.check_output(["git", "show", BENCHMARK_REF], cwd=REPO))["tasks"]
    rows = []
    for task in tasks:
        path = HERE / "judge" / f"{task['task_id']}.json"
        if not path.exists():
            raise RuntimeError(f"{task['task_id']}: missing single-reviewer verdict")
        judge = json.loads(path.read_text(encoding="utf-8"))
        if judge.get("status") != "completed" or judge.get("actual_model") != MODEL:
            raise RuntimeError(f"{task['task_id']}: judge incomplete or model substituted")
        rows.append({"task_id": task["task_id"], "category": task["category"],
                     "answerable": task["answerable"],
                     "cross_language": bool(task.get("supporting_spans")) and
                                       any("가" <= char <= "힣" for char in task["question"]),
                     "systems": {system: score(task, system, judge) for system in SYSTEMS}})
    metrics = {}
    for system in SYSTEMS:
        values = [row["systems"][system] for row in rows]
        numeric_values = [value["numeric_correct"] for value in values if value["numeric_correct"] is not None]
        metrics[system] = {
            "tasks": len(values), "goal_success_percent": percent(v["goal_success"] for v in values),
            "claim_coverage_percent": percent(v["claim_coverage"] for v in values),
            "hallucination_free_percent": percent(v["hallucination_free"] for v in values),
            "numerical_accuracy_percent": percent(numeric_values),
            "numeric_n": len(numeric_values),
            "median_latency_seconds": (statistics.median(v["latency_seconds"] for v in values)
                                       if all(v["latency_seconds"] is not None for v in values) else None),
        }
    agent = "v21_2_agent"
    nums = [row["systems"][agent] for row in rows if row["category"] in NUMERIC_CATEGORIES]
    kb = [row["systems"][agent] for row in rows if row["category"] == "kb_formula"]
    cross = [row["systems"][agent] for row in rows if row["cross_language"]]
    answerable = [row["systems"][agent] for row in rows if row["answerable"]]
    resume_files = sorted((HERE / "raw" / "resume_suite").glob("*.json"))
    resumes = [json.loads(path.read_text(encoding="utf-8")) for path in resume_files]
    diagnostics = {
        "numeric": {"operands_complete": sum(v["diagnostics"]["operands_complete"] for v in nums),
                    "calculation_executed": sum(v["diagnostics"]["calculation_executed"] for v in nums),
                    "numeric_correct": sum(bool(v["numeric_correct"]) for v in nums), "n": len(nums)},
        "kb_formula": {"retrieval": sum(v["diagnostics"]["retrieval_success"] for v in kb),
                       "correct_span": sum(v["diagnostics"]["correct_formula_span_retrieved"] for v in kb),
                       "retrieve_to_calculate": sum(v["diagnostics"]["route_correct"] for v in kb),
                       "numeric_correct": sum(bool(v["numeric_correct"]) for v in kb), "n": len(kb)},
        "cross_language": {"goal_success": sum(v["goal_success"] for v in cross), "n": len(cross)},
        "unnecessary_refusals": {"count": sum(v["unnecessary_refusal"] for v in answerable),
                                 "n": len(answerable)},
        "resume": {"passes": sum(row.get("status") == "completed" and
                                  (row.get("turn_2_run") or {}).get("status") == "achieved"
                                  for row in resumes), "n": len(resumes)},
    }
    save(HERE / "scored_rows.json", {"label": "Observed legacy regression benchmark; not unseen.",
                                      "judge_model": MODEL, "rows": rows})
    save(HERE / "metrics.json", {"label": "Observed legacy regression benchmark; not unseen.",
                                   "judge_model": MODEL, "systems": metrics, "diagnostics": diagnostics})
    with (HERE / "results.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["task_id", "category", "system", "goal_success",
                                                  "claim_coverage", "hallucination_free", "numeric_correct"])
        writer.writeheader()
        for row in rows:
            for system, value in row["systems"].items():
                writer.writerow({"task_id": row["task_id"], "category": row["category"], "system": system,
                                 **{key: value[key] for key in ("goal_success", "claim_coverage",
                                                                  "hallucination_free", "numeric_correct")}})
    print(json.dumps({"systems": metrics, "diagnostics": diagnostics}, indent=2))


if __name__ == "__main__":
    main()
