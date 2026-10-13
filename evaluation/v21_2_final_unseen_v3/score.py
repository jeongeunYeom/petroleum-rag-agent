"""Deterministic V3 scoring, provenance checks, paired bootstrap, and report."""

from __future__ import annotations

import csv
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from common import HERE, TASKS, write_json
from integrity_check import main as integrity_check


SYSTEMS = ("qwen_closed_book", "v21_2_agent", "gpt_reference")
LABELS = {"qwen_closed_book": "Qwen3:8b Closed-book", "v21_2_agent": "V21.2 Agent", "gpt_reference": "GPT Reference"}
NUMBER = re.compile(r"(?<![A-Za-z])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
UNIT_FORMS = {
    "ppg": ("ppg", "lb/gal"), "%": ("%", "percent", "퍼센트"),
    "psi": ("psi", "psia"), "lbf": ("lbf", "lb-force"),
    "bbl": ("bbl", "barrel", "배럴"),
    "bbl/day": ("bbl/day", "bbl/d", "bpd"),
    "scf/stb": ("scf/stb", "scf/bbl"),
    "m3/day": ("m3/day", "m³/day", "m3/d"),
    "g/cm3": ("g/cm3", "g/cm³", "g/cc"),
    "1/m": ("1/m", "m^-1", "m⁻¹"),
    "fraction": (), "score": (), "dimensionless": (),
}


def compact(text: str) -> str:
    return " ".join(text.split()).casefold()


def numeric_present(answer: str, target: dict) -> bool:
    expected = float(target["expected_value"])
    tolerance = float(target["tolerance"])
    numbers = []
    for match in NUMBER.finditer(answer):
        try:
            numbers.append(float(match.group().replace(",", "")))
        except ValueError:
            pass
    if not any(math.isclose(value, expected, abs_tol=tolerance, rel_tol=0) for value in numbers):
        return False
    forms = UNIT_FORMS.get(target["expected_unit"], (target["expected_unit"],))
    return not forms or any(form.casefold() in answer.casefold() for form in forms)


def source_matches(actual: dict, gold: dict) -> bool:
    return actual.get("document") == gold["document"] and actual.get("page") == gold["page"]


def agent_provenance(task: dict, run: dict) -> dict:
    sources = run.get("internal_sources") or []
    cited = re.findall(r"\[(KB\d+|FIG\d+)\]", run.get("final_answer") or "")
    source_by_id = {item.get("evidence_id"): item for item in sources + (run.get("figures") or [])}
    valid_ids = bool(cited) and all(item in source_by_id for item in cited)
    gold = task["gold_sources"]
    gold_page_retrieved = any(source_matches(actual, expected) for actual in sources for expected in gold)
    formula = task["formula_source"]
    formula_span_retrieved = False
    formula_provenance_correct = False
    if formula.get("required"):
        literal = compact(formula["exact_formula_span"])
        formula_span_retrieved = any(
            source_matches(actual, formula) and literal in compact(actual.get("excerpt") or "")
            for actual in sources
        )
        formula_provenance_correct = any(
            calc.get("validation_passed")
            and any(
                (src := source_by_id.get(fid)) is not None
                and source_matches(src, formula)
                and literal in compact(src.get("excerpt") or "")
                for fid in calc.get("formula_source_ids") or []
            )
            for calc in run.get("computations") or []
        )
    actions = [item.get("action_type") for item in run.get("action_history") or [] if item.get("status") == "completed"]
    retrieve_calculate = "retrieve" in actions and "calculate" in actions and actions.index("retrieve") < actions.index("calculate")
    computations = run.get("computations") or []
    validated = [item for item in computations if item.get("validation_passed")]
    complete_provenance = any(
        item.get("input_fact_ids") and item.get("bound_variables")
        and item.get("normalized_formula") and item.get("execution_hash")
        and item.get("output") and item.get("validation_passed")
        and item.get("formula_source_ids")
        for item in validated
    )
    return {
        "calculation_executed": bool(run.get("python_calls_total", 0)),
        "calculation_validated": bool(validated),
        "calculation_provenance_complete": bool(complete_provenance),
        "gold_page_retrieved": gold_page_retrieved,
        "formula_span_retrieved": formula_span_retrieved,
        "formula_provenance_correct": formula_provenance_correct,
        "retrieve_then_calculate": retrieve_calculate,
        "citation_id_correct": valid_ids,
        "citation_ids": cited,
        "action_sequence": actions,
    }


def score_row(task: dict, system: str) -> dict:
    raw = json.loads((HERE / "raw" / system / f"{task['task_id']}.json").read_text(encoding="utf-8"))
    judged = json.loads((HERE / "judge" / f"{task['task_id']}__{system}.json").read_text(encoding="utf-8"))
    if judged.get("status") not in {"completed", "deterministic_technical_failure"}:
        raise RuntimeError(f"missing completed judgment for {task['task_id']} {system}")
    judgment = judged["judgment"]
    if len(judgment["claim_scores"]) != len(task["required_claims"]):
        raise RuntimeError(f"claim-score count mismatch for {task['task_id']} {system}")
    technical = bool(raw["technical_failure"])
    coverage = 0.0 if technical else statistics.mean(judgment["claim_scores"])
    numeric = bool(task["numeric_targets"])
    numeric_correct = bool(numeric and not technical and judgment["numeric_accuracy"] and judgment["unit_accuracy"]
                           and all(numeric_present(raw["answer_text"], target) for target in task["numeric_targets"]))
    run = raw.get("run") or {}
    provenance = agent_provenance(task, run) if system == "v21_2_agent" and not technical else {}
    goal = bool(not technical and judgment["all_required_goals_met"] and all(score == 1 for score in judgment["claim_scores"]))
    if task["category"] == "false_premise":
        goal = goal and judgment["false_premise_explicitly_corrected"]
        if system == "v21_2_agent":
            goal = goal and provenance["citation_id_correct"] and judgment["citation_semantic_support"]
    if task["category"] == "unanswerable":
        goal = goal and judgment["unanswerable_specific_missing_identified"]
    if numeric:
        goal = goal and numeric_correct
        if system == "v21_2_agent":
            goal = goal and provenance["calculation_validated"]
    if task["category"] == "kb_formula":
        # The frozen policy requires a sourced, validated path for all systems.
        goal = goal and system == "v21_2_agent" and provenance["formula_provenance_correct"]
    if system == "v21_2_agent" and task["citation_required_for_agent"] and task["category"] != "unanswerable":
        goal = goal and provenance["citation_id_correct"] and judgment["citation_semantic_support"]
    return {
        "task_id": task["task_id"], "category": task["category"], "domain": task["domain"],
        "question_language": task["question_language"], "multi_goal": task["multi_goal"],
        "answerable": task["answerable"], "system": system,
        "response_status": raw["response_status"], "technical_failure": technical,
        "goal_success": bool(goal), "claim_coverage": coverage,
        "hallucination_free": not judgment["hallucination"],
        "hallucination": bool(judgment["hallucination"]),
        "numeric_correct": numeric_correct if numeric else None,
        "unnecessary_refusal": bool(judgment["unnecessary_refusal"] and not technical),
        "citation_semantic_support": bool(judgment["citation_semantic_support"] and provenance.get("citation_id_correct")) if system == "v21_2_agent" else None,
        "latency_seconds": raw.get("latency_seconds"),
        "run_status": run.get("run_status") if run else None,
        "final_status": run.get("status") if run else None,
        "python_calls": run.get("python_calls_total", 0) if run else 0,
        **provenance,
    }


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    pos = (len(ordered) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (pos - lower)


def summarize(rows: list[dict]) -> dict:
    latencies = [float(row["latency_seconds"]) for row in rows if row["latency_seconds"] is not None]
    numeric_rows = [row for row in rows if row["numeric_correct"] is not None]
    return {
        "n": len(rows),
        "goal_success": average([float(row["goal_success"]) for row in rows]),
        "claim_coverage": average([row["claim_coverage"] for row in rows]),
        "hallucination_free": average([float(row["hallucination_free"]) for row in rows]),
        "numeric_accuracy": average([float(row["numeric_correct"]) for row in numeric_rows]),
        "numeric_denominator": len(numeric_rows),
        "technical_failures": sum(row["technical_failure"] for row in rows),
        "unnecessary_refusals": sum(row["unnecessary_refusal"] for row in rows),
        "mean_latency_seconds": average(latencies),
        "median_latency_seconds": statistics.median(latencies) if latencies else 0.0,
        "p95_latency_seconds": percentile(latencies, 0.95),
    }


def paired_ci(rows: list[dict], other: str, metric: str, numeric_only: bool = False) -> dict:
    agent = {row["task_id"]: row for row in rows if row["system"] == "v21_2_agent"}
    baseline = {row["task_id"]: row for row in rows if row["system"] == other}
    ids = [task["task_id"] for task in TASKS if not numeric_only or task["numeric_targets"]]
    assert len(ids) == (16 if numeric_only else 36)
    differences = [float(agent[task_id][metric]) - float(baseline[task_id][metric]) for task_id in ids]
    rng = random.Random(20261013)
    samples = [average([differences[rng.randrange(len(differences))] for _ in differences]) for _ in range(10000)]
    return {"delta": average(differences), "ci95_low": percentile(samples, 0.025), "ci95_high": percentile(samples, 0.975), "n": len(ids), "resamples": 10000, "seed": 20261013}


def resume_summary() -> dict:
    rows = []
    for probe in json.loads((HERE / "benchmark.json").read_text(encoding="utf-8"))["resume_probes"]:
        record = json.loads((HERE / "resume" / f"{probe['probe_id']}.json").read_text(encoding="utf-8"))
        first = record.get("turn1_state") or {}
        second = record.get("turn2_state") or {}
        answer = second.get("final_answer") or ""
        supplied = probe["missing_input"].casefold()
        repeated = supplied in (second.get("clarification_question") or "").casefold()
        rows.append({
            "probe_id": probe["probe_id"],
            "turn1_waiting_correctly": first.get("run_status") == "waiting_for_user_input",
            "same_run_preserved": bool(record.get("run_id") and record.get("resume_response_run_id") == record.get("run_id")),
            "missing_input_bound": any(c.get("validation_passed") for c in second.get("computations") or []) or supplied not in [x.casefold() for x in second.get("required_inputs") or []],
            "repeated_clarification": repeated,
            "final_completion": second.get("status") == "achieved" and second.get("run_status") == "completed",
            "validated_calculation": any(c.get("validation_passed") for c in second.get("computations") or []),
            "run_id": record.get("run_id"),
            "turn1_status": first.get("run_status"),
            "turn2_status": second.get("run_status"),
        })
    return {"probes": rows, "turn1_waiting_count": sum(x["turn1_waiting_correctly"] for x in rows), "same_run_count": sum(x["same_run_preserved"] for x in rows), "final_completion_count": sum(x["final_completion"] for x in rows)}


def report(metrics: dict, rows: list[dict]) -> str:
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    receipt = json.loads((HERE / "freeze_receipt.json").read_text(encoding="utf-8"))
    lines = [
        "# V21.2 final unseen V3 evaluation",
        "",
        "V21.2 was evaluated once on a newly authored V3 benchmark frozen after the product freeze and before any evaluated product call. Generation attempts were not retried. Technical execution failures were handled according to a predeclared deterministic missing-response scoring rule.",
        "",
        f"- FINALIZED: **{str(metrics['finalized']).lower()}**",
        f"- Frozen product: `{manifest['product_sha']}`; freeze commit: `{receipt['freeze_commit']}`",
        f"- Benchmark SHA256: `{receipt['sha256']['benchmark.json']}`; rubric SHA256: `{receipt['sha256']['rubric.json']}`",
        "- Primary tasks: 36; numeric denominator: 16; Korean questions with English source: 12; multi-goal: 6; independent resume probes: 4.",
        f"- Excluded prior document/page pairs: {manifest['excluded_prior_page_count']}; unique primary gold source pages: {manifest['unique_primary_source_pages']}.",
        f"- Novelty screen: character-four-gram Jaccard maximum {manifest['novelty']['max_lexical_similarity']:.3f} (< 0.45) and multilingual BGE-M3 cosine maximum {manifest['novelty']['max_semantic_cosine']:.3f} (< 0.90). V2 question text was processed only mechanically.",
        "",
        "## Headline (all 36; numeric 16)",
        "",
        "| System | Goal Success | Claim Coverage | Hallucination-free | Numerical Accuracy | Technical failures | Median latency | P95 latency |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for system in SYSTEMS:
        item = metrics["systems"][system]
        lines.append(f"| {LABELS[system]} | {item['goal_success']:.1%} | {item['claim_coverage']:.1%} | {item['hallucination_free']:.1%} | {item['numeric_accuracy']:.1%} | {item['technical_failures']}/36 | {item['median_latency_seconds']:.1f}s | {item['p95_latency_seconds']:.1f}s |")
    lines += ["", "## Paired differences (V21.2 minus baseline)", "", "| Baseline | Metric | Delta | 95% CI | Interpretation |", "| --- | --- | ---: | --- | --- |"]
    for baseline, by_metric in metrics["paired_differences"].items():
        for name, value in by_metric.items():
            phrase = "descriptive difference; superiority not established" if value["ci95_low"] <= 0 <= value["ci95_high"] else "95% CI excludes zero"
            lines.append(f"| {LABELS[baseline]} | {name} | {value['delta']:+.1%} | [{value['ci95_low']:+.1%}, {value['ci95_high']:+.1%}] | {phrase} |")
    lines += ["", "## Agent diagnostics", ""]
    for label, value in metrics["agent_diagnostics"].items():
        lines.append(f"- {label}: {value}")
    lines += ["", "## Category Goal Success", "", "| Category | Qwen | V21.2 | GPT |", "| --- | ---: | ---: | ---: |"]
    for category in sorted(manifest["category_distribution"]):
        vals = metrics["category_goal_success"][category]
        lines.append(f"| {category} | {vals['qwen_closed_book']:.1%} | {vals['v21_2_agent']:.1%} | {vals['gpt_reference']:.1%} |")
    lines += [
        "", "## Protocol and limitations", "",
        "The baseline systems had no KB, tools, or Python. The frozen Goal Success rubric requires a literal formula source and validated calculation path for KB-formula tasks; this requirement is not satisfiable by a closed-book system and should be considered when interpreting that category. Numerical Accuracy separately measures the final values.",
        "Technical failures are retained in the 36-task denominators as no responses: Goal Success and Claim Coverage 0, numeric incorrect where applicable, Hallucination-free true, not a refusal. A systemic infrastructure failure threshold of >20% per required system was fixed before execution.",
        "Semantic correctness and citation support were assessed by one blinded AI reviewer per completed answer, not human review. The exact judge was gpt-5.4-2026-03-05 at temperature 0. Its judgments may have residual error, particularly for subtle engineering interpretation. Structured numeric and provenance gates were applied deterministically afterward.",
        "The 4 resume probes are diagnostic and excluded from the primary denominator. The previous V2 evaluation is observed and was not reused as a final unseen estimate.",
        "",
        f"Integrity: product unchanged={metrics['integrity']['product_unchanged']}; benchmark unchanged={metrics['integrity']['benchmark_unchanged']}; rubric unchanged={metrics['integrity']['rubric_unchanged']}; KB unchanged={metrics['integrity']['kb_unchanged']}; one attempt per system/task={metrics['integrity']['one_attempt_integrity']}; generation retries=0.",
        "",
        "## Poster-safe conclusions", "",
    ]
    for sentence in metrics["poster_safe_conclusions"]:
        lines.append(f"- {sentence}")
    return "\n".join(lines) + "\n"


def main() -> None:
    rows = [score_row(task, system) for task in TASKS for system in SYSTEMS]
    write_json(HERE / "scored_rows.json", rows)
    systems = {system: summarize([row for row in rows if row["system"] == system]) for system in SYSTEMS}
    paired = {
        baseline: {
            metric: paired_ci(rows, baseline, metric, numeric_only=(metric == "numeric_correct"))
            for metric in ("goal_success", "claim_coverage", "hallucination_free", "numeric_correct")
        }
        for baseline in ("qwen_closed_book", "gpt_reference")
    }
    agent = [row for row in rows if row["system"] == "v21_2_agent"]
    numeric_agent = [row for row in agent if row["numeric_correct"] is not None]
    kb_agent = [row for row in agent if row["category"] == "kb_formula"]
    diag = {
        "calculation executed /16": f"{sum(row.get('calculation_executed', False) for row in numeric_agent)}/16",
        "calculation validated /16": f"{sum(row.get('calculation_validated', False) for row in numeric_agent)}/16",
        "numeric correct /16": f"{sum(row['numeric_correct'] for row in numeric_agent)}/16",
        "formula source retrieved /6": f"{sum(row.get('gold_page_retrieved', False) for row in kb_agent)}/6",
        "correct formula span /6": f"{sum(row.get('formula_span_retrieved', False) for row in kb_agent)}/6",
        "retrieve to calculate /6": f"{sum(row.get('retrieve_then_calculate', False) for row in kb_agent)}/6",
        "KB-formula numeric correct /6": f"{sum(row['numeric_correct'] for row in kb_agent)}/6",
        "KB-formula provenance correct /6": f"{sum(row.get('formula_provenance_correct', False) for row in kb_agent)}/6",
        "calculation provenance complete /16": f"{sum(row.get('calculation_provenance_complete', False) for row in numeric_agent)}/16",
        "citation semantic support / source tasks": f"{sum(row.get('citation_semantic_support', False) for row in agent if row['category'] not in {'direct_calculation','user_formula'})}/{sum(row['category'] not in {'direct_calculation','user_formula'} for row in agent)}",
        "cross-language Goal Success /12": f"{sum(row['goal_success'] for row in agent if row['question_language']=='ko')}/12",
        "multi-goal Goal Success /6": f"{sum(row['goal_success'] for row in agent if row['multi_goal'])}/6",
        "unnecessary refusals": sum(row["unnecessary_refusal"] for row in agent),
        "resume final completion /4": f"{resume_summary()['final_completion_count']}/4",
    }
    categories = {category: {system: average([float(row["goal_success"]) for row in rows if row["category"] == category and row["system"] == system]) for system in SYSTEMS} for category in {task["category"] for task in TASKS}}
    with (HERE / "results.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        columns = ["task_id", "system", "category", "domain", "question_language", "multi_goal", "answerable", "response_status", "technical_failure", "goal_success", "claim_coverage", "hallucination_free", "numeric_correct", "unnecessary_refusal", "citation_semantic_support", "latency_seconds", "run_status", "final_status", "python_calls", "calculation_executed", "calculation_validated", "calculation_provenance_complete", "gold_page_retrieved", "formula_span_retrieved", "formula_provenance_correct", "retrieve_then_calculate", "citation_id_correct", "action_sequence"]
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "action_sequence": "/".join(row.get("action_sequence") or [])})
    # Verify CSV round-trip and exact paired row count.
    with (HERE / "results.csv").open("r", newline="", encoding="utf-8-sig") as stream:
        assert len(list(csv.DictReader(stream))) == 108

    integrity_check("post")
    post = json.loads((HERE / "integrity_post.json").read_text(encoding="utf-8"))
    integrity = {
        "product_unchanged": not post["product_changed_files"],
        "benchmark_unchanged": post["benchmark_rubric_hashes_match_receipt"],
        "rubric_unchanged": post["benchmark_rubric_hashes_match_receipt"],
        "kb_unchanged": post["kb_matches_before"],
        "one_attempt_integrity": all(x["one_attempt_each"] for x in post["attempts"].values()),
        "judge_coverage": post["judge_coverage"],
    }
    conclusions = [
        "This estimate describes only the newly frozen 36-task V3 corpus; V2 is not an independent final benchmark.",
        "Technical failures were retained as predeclared missing responses rather than repaired or excluded.",
    ]
    delta = paired["qwen_closed_book"]["goal_success"]
    if delta["ci95_low"] <= 0 <= delta["ci95_high"]:
        conclusions.append("V21.2–Qwen Goal Success difference is descriptive; superiority not established by the paired 95% CI.")
    elif delta["delta"] > 0:
        conclusions.append("V21.2 exceeded Qwen on Goal Success on this corpus, with a paired 95% CI above zero.")
    else:
        conclusions.append("Qwen exceeded V21.2 on Goal Success on this corpus, with a paired 95% CI below zero.")
    metrics = {
        "finalized": bool(post["finalized"]), "primary_denominator": 36, "numeric_denominator": 16,
        "systems": systems, "paired_differences": paired, "agent_diagnostics": diag,
        "category_goal_success": categories, "resume": resume_summary(), "integrity": integrity,
        "poster_safe_conclusions": conclusions,
    }
    write_json(HERE / "metrics.json", metrics)
    (HERE / "FINAL_REPORT.md").write_text(report(metrics, rows), encoding="utf-8")
    poster = ["# V21.2 final unseen V3 poster metrics", "", "| Metric | Qwen3:8b Closed-book | V21.2 Agent | GPT Reference |", "| --- | ---: | ---: | ---: |"]
    for metric in ("goal_success", "claim_coverage", "hallucination_free", "numeric_accuracy"):
        poster.append(f"| {metric.replace('_',' ').title()} | {systems['qwen_closed_book'][metric]:.1%} | {systems['v21_2_agent'][metric]:.1%} | {systems['gpt_reference'][metric]:.1%} |")
    poster += ["", "## V21.2 minus Qwen (paired bootstrap 95% CI)", "", "| Metric | Delta | 95% CI |", "| --- | ---: | --- |"]
    for metric, value in paired["qwen_closed_book"].items():
        poster.append(f"| {metric.replace('_',' ').title()} | {value['delta']:+.1%} | [{value['ci95_low']:+.1%}, {value['ci95_high']:+.1%}] |")
    poster += ["", "## Category Goal Success", "", "| Category | Qwen | V21.2 | GPT |", "| --- | ---: | ---: | ---: |"]
    for category in sorted(categories):
        value = categories[category]
        poster.append(f"| {category} | {value['qwen_closed_book']:.1%} | {value['v21_2_agent']:.1%} | {value['gpt_reference']:.1%} |")
    poster += ["", "Technical failures: " + ", ".join(f"{LABELS[system]} {systems[system]['technical_failures']}/36" for system in SYSTEMS) + ".", "", "Single-reviewer AI-assisted semantic adjudication; not human review. All technical failures remain in the denominators."]
    (HERE / "poster_metrics.md").write_text("\n".join(poster) + "\n", encoding="utf-8")
    print({"finalized": metrics["finalized"], "goal_success": {system: systems[system]["goal_success"] for system in SYSTEMS}, "technical_failures": {system: systems[system]["technical_failures"] for system in SYSTEMS}})


if __name__ == "__main__":
    main()
