"""Deterministic stage and target audit of one frozen v4 A/B run.

Semantic criteria remain preliminary until blind review and 24/24 manual QA.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "backend"))

from run_python_tool_heldout_v4 import CATALOG, load_frozen  # noqa: E402
from app.services.evidence_fact_registry import EvidenceFactRegistry  # noqa: E402
from app.services.formula_source_registry import FormulaSourceRegistry, normalize_formula  # noqa: E402
from app.services.user_fact_registry import UserFactRegistry  # noqa: E402

NUM = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
ID = re.compile(r"\[(?:KB|FIG|WEB|CALC|USERF)\d+\]")
UNIT_PATTERNS = {
    "psi": r"\bpsi(?:a)?\b", "psia": r"\bpsia\b", "bbl": r"\bbbl\b|\bbarrels?\b",
    "bbl/d": r"\bbbl/d\b|\bbbl/day\b|\bbarrels?/day\b", "%": r"%|\bpercent\b",
    "dimensionless": r"\bdimensionless\b|\bunitless\b|\bratio\b|\bfraction\b",
    "percentage_point": r"percentage[ -]points?|\bpp\b",
}
STAGES = ("decision_parsed", "tool_selected", "plan_parsed", "plan_materialized",
          "contract_generated", "contract_complete", "facts_verified", "formula_verified",
          "recovery_triggered", "recovery_success", "execution_boundary", "code_generated",
          "sandbox_passed", "subprocess", "result_schema_valid", "validated_calc",
          "contract_complete_calc", "gt_correct_calc", "grounded_adoption")


def sha(value: object) -> str:
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def equivalent_name(expected: str, observed: str) -> bool:
    a, b = normalized(expected), normalized(observed)
    if a == b:
        return True
    prefix_a = re.match(r"^[a-z]+\d+", expected.casefold())
    prefix_b = re.match(r"^[a-z]+\d+", observed.casefold())
    if prefix_a and prefix_b and prefix_a.group() != prefix_b.group():
        return False
    return (len(a) >= 5 and a in b) or (len(b) >= 5 and b in a)


def unit_equivalent(expected: str, observed: str | None) -> bool:
    e = expected.casefold().replace(" ", "")
    o = (observed or "").casefold().replace(" ", "")
    aliases = {"bbl/day": "bbl/d", "barrels/day": "bbl/d", "percent": "%",
               "fraction": "dimensionless", "ratio": "dimensionless", "unitless": "dimensionless",
               "percentagepoints": "percentage_point", "pp": "percentage_point"}
    return aliases.get(e, e) == aliases.get(o, o)


def _candidate_lines(answer: str, name: str) -> list[str]:
    lines = [line for line in answer.replace("|", " ").splitlines() if line.strip()]
    prefix = name.split("_", 1)[0]
    if re.fullmatch(r"[A-Z][1-9]\d*", prefix):
        selected = [line for line in lines if re.search(rf"(?<![A-Za-z0-9]){re.escape(prefix)}(?![A-Za-z0-9])", line, re.I)]
        if selected:
            return selected
    semantic = name.replace("_", " ")
    aliases = [name, semantic, name.split("_", 1)[-1].replace("_", " ")]
    selected = [line for line in lines if any(a.casefold() in line.casefold() for a in aliases if len(a) >= 4)]
    return selected or lines


def numeric_match(answer: str, target: dict) -> dict:
    wanted = float(target["value"])
    tolerance = float(target["abs_tolerance"])
    unit = target["unit"]
    for line in _candidate_lines(answer, target["semantic_name"]):
        for match in NUM.finditer(line):
            value = float(match.group().replace(",", ""))
            right = line[match.end():match.end()+18]
            percent = bool(re.match(r"\s*(?:%|percent\b)", right, re.I))
            comparable = value / 100 if unit == "dimensionless" and percent else value
            if abs(comparable - wanted) > tolerance:
                continue
            vicinity = line[max(0, match.start()-30):min(len(line), match.end()+35)]
            unit_ok = bool(re.search(UNIT_PATTERNS.get(unit, re.escape(unit)), vicinity, re.I))
            if unit == "dimensionless" and percent:
                unit_ok = True
            return {"value": True, "unit": unit_ok, "observed": value, "line": line[:400]}
    return {"value": False, "unit": False, "observed": None, "line": None}


def numeric_score(answer: str, targets: list[dict]) -> dict:
    matched = {item["semantic_name"]: numeric_match(answer, item) for item in targets}
    return {"total": len(targets), "correct": sum(m["value"] for m in matched.values()),
            "unit_correct": sum(m["value"] and m["unit"] for m in matched.values()),
            "target_matches": matched,
            "complete": all(m["value"] and m["unit"] for m in matched.values())}


def typed_match(answer: str, target: dict) -> bool:
    expected = target["value"]
    if isinstance(expected, str):
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(expected)}(?![A-Za-z0-9])", answer, re.I))
    if isinstance(expected, list):
        labels = [str(label) for label in expected]
        positions = [re.search(rf"(?<![A-Za-z0-9]){re.escape(label)}(?![A-Za-z0-9])", answer, re.I) for label in labels]
        if not all(positions):
            return False
        if target.get("type") == "ranking":
            return all(positions[i].start() < positions[i+1].start() for i in range(len(positions)-1))
        return True
    return False


def _all_traces(response: dict) -> list[dict]:
    return [item["python_trace"] for item in response.get("iterations", []) if item.get("python_trace")]


def _all_outputs(response: dict) -> list[dict]:
    rows = []
    for calc in response.get("computations", []):
        for output_id, item in (calc.get("output_manifest") or {}).items():
            rows.append({"calc_id": calc.get("computation_id"), "output_id": output_id, **item})
    return rows


def contract_score(task: dict, response: dict) -> dict:
    expected = task["ground_truth"]["expected_contract_outputs"]
    outputs = _all_outputs(response)
    matches = {}
    for target in expected:
        matches[target["semantic_name"]] = next(
            (row for row in outputs if equivalent_name(target["semantic_name"], str(row.get("name") or row["output_id"]))),
            None,
        )
    observed = [row for row in matches.values() if row]
    unit_hits = sum(unit_equivalent(item["unit"], matches[item["semantic_name"]].get("unit"))
                    for item in expected if item["type"] == "numeric" and matches[item["semantic_name"]])
    numeric_matched = sum(item["type"] == "numeric" and bool(matches[item["semantic_name"]]) for item in expected)
    scenario_expected = {re.match(r"^[A-Z]\d+", item["semantic_name"]).group()
                         for item in expected if re.match(r"^[A-Z]\d+", item["semantic_name"])}
    scenario_matched = {re.match(r"^[A-Z]\d+", key).group() for key, value in matches.items()
                        if value and re.match(r"^[A-Z]\d+", key)}
    # Product v5 exposes contract IDs and output IDs, but not the full contract
    # names/units before execution. Post-result semantic matching is a lower bound.
    return {
        "contract_output_recall_observable": len(observed) / len(expected) if expected and outputs else None,
        "contract_output_precision_observable": len({id(row) for row in observed}) / len(outputs) if outputs else None,
        "contract_unit_accuracy_observable": unit_hits / numeric_matched if numeric_matched else None,
        "contract_scenario_coverage_observable": len(scenario_matched & scenario_expected) / len(scenario_expected) if scenario_expected and outputs else None,
        "contract_external_complete_observable": len(observed) == len(expected) if outputs else None,
        "matched_output_ids": {key: value["output_id"] if value else None for key, value in matches.items()},
        "contract_observability_limit": "Full pre-execution contract names/units are not persisted by product v5.",
    }


def calc_score(task: dict, response: dict) -> dict:
    expected = task["ground_truth"]
    validated = [calc for calc in response.get("computations", []) if calc.get("validation_passed")]
    best = None
    for calc in validated:
        outputs = [{"output_id": key, **item} for key, item in (calc.get("output_manifest") or {}).items()]
        match = {}
        for target in expected["numeric_targets"]:
            row = next((item for item in outputs if equivalent_name(target["semantic_name"], str(item.get("name") or item["output_id"]))), None)
            value = row.get("value") if row else None
            correct = isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value - target["value"]) <= target["abs_tolerance"]
            match[target["semantic_name"]] = {"present": row is not None, "value": bool(correct),
                                               "unit": bool(correct and unit_equivalent(target["unit"], row.get("unit") if row else None)),
                                               "observed": value}
        typed = {target["semantic_name"]: next((item for item in outputs if equivalent_name(target["semantic_name"], str(item.get("name") or item["output_id"]))), None)
                 for target in expected["typed_targets"]}
        typed_correct = all(row and row.get("value") == target["value"] for target in expected["typed_targets"]
                            for row in [typed[target["semantic_name"]]])
        complete = bool(calc.get("contract_validation_passed")) and all(item["present"] for item in match.values()) and all(typed.values())
        gt_correct = complete and all(item["value"] and item["unit"] for item in match.values()) and typed_correct
        score = {"calc_id": calc.get("computation_id"), "contract_complete_calc": complete, "gt_correct_calc": gt_correct,
                 "calc_numeric_correct": sum(item["value"] for item in match.values()),
                 "calc_unit_correct": sum(item["unit"] for item in match.values()),
                 "calc_typed_correct": sum(bool(row and row.get("value") == target["value"]) for target in expected["typed_targets"]
                                       for row in [typed[target["semantic_name"]]]),
                 "calc_target_matches": match, "calc_typed_matches": {key: row.get("value") if row else None for key, row in typed.items()}}
        if best is None or (score["gt_correct_calc"], score["calc_numeric_correct"]) > (best["gt_correct_calc"], best["calc_numeric_correct"]):
            best = score
    return {"calc_created": bool(validated), "validated_calc_count": len(validated),
            "contract_complete_calc": bool(best and best["contract_complete_calc"]),
            "gt_correct_calc": bool(best and best["gt_correct_calc"]),
            "calc_numeric_correct": best["calc_numeric_correct"] if best else 0,
            "calc_unit_correct": best["calc_unit_correct"] if best else 0,
            "calc_typed_correct": best["calc_typed_correct"] if best else 0,
            "calc_best": best}


def runtime_registry(task: dict, response: dict, catalog: dict) -> dict:
    gt = task["ground_truth"]
    retrieved = {key: [row["evidence_id"] for row in response.get("internal_sources", [])
                       if row.get("chunk_id") == catalog[key]["chunk_id"]] for key in gt["source_ids"]}
    records = [{"evidence_id": row["evidence_id"], "source_type": "knowledge_base",
                "locator": f"{row.get('document')} p.{row.get('page')}", "text": row.get("excerpt", "")}
               for row in response.get("internal_sources", [])]
    user = UserFactRegistry.from_topic(task["topic"]).records
    evidence = EvidenceFactRegistry.from_evidence(records).records
    formula = FormulaSourceRegistry.from_evidence(records).records
    def same(row, item):
        return row.name.casefold() == str(item[0]).casefold() and math.isclose(row.value, item[1], abs_tol=1e-8) and row.unit.casefold() == item[2].casefold()
    user_found = [item for item in gt["expected_user_facts"] if any(same(row, item) for row in user)]
    evidence_found = [item for item in gt["expected_evidence_facts"] if any(
        row.source_id in retrieved.get(item[0], []) and same(row, item[1:]) for row in evidence)]
    formula_found = [item for item in gt["formula_sources"] if any(
        row.source_id in retrieved.get(item[0], []) and row.expression_candidate and
        normalize_formula(row.raw_span) == normalize_formula(item[1]) for row in formula)]
    return {"source_retrieved": {key: bool(val) for key, val in retrieved.items()},
            "runtime_userf_recall": len(user_found) / len(gt["expected_user_facts"]) if gt["expected_user_facts"] else None,
            "runtime_efact_recall": len(evidence_found) / len(gt["expected_evidence_facts"]) if gt["expected_evidence_facts"] else None,
            "runtime_formula_recall": len(formula_found) / len(gt["formula_sources"]) if gt["formula_sources"] else None}


def aggregate_stages(response: dict, calc: dict, answer: str) -> dict:
    traces = _all_traces(response)
    anyt = lambda key: any(bool(t.get(key)) for t in traces)
    stages = {
        "decision_parsed": any(t.get("planner_decision_status") not in (None, "planner_decision_parse_failed") for t in traces),
        "tool_selected": anyt("tool_selected"),
        "plan_parsed": anyt("plan_present"),
        "plan_materialized": any(t.get("planner_plan_status") == "materialized" for t in traces),
        "contract_generated": any(t.get("calculation_contract_id") for t in traces),
        "contract_complete": anyt("contract_complete"),
        "facts_verified": anyt("facts_verified"),
        "formula_verified": anyt("formula_verified"),
        "recovery_triggered": anyt("recovery_triggered"),
        "recovery_success": anyt("recovery_materialization_success"),
        "execution_boundary": anyt("call_boundary_reached"),
        "code_generated": anyt("code_generated"),
        "sandbox_passed": anyt("sandbox_validation_passed"),
        "subprocess": anyt("subprocess_reached"),
        "result_schema_valid": anyt("result_validation_passed"),
        "validated_calc": calc["calc_created"],
        "contract_complete_calc": calc["contract_complete_calc"],
        "gt_correct_calc": calc["gt_correct_calc"],
        "grounded_adoption": bool(calc["gt_correct_calc"] and any(
            t.get("calc_grounding_validation_passed") and t.get("calc_output_adoption_count", 0) > 0 for t in traces
        ) and calc["calc_best"] and f"[{calc['calc_best']['calc_id']}]" in answer),
    }
    return stages


def furthest_stage(stages: dict) -> int:
    scale = ((1,"decision_parsed"),(2,"tool_selected"),(3,"plan_parsed"),(4,"plan_materialized"),
             (5,"contract_generated"),(6,"contract_complete"),(7,"facts_verified"),(8,"execution_boundary"),
             (9,"code_generated"),(10,"sandbox_passed"),(11,"subprocess"),(12,"result_schema_valid"),
             (13,"contract_complete_calc"),(14,"gt_correct_calc"),(15,"grounded_adoption"))
    return max((number for number, key in scale if stages.get(key)), default=0)


def trace_integrity(stages: dict, traces: list[dict]) -> list[str]:
    errors = []
    if stages["validated_calc"] and not stages["subprocess"]:
        errors.append("calc_without_subprocess")
    if stages["gt_correct_calc"] and not stages["contract_complete_calc"]:
        errors.append("gt_correct_without_complete")
    if stages["grounded_adoption"] and not stages["gt_correct_calc"]:
        errors.append("adoption_without_gt_correct")
    for trace in traces:
        if trace.get("contract_complete") and trace.get("missing_output_ids"):
            errors.append("contract_complete_with_missing_outputs")
    return errors


def strong_benefit(off: dict, on: dict) -> bool:
    return bool(
        not off["goal_success_preliminary"]
        and on["gt_correct_calc"]
        and on["grounded_adoption"]
        and on["goal_success_preliminary"]
    )


def weak_numeric_improvement(off: dict, on: dict) -> bool:
    return bool(
        on["numeric_correct"] > off["numeric_correct"]
        and not (on["gt_correct_calc"] and on["grounded_adoption"])
    )


def paired_bootstrap(pairs: list[tuple[float, float]], samples: int = 10000, seed: int = 42) -> dict:
    if not pairs:
        return {"delta": None, "ci95": None, "samples": samples, "seed": seed}
    differences = [on - off for off, on in pairs]
    rng = random.Random(seed)
    n = len(differences)
    estimates = sorted(sum(differences[rng.randrange(n)] for _ in range(n)) / n for _ in range(samples))
    return {"delta": statistics.mean(differences),
            "ci95": [estimates[int(.025 * samples)], estimates[math.ceil(.975 * samples)-1]],
            "samples": samples, "seed": seed}


def citation_mapping(response: dict) -> dict:
    mapping = {f"[{row['evidence_id']}]": [row.get("document"), row.get("page"), row.get("chunk_id")]
               for row in response.get("internal_sources", [])}
    mapping.update({f"[{row['computation_id']}]": [row.get("source_evidence_ids"), row.get("source_input_ids"),
                                                     row.get("formula_evidence_ids")]
                    for row in response.get("computations", [])})
    return {key: mapping.get(key) for key in sorted(set(ID.findall(response.get("final_answer", ""))))}


def failure_attribution(task: dict, row: dict) -> list[str]:
    if row["goal_success_preliminary"]:
        return []
    labels = []
    if any(not val for val in row["source_retrieved"].values()):
        labels.append("retrieval_source_missing")
    if row["runtime_efact_recall"] not in (None, 1):
        labels.append("fact_registry_missing")
    if row["runtime_formula_recall"] not in (None, 1):
        labels.append("formula_registry_missing")
    if row["condition"] == "python_on" and task["python_expected"] == "required":
        for key, label in (("tool_selected","planner_not_selected"),("plan_parsed","plan_parse_failed"),
                           ("plan_materialized","materialization_failed"),("contract_generated","contract_parse_failed"),
                           ("contract_complete","contract_incomplete"),("facts_verified","facts_verification_failed"),
                           ("formula_verified","formula_verification_failed"),("code_generated","code_generation_failed"),
                           ("sandbox_passed","sandbox_failed"),("subprocess","runtime_failed"),
                           ("result_schema_valid","result_schema_failed"),("contract_complete_calc","result_contract_incomplete"),
                           ("gt_correct_calc","calc_gt_incorrect"),("grounded_adoption","final_adoption_failed")):
            if not row[key]:
                labels.append(label)
                break
    if row["numeric_correct"] < row["numeric_total"] and not labels:
        labels.append("final_synthesis")
    return labels or ["other"]


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    names = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                          for key, value in row.items()} for row in rows)


def _population_summary(rows: list[dict]) -> dict:
    latencies = sorted(row["elapsed_seconds"] for row in rows)
    total = sum(row["numeric_total"] for row in rows)
    return {
        "n": len(rows), "goal_success_preliminary": statistics.mean(row["goal_success_preliminary"] for row in rows) if rows else None,
        "external_coverage_preliminary": statistics.mean(row["external_coverage_preliminary"] for row in rows) if rows else None,
        "numeric_accuracy_preliminary": sum(row["numeric_correct"] for row in rows) / total if total else None,
        "unit_accuracy_preliminary": sum(row["unit_correct"] for row in rows) / total if total else None,
        "latency_mean": statistics.mean(latencies) if latencies else None,
        "latency_median": statistics.median(latencies) if latencies else None,
        "latency_p95": latencies[math.ceil(.95 * len(latencies))-1] if latencies else None,
    }


def score(run_dir: Path, output_dir: Path) -> dict:
    benchmark, manifest = load_frozen()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    raw = {name: json.loads((run_dir / f"{name}.json").read_text(encoding="utf-8"))
           for name in ("python_off", "python_on")}
    expected = [task["task_id"] for task in benchmark["tasks"]]
    for name, payload in raw.items():
        if not payload["complete"] or payload["benchmark_sha256"] != manifest["benchmark_sha256"] or [row["task_id"] for row in payload["results"]] != expected:
            raise ValueError(f"Incomplete or altered {name} run")
    if raw["python_off"]["run_id"] != raw["python_on"]["run_id"]:
        raise ValueError("Unpaired runs")
    rows, iterations, contracts, calcs = [], [], [], []
    for condition in ("python_off", "python_on"):
        for task, raw_row in zip(benchmark["tasks"], raw[condition]["results"]):
            response = raw_row.get("response") or {}
            answer = response.get("final_answer", "")
            targets = task["ground_truth"]["numeric_targets"]
            numeric = numeric_score(answer, targets)
            typed = {target["semantic_name"]: typed_match(answer, target) for target in task["ground_truth"]["typed_targets"]}
            calc = calc_score(task, response)
            contract = contract_score(task, response)
            registry = runtime_registry(task, response, catalog)
            stages = aggregate_stages(response, calc, answer)
            traces = _all_traces(response)
            semantic_source = not task["ground_truth"]["source_ids"] or all(registry["source_retrieved"].values())
            numeric_pass = numeric["complete"] and all(typed.values())
            criterion = {"C1": semantic_source, "C2": numeric_pass if task["python_expected"] != "not_needed" else True,
                         "C3": task["python_expected"] != "not_needed" or not stages["subprocess"]}
            row = {
                "task_id": task["task_id"], "condition": condition, "domain": task["domain"],
                "python_expected": task["python_expected"], "evaluation_stratum": task["evaluation_stratum"],
                "elapsed_seconds": raw_row["elapsed_seconds"], "product_exception": raw_row.get("product_exception"),
                "product_status": response.get("status"), "internal_coverage": response.get("goal_coverage"),
                "external_coverage_preliminary": sum(criterion.values()) / 3,
                "goal_success_preliminary": all(criterion.values()), "criterion_pass_preliminary": criterion,
                "numeric_total": numeric["total"], "numeric_correct": numeric["correct"],
                "unit_correct": numeric["unit_correct"], "numeric_matches": numeric["target_matches"],
                "typed_total": len(typed), "typed_correct": sum(typed.values()), "typed_matches": typed,
                "answer_sha256": sha(answer.encode()), "citation_mapping_sha256": sha(citation_mapping(response)),
                "final_answer": answer, "python_calls_total": response.get("python_calls_total", 0),
                "python_attempts_total": response.get("python_attempts_total", 0),
                "python_seconds": sum(item.get("timing", {}).get("python_seconds", 0) for item in response.get("iterations", [])),
                "recovery_trigger_count": sum(bool(trace.get("recovery_triggered")) for trace in traces),
                "recovery_success_count": sum(bool(trace.get("recovery_materialization_success")) for trace in traces),
                "recovery_new_source_count": sum(len(trace.get("recovery_new_source_ids") or []) for trace in traces),
                "recovery_efact_gain": sum(trace.get("recovery_efact_count", 0) for trace in traces),
                "recovery_formula_gain": sum(trace.get("recovery_formula_count", 0) for trace in traces),
                "recovery_query_count": sum(trace.get("recovery_query_count", 0) for trace in traces),
                "adoption_coverage_product": max((trace.get("calc_adoption_coverage", 0) for trace in traces), default=0),
                "web_source_count": len(response.get("web_sources", [])),
                "engineering_contradiction_count": sum(item.get("engineering_contradiction_count", 0) for item in response.get("iterations", [])),
                "unsupported_engineering_claim_count": sum(item.get("unsupported_engineering_claim_count", 0) for item in response.get("iterations", [])),
                "calc_grounding_failure_reasons": [reason for trace in traces for reason in trace.get("calc_grounding_failures", [])],
                **registry, **contract, **calc, **stages,
            }
            row["furthest_stage"] = furthest_stage(stages)
            row["trace_integrity_errors"] = trace_integrity(stages, traces)
            row["recovery_safety_errors"] = (
                (["recovery_query_limit_exceeded"] if row["recovery_query_count"] > 1 else [])
                + (["web_source_in_internal_run"] if row["web_source_count"] else [])
            )
            row["failure_attribution"] = failure_attribution(task, row)
            rows.append(row)
            contracts.append({key: row[key] for key in ("task_id","condition","contract_generated","contract_complete",
                "contract_output_recall_observable","contract_output_precision_observable",
                "contract_unit_accuracy_observable","contract_scenario_coverage_observable",
                "contract_external_complete_observable","matched_output_ids")})
            calcs.append({key: row[key] for key in ("task_id","condition","calc_created","validated_calc_count",
                "contract_complete_calc","gt_correct_calc","calc_numeric_correct","calc_unit_correct",
                "calc_typed_correct","calc_best","grounded_adoption")})
            for item in response.get("iterations", []):
                iterations.append({"task_id": task["task_id"], "condition": condition, "iteration": item.get("iteration"),
                                   "python_seconds": item.get("timing", {}).get("python_seconds", 0),
                                   **(item.get("python_trace") or {})})
    pairs = list(zip(rows[:12], rows[12:]))
    if any(off["task_id"] != on["task_id"] for off, on in pairs):
        raise ValueError("Task-pair mismatch")
    populations = {"all_12": lambda row: True, "required_8": lambda row: row["python_expected"] == "required",
                   "pipeline_6": lambda row: row["evaluation_stratum"] == "pipeline",
                   "end_to_end_2": lambda row: row["evaluation_stratum"] == "end_to_end"}
    comparison = {"benchmark_id": benchmark["benchmark_id"], "run_id": raw["python_off"]["run_id"],
                  "product_code_sha": manifest["product_code_sha"], "scoring_status": "PRELIMINARY_PENDING_BLIND_AND_MANUAL_QA",
                  "populations": {}, "funnel": {}, "bootstrap_preliminary": {}, "rows": rows}
    for name, keep in populations.items():
        selected = [(off, on) for off, on in pairs if keep(off)]
        comparison["populations"][name] = {
            "python_off": _population_summary([off for off, _ in selected]),
            "python_on": _population_summary([on for _, on in selected]),
        }
        comparison["funnel"][name] = {stage: sum(bool(on[stage]) for _, on in selected) for stage in STAGES}
        comparison["bootstrap_preliminary"][name] = {
            metric: paired_bootstrap([(off[metric], on[metric]) for off, on in selected])
            for metric in ("goal_success_preliminary", "external_coverage_preliminary")
        }
        comparison["bootstrap_preliminary"][name]["numeric_accuracy_preliminary"] = paired_bootstrap([
            (off["numeric_correct"] / off["numeric_total"] if off["numeric_total"] else 0,
             on["numeric_correct"] / on["numeric_total"] if on["numeric_total"] else 0)
            for off, on in selected
        ])
        if name == "required_8":
            comparison["bootstrap_preliminary"][name]["unit_accuracy_preliminary"] = paired_bootstrap([
                (off["unit_correct"] / off["numeric_total"], on["unit_correct"] / on["numeric_total"])
                for off, on in selected
            ])
    required = [(off, on) for off, on in pairs if off["python_expected"] == "required"]
    comparison["required_benefit_neutral_harm_preliminary"] = dict(Counter(
        "benefit" if on["external_coverage_preliminary"] > off["external_coverage_preliminary"] else
        "harm" if on["external_coverage_preliminary"] < off["external_coverage_preliminary"] else "neutral"
        for off, on in required
    ))
    comparison["strong_python_benefit_preliminary"] = sum(strong_benefit(off, on) for off, on in required)
    comparison["weak_unattributed_numeric_improvement"] = sum(weak_numeric_improvement(off, on) for off, on in required)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "python_tool_heldout_v4_deterministic.json"
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(output_dir / "python_tool_heldout_v4_funnel.csv", [
        {"population": name, "stage": stage, "python_on_count": count,
         "n": comparison["populations"][name]["python_on"]["n"]}
        for name, stages in comparison["funnel"].items() for stage, count in stages.items()
    ])
    write_csv(output_dir / "python_tool_heldout_v4_contracts.csv", contracts)
    write_csv(output_dir / "python_tool_heldout_v4_calcs.csv", calcs)
    write_csv(output_dir / "python_tool_heldout_v4_iterations.csv", iterations)
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluation/review")
    args = parser.parse_args()
    result = score(args.run_dir, args.output_dir)
    print(json.dumps({"run_id": result["run_id"], "populations": result["populations"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
