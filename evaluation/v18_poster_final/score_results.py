"""Frozen-rubric scoring, paired uncertainty, and poster tables."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
import statistics
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BENCHMARK = json.loads((ROOT / "benchmark.json").read_text(encoding="utf-8"))
TASKS = BENCHMARK["tasks"]
SYSTEMS = ["qwen_closed_book", "v17_agent", "v18_agent", "gpt_reference"]
NUMERIC_CATEGORIES = {"direct_calculation", "user_formula", "kb_formula"}
SOURCE_CATEGORIES = {"knowledge_qa", "multi_claim_reasoning", "kb_formula", "false_premise"}
NUMBER = re.compile(r"(?<![A-Za-z0-9_])[-+]?(?:\d+(?:[.,]\d+)?|\.\d+)(?![A-Za-z0-9_])")
CITATION = re.compile(r"\[(?:KB|FIG)\d+\]")
EXPECTED_OPERANDS = {
    "V18P-011": ["initial usable volume", "final usable volume"],
    "V18P-012": ["first well rate", "second well rate"],
    "V18P-013": ["initial ROP", "final ROP"],
    "V18P-014": ["four temperature readings"],
    "V18P-015": ["rho", "Q"],
    "V18P-016": ["recovered_volume", "injected_volume"],
    "V18P-017": ["delta_p", "Q"],
    "V18P-018": ["MW", "Pd", "D"],
    "V18P-019": ["Bo", "Bg", "Rsb", "Rs"],
    "V18P-020": ["a", "phi", "m"],
}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(name: str, value: object) -> None:
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    with (ROOT / name).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
        writer.writeheader()
        writer.writerows(rows)


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    position = (len(ordered) - 1) * p
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def numeric_match(answer: str, target: dict) -> dict:
    """Compare visibly printed numbers/units against a frozen target."""
    value = float(target["value"])
    unit = target["unit"]
    tolerance = float(target["tolerance"])
    matches = []
    for hit in NUMBER.finditer(answer):
        try:
            observed = float(hit.group().replace(",", ""))
        except ValueError:
            continue
        nearby = answer[max(0, hit.start() - 12):min(len(answer), hit.end() + 36)]
        if unit == "dimensionless" and "%" in nearby and math.isclose(observed / 100, value, abs_tol=tolerance):
            matches.append((observed, True, nearby))
        elif math.isclose(observed, value, abs_tol=tolerance):
            normalized = nearby.casefold().replace("³", "3").replace("㎥", "m3")
            # Closed-book systems may print an equivalent unit in LaTeX.
            normalized = re.sub(r"\\(?:text|mathrm)\{([^{}]*)\}", r"\1", normalized)
            normalized = normalized.replace("\\circ", "°").replace("\\,", " ").replace("^", "")
            if unit == "dimensionless":
                unit_ok = not bool(re.search(r"\b(?:psi|kpa|mpa|ppg|kw|m3|kg/s|m/s|bbl/d|stb/d)\b", normalized))
            elif unit == "%":
                unit_ok = "%" in nearby or "percent" in normalized or "퍼센트" in normalized
            elif unit == "°C":
                unit_ok = "°c" in normalized or "celsius" in normalized or "섭씨" in normalized
            else:
                aliases = {"m3": ["m3", "m^3"], "rb/STB": ["rb/stb", "reservoir bbl/stb"]}
                unit_ok = any(alias in normalized for alias in aliases.get(unit, [unit.casefold()]))
            matches.append((observed, unit_ok, nearby))
    return {"value_correct": bool(matches), "unit_correct": any(m[1] for m in matches),
            "matching_text": next((m[2] for m in matches if m[1]), matches[0][2] if matches else "")}


def numeric_score(task: dict, answer: str) -> dict:
    targets = [numeric_match(answer, target) for target in task.get("numeric_gold", [])]
    return {"numeric_value_correct": bool(targets) and all(t["value_correct"] for t in targets),
            "unit_correct": bool(targets) and all(t["unit_correct"] for t in targets),
            "final_numeric_correct": bool(targets) and all(t["value_correct"] and t["unit_correct"] for t in targets),
            "numeric_evidence": [t["matching_text"] for t in targets]}


def actions(run: dict) -> list[str]:
    return [str(a.get("action_type", "")).lower() for a in run.get("action_history", [])]


def agent_diag(task: dict, run: dict) -> dict:
    telemetry = run.get("telemetry") or {}
    history = actions(run)
    computations = run.get("computations") or []
    valid = [item for item in computations if item.get("validation_passed")]
    sources = run.get("internal_sources") or []
    expected = task.get("source_document")
    page = task.get("source_page")
    exact_sources = [s for s in sources if s.get("document") == expected and s.get("page") == page]
    formula_chunk = task.get("supporting_spans", [{}])[0].get("chunk_id") if task.get("supporting_spans") else None
    span_sources = [s for s in exact_sources if s.get("chunk_id") == formula_chunk]
    formula_ids = {sid for c in valid for sid in (
        (c.get("formula_source_ids") or []) + (c.get("formula_evidence_ids") or [])
        + ([c["formula_source_id"]] if c.get("formula_source_id") else [])
    )}
    formula_source_correct = any(s.get("evidence_id") in formula_ids for s in span_sources)
    if task["category"] == "kb_formula":
        route_correct = "retrieve" in history and "calculate" in history and history.index("retrieve") < history.index("calculate")
    elif task["category"] in {"direct_calculation", "user_formula"}:
        route_correct = bool(history) and history[0] in {"calculate", "simulate"}
    else:
        route_correct = None
    return {
        "intent_route": telemetry.get("intent_route"),
        "route_correct": route_correct,
        "required_operands": EXPECTED_OPERANDS.get(task["task_id"], []),
        "bound_operands": telemetry.get("formula_variables_bound") or telemetry.get("operands_bound"),
        "operands_complete": bool(telemetry.get("operands_bound", 0) >= telemetry.get("operands_expected", 1)),
        "operand_validation_passed": bool(telemetry.get("operand_validation_passed")),
        "formula_required": task["category"] in {"user_formula", "kb_formula"},
        "formula_selected": bool(telemetry.get("formula_selected")),
        "formula_source_verified": bool(telemetry.get("formula_source_verified")),
        "formula_ready": bool(telemetry.get("formula_ready")),
        "calculation_ready": bool(telemetry.get("calculation_ready")),
        "calculation_executed": bool(telemetry.get("calculation_executed") or run.get("python_calls_total", 0)),
        "calculation_validated": bool(telemetry.get("calculation_validated") or valid),
        "deterministic_calc_finalizer_used": bool(telemetry.get("deterministic_calc_finalizer_used")),
        "retrieval_success": bool(sources),
        "correct_source_page_retrieved": bool(exact_sources),
        "correct_formula_span_retrieved": bool(span_sources),
        "formula_candidate_selected": bool((telemetry.get("formula") or {}).get("selected_formula_id")),
        "formula_source_correct": formula_source_correct,
        "variables_bound": bool(telemetry.get("operand_validation_passed")),
        "claim_support_checked": bool(telemetry.get("claim_support_checked")),
        "detected_claim_count": telemetry.get("required_claim_count", 0),
        "supported_claim_count": telemetry.get("supported_claim_count", 0),
        "partial_claim_count": telemetry.get("partially_supported_claim_count", 0),
        "grounded_fast_path_used": bool(telemetry.get("grounded_fast_path_used")),
        "exact_span_validation_passed": bool(telemetry.get("exact_span_validation_passed")),
        "fallback_used": bool(telemetry.get("extractive_fallback_used")),
        "action_sequence": history,
        "timing": run.get("timing") or {},
    }


def bootstrap(rows: list[dict], a: str, b: str, field: str, numeric_only: bool = False) -> dict:
    paired = [r for r in rows if (not numeric_only or r["category"] in NUMERIC_CATEGORIES)]
    delta = [float(r[b][field]) - float(r[a][field]) for r in paired]
    rng = random.Random(20261012)
    means = [statistics.fmean(delta[rng.randrange(len(delta))] for _ in delta) for _ in range(10000)]
    return {"difference": statistics.fmean(delta), "ci95_low": percentile(means, 0.025),
            "ci95_high": percentile(means, 0.975), "n": len(delta), "resamples": 10000,
            "seed": 20261012}


def main() -> None:
    receipt = read(ROOT / "freeze_receipt.json")
    benchmark_hash = hashlib.sha256((ROOT / "benchmark.json").read_bytes()).hexdigest()
    if benchmark_hash != receipt["benchmark_sha256"]:
        raise RuntimeError("frozen benchmark SHA256 changed")
    rows = []
    for task in TASKS:
        task_id = task["task_id"]
        judge = read(ROOT / "raw" / "judge" / f"{task_id}.json")
        if judge.get("status") != "completed":
            raise RuntimeError(f"{task_id}: judge incomplete")
        scored = {"task_id": task_id, "category": task["category"], "domain": task["domain"],
                  "answerable": task["answerable"], "numeric": task["category"] in NUMERIC_CATEGORIES,
                  "cross_language": bool(task.get("supporting_spans")) and bool(re.search(r"[가-힣]", task["question"]))}
        for label, system in judge["anonymous_labels"].items():
            raw = read(ROOT / "raw" / system / f"{task_id}.json")
            if raw.get("status") != "completed" or raw.get("attempt_count") != 1:
                raise RuntimeError(f"{task_id}: {system} not one completed attempt")
            verdict = judge["verdict"]["responses"][label]
            claims = verdict["claim_scores"]
            if len(claims) != len(task["required_claims"]) or any(x not in (0, 0.5, 1) for x in claims):
                raise RuntimeError(f"{task_id}: {system} invalid claim scores")
            answer = raw.get("answer", "")
            numeric = numeric_score(task, answer) if scored["numeric"] else {}
            diag = agent_diag(task, raw["run"]) if system.endswith("_agent") else {}
            goal = bool(verdict["goal_success"])
            if scored["numeric"]:
                goal = goal and numeric["final_numeric_correct"]
                if diag:
                    goal = goal and diag["route_correct"] and diag["calculation_validated"]
                    if task["category"] == "kb_formula":
                        goal = goal and diag["formula_source_verified"] and diag["formula_source_correct"]
            if diag and task["category"] in SOURCE_CATEGORIES:
                goal = goal and verdict.get("citation_semantic_support") is True
            hallucination_free = bool(verdict["hallucination_free"])
            if scored["numeric"] and numeric["numeric_value_correct"] is False and verdict.get("final_numeric_outputs"):
                hallucination_free = False
            waiting_for_supplied_input = bool(
                system.endswith("_agent") and task["answerable"]
                and raw.get("run_status") == "waiting_for_user_input"
            )
            error_labels = list(verdict.get("error_labels", []))
            if waiting_for_supplied_input and "incorrect_refusal" not in error_labels:
                error_labels.append("incorrect_refusal")
            scored[system] = {
                "goal_success": bool(goal), "claim_coverage": statistics.fmean(claims),
                "claim_scores": claims, "hallucination_free": hallucination_free,
                "error_labels": error_labels,
                # A waiting run's public response is its clarification_question, not final_answer.
                # The raw final_answer is empty in that state, so the judge could not see the
                # question. Under the frozen policy, an answerable task that pauses for more
                # input is an unnecessary refusal even if the semantic verdict missed it.
                "unnecessary_refusal": (
                    bool(verdict.get("unnecessary_refusal"))
                    or waiting_for_supplied_input
                ) if task["answerable"] else False,
                "unnecessary_refusal_basis": (
                    "frozen_policy_waiting_on_answerable_task" if waiting_for_supplied_input
                    else "semantic_reviewer" if verdict.get("unnecessary_refusal") else None
                ),
                "citation_semantic_support": verdict.get("citation_semantic_support"),
                "relevant_evidence_retrieved": verdict.get("relevant_evidence_retrieved") if diag else None,
                "latency_seconds": raw.get("latency_seconds"), "answer": answer,
                "run_id": raw.get("run_id"), "run_status": raw.get("run_status"),
                "numeric": numeric, "diagnostics": diag,
                "judge_rationale": verdict.get("brief_rationale", ""),
            }
        if set(judge["anonymous_labels"].values()) != set(SYSTEMS):
            raise RuntimeError(f"{task_id}: anonymous labels do not cover all systems")
        rows.append(scored)
    write_json("scored_rows.json", rows)

    metrics = {}
    for system in SYSTEMS:
        vals = [r[system] for r in rows]
        nums = [r[system]["numeric"]["final_numeric_correct"] for r in rows if r["numeric"]]
        latencies = [v["latency_seconds"] for v in vals]
        metrics[system] = {
            "task_count": len(vals), "goal_success": statistics.fmean(v["goal_success"] for v in vals),
            "claim_coverage": statistics.fmean(v["claim_coverage"] for v in vals),
            "hallucination_free": statistics.fmean(v["hallucination_free"] for v in vals),
            "numerical_accuracy": statistics.fmean(nums), "numeric_task_count": len(nums),
            "latency_mean_seconds": statistics.fmean(latencies),
            "latency_median_seconds": statistics.median(latencies),
            "latency_p95_seconds": percentile(latencies, 0.95),
        }
    comparisons = {}
    for a, b, label in (("v17_agent", "v18_agent", "v18_minus_v17"),
                        ("qwen_closed_book", "v18_agent", "v18_minus_qwen")):
        comparisons[label] = {
            field: bootstrap(rows, a, b, field, field == "numeric.final_numeric_correct")
            for field in ("goal_success", "claim_coverage", "hallucination_free")
        }
        numeric_rows = [r for r in rows if r["numeric"]]
        delta = [float(r[b]["numeric"]["final_numeric_correct"]) - float(r[a]["numeric"]["final_numeric_correct"]) for r in numeric_rows]
        rng = random.Random(20261012)
        samples = [statistics.fmean(delta[rng.randrange(len(delta))] for _ in delta) for _ in range(10000)]
        comparisons[label]["numerical_accuracy"] = {"difference": statistics.fmean(delta),
            "ci95_low": percentile(samples, 0.025), "ci95_high": percentile(samples, 0.975),
            "n": 10, "resamples": 10000, "seed": 20261012}
    write_json("final_metrics.json", {"systems": metrics, "comparisons": comparisons})

    flat = []
    for r in rows:
        for system in SYSTEMS:
            v = r[system]
            flat.append({"task_id": r["task_id"], "category": r["category"], "domain": r["domain"],
                         "system": system, "goal_success": v["goal_success"], "claim_coverage": v["claim_coverage"],
                         "hallucination_free": v["hallucination_free"], "numeric_value_correct": v["numeric"].get("numeric_value_correct"),
                         "unit_correct": v["numeric"].get("unit_correct"),
                         "final_numeric_correct": v["numeric"].get("final_numeric_correct"),
                         "unnecessary_refusal": v["unnecessary_refusal"], "latency_seconds": v["latency_seconds"]})
    write_csv("final_results.csv", flat)
    write_csv("poster_v17_v18_effect.csv", [{"metric": field, "v17_percent": 100*metrics["v17_agent"][field],
        "v18_percent": 100*metrics["v18_agent"][field], "difference_pp": 100*comparisons["v18_minus_v17"][field]["difference"],
        "ci95_low_pp": 100*comparisons["v18_minus_v17"][field]["ci95_low"],
        "ci95_high_pp": 100*comparisons["v18_minus_v17"][field]["ci95_high"]}
        for field in ("goal_success", "claim_coverage", "hallucination_free", "numerical_accuracy")])
    write_csv("poster_rag_effect.csv", [{"metric": field, "qwen_percent": 100*metrics["qwen_closed_book"][field],
        "v18_percent": 100*metrics["v18_agent"][field], "difference_pp": 100*comparisons["v18_minus_qwen"][field]["difference"],
        "ci95_low_pp": 100*comparisons["v18_minus_qwen"][field]["ci95_low"],
        "ci95_high_pp": 100*comparisons["v18_minus_qwen"][field]["ci95_high"]}
        for field in ("goal_success", "claim_coverage", "hallucination_free", "numerical_accuracy")])
    write_csv("poster_reference_metrics.csv", [{"system": system, **metrics[system]} for system in SYSTEMS])
    groups = {"Knowledge": {"knowledge_qa"}, "Reasoning": {"multi_claim_reasoning"},
              "Calculation": NUMERIC_CATEGORIES, "Safety": {"false_premise", "unanswerable"}}
    write_csv("poster_category_metrics.csv", [{"category": group, "system": system, "n": len(group_rows),
        "goal_success": statistics.fmean(r[system]["goal_success"] for r in group_rows)}
        for group, categories in groups.items() for group_rows in [[r for r in rows if r["category"] in categories]]
        for system in SYSTEMS])
    numeric_pipeline = [{"task_id": r["task_id"], **{k: v for k, v in r["v18_agent"]["diagnostics"].items()
        if k not in ("timing", "action_sequence")}, **r["v18_agent"]["numeric"]}
        for r in rows if r["numeric"]]
    write_csv("poster_numeric_pipeline.csv", numeric_pipeline)
    write_csv("poster_kb_formula_pipeline.csv", [{"task_id": r["task_id"],
        **{k: r["v18_agent"]["diagnostics"].get(k) for k in (
            "retrieval_success", "correct_source_page_retrieved", "correct_formula_span_retrieved",
            "formula_candidate_selected", "formula_source_verified", "formula_source_correct",
            "variables_bound", "calculation_executed", "calculation_validated", "route_correct")},
        "numeric_correct": r["v18_agent"]["numeric"].get("final_numeric_correct")}
        for r in rows if r["category"] == "kb_formula"])
    write_csv("poster_refusal_analysis.csv", [{"task_id": r["task_id"], "answerable": r["answerable"],
        "v17_unnecessary_refusal": r["v17_agent"]["unnecessary_refusal"],
        "v18_unnecessary_refusal": r["v18_agent"]["unnecessary_refusal"],
        "v17_relevant_evidence": r["v17_agent"]["relevant_evidence_retrieved"],
        "v18_relevant_evidence": r["v18_agent"]["relevant_evidence_retrieved"],
        "v17_goal_success": r["v17_agent"]["goal_success"],
        "v18_goal_success": r["v18_agent"]["goal_success"]} for r in rows])
    write_csv("poster_cross_language.csv", [{"task_id": r["task_id"],
        "v17_goal_success": r["v17_agent"]["goal_success"], "v18_goal_success": r["v18_agent"]["goal_success"],
        "v17_unnecessary_refusal": r["v17_agent"]["unnecessary_refusal"],
        "v18_unnecessary_refusal": r["v18_agent"]["unnecessary_refusal"],
        "v18_support_checked": r["v18_agent"]["diagnostics"].get("claim_support_checked"),
        "v18_exact_span_passed": r["v18_agent"]["diagnostics"].get("exact_span_validation_passed"),
        "v18_grounded_fast_path": r["v18_agent"]["diagnostics"].get("grounded_fast_path_used"),
        "v18_fallback_used": r["v18_agent"]["diagnostics"].get("fallback_used")}
        for r in rows if r["cross_language"]])
    write_csv("poster_citation_support.csv", [{"system": system,
        "task_id": r["task_id"], "citation_links": len(CITATION.findall(r[system]["answer"])),
        "citation_semantic_support": r[system]["citation_semantic_support"],
        "exact_span_validation_passed": r[system]["diagnostics"].get("exact_span_validation_passed")}
        for r in rows for system in ("v17_agent", "v18_agent")])
    diagnostic_rows = []
    for system in ("v17_agent", "v18_agent"):
        vals = [r[system] for r in rows]
        relevant = [v for v in vals if v["relevant_evidence_retrieved"] is True]
        diagnostic_rows.append({"system": system,
            "unnecessary_refusal_count": sum(v["unnecessary_refusal"] for v in vals),
            "unnecessary_refusal_rate_answerable": sum(v["unnecessary_refusal"] for v in vals)/sum(r["answerable"] for r in rows),
            "unnecessary_refusal_rate_all": sum(v["unnecessary_refusal"] for v in vals)/24,
            "relevant_evidence_count": len(relevant),
            "relevant_evidence_but_failed": sum(not v["goal_success"] for v in relevant),
            "relevant_evidence_to_non_refusal": sum(not v["unnecessary_refusal"] for v in relevant),
            "relevant_evidence_to_success": sum(v["goal_success"] for v in relevant),
            "calculation_executions": sum(v["diagnostics"].get("calculation_executed", False) for v in vals if v["diagnostics"]),
            "supported_but_refused": sum(v["diagnostics"].get("supported_claim_count", 0) > 0 and v["unnecessary_refusal"] for v in vals),
            "grounded_fast_path_used": sum(v["diagnostics"].get("grounded_fast_path_used", False) for v in vals),
        })
    write_csv("poster_v18_diagnostics.csv", diagnostic_rows)
    print(json.dumps({"tasks": len(rows), "systems": metrics, "comparisons": comparisons}, indent=2))


if __name__ == "__main__":
    assert numeric_score({"numeric_gold": [{"value": 4.5, "unit": "kW", "tolerance": 0.01}]}, "P = 4.5 kW")["final_numeric_correct"]
    assert not numeric_score({"numeric_gold": [{"value": 4.5, "unit": "kW", "tolerance": 0.01}]}, "P = 4.5 psi")["final_numeric_correct"]
    main()
