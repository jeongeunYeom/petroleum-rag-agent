"""Score frozen agentic run from independent blind reviews and deterministic telemetry."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_agentic_heldout import BENCHMARK, CONDITIONS, MANIFEST, ROOT, _save, sha256


def coverage(scores: dict[str, int], criteria: list[dict]) -> float:
    required = [c["criterion_id"] for c in criteria if c["required"]]
    return sum(scores[cid] for cid in required) / (2 * len(required))


def paired_bootstrap(left: list[float], right: list[float], *, seed: int = 42, samples: int = 10000) -> dict:
    if len(left) != len(right) or not left:
        raise ValueError("Paired samples must be aligned and nonempty")
    delta = [b - a for a, b in zip(left, right)]
    rng = random.Random(seed)
    means = sorted(sum(delta[rng.randrange(len(delta))] for _ in delta) / len(delta) for _ in range(samples))
    return {"delta": statistics.mean(delta), "ci95_low": means[int(0.025 * samples)], "ci95_high": means[int(0.975 * samples) - 1], "samples": samples, "seed": seed}


def _unit_ok(actual: str, expected: str) -> bool:
    norm = lambda value: re.sub(r"\s+", "", value.lower().replace("³", "^3").replace("/d/", "/day/").replace("bbl", "stb"))
    a, e = norm(actual), norm(expected)
    if e == "dimensionless":
        return not a or a in {"dimensionless", "ratio", "unitless", "1"}
    if e == "stock-tankm^3":
        return ("m^3" in a or "m3" in a) and ("stock" in a or "st" in a or "sm" in a)
    return a == e


def _quote_supports_value(quote: str, value: float) -> bool:
    numbers = [float(v.replace(",", "")) for v in re.findall(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?", quote)]
    multipliers = [1]
    if re.search(r"\bmillion\b|\bMM\b|백만", quote, re.I):
        multipliers.append(1_000_000)
    if re.search(r"\bthousand\b|천", quote, re.I):
        multipliers.append(1_000)
    direction = -1 if re.search(r"reduc|decreas|drop|하락|감소", quote, re.I) else 1
    return any(math.isclose(n * factor * sign, value, rel_tol=1e-3, abs_tol=1e-6) for n in numbers for factor in multipliers for sign in (1, direction))


def _answer_numeric_match(answer: str, target: dict) -> dict | None:
    expected = target["value"]
    unit = target["unit"]
    for match in re.finditer(r"(?<![\w])[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?", answer):
        before = answer[max(0, match.start() - 100):match.start()]
        after = answer[match.end():match.end() + 40]
        prefix = after[:25].lower()
        if unit == "%":
            unit_present = bool(re.match(r"\s*(?:%|percent\b)", prefix))
        elif unit == "stock-tank m^3":
            unit_present = bool(re.search(r"\bm(?:\^?3|³)\b", prefix) and re.search(r"stock[- ]tank|STOIIP|OOIP|oil in place|recoverable|reserves", before + after, re.I))
        elif unit == "dimensionless":
            unit_present = bool(re.search(r"ratio|times|fold|dimensionless", before[-70:] + after, re.I))
        else:
            unit_present = bool(re.search(rf"^\s*{re.escape(unit)}\b", prefix, re.I))
        if not unit_present:
            continue
        value = float(match.group().replace(",", ""))
        if re.match(r"\s*(?:million|MM)\b", prefix, re.I):
            value *= 1_000_000
        if expected < 0 and value > 0 and re.search(r"reduc|decreas|drop|하락|감소", before[-50:] + after, re.I):
            value = -value
        if abs(value - expected) <= target["abs_tolerance"]:
            return {"value": value, "unit": unit, "quote": answer[match.start():match.end() + min(25, len(after))]}
    return None


def score_numeric(answer: str, targets: list[dict], extractions: list[dict]) -> dict[str, dict]:
    by_id = {item["target_id"]: item for item in extractions}
    results = {}
    for target in targets:
        item = by_id.get(target["target_id"], {})
        value = item.get("value")
        quote = str(item.get("quote") or "")
        actual_unit = str(item.get("unit") or "")
        if value is not None and re.search(r"\bmillion\b|\bMM\b|백만", quote, re.I) and target["value"] >= 100_000 and abs(float(value)) < 1000:
            value = float(value) * 1_000_000
        quoted = bool(quote and quote in answer and value is not None and _quote_supports_value(quote, float(value)))
        unit_ok = _unit_ok(actual_unit, target["unit"])
        passed = bool(quoted and unit_ok and abs(float(value) - target["value"]) <= target["abs_tolerance"])
        direct = _answer_numeric_match(answer, target)
        if direct is not None:
            passed = True
            value, actual_unit, quote = direct["value"], direct["unit"], direct["quote"]
            quoted = unit_ok = True
        results[target["target_id"]] = {"passed": passed, "value": value, "unit": actual_unit, "quote_verified": quoted, "unit_verified": unit_ok, "source": "answer_scan" if direct is not None else "reviewer_extraction"}
    return results


def _mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def _latency(values: list[float]) -> dict:
    ordered = sorted(values)
    return {"mean": _mean(values), "median": statistics.median(values), "p95": ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]}


def score_final(task: dict, row: dict, judgment: dict) -> dict:
    gt = task["ground_truth"]
    scores = judgment["criterion_scores"]
    expected = {c["criterion_id"] for c in task["success_criteria"]}
    if set(scores) != expected or any(v not in (0, 1, 2) for v in scores.values()):
        raise ValueError(f"{task['task_id']}: invalid criterion scores")
    answer = row["response"].get("answer", row["response"].get("final_answer", ""))
    numeric = score_numeric(answer, gt["numeric_targets"], judgment["numeric_extractions"])
    numeric_pass = all(numeric[n["target_id"]]["passed"] for n in gt["numeric_targets"] if n["critical"])
    hypothesis_required = gt["expected_hypothesis_status"] == "contradicted"
    insuff_required = gt["goal_feasibility"] == "insufficient_evidence"
    hypothesis_ok = judgment["hypothesis_handling_correct"] is True if hypothesis_required else True
    insuff_ok = judgment["insufficient_evidence_handling_correct"] is True if insuff_required else True
    ext_coverage = coverage(scores, task["success_criteria"])
    success = bool(ext_coverage == 1 and numeric_pass and not judgment["engineering_contradiction"] and hypothesis_ok and insuff_ok)
    claims = judgment["claim_results"]
    if set(claims) != {c["claim_id"] for c in gt["claims"]}:
        raise ValueError(f"{task['task_id']}: claim IDs mismatch")
    qa_flags = []
    for target in gt["numeric_targets"]:
        if not numeric[target["target_id"]]["passed"] and scores[target["criterion_id"]] == 2:
            qa_flags.append(f"reviewer_full_numeric_criterion_but_target_failed:{target['target_id']}")
    qa_flags.extend(f"reviewer_quote_gate:{criterion_id}" for criterion_id in judgment.get("quote_gated_criteria", []))
    return {
        "task_id": task["task_id"], "condition": row["condition"], "goal_success": int(success),
        "external_goal_coverage": ext_coverage, "criterion_scores": scores,
        "claim_accuracy": sum(bool(v) for v in claims.values()) / len(claims),
        "hallucination": bool(judgment["hallucination"]),
        "engineering_contradiction": bool(judgment["engineering_contradiction"]),
        "evidence_grounding": judgment["evidence_grounding"],
        "hypothesis_handling_correct": judgment["hypothesis_handling_correct"] if hypothesis_required else None,
        "impossible_goal_detected": hypothesis_ok if gt["goal_feasibility"] == "conflicts_with_evidence" else None,
        "insufficient_evidence_detected": insuff_ok if insuff_required else None,
        "numeric_targets": numeric, "numeric_pass": numeric_pass,
        "latency_seconds": row["elapsed_seconds"],
        "qa_flags": qa_flags,
    }


def score_process(task: dict, row: dict, review: dict, final: dict) -> dict:
    response = row["response"]
    iterations = response["iterations"]
    judgments = review["iteration_reviews"]
    if len(iterations) != len(judgments):
        raise ValueError(f"{task['task_id']}: process review length mismatch")
    ext = [coverage(j["criterion_scores"], task["success_criteria"]) for j in judgments]
    useful = []
    new_relevant = []
    unnecessary = []
    for idx in range(1, len(iterations)):
        relevant = bool(set(judgments[idx]["relevant_new_evidence_ids"]) & set(iterations[idx]["evidence_added"]))
        improved = ext[idx] > ext[idx - 1]
        corrected = judgments[idx - 1]["engineering_error"] and not judgments[idx]["engineering_error"]
        computed = bool(iterations[idx]["computation_ids"] and task["python_expected"] == "required")
        useful.append(bool(relevant or improved or corrected or computed))
        new_relevant.append(relevant)
        unnecessary.append(not useful[-1])
    first_scores = judgments[0]["criterion_scores"] if judgments else {}
    first_gap = bool(first_scores and (any(v == 0 for v in first_scores.values()) or judgments[0]["engineering_error"]))
    corrected = bool(judgments and (any(first_scores[cid] == 0 and final["criterion_scores"][cid] == 2 for cid in first_scores) or (judgments[0]["engineering_error"] and not final["engineering_contradiction"])))
    internal = response["goal_coverage"]
    stop_reason = response.get("stop_reason")
    no_progress_correct = None
    if stop_reason == "no_progress":
        patience = row["request"]["no_progress_patience"]
        no_progress_correct = not any(useful[-patience:])
    return {
        "task_id": task["task_id"], "condition": row["condition"],
        "iterations": len(iterations),
        "iterations_to_success": next((i + 1 for i, j in enumerate(judgments) if final["goal_success"] and coverage(j["criterion_scores"], task["success_criteria"]) == 1 and not j["engineering_error"]), None),
        "iteration_coverages": ext,
        "coverage_improvement": final["external_goal_coverage"] - ext[0] if ext else 0,
        "self_correction_opportunity": first_gap,
        "self_correction_success": corrected if first_gap else None,
        "useful_replans": sum(useful), "replans": len(useful),
        "new_evidence_replans": sum(new_relevant),
        "unnecessary_iterations": sum(unnecessary),
        "no_progress_stop_correct": no_progress_correct,
        "internal_goal_coverage": internal,
        "calibration_error": abs(internal - final["external_goal_coverage"]),
        "overconfident": response.get("status") == "achieved" and not final["goal_success"],
        "python_selected": any(it["python_requested"] for it in iterations),
        "python_calls": response["python_calls_total"],
        "python_attempts": response["python_attempts_total"],
        "python_failures": response["python_failures"],
        "validated_computations": sum(c["validation_passed"] for c in response["computations"]),
        "computation_count": len(response["computations"]),
        "calc_provenance_correct": [bool(c["validation_passed"] and c["computation_id"] in response["final_answer"] and any(s in response["final_answer"] for s in c["source_evidence_ids"])) for c in response["computations"]],
        "python_repair_opportunities": sum(c["attempts"] > 1 for c in response["computations"]),
        "python_repair_successes": sum(c["attempts"] > 1 and c["validation_passed"] for c in response["computations"]),
        "reviewer_process_notes": review["reviewer_notes"],
        "qa_flags": (["final_process_coverage_disagreement"] if ext and abs(ext[-1] - final["external_goal_coverage"]) > 0.25 else [])
        + (["reviewer_named_old_evidence_as_new"] if any(set(j["relevant_new_evidence_ids"]) - set(it["evidence_added"]) for it, j in zip(iterations, judgments)) else []),
    }


def aggregate(benchmark: dict, scored: list[dict], process: list[dict]) -> dict:
    by_condition = {condition: [r for r in scored if r["condition"] == condition] for condition in CONDITIONS}
    by_process = {condition: [r for r in process if r["condition"] == condition] for condition in CONDITIONS[1:]}
    conditions = {}
    for condition, rows in by_condition.items():
        metrics = {
            "external_goal_success_rate": _mean([r["goal_success"] for r in rows]),
            "external_goal_coverage": _mean([r["external_goal_coverage"] for r in rows]),
            "final_claim_accuracy": _mean([r["claim_accuracy"] for r in rows]),
            "hallucination_rate": _mean([r["hallucination"] for r in rows]),
            "engineering_contradiction_rate": _mean([r["engineering_contradiction"] for r in rows]),
            "evidence_grounding": _mean([r["evidence_grounding"] for r in rows]),
            "correct_hypothesis_handling": _mean([r["hypothesis_handling_correct"] for r in rows if r["hypothesis_handling_correct"] is not None]),
            "impossible_goal_detection": _mean([r["impossible_goal_detected"] for r in rows if r["impossible_goal_detected"] is not None]),
            "insufficient_evidence_detection": _mean([r["insufficient_evidence_detected"] for r in rows if r["insufficient_evidence_detected"] is not None]),
            "latency_seconds": _latency([r["latency_seconds"] for r in rows]),
        }
        if condition != "single_shot":
            p = by_process[condition]
            metrics["agentic"] = {
                "mean_iterations": _mean([r["iterations"] for r in p]),
                "iterations_to_success": _mean([r["iterations_to_success"] for r in p if r["iterations_to_success"] is not None]),
                "coverage_improvement": _mean([r["coverage_improvement"] for r in p]),
                "self_correction_rate": sum(bool(r["self_correction_success"]) for r in p) / sum(r["self_correction_opportunity"] for r in p) if any(r["self_correction_opportunity"] for r in p) else None,
                "useful_replanning_rate": sum(r["useful_replans"] for r in p) / sum(r["replans"] for r in p) if any(r["replans"] for r in p) else None,
                "new_evidence_acquisition_rate": sum(r["new_evidence_replans"] for r in p) / sum(r["replans"] for r in p) if any(r["replans"] for r in p) else None,
                "no_progress_stop_correctness": _mean([r["no_progress_stop_correct"] for r in p if r["no_progress_stop_correct"] is not None]),
                "unnecessary_iteration_rate": sum(r["unnecessary_iterations"] for r in p) / sum(r["replans"] for r in p) if any(r["replans"] for r in p) else None,
                "calibration_error": _mean([r["calibration_error"] for r in p]),
                "overconfidence_rate": _mean([r["overconfident"] for r in p]),
            }
            curve = []
            for index in range(4):
                curve.append(_mean([r["iteration_coverages"][min(index, len(r["iteration_coverages"]) - 1)] for r in p if r["iteration_coverages"]]))
            metrics["agentic"]["external_coverage_by_iteration_locf"] = curve
        conditions[condition] = metrics
    c_rows = by_condition["full_agent"]
    c_proc = by_process["full_agent"]
    by_id = {t["task_id"]: t for t in benchmark["tasks"]}
    required = [r for r in c_rows if by_id[r["task_id"]]["python_expected"] == "required"]
    selected = [r for r in c_proc if r["python_selected"]]
    required_selected = [r for r in selected if by_id[r["task_id"]]["python_expected"] == "required"]
    python = {
        "required_task_count": len(required), "selected_task_count": len(selected),
        "selection_precision": len([r for r in selected if by_id[r["task_id"]]["python_expected"] != "not_needed"]) / len(selected) if selected else None,
        "selection_recall": len(required_selected) / len(required) if required else None,
        "calculation_success_rate": sum(r["validated_computations"] > 0 for r in c_proc if by_id[r["task_id"]]["python_expected"] == "required") / len(required) if required else None,
        "validated_calc_rate": sum(r["validated_computations"] for r in c_proc) / sum(r["computation_count"] for r in c_proc) if any(r["computation_count"] for r in c_proc) else None,
        "numeric_accuracy": sum(passed["passed"] for r in required for passed in r["numeric_targets"].values()) / sum(len(r["numeric_targets"]) for r in required) if required else None,
        "calc_provenance_correctness": _mean([value for r in c_proc for value in r["calc_provenance_correct"]]),
        "repair_success_rate": sum(r["python_repair_successes"] for r in c_proc) / sum(r["python_repair_opportunities"] for r in c_proc) if any(r["python_repair_opportunities"] for r in c_proc) else None,
        "unnecessary_python_rate": sum(r["python_calls"] for r in c_proc if by_id[r["task_id"]]["python_expected"] == "not_needed") / sum(r["python_calls"] for r in c_proc) if any(r["python_calls"] for r in c_proc) else None,
    }
    paired = {}
    aligned = {condition: {r["task_id"]: r for r in rows} for condition, rows in by_condition.items()}
    ids = [t["task_id"] for t in benchmark["tasks"]]
    for left, right in (("single_shot", "goal_agent"), ("goal_agent", "full_agent"), ("single_shot", "full_agent")):
        paired[f"{right}-{left}"] = {
            "goal_success": paired_bootstrap([aligned[left][i]["goal_success"] for i in ids], [aligned[right][i]["goal_success"] for i in ids]),
            "goal_coverage": paired_bootstrap([aligned[left][i]["external_goal_coverage"] for i in ids], [aligned[right][i]["external_goal_coverage"] for i in ids]),
        }
    required_ids = [t["task_id"] for t in benchmark["tasks"] if t["python_expected"] == "required"]
    python["required_task_goal_success_B"] = _mean([aligned["goal_agent"][i]["goal_success"] for i in required_ids])
    python["required_task_goal_success_C"] = _mean([aligned["full_agent"][i]["goal_success"] for i in required_ids])
    python["required_task_numeric_accuracy_B"] = _mean([_mean([v["passed"] for v in aligned["goal_agent"][i]["numeric_targets"].values()]) for i in required_ids])
    python["required_task_numeric_accuracy_C"] = _mean([_mean([v["passed"] for v in aligned["full_agent"][i]["numeric_targets"].values()]) for i in required_ids])
    return {"benchmark_id": benchmark["benchmark_id"], "condition_metrics": conditions, "python_metrics": python, "paired_comparisons": paired, "task_scores": scored, "process_scores": process}


def _format_pct(value):
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(comparison: dict, output_root: Path, run_dir: Path, suffix: str = "") -> None:
    stem = "agentic_heldout_v1"
    _save(output_root / f"{stem}_comparison{suffix}.json", comparison)
    rows = []
    for condition, m in comparison["condition_metrics"].items():
        rows.append({"condition": condition, "goal_success": m["external_goal_success_rate"], "goal_coverage": m["external_goal_coverage"], "claim_accuracy": m["final_claim_accuracy"], "hallucination": m["hallucination_rate"], "engineering_error": m["engineering_contradiction_rate"], "evidence_grounding": m["evidence_grounding"], "latency_mean_seconds": m["latency_seconds"]["mean"], "latency_median_seconds": m["latency_seconds"]["median"], "latency_p95_seconds": m["latency_seconds"]["p95"]})
    _write_csv(output_root / f"{stem}_comparison{suffix}.csv", rows)
    _write_csv(output_root / f"{stem}_poster{suffix}.csv", [{k: row[k] for k in ("condition", "goal_success", "goal_coverage", "hallucination", "engineering_error", "latency_mean_seconds")} | {"self_correction": comparison["condition_metrics"][row["condition"]].get("agentic", {}).get("self_correction_rate")} for row in rows])
    _write_csv(output_root / f"{stem}_iteration_curves{suffix}.csv", [{"condition": condition, "iteration": index + 1, "external_goal_coverage_locf": value} for condition in CONDITIONS[1:] for index, value in enumerate(comparison["condition_metrics"][condition]["agentic"]["external_coverage_by_iteration_locf"])])
    _write_csv(output_root / f"{stem}_task_scores{suffix}.csv", [{"task_id": r["task_id"], "condition": r["condition"], "goal_success": r["goal_success"], "goal_coverage": r["external_goal_coverage"], "hallucination": int(r["hallucination"]), "engineering_error": int(r["engineering_contradiction"]), "numeric_pass": int(r["numeric_pass"]), "latency_seconds": r["latency_seconds"]} for r in comparison["task_scores"]])
    label = suffix.replace("_", " ").strip()
    lines = ["# Agentic Baseline v1" + (f" — {label}" if label else ""), "", f"Run: `{run_dir.name}`. Product code remains frozen. Single AI-assisted semantic reviewer: `gemma4:latest`. Exploratory N=18; interval estimates are paired 10,000-bootstrap percentile 95% CIs.", "", "| Metric | Single-shot | Goal Agent | Full Agent |", "|---|---:|---:|---:|"]
    for label, key in (("External goal success", "external_goal_success_rate"), ("External goal coverage", "external_goal_coverage"), ("Hallucination", "hallucination_rate"), ("Engineering contradiction", "engineering_contradiction_rate")):
        lines.append("| " + label + " | " + " | ".join(_format_pct(comparison["condition_metrics"][c][key]) for c in CONDITIONS) + " |")
    lines.append("| System-level latency mean (s) | " + " | ".join(f"{comparison['condition_metrics'][c]['latency_seconds']['mean']:.1f}" for c in CONDITIONS) + " |")
    lines += ["", "## Process and Python", "", "The iteration curve uses last observation carried forward after a task stops. Internal goal coverage is reported only as calibration telemetry; it never determines external success.", "", f"Python-required task count: {comparison['python_metrics']['required_task_count']}. Python selection precision/recall: {_format_pct(comparison['python_metrics']['selection_precision'])} / {_format_pct(comparison['python_metrics']['selection_recall'])}.", "", "## Paired differences", ""]
    for key, data in comparison["paired_comparisons"].items():
        lines.append(f"- {key}: success {data['goal_success']['delta']:+.3f} [{data['goal_success']['ci95_low']:+.3f}, {data['goal_success']['ci95_high']:+.3f}]; coverage {data['goal_coverage']['delta']:+.3f} [{data['goal_coverage']['ci95_low']:+.3f}, {data['goal_coverage']['ci95_high']:+.3f}].")
    lines += ["", "## Review QA", "", "Original semantic reviews are preserved in the run directory. Deterministic checks control numeric target/units and provenance. Reviewer quote-gating and process-ID disagreements are flagged in task scores. Adjudicated versions are separate files; no original review is overwritten."]
    if comparison.get("adjudication"):
        lines.append(f"Manual QA corrected {comparison['adjudication']['corrected_rows']} task-condition rows in v{comparison['adjudication']['version']}; see the separately hashed adjudication file for itemized reasons.")
    if comparison.get("strict_review_quote_gates") is not None:
        lines.append(f"The strict reviewer had {comparison['strict_review_quote_gates']} missing/non-verbatim criterion quotes; these criteria were gated to zero before any itemized adjudication.")
    lines.append("")
    (ROOT / "evaluation/review" / f"{stem}_summary{suffix}.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--strict-final-review", action="store_true")
    args = parser.parse_args()
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if sha256(BENCHMARK) != manifest["benchmark_sha256"]:
        raise ValueError("Frozen benchmark checksum mismatch")
    mapping = json.loads((args.run_dir / "blind_review_map.json").read_text(encoding="utf-8"))
    final_name = "final_review_strict_v1_1.json" if args.strict_final_review else "final_review_original.json"
    final_review = json.loads((args.run_dir / final_name).read_text(encoding="utf-8"))["items"]
    process_review = json.loads((args.run_dir / "process_review_original.json").read_text(encoding="utf-8"))["items"]
    if set(mapping["final"]) != set(final_review) or set(mapping["process"]) != set(process_review):
        raise ValueError("Incomplete review")
    tasks = {t["task_id"]: t for t in benchmark["tasks"]}
    overrides = {}
    if args.adjudication:
        adjudication = json.loads(args.adjudication.read_text(encoding="utf-8"))
        overrides = {(entry["task_id"], entry["condition"]): entry for entry in adjudication["corrections"]}
        if len(overrides) != len(adjudication["corrections"]):
            raise ValueError("Duplicate adjudication key")
    raws = {condition: json.loads((args.run_dir / f"{condition}.json").read_text(encoding="utf-8")) for condition in CONDITIONS}
    if any(not raw["complete"] for raw in raws.values()):
        raise ValueError("Incomplete raw run")
    run_rows = {(row["task_id"], condition): row for condition, raw in raws.items() for row in raw["results"]}
    scored = []
    by_key = {}
    for anonymous_id, key in mapping["final"].items():
        task_id, condition = key["task_id"], key["condition"]
        judgment = final_review[anonymous_id]
        override = overrides.get((task_id, condition))
        if override:
            judgment = {**judgment, "criterion_scores": {**judgment["criterion_scores"], **override.get("criterion_scores", {})}, **override.get("judgment_fields", {})}
        item = score_final(tasks[task_id], run_rows[(task_id, condition)], judgment)
        scored.append(item)
        by_key[(task_id, condition)] = item
    process = []
    for anonymous_id, key in mapping["process"].items():
        task_id, condition = key["task_id"], key["condition"]
        process.append(score_process(tasks[task_id], run_rows[(task_id, condition)], process_review[anonymous_id], by_key[(task_id, condition)]))
    comparison = aggregate(benchmark, scored, process)
    comparison["run_id"] = args.run_dir.name
    comparison["benchmark_sha256"] = manifest["benchmark_sha256"]
    comparison["reviewer_method"] = "single AI-assisted semantic reviewer"
    comparison["reviewer_model"] = "gemma4:latest"
    comparison["final_review_file"] = final_name
    if args.strict_final_review:
        comparison["strict_review_quote_gates"] = sum(len(j.get("quote_gated_criteria", [])) for j in final_review.values())
    if args.adjudication:
        comparison["adjudication"] = {"version": adjudication["version"], "sha256": sha256(args.adjudication), "corrected_rows": len(overrides), "original_reviews_preserved": True}
    random_sample = random.Random(42).sample(scored, min(6, len(scored)))
    comparison["review_qa_sample"] = [
        {"task_id": row["task_id"], "condition": row["condition"], "qa_flags": row["qa_flags"], "numeric_targets": row["numeric_targets"]}
        for row in random_sample
    ]
    priority_types = {"quantitative", "false_premise", "insufficient_evidence"}
    comparison["review_qa_priority"] = [
        {"task_id": row["task_id"], "condition": row["condition"], "qa_flags": row["qa_flags"], "numeric_targets": row["numeric_targets"], "hypothesis_handling_correct": row["hypothesis_handling_correct"], "insufficient_evidence_detected": row["insufficient_evidence_detected"]}
        for row in scored if tasks[row["task_id"]]["task_type"] in priority_types
    ]
    comparison["review_qa_flags"] = [
        {"task_id": row["task_id"], "condition": row["condition"], "flags": row["qa_flags"]}
        for row in [*scored, *process] if row["qa_flags"]
    ]
    suffix = "_strict_v1_1" if args.strict_final_review else ("_adjudicated_v1_1" if args.adjudication else "")
    if args.strict_final_review and args.adjudication:
        suffix = "_strict_adjudicated_v1_2"
    write_outputs(comparison, args.run_dir.parent.parent, args.run_dir, suffix)
    print(f"scored={len(scored)} process={len(process)} output={args.run_dir.parent.parent / f'agentic_heldout_v1_comparison{suffix}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
