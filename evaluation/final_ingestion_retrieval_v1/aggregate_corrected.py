"""Post-freeze evaluator erratum: score actual answers, not gold/evidence leakage.

The frozen rubric, product, raw model outputs, reviewer prompt, and first-pass
aggregator are untouched. See EVALUATOR_ERRATUM.md for the correction policy.
"""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

from aggregate import CITE_RE, HERE, classify_failure, expected_sources, load_jsonl, mean, source_ranks

NUMBER_RE = re.compile(r"(?<![\w])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
ID_RE = re.compile(r"(?:KB|FIG|CALC)\d+")
GENERIC_STOP = re.compile(r"^근거 자료에서 필요한 관계식이나 입력값을 확인하지 못해 수치 결과를 계산하거나 추정하지 않았습니다\.$")
META_NONANSWER = re.compile(r"(?:설명|답변|기술적 설명)(?:이|가)?\s*(?:포함되어야|제공되어야|제시되어야|필요합니다)")


def answer_text(system: str, raw: dict) -> str:
    return ((raw.get("response") or {}).get("final_answer") if system == "agent"
            else raw.get("answer")) or ""


def value_match(answer: str, required: list[dict]) -> bool:
    """A required numeric result must appear in the actual final answer."""
    numbers = [float(item.replace(",", "")) for item in NUMBER_RE.findall(answer)]
    for spec in required:
        if "value" in spec:
            target = float(spec["value"])
            tolerance = float(spec.get("tolerance", 0))
            if not any(math.isclose(value, target, abs_tol=tolerance + 1e-8, rel_tol=0)
                       for value in numbers):
                return False
        elif "min" in spec and "max" in spec:
            if not all(any(math.isclose(value, target, abs_tol=1e-8, rel_tol=0)
                           for value in numbers)
                       for target in (float(spec["min"]), float(spec["max"]))):
                return False
    return True


def equation_constants_match(answer: str, equation: str | None) -> bool:
    if not equation:
        return True
    # A source-specific coefficient may not be silently exchanged for a nearby
    # textbook conversion constant. Trivial integer coefficients are reviewed
    # semantically by the frozen judge, rather than matched against prose.
    constants = [value for value in NUMBER_RE.findall(equation)
                 if "." in value and float(value) not in (0, 1)]
    return all(value in answer for value in constants)


def citation_supported(value: object, answer: str, valid_ids: set[str]) -> bool:
    if value is True:
        return bool(CITE_RE.search(answer))
    if value is False or value is None:
        return False
    ids = ID_RE.findall(" ".join(map(str, value)) if isinstance(value, list) else str(value))
    return bool(ids) and all(item in valid_ids and item in CITE_RE.findall(answer) for item in ids)


def score_row(task: dict, system: str, raw: dict, review: dict) -> dict:
    verdict = (review.get("review") or {}).get("parsed") or {}
    answer = answer_text(system, raw).strip()
    response = raw.get("response") or {}
    checks = {item.get("index"): item for item in verdict.get("claim_checks", [])
              if isinstance(item, dict) and isinstance(item.get("index"), int)}
    claims = [checks.get(index, {}) for index in range(len(task["required_claims"]))]
    answer_available = bool(answer) and not GENERIC_STOP.fullmatch(answer) and not META_NONANSWER.search(answer)
    refusal = bool(verdict.get("refusal") is True or not answer or GENERIC_STOP.fullmatch(answer))
    enumerated_count = bool(task["task_type"] == "document_specific_fact" and
                            len(task["required_values"]) == 1 and
                            task["required_values"][0].get("value") == len(task["required_claims"]) and
                            len(task["required_claims"]) > 1)
    numeric = (bool((verdict.get("numeric_and_units_correct") is True and
                     value_match(answer, task["required_values"])) or
                    (enumerated_count and answer_available and
                     all(checks.get(index, {}).get("answer_correct") is True and
                         checks.get(index, {}).get("answer_present") is True
                         for index in range(len(task["required_claims"])))))
               if task["required_values"] else None)
    equation = (bool(verdict.get("equation_correct") is True and
                     equation_constants_match(answer, task.get("acceptable_equation")))
                if task.get("acceptable_equation") else None)
    figure = bool(verdict.get("figure_correct") is True) if task["task_type"] == "figure_understanding" else None
    calc_applicable = task["task_type"] == "calculation" or task["required_evidence_type"] in {
        "KB_FORMULA_AND_VALIDATED_CALC", "KB_FORMULA_AND_VALIDATED_SIMULATION",
        "USER_FACT_AND_VALIDATED_CALC"}
    calculation = bool(verdict.get("calculation_correct") is True and numeric is not False and
                       equation is not False) if calc_applicable else None
    claim_ok = [bool(answer_available and item.get("answer_present") is True and
                     item.get("answer_correct") is True) for item in claims]
    claim_coverage = mean(claim_ok)
    # A closed-book answer may explicitly disclaim access to the private book
    # and still provide all substantive claims. That caveat is not a refusal.
    if system == "baseline" and answer_available and all(claim_ok):
        refusal = False
    unsupported = verdict.get("unsupported_new_claims") or 0
    # The closed-book comparator never received evidence. The judge sometimes
    # called every otherwise-correct claim "unsupported" solely for that reason,
    # contrary to the frozen distinction between truth and grounding.
    reason = (verdict.get("brief_reason") or "").lower()
    evidence_only_reason = any(phrase in reason for phrase in (
        "no evidence", "no actual evidence", "no supporting evidence",
        "fails to cite any evidence", "provides no supporting evidence",
        "not supported by any evidence"))
    if (system == "baseline" and all(claim_ok) and unsupported and evidence_only_reason and
        not any(phrase in reason for phrase in ("wrong", "incorrect", "cannot confirm"))):
        unsupported = 0
    hallucination = unsupported > 0
    valid_calcs = sum(item.get("validation_passed") is True for item in response.get("computations", []))
    calc_required = task["required_evidence_type"] in {
        "KB_FORMULA_AND_VALIDATED_CALC", "KB_FORMULA_AND_VALIDATED_SIMULATION",
        "USER_FACT_AND_VALIDATED_CALC"}
    if system == "agent" and calc_required and valid_calcs == 0:
        calculation = False
    if task["answerable"]:
        accuracy = bool(all(claim_ok) and not refusal and not hallucination and
                        numeric is not False and equation is not False and
                        figure is not False and calculation is not False and
                        (task["task_type"] != "false_premise" or
                         verdict.get("explicit_premise_correction") is True))
    else:
        accuracy = bool(refusal and not hallucination and answer)
        claim_coverage = 1.0 if accuracy else 0.0
    ids = {item.get("evidence_id") for item in response.get("internal_sources", []) + response.get("figures", [])}
    ids |= {item.get("computation_id") for item in response.get("computations", [])}
    cited = CITE_RE.findall(answer)
    citation_ids_correct = all(item in ids for item in cited) if cited else None
    evidence_coverage = mean([item.get("evidence_support") is True for item in claims]) if claims else None
    citation_semantic = (mean([citation_supported(item.get("citation_support"), answer, ids)
                               for item in claims]) if claims else None)
    grounded = (bool(accuracy and evidence_coverage == 1 and citation_semantic == 1 and
                     citation_ids_correct is True and (not calc_required or valid_calcs > 0))
                if system == "agent" and task["answerable"] else None)
    return {
        "question_id": task["question_id"], "system": system, "category": task["task_type"],
        "domain": task["domain"], "answerable": task["answerable"],
        "accuracy": accuracy, "grounded_accuracy": grounded, "claim_coverage": claim_coverage,
        "evidence_coverage": evidence_coverage if system == "agent" else None,
        "citation_semantic_support": citation_semantic if system == "agent" else None,
        "citation_id_correctness": citation_ids_correct if system == "agent" else None,
        "numeric_accuracy": numeric, "equation_accuracy": equation, "figure_accuracy": figure,
        "calculation_accuracy": calculation,
        "task_completed": bool(accuracy and (not calc_required or system != "agent" or valid_calcs > 0)),
        "correct_refusal": bool(accuracy) if not task["answerable"] else None,
        "over_refusal": bool(refusal) if system == "agent" and task["answerable"] else None,
        "hallucination": hallucination, "unsupported_new_claim_count": unsupported,
        "false_premise_corrected": (bool(verdict.get("explicit_premise_correction") is True and accuracy)
                                    if task["task_type"] == "false_premise" else None),
        "run_id": response.get("run_id"), "run_status": response.get("run_status"),
        "agent_self_status": response.get("status"), "iterations": response.get("iterations_completed"),
        "goal_coverage_percent": response.get("goal_coverage_percent"),
        "validated_calculations": valid_calcs, "python_calls": response.get("python_calls_total"),
        "latency_seconds": raw.get("elapsed_seconds"), "reviewer_error": review.get("error"),
        "reviewer_reason": verdict.get("brief_reason"),
        "answer_gate": "substantive" if answer_available else "empty_or_generic_stop_or_meta",
    }


def root_cause(task: dict, score: dict, raw: dict, probe: dict) -> str:
    """Separate a terminal refusal symptom from observable retrieval/execution cause."""
    response = raw.get("response") or {}
    if raw.get("error") or response.get("run_status") == "failed":
        return "runtime/tool failure"
    if score["hallucination"]:
        return "hallucination"
    if task["task_type"] == "figure_understanding":
        return "Figure grounding failure"
    gold = expected_sources(task)
    if gold:
        selected = source_ranks(task, response.get("internal_sources", []) + response.get("figures", []))
        diagnostic = source_ranks(task, (probe.get("response") or {}).get("internal_sources", []))
        if any(rank is None for rank in diagnostic):
            return "retrieval miss in question-only probe"
        if any(rank is None for rank in selected):
            return "evidence selection / query divergence"
    if task["required_evidence_type"] in {
        "KB_FORMULA_AND_VALIDATED_CALC", "KB_FORMULA_AND_VALIDATED_SIMULATION",
        "USER_FACT_AND_VALIDATED_CALC"} and not score["validated_calculations"]:
        return "calculation failure"
    if score["over_refusal"]:
        return "over-refusal with selected evidence"
    return "synthesis failure"


def main() -> None:
    tasks = json.loads((HERE / "rubric.json").read_text(encoding="utf-8"))["tasks"]
    agent = load_jsonl("agent_raw.jsonl")
    baseline = load_jsonl("baseline_raw.jsonl")
    probes = load_jsonl("retrieval_probe_raw.jsonl")
    retrieval_rows = json.loads((HERE / "retrieval_metrics.json").read_text(encoding="utf-8"))["rows"]
    reviews = load_jsonl("semantic_review_raw.jsonl", lambda row: (row["system"], row["question_id"]))
    qc = json.loads((HERE / "reviewer_quality_control.json").read_text(encoding="utf-8"))
    qc_by_key = {(item["system"], item["question_id"]): item for item in qc["entries"]}
    rows = []
    failures = []
    for task in tasks:
        key = task["question_id"]
        for system, raw in (("agent", agent[key]), ("baseline", baseline[key])):
            row = score_row(task, system, raw, reviews[(system, key)])
            correction = qc_by_key.get((system, key))
            if correction:
                for field in ("accuracy", "hallucination", "false_premise_corrected"):
                    if field in correction:
                        row[field] = correction[field]
                if row["hallucination"]:
                    row["unsupported_new_claim_count"] = max(1, row["unsupported_new_claim_count"])
                if row["accuracy"] is False:
                    row["task_completed"] = False
                    if row["grounded_accuracy"] is not None:
                        row["grounded_accuracy"] = False
                row["quality_control_reason"] = correction["reason"]
            else:
                row["quality_control_reason"] = None
            rows.append(row)
            if system == "agent" and not row["accuracy"]:
                probe = probes.get(key, {})
                failures.append({"question_id": key, "category": task["task_type"],
                                 "primary_cause": root_cause(task, row, raw, probe),
                                 "terminal_symptom": classify_failure(task, row, raw, probe),
                                 "reviewer_reason": row["reviewer_reason"],
                                 "run_status": row["run_status"],
                                 "gold_page_ranks": source_ranks(task, (probe.get("response") or {}).get("internal_sources", []))})
    systems = {}
    for system in ("agent", "baseline"):
        part = [row for row in rows if row["system"] == system]
        def avg(field: str) -> float | None:
            return mean([row[field] for row in part if row[field] is not None])
        latencies = sorted(row["latency_seconds"] for row in part if row["latency_seconds"] is not None)
        systems[system] = {
            "n": len(part), "answer_accuracy": avg("accuracy"),
            "grounded_answer_rate_answerable_only": avg("grounded_accuracy"),
            "claim_coverage": avg("claim_coverage"), "evidence_coverage": avg("evidence_coverage"),
            "citation_semantic_support": avg("citation_semantic_support"),
            "citation_id_correctness": avg("citation_id_correctness"),
            "numeric_accuracy": avg("numeric_accuracy"), "equation_accuracy": avg("equation_accuracy"),
            "figure_accuracy": avg("figure_accuracy"), "calculation_accuracy": avg("calculation_accuracy"),
            "correct_refusal_rate": avg("correct_refusal"), "over_refusal_rate": avg("over_refusal"),
            "hallucination_rate": avg("hallucination"),
            "goal_task_completion_rate": mean([row["task_completed"] for row in part
                                               if row["category"] == "goal_style_multi_step"]),
            "average_iterations": avg("iterations"), "average_goal_coverage_percent": avg("goal_coverage_percent"),
            "median_goal_coverage_percent": (statistics.median(row["goal_coverage_percent"] for row in part
                                               if row["goal_coverage_percent"] is not None) if system == "agent" else None),
            "mean_latency_seconds": mean(latencies),
            "median_latency_seconds": round(statistics.median(latencies), 3) if latencies else None,
            "p95_latency_seconds": latencies[min(len(latencies)-1, int(0.95*len(latencies)))] if latencies else None,
            "reviewer_error_count": sum(bool(row["reviewer_error"]) for row in part),
        }
    categories = {}
    for category in sorted({task["task_type"] for task in tasks}):
        categories[category] = {}
        for system in ("agent", "baseline"):
            part = [row for row in rows if row["category"] == category and row["system"] == system]
            categories[category][system] = {"n": len(part), "answer_accuracy": mean([row["accuracy"] for row in part]),
                "grounded_accuracy": mean([row["grounded_accuracy"] for row in part
                                            if row["grounded_accuracy"] is not None]),
                "refusal_count": sum(row["over_refusal"] is True for row in part),
                "hit_at_5": (mean([item["hit_at_5"] for item in retrieval_rows
                                   if item["task_type"] == category]) if system == "agent" else None)}
    (HERE / "answer_metrics.json").write_text(json.dumps({"systems": systems,
        "scoring_policy": "SCORING_POLICY.md + EVALUATOR_ERRATUM.md", "rows": rows}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (HERE / "category_metrics.json").write_text(json.dumps(categories, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (HERE / "failure_analysis.json").write_text(json.dumps({"failure_count": len(failures),
        "cause_counts": dict(Counter(row["primary_cause"] for row in failures)), "rows": failures},
        ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    for system, source in (("agent", agent), ("baseline", baseline)):
        exported = []
        for task in tasks:
            key = task["question_id"]
            raw = source[key]
            response = raw.get("response") or {}
            selected = response.get("internal_sources", []) + response.get("figures", [])
            exported.append({
                "question_id": key, "question": task["question"], "system": system,
                "model_id": ("qwen3:8b" if system == "agent" else raw.get("model_id")),
                "route": ("POST /api/research/goal-runs/from-message" if system == "agent"
                          else "OpenAI Responses closed-book"),
                "retrieval_query": None,
                "retrieval_query_note": ("not exposed by frozen product response" if system == "agent"
                                         else "no retrieval"),
                "run_id": response.get("run_id"), "run_status": response.get("run_status"),
                "stop_reason": response.get("stop_reason"),
                "iterations_completed": response.get("iterations_completed"),
                "goal_coverage_percent": response.get("goal_coverage_percent"),
                "selected_evidence": [{"evidence_id": item.get("evidence_id"),
                    "document": item.get("document"), "page": item.get("page"),
                    "chunk_id": item.get("chunk_id"), "score": item.get("score"),
                    "evidence_type": "figure" if item in response.get("figures", []) else "KB"}
                    for item in selected],
                "final_answer": answer_text(system, raw),
                "citations": CITE_RE.findall(answer_text(system, raw)),
                "refusal_or_waiting": bool(response.get("run_status") == "waiting_for_user_input" or
                                           GENERIC_STOP.fullmatch(answer_text(system, raw).strip())),
                "validated_calculations": sum(item.get("validation_passed") is True
                                               for item in response.get("computations", [])),
                "latency_seconds": raw.get("elapsed_seconds"),
            })
        (HERE / f"{system}_results.json").write_text(json.dumps(exported, ensure_ascii=False, indent=2)+"\n",
                                                        encoding="utf-8")
    with (HERE / "final_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    poster = [{"Metric": label, "Petroleum Agent": systems["agent"][key],
               "ChatGPT closed-book": systems["baseline"][key]} for label, key in (
        ("Answer Accuracy", "answer_accuracy"), ("Numeric Accuracy", "numeric_accuracy"),
        ("Equation Accuracy", "equation_accuracy"), ("Correct Refusal", "correct_refusal_rate"),
        ("Hallucination Rate", "hallucination_rate"), ("Median Latency (s)", "median_latency_seconds"))]
    with (HERE / "poster_metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(poster[0]))
        writer.writeheader()
        writer.writerows(poster)
    print(json.dumps({"systems": systems, "failures": len(failures)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
