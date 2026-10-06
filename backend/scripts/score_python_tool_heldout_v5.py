"""Independent deterministic scorer for the one frozen v5 A/B run.

Qualitative citation/engineering QA remains separately blinded and adjudicated.
"""

from __future__ import annotations

import argparse
import ast
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
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/scripts")]
from app.services.evidence_fact_registry import EvidenceFactRegistry  # noqa: E402
from app.services.formula_source_registry import FormulaSourceRegistry, normalize_formula  # noqa: E402
from app.services.user_fact_registry import UserFactRegistry  # noqa: E402
from run_python_tool_heldout_v5 import CATALOG, load_frozen  # noqa: E402

PREFIX = "python_tool_heldout_v5"
CATALOG_DATA = json.loads(CATALOG.read_text(encoding="utf-8"))
NUM = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
CITATION = re.compile(r"\[(?:KB|FIG|WEB|CALC|USERF)\d+\]")
UNIT_PATTERNS = {
    "psi": r"\bpsi(?:a)?\b", "psia": r"\bpsia\b", "bbl": r"\bbbl\b|\bbarrels?\b",
    "stb/d": r"\bstb/d\b|\bstb/day\b", "percent": r"%|\bpercent\b",
    "percentage_point": r"percentage[ -]points?|\bpp\b",
    "dimensionless": r"\bdimensionless\b|\bunitless\b|\bratio\b|\bfraction\b",
}


def sha(value: object) -> str:
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def equivalent_name(expected: str, observed: str) -> bool:
    a, b = norm(expected), norm(observed)
    if a == b:
        return True
    # Permit e.g. A_K vs K_A, but not A and B case conflation.
    ea, oa = expected.split("_", 1), observed.split("_", 1)
    if len(ea) == len(oa) == 2 and len(ea[0]) <= 2 and len(oa[0]) <= 2 and ea[0].casefold() != oa[0].casefold():
        return False
    return len(a) >= 5 and a in b or len(b) >= 5 and b in a


def unit_equivalent(expected: str | None, observed: str | None) -> bool:
    e = (expected or "").casefold().replace(" ", "")
    o = (observed or "").casefold().replace(" ", "")
    aliases = {"percent": "%", "fraction": "dimensionless", "ratio": "dimensionless",
               "unitless": "dimensionless", "percentagepoints": "percentage_point",
               "stb/day": "stb/d"}
    return aliases.get(e, e) == aliases.get(o, o)


def traces(response: dict) -> list[dict]:
    return [item["python_trace"] for item in response.get("iterations", []) if item.get("python_trace")]


def _candidate_lines(answer: str, target: dict) -> list[str]:
    lines = [line for line in answer.replace("|", " ").splitlines() if line.strip()]
    name = target["semantic_name"]
    scenario = target.get("scenario_id")
    if scenario:
        selected = [line for line in lines if re.search(rf"(?<![A-Za-z0-9]){re.escape(scenario)}(?![A-Za-z0-9])", line, re.I)]
        lines = selected
    aliases = (name, name.replace("_", " "), name.split("_", 1)[-1].replace("_", " "))
    selected = [line for line in lines if any(alias.casefold() in line.casefold() for alias in aliases if len(alias) >= 4)]
    return selected or lines


def numeric_match(answer: str, target: dict) -> dict:
    wanted, tolerance, unit = float(target["value"]), float(target["abs_tolerance"]), target["unit"]
    for line in _candidate_lines(answer, target):
        for match in NUM.finditer(line):
            value = float(match.group().replace(",", ""))
            percent = bool(re.match(r"\s*(?:%|percent\b)", line[match.end():], re.I))
            comparable = value / 100 if unit == "dimensionless" and percent else value
            if abs(comparable - wanted) > tolerance:
                continue
            vicinity = line[max(0, match.start()-35):min(len(line), match.end()+40)]
            unit_ok = bool(re.search(UNIT_PATTERNS.get(unit, re.escape(unit)), vicinity, re.I))
            if unit == "dimensionless" and percent:
                unit_ok = True
            return {"value": True, "unit": unit_ok, "observed": value, "line": line[:400]}
    return {"value": False, "unit": False, "observed": None, "line": None}


def typed_match(answer: str, target: dict) -> bool:
    expected = target["value"]
    if isinstance(expected, str):
        token = rf"(?<![A-Za-z0-9]){re.escape(expected)}(?![A-Za-z0-9])"
        return any(re.search(token, line, re.I) and re.search(r"\b(?:leader|highest|maximum|max|argmax|top)\b", line, re.I)
                   for line in answer.splitlines())
    if isinstance(expected, list):
        for line in answer.splitlines():
            if not re.search(r"\b(?:rank|ranking|order|descending)\b|>|→|≥", line, re.I):
                continue
            positions = [re.search(rf"(?<![A-Za-z0-9]){re.escape(str(item))}(?![A-Za-z0-9])", line, re.I)
                         for item in expected]
            if all(positions) and all(positions[i].start() < positions[i+1].start()
                                      for i in range(len(positions)-1)):
                return True
        return False
    if isinstance(expected, bool):
        return ("true" if expected else "false") in answer.casefold()
    return False


def final_targets(task: dict, answer: str) -> dict:
    canonical = {row["target_id"]: row for row in task["ground_truth"]["canonical_targets"]}
    numeric = {row["semantic_name"]: numeric_match(answer, {**canonical[row["target_id"]], **row})
               for row in task["ground_truth"]["numeric_targets"]}
    typed = {row["semantic_name"]: typed_match(answer, row) for row in task["ground_truth"]["typed_targets"]}
    ranking = {row["semantic_name"]: typed[row["semantic_name"]] for row in task["ground_truth"]["ranking_targets"]}
    return {"numeric_total": len(numeric), "numeric_correct": sum(item["value"] for item in numeric.values()),
            "unit_correct": sum(item["value"] and item["unit"] for item in numeric.values()),
            "typed_total": len(typed), "typed_correct": sum(typed.values()),
            "ranking_total": len(ranking), "ranking_correct": sum(ranking.values()),
            "numeric_matches": numeric, "typed_matches": typed,
            "target_complete": all(item["value"] and item["unit"] for item in numeric.values()) and all(typed.values())}


def _source_rows(response: dict, active_ids: set[str] | None = None) -> list[dict]:
    rows = []
    for row in response.get("internal_sources", []):
        if active_ids is None or row["evidence_id"] in active_ids:
            rows.append({"evidence_id": row["evidence_id"], "source_type": "knowledge_base",
                         "locator": f"{row.get('document')} p.{row.get('page')}", "text": row.get("excerpt") or ""})
    return rows


def source_audit(task: dict, response: dict, catalog: dict, reference: dict,
                 active_ids: set[str] | None = None) -> dict:
    gt = task["ground_truth"]
    internal = [row for row in response.get("internal_sources", []) if active_ids is None or row["evidence_id"] in active_ids]
    located = {key: [row["evidence_id"] for row in internal if row.get("chunk_id") == catalog[key]["chunk_id"]]
               for key in gt["source_ids"]}
    source_rows = _source_rows(response, active_ids)
    facts = EvidenceFactRegistry.from_evidence(source_rows).records
    formulas = FormulaSourceRegistry.from_evidence(source_rows).records
    matched_facts = {}
    for handle, (source_id, name, value, unit) in reference["evidence_inputs"].items():
        match = next((row for row in facts if row.source_id in located.get(source_id, []) and
                      row.name.casefold() == name.casefold() and math.isclose(row.value, value, abs_tol=1e-9) and
                      row.unit.casefold() == unit.casefold()), None)
        matched_facts[handle] = match.fact_id if match else None
    matched_formulas = {}
    for source_id, expression in gt["formula_sources"]:
        match = next((row for row in formulas if row.source_id in located.get(source_id, []) and
                      row.expression_candidate and normalize_formula(row.raw_span) == normalize_formula(expression)), None)
        matched_formulas[expression] = match.formula_id if match else None
    users = UserFactRegistry.from_topic(task["topic"]).records
    matched_users = {name: next((row.fact_id for row in users if row.name.casefold() == name.casefold() and
                                  math.isclose(row.value, value, abs_tol=1e-9) and row.unit.casefold() == unit.casefold()), None)
                     for name, value, unit in gt["expected_user_facts"]}
    ready = all(located.values()) and all(matched_facts.values()) and all(matched_formulas.values()) and all(matched_users.values())
    return {"source_retrieved": {key: bool(ids) for key, ids in located.items()},
            "matched_evidence_fact_ids": matched_facts, "matched_formula_ids": matched_formulas,
            "matched_user_fact_ids": matched_users,
            "source_complete_external": ready,
            "formula_expected": len(gt["formula_sources"]),
            "formula_found": sum(bool(value) for value in matched_formulas.values()),
            "efact_expected": len(gt["expected_evidence_facts"]),
            "efact_found": sum(bool(value) for value in matched_facts.values()),
            "userf_expected": len(gt["expected_user_facts"]),
            "userf_found": sum(bool(value) for value in matched_users.values())}


def binding_audit(task: dict, response: dict, source: dict) -> dict:
    expected = task["ground_truth"]["expected_bindings"]
    total = sum(map(len, expected.values()))
    fact_ids = {**source["matched_user_fact_ids"], **source["matched_evidence_fact_ids"]}
    graphs = [(trace.get("requirement_graph") or {}) for trace in traces(response)]
    best = {"correct": 0, "bound": 0, "missing": total, "ambiguous": 0, "unit_mismatch": 0,
            "scenario_errors": 0, "graph": None}
    for graph in graphs:
        requirements = graph.get("formula_variables") or []
        correct, bound, scenario_errors = 0, 0, 0
        for scenario, mapping in expected.items():
            for variable, authored in mapping.items():
                candidates = [item for item in requirements if norm(str(item.get("variable_name") or "")) == norm(variable)
                              and str(item.get("scenario_id") or "default").casefold() == scenario.casefold()]
                if not candidates:
                    scenario_errors += 1
                    continue
                item = candidates[0]
                bound += item.get("status") == "bound"
                correct += bool(item.get("status") == "bound" and fact_ids.get(authored) and
                                item.get("bound_fact_id") == fact_ids[authored])
        candidate = {"correct": correct, "bound": bound, "missing": len(graph.get("missing_variables") or []),
                     "ambiguous": len(graph.get("ambiguous_variables") or []),
                     "unit_mismatch": len(graph.get("unit_mismatch_variables") or []),
                     "scenario_errors": scenario_errors, "graph": graph}
        if best["graph"] is None or (candidate["correct"], candidate["bound"]) > (best["correct"], best["bound"]):
            best = candidate
    graph = best["graph"] or {}
    bound_ids = {row.get("bound_fact_id") for row in graph.get("formula_variables", []) if row.get("status") == "bound"}
    user_ids = set(source["matched_user_fact_ids"].values()) - {None}
    evidence_ids = set(source["matched_evidence_fact_ids"].values()) - {None}
    initial_binding = None if any(trace.get("recovery_triggered") for trace in traces(response)) else (
        bool(total and best["correct"] == total) if expected else None)
    return {"binding_required": total, "binding_correct": best["correct"], "binding_bound": best["bound"],
            "binding_complete": bool(total and best["correct"] == total) if expected else None,
            "initial_binding_complete_observable": initial_binding,
            "userf_runtime_bound": len(bound_ids & user_ids), "efact_runtime_bound": len(bound_ids & evidence_ids),
            "formula_runtime_bound": bool(graph.get("formula_id") and
                                         graph.get("formula_id") in set(source["matched_formula_ids"].values())),
            "binding_missing_count": best["missing"], "binding_ambiguous_count": best["ambiguous"],
            "binding_unit_mismatch_count": best["unit_mismatch"],
            "cross_scenario_binding_errors": best["scenario_errors"], "best_requirement_graph": best["graph"]}


def recovery_audit(task: dict, response: dict, catalog: dict, reference: dict) -> dict:
    items = response.get("iterations", [])
    initial_ids: set[str] = set()
    all_ids: set[str] = set()
    rounds = []
    initial_frozen = False
    false_positive = false_negative = 0
    first_ready = None
    for item in items:
        trace = item.get("python_trace") or {}
        recovered = {source_id for round_item in trace.get("recovery_rounds", [])
                     for source_id in round_item.get("new_source_ids", [])}
        additions = set(item.get("evidence_added") or [])
        all_ids.update(additions - recovered)
        if not initial_frozen:
            initial_ids.update(additions - recovered)
        if trace.get("recovery_triggered") and not initial_frozen:
            initial_frozen = True
            first_ready = source_audit(task, response, catalog, reference, initial_ids)
        for round_item in trace.get("recovery_rounds", []):
            before = source_audit(task, response, catalog, reference, all_ids)
            all_ids.update(round_item.get("new_source_ids", []))
            after = source_audit(task, response, catalog, reference, all_ids)
            before_hits = sum(before["source_retrieved"].values()) + before["efact_found"] + before["formula_found"]
            after_hits = sum(after["source_retrieved"].values()) + after["efact_found"] + after["formula_found"]
            rounds.append({"round": round_item.get("round"), "product_required_gain": bool(round_item.get("required_gain")),
                           "external_required_gain": after_hits > before_hits,
                           "external_source_complete_after": after["source_complete_external"],
                           "new_source_ids": round_item.get("new_source_ids", []),
                           "query": round_item.get("query", "")})
        state = source_audit(task, response, catalog, reference, all_ids)
        if trace.get("source_complete") is True:
            single_binding = binding_audit(task, {"iterations": [item]}, state)
            if not state["source_complete_external"] or (single_binding["binding_required"] and
                    not single_binding["binding_complete"]):
                false_positive += 1
        if trace.get("source_complete") is False and state["source_complete_external"]:
            false_negative += 1
    if first_ready is None:
        first_ready = source_audit(task, response, catalog, reference, initial_ids)
    post = source_audit(task, response, catalog, reference, all_ids if items else None)
    query_leaks = []
    source_ids = {row["chunk_id"] for row in catalog.values()}
    for round_item in rounds:
        query = round_item["query"]
        if any(chunk in query for chunk in source_ids):
            query_leaks.append("hidden_source_chunk_id")
        if any(str(target["value"]) in query for target in task["ground_truth"]["canonical_targets"]
               if target["target_type"] == "numeric" and abs(target["value"]) >= 10):
            query_leaks.append("possible_gt_numeric_leak")
    return {"initial_source_complete_external": first_ready["source_complete_external"],
            "post_recovery_source_complete_external": post["source_complete_external"],
            "recovery_source_complete_gain": bool(post["source_complete_external"] and
                                                  not first_ready["source_complete_external"]),
            "initial_formula_found": first_ready["formula_found"], "post_formula_found": post["formula_found"],
            "initial_efact_found": first_ready["efact_found"], "post_efact_found": post["efact_found"],
            "recovery_triggered": bool(rounds), "recovery_round_count": len(rounds),
            "recovery_round_1_required_gain": bool(rounds and rounds[0]["external_required_gain"]),
            "recovery_round_2_required_gain": bool(len(rounds) > 1 and rounds[1]["external_required_gain"]),
            "recovery_required_gain_count": sum(row["external_required_gain"] for row in rounds),
            "recovery_success": any(row["external_required_gain"] for row in rounds),
            "source_complete_false_positive_count": false_positive,
            "source_complete_false_negative_count": false_negative,
            "recovery_rounds_external": rounds,
            "recovery_safety_errors": (["recovery_query_limit_exceeded"] if len(rounds) > 2 else []) +
                                      (["web_source_in_internal_run"] if response.get("web_sources") else []) + query_leaks,
            "post_source_audit": post}


def _intent_covers(target: dict, item: dict) -> bool:
    semantic = str(item.get("semantic_name") or "").casefold()
    scenario = target.get("scenario_id")
    if scenario:
        return semantic == "per_case" and str(item.get("scenario_id") or "").casefold() == scenario.casefold()
    name = target["semantic_name"].casefold()
    if target["target_type"] == "ranking":
        return semantic == "ranking"
    if name.startswith("mean_"):
        return semantic == "mean"
    if name.startswith("max_"):
        return semantic == "maximum"
    if name.startswith("min_"):
        return semantic == "minimum"
    return semantic == name


def checklist_audit(task: dict, response: dict) -> dict:
    targets = task["ground_truth"]["canonical_targets"]
    checklists = [trace.get("required_output_checklist") or [] for trace in traces(response)]
    best = []
    for checklist in checklists:
        matches = [target for target in targets if any(_intent_covers(target, item) for item in checklist)]
        if len(matches) > len(best):
            best = matches
    scenario_targets = [target for target in targets if target.get("scenario_id")]
    aggregate_targets = [target for target in targets if not target.get("scenario_id")]
    return {"checklist_built": any(checklists), "checklist_output_recall": len(best) / len(targets) if targets else None,
            "checklist_scenario_coverage": sum(target in best for target in scenario_targets) / len(scenario_targets) if scenario_targets else None,
            "checklist_aggregate_coverage": sum(target in best for target in aggregate_targets) / len(aggregate_targets) if aggregate_targets else None,
            "checklist_missing_targets": [target["semantic_name"] for target in targets if target not in best]}


def _output_match(target: dict, outputs: list[dict]) -> dict | None:
    exact = [row for row in outputs if norm(str(row.get("name") or row.get("output_id") or "")) == norm(target["semantic_name"])]
    candidates = exact or [row for row in outputs if equivalent_name(target["semantic_name"],
                   str(row.get("name") or row.get("output_id") or ""))]
    if target.get("scenario_id"):
        candidates = [row for row in candidates if str(row.get("scenario_id") or "").casefold() ==
                      target["scenario_id"].casefold()]
    return candidates[0] if candidates else None


def _contract_metrics(task: dict, contract: dict) -> dict:
    targets = task["ground_truth"]["canonical_targets"]
    outputs = contract.get("required_outputs") or []
    matched = {target["semantic_name"]: _output_match(target, outputs) for target in targets}
    found = [row for row in matched.values() if row]
    numeric = [target for target in targets if target["target_type"] == "numeric"]
    units = sum(bool(matched[target["semantic_name"]] and unit_equivalent(target["unit"],
                matched[target["semantic_name"]].get("unit"))) for target in numeric)
    types = sum(bool(matched[target["semantic_name"]] and
                matched[target["semantic_name"]].get("semantic_type") == target["target_type"])
                for target in targets)
    scenarios = [target for target in targets if target.get("scenario_id")]
    scenario_hits = sum(bool(matched[target["semantic_name"]]) for target in scenarios)
    complete = len(found) == len(targets) and units == len(numeric) and types == len(targets)
    return {"contract_output_recall": len(found) / len(targets) if targets else None,
            "contract_output_precision": len({id(row) for row in found}) / len(outputs) if outputs else None,
            "contract_unit_accuracy": units / len(numeric) if numeric else None,
            "contract_scenario_coverage": scenario_hits / len(scenarios) if scenarios else None,
            "external_contract_complete": complete,
            "matched_contract_outputs": {key: row.get("output_id") if row else None for key, row in matched.items()}}


def contract_audit(task: dict, response: dict) -> dict:
    candidates = [trace.get("calculation_contract") for trace in traces(response) if trace.get("calculation_contract")]
    best = None
    for candidate in candidates:
        metrics = _contract_metrics(task, candidate)
        if best is None or (metrics["external_contract_complete"], metrics["contract_output_recall"]) > (
                best["external_contract_complete"], best["contract_output_recall"]):
            best = metrics
    best = best or {"contract_output_recall": None, "contract_output_precision": None,
                    "contract_unit_accuracy": None, "contract_scenario_coverage": None,
                    "external_contract_complete": False, "matched_contract_outputs": {}}
    return {"contract_generated": bool(candidates),
            "product_contract_complete": any(trace.get("contract_complete") for trace in traces(response)),
            "contract_attempts": sum(trace.get("contract_attempts", 0) for trace in traces(response)), **best}


def assumption_audit(task: dict, response: dict, reference: dict) -> dict:
    allowed = {float(value) for _, value, _ in reference["inputs"]} | {
        float(row[2]) for row in reference["evidence_inputs"].values()}
    physical = re.compile(r"(?i)(?:thickness|porosity|permeability|viscosity|compressibility|radius|\bdx\b)")
    unsupported = []
    literal_candidates = []
    for calc in response.get("computations", []):
        code = calc.get("code_record") or ""
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)):
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                value = float(node.value.value)
                if any(physical.search(name) for name in names) and value not in allowed:
                    unsupported.append({"calc_id": calc.get("computation_id"), "variables": names, "value": value})
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                value = float(node.value)
                if value not in allowed and value not in {0, 1, 2, 100}:
                    literal_candidates.append(value)
    guards = [trace.get("assumption_guard_passed") for trace in traces(response)]
    passed = any(value is True for value in guards)
    return {"assumption_guard_pass": passed, "assumption_guard_blocks": sum(value is False for value in guards),
            "unsupported_physical_assumptions": unsupported,
            "unsupported_literal_candidates": sorted(set(literal_candidates)),
            "assumption_guard_false_negative": bool(passed and unsupported)}


def calc_audit(task: dict, response: dict, source: dict, binding: dict,
               contract: dict, assumption: dict, final: dict) -> dict:
    targets = task["ground_truth"]["canonical_targets"]
    required_fact_ids = set(source["matched_user_fact_ids"].values()) | set(source["matched_evidence_fact_ids"].values())
    required_fact_ids.discard(None)
    formula_evidence_ids = {row["evidence_id"] for row in response.get("internal_sources", []) if any(
        row.get("chunk_id") == catalog_row["chunk_id"] for catalog_row in
        (CATALOG_DATA[key] for key, _ in task["ground_truth"]["formula_sources"]))}
    scored = []
    for calc in response.get("computations", []):
        outputs = [{"output_id": key, **entry} for key, entry in (calc.get("output_manifest") or {}).items()]
        matches = {target["semantic_name"]: _output_match(target, outputs) for target in targets}
        matched = [row for row in matches.values() if row]
        numeric = [target for target in targets if target["target_type"] == "numeric"]
        numeric_hits = sum(bool((row := matches[target["semantic_name"]]) and
                               isinstance(row.get("value"), (int, float)) and not isinstance(row.get("value"), bool) and
                               abs(row["value"] - target["value"]) <= target["abs_tolerance"])
                           for target in numeric)
        unit_hits = sum(bool((row := matches[target["semantic_name"]]) and
                             unit_equivalent(target["unit"], row.get("unit"))) for target in numeric)
        typed = [target for target in targets if target["target_type"] != "numeric"]
        typed_hits = sum(bool((row := matches[target["semantic_name"]]) and row.get("value") == target["value"])
                         for target in typed)
        ranking_hits = sum(bool((row := matches[target["semantic_name"]]) and row.get("value") == target["value"])
                           for target in targets if target["target_type"] == "ranking")
        type_hits = sum(bool((row := matches[target["semantic_name"]]) and
                             row.get("semantic_type") == target["target_type"]) for target in targets)
        unit_complete = unit_hits == len(numeric)
        output_complete = len(matched) == len(targets) and type_hits == len(targets) and unit_complete
        source_ready = source["source_complete_external"]
        bound = not binding["binding_required"] or binding["binding_complete"]
        used_inputs = required_fact_ids <= set(calc.get("used_input_ids") or [])
        formula_provenance = not formula_evidence_ids or formula_evidence_ids <= set(calc.get("formula_evidence_ids") or [])
        assumption_clean = not assumption["unsupported_physical_assumptions"] and assumption["assumption_guard_pass"]
        external_valid = bool(output_complete and contract["external_contract_complete"] and source_ready and bound and used_inputs and
                              formula_provenance and assumption_clean and calc.get("contract_validation_passed"))
        gt_correct = bool(external_valid and numeric_hits == len(numeric) and typed_hits == len(typed))
        answer = response.get("final_answer") or ""
        calc_cited = f"[{calc.get('computation_id')}]" in answer
        source_cited = all(any(f"[{row['evidence_id']}]" in answer for row in response.get("internal_sources", [])
                               if row.get("chunk_id") == CATALOG_DATA[key]["chunk_id"])
                           for key in task["ground_truth"]["source_ids"])
        final_complete = final["target_complete"]
        grounded = bool(gt_correct and calc_cited and source_cited and final_complete and
                        any(trace.get("calc_grounding_validation_passed") is True for trace in traces(response)))
        adopted_targets = final["numeric_correct"] + final["typed_correct"] if calc_cited and gt_correct else 0
        scored.append({"calc_id": calc.get("computation_id"), "product_validated": bool(calc.get("validation_passed")),
                       "externally_contract_complete": output_complete, "externally_valid": external_valid,
                       "gt_correct": gt_correct, "grounded_adoption": grounded,
                       "numeric_correct": numeric_hits, "numeric_total": len(numeric),
                       "unit_correct": unit_hits, "typed_correct": typed_hits, "typed_total": len(typed),
                       "ranking_correct": ranking_hits, "scenario_complete": len(matched) == len(targets),
                       "required_inputs_used": used_inputs, "formula_provenance_valid": formula_provenance,
                       "calc_cited": calc_cited, "source_cited": source_cited,
                       "adopted_target_count": adopted_targets, "matched_outputs": {
                           key: row.get("output_id") if row else None for key, row in matches.items()}})
    best = max(scored, key=lambda row: (row["gt_correct"], row["externally_valid"],
                                         row["externally_contract_complete"], row["numeric_correct"]), default=None)
    return {"calc_created": bool(scored), "product_validated_calc": any(row["product_validated"] for row in scored),
            "externally_contract_complete_calc": any(row["externally_contract_complete"] for row in scored),
            "externally_valid_calc": any(row["externally_valid"] for row in scored),
            "gt_correct_calc": any(row["gt_correct"] for row in scored),
            "grounded_adoption": any(row["grounded_adoption"] for row in scored),
            "adoption_coverage": max((row["adopted_target_count"] / len(targets) for row in scored), default=0),
            "calc_numeric_correct": best["numeric_correct"] if best else 0,
            "calc_unit_correct": best["unit_correct"] if best else 0,
            "calc_typed_correct": best["typed_correct"] if best else 0,
            "calc_ranking_correct": best["ranking_correct"] if best else 0,
            "calc_scenario_complete": bool(best and best["scenario_complete"]),
            "calc_best": best, "all_calc_scores": scored}


def stage_audit(response: dict, recovery: dict, binding: dict, checklist: dict,
                contract: dict, assumption: dict, calc: dict) -> dict:
    all_traces = traces(response)
    anyt = lambda key: any(bool(trace.get(key)) for trace in all_traces)
    steps = {
        1: any(trace.get("planner_decision_status") not in (None, "planner_decision_parse_failed") for trace in all_traces),
        2: anyt("tool_selected"),
        3: anyt("plan_present"),
        4: any(trace.get("requirement_graph") for trace in all_traces),
        5: binding["binding_complete"] is True,
        6: recovery["initial_source_complete_external"],
        7: recovery["recovery_success"],
        8: recovery["post_recovery_source_complete_external"],
        9: checklist["checklist_built"],
        10: contract["contract_generated"],
        11: contract["external_contract_complete"],
        12: assumption["assumption_guard_pass"],
        13: anyt("call_boundary_reached"),
        14: anyt("code_generated"),
        15: anyt("sandbox_validation_passed"),
        16: anyt("subprocess_reached"),
        17: calc["product_validated_calc"],
        18: calc["externally_valid_calc"],
        19: calc["gt_correct_calc"],
        20: calc["grounded_adoption"],
    }
    errors = []
    for trace in all_traces:
        graph = trace.get("requirement_graph") or {}
        if trace.get("source_complete") and graph.get("missing_variables"):
            errors.append("source_complete_with_missing_variables")
        if graph.get("source_complete") and graph.get("ambiguous_variables"):
            errors.append("binding_complete_with_ambiguity")
        if trace.get("contract_complete") and trace.get("missing_requested_outputs"):
            errors.append("contract_complete_with_missing_checklist")
    if calc["product_validated_calc"] and not steps[16]:
        errors.append("validated_calc_without_subprocess")
    if calc["externally_valid_calc"] and not recovery["post_recovery_source_complete_external"]:
        errors.append("external_calc_without_source_complete")
    if calc["gt_correct_calc"] and not contract["external_contract_complete"]:
        errors.append("gt_correct_without_external_contract")
    if calc["grounded_adoption"] and not calc["gt_correct_calc"]:
        errors.append("adoption_without_grounding")
    return {"furthest_stage": max((stage for stage, reached in steps.items() if reached), default=0),
            "stages": {str(stage): bool(reached) for stage, reached in steps.items()},
            "trace_integrity_errors": sorted(set(errors))}


def failure_attribution(task: dict, row: dict) -> list[str]:
    if row["goal_success_deterministic"]:
        return []
    labels = []
    if not all(row["source_retrieved"].values()):
        labels.append("retrieval_source_missing")
    if row["post_efact_found"] < row["efact_expected"]:
        labels.append("efact_registry_missing")
    if row["post_formula_found"] < row["formula_expected"]:
        labels.append("formula_registry_missing")
    if task["python_expected"] == "required" and row["condition"] == "python_on":
        if row["binding_required"] and not row["binding_complete"]:
            labels.append("binding_ambiguous" if row["binding_ambiguous_count"] else
                          "binding_unit_mismatch" if row["binding_unit_mismatch_count"] else "binding_missing")
        if row["source_complete_false_positive_count"]:
            labels.append("source_complete_false_positive")
        if row["source_complete_false_negative_count"]:
            labels.append("source_complete_false_negative")
        if row["recovery_triggered"] and not row["recovery_success"]:
            labels.append("recovery_no_required_gain")
        if row["recovery_round_count"] >= 2 and not row["post_recovery_source_complete_external"]:
            labels.append("recovery_budget_exhausted")
        blocked = {trace.get("blocked_stage") for trace in row["python_traces"]}
        if "planner_decision_parse_failed" in blocked:
            labels.append("planner_parse_failed")
        if "planner_plan_parse_failed" in blocked or "materialization_failed" in blocked:
            labels.append("plan_materialization_failed")
        if "calculation_contract_parse_failed" in blocked:
            labels.append("contract_parse_failed")
        if "assumption_guard_failed" in blocked:
            labels.append("assumption_guard_blocked")
        if "CALC_INCOMPLETE_OUTPUTS" in blocked:
            labels.append("result_schema_failed")
        if row["checklist_output_recall"] is not None and row["checklist_output_recall"] < 1:
            labels.append("checklist_incomplete")
        if row["contract_generated"] and not row["external_contract_complete"]:
            labels.append("contract_incomplete")
        if row["assumption_guard_false_negative"]:
            labels.append("assumption_guard_false_negative")
        if not row["stages"]["14"] and row["stages"]["13"]:
            labels.append("code_generation_failed")
        if row["stages"]["14"] and not row["stages"]["15"]:
            labels.append("sandbox_failed")
        if row["stages"]["15"] and not row["stages"]["16"]:
            labels.append("runtime_failed")
        if row["product_validated_calc"] and not row["externally_contract_complete_calc"]:
            labels.append("result_contract_incomplete")
        if row["externally_valid_calc"] and not row["gt_correct_calc"]:
            labels.append("calc_gt_incorrect")
        if row["gt_correct_calc"] and not row["grounded_adoption"]:
            labels.append("calc_grounding_failed" if row["calc_grounding_failure_reasons"] else "final_adoption_failed")
    if row["final_leakage"]:
        labels.append("final_response_leak")
    return labels or (["final_synthesis"] if row["numeric_correct"] < row["numeric_total"] else ["other"])


def citation_mapping(response: dict) -> dict:
    mapping = {f"[{row['evidence_id']}]": [row.get("document"), row.get("page"), row.get("chunk_id")]
               for row in response.get("internal_sources", [])}
    mapping.update({f"[{row['computation_id']}]":[row.get("source_evidence_ids"), row.get("source_input_ids"),
                                                     row.get("formula_evidence_ids")]
                    for row in response.get("computations", [])})
    return {key: mapping.get(key) for key in sorted(set(CITATION.findall(response.get("final_answer") or "")))}


def _final_leakage(answer: str) -> list[str]:
    patterns = {
        "internal_schema_leak": r"(?i)\b(?:output_ids|formula_id|source_fact_ids|requirement_graph|calculation_contract)\b",
        "internal_instruction_leak": r"(?i)(?:every material claim must be cited|response schema failed|untrusted evidence)",
        "raw_output_id_leak": r"\bOUT_[A-Za-z0-9_]+\b",
    }
    return [key for key, pattern in patterns.items() if re.search(pattern, answer)]


def score_one(task: dict, raw_row: dict, catalog: dict, reference: dict) -> dict:
    response = raw_row.get("response") or {}
    answer = response.get("final_answer") or ""
    final = final_targets(task, answer)
    recovery = recovery_audit(task, response, catalog, reference)
    source = recovery.pop("post_source_audit")
    binding = binding_audit(task, response, source)
    checklist = checklist_audit(task, response)
    contract = contract_audit(task, response)
    assumption = assumption_audit(task, response, reference)
    calc = calc_audit(task, response, source, binding, contract, assumption, final)
    stage = stage_audit(response, recovery, binding, checklist, contract, assumption, calc)
    c1 = source["source_complete_external"] and bool(answer.strip())
    c2 = final["target_complete"]
    criteria = {"C1": c1, "C2": c2, "C3": None}
    row = {
        "task_id": task["task_id"], "condition": raw_row["condition"], "domain": task["domain"],
        "python_expected": task["python_expected"], "evaluation_stratum": task["evaluation_stratum"],
        "recovery_challenge": task.get("recovery_challenge"),
        "elapsed_seconds": raw_row["elapsed_seconds"], "product_exception": raw_row.get("product_exception"),
        "product_status": response.get("status"), "internal_goal_coverage": response.get("goal_coverage"),
        "criterion_pass_preliminary": criteria,
        "external_coverage_deterministic": (int(c1) + int(c2)) / 2,
        "goal_success_deterministic": bool(c1 and c2),
        "qualitative_C3_pending": True,
        "answer_sha256": sha(answer.encode()), "citation_mapping_sha256": sha(citation_mapping(response)),
        "citation_mapping": citation_mapping(response), "final_answer": answer,
        "python_calls_total": response.get("python_calls_total", 0),
        "python_attempts_total": response.get("python_attempts_total", 0),
        "python_seconds": sum(item.get("timing", {}).get("python_seconds", 0) for item in response.get("iterations", [])),
        "planner_decisions_before_recovery": sum(bool(trace.get("planner_decision_attempts")) for trace in traces(response)
                                                if not trace.get("recovery_triggered")),
        "planner_decisions_after_recovery": sum(bool(trace.get("planner_decision_attempts")) for trace in traces(response)
                                               if trace.get("recovery_triggered")),
        "web_source_count": len(response.get("web_sources", [])),
        "engineering_contradiction_count": sum(item.get("engineering_contradiction_count", 0) for item in response.get("iterations", [])),
        "unsupported_engineering_claim_count": sum(item.get("unsupported_engineering_claim_count", 0) for item in response.get("iterations", [])),
        "final_leakage": _final_leakage(answer),
        "calc_grounding_failure_reasons": [reason for trace in traces(response) for reason in trace.get("calc_grounding_failures", [])],
        "python_traces": traces(response),
        **final, **source, **recovery, **binding, **checklist, **contract, **assumption, **calc, **stage,
    }
    row["internal_external_calibration_error"] = (abs(row["internal_goal_coverage"] - row["external_coverage_deterministic"])
                                                   if isinstance(row["internal_goal_coverage"], (int, float)) else None)
    row["failure_attribution"] = failure_attribution(task, row)
    row.pop("python_traces")
    return row


def strong_benefit(off: dict, on: dict) -> bool:
    return bool(not off["criterion_pass_preliminary"]["C2"] and on["gt_correct_calc"] and
                on["grounded_adoption"] and on["criterion_pass_preliminary"]["C2"])


def weak_numeric_improvement(off: dict, on: dict) -> bool:
    return bool(on["numeric_correct"] > off["numeric_correct"] and not
                (on["gt_correct_calc"] and on["grounded_adoption"]))


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


def _population_summary(rows: list[dict]) -> dict:
    latencies = sorted(row["elapsed_seconds"] for row in rows)
    numeric = sum(row["numeric_total"] for row in rows)
    typed = sum(row["typed_total"] for row in rows)
    rank = sum(row["ranking_total"] for row in rows)
    return {
        "n": len(rows),
        "goal_success_deterministic": statistics.mean(row["goal_success_deterministic"] for row in rows) if rows else None,
        "external_coverage_deterministic": statistics.mean(row["external_coverage_deterministic"] for row in rows) if rows else None,
        "numeric_accuracy": sum(row["numeric_correct"] for row in rows) / numeric if numeric else None,
        "unit_accuracy": sum(row["unit_correct"] for row in rows) / numeric if numeric else None,
        "typed_accuracy": sum(row["typed_correct"] for row in rows) / typed if typed else None,
        "ranking_accuracy": sum(row["ranking_correct"] for row in rows) / rank if rank else None,
        "latency_mean": statistics.mean(latencies) if latencies else None,
        "latency_median": statistics.median(latencies) if latencies else None,
        "latency_p95": latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                          for key, value in row.items()} for row in rows)


def score(run_dir: Path, output_dir: Path) -> dict:
    benchmark, manifest = load_frozen()
    raw = {name: json.loads((run_dir / f"{name}.json").read_text(encoding="utf-8"))
           for name in ("python_off", "python_on")}
    expected_ids = [task["task_id"] for task in benchmark["tasks"]]
    for name, payload in raw.items():
        if not payload["complete"] or payload["benchmark_sha256"] != manifest["benchmark_sha256"] or (
                [row["task_id"] for row in payload["results"]] != expected_ids):
            raise ValueError(f"Incomplete or altered {name} run")
    if raw["python_off"]["run_id"] != raw["python_on"]["run_id"]:
        raise ValueError("OFF/ON are not one paired run")
    reference = json.loads((ROOT / "evaluation/reference/python_tool_heldout_v5_reference_outputs.json").read_text(encoding="utf-8"))
    rows = [score_one(task, raw[name]["results"][index], CATALOG_DATA, reference[task["task_id"]])
            for name in ("python_off", "python_on") for index, task in enumerate(benchmark["tasks"])]
    pairs = list(zip(rows[:12], rows[12:]))
    if any(off["task_id"] != on["task_id"] for off, on in pairs):
        raise ValueError("OFF/ON task identities differ")
    populations = {
        "all_12": lambda row: True,
        "required_8": lambda row: row["python_expected"] == "required",
        "pipeline_6": lambda row: row["evaluation_stratum"].startswith("pipeline"),
        "direct_4": lambda row: row["evaluation_stratum"] == "pipeline_direct",
        "recovery_challenge_2": lambda row: row["evaluation_stratum"] == "pipeline_recovery_challenge",
        "end_to_end_2": lambda row: row["evaluation_stratum"] == "end_to_end",
        "optional_2": lambda row: row["python_expected"] == "optional",
        "not_needed_2": lambda row: row["python_expected"] == "not_needed",
    }
    comparison = {"benchmark_id": PREFIX, "run_id": raw["python_off"]["run_id"],
                  "product_code_sha": manifest["product_code_sha"], "freeze_commit_sha": manifest["freeze_commit_sha"],
                  "status": "DETERMINISTIC_PRELIMINARY_PENDING_BLIND_AND_MANUAL_QA",
                  "populations": {}, "funnel": {}, "paired_bootstrap": {}, "rows": rows}
    for name, keep in populations.items():
        selected = [(off, on) for off, on in pairs if keep(off)]
        comparison["populations"][name] = {"python_off": _population_summary([off for off, _ in selected]),
                                          "python_on": _population_summary([on for _, on in selected])}
        comparison["funnel"][name] = {str(stage): sum(on["stages"][str(stage)] for _, on in selected)
                                       for stage in range(1, 21)}
        if name in ("all_12", "required_8", "pipeline_6"):
            metrics = {
                "goal_success_deterministic": [(float(off["goal_success_deterministic"]), float(on["goal_success_deterministic"]))
                                               for off, on in selected],
                "external_coverage_deterministic": [(off["external_coverage_deterministic"], on["external_coverage_deterministic"])
                                                    for off, on in selected],
                "numeric_accuracy": [(off["numeric_correct"] / off["numeric_total"] if off["numeric_total"] else 0,
                                      on["numeric_correct"] / on["numeric_total"] if on["numeric_total"] else 0)
                                     for off, on in selected],
            }
            if name == "required_8":
                metrics["unit_accuracy"] = [(off["unit_correct"] / off["numeric_total"],
                                             on["unit_correct"] / on["numeric_total"]) for off, on in selected]
            comparison["paired_bootstrap"][name] = {metric: paired_bootstrap(values) for metric, values in metrics.items()}
    required = [(off, on) for off, on in pairs if off["python_expected"] == "required"]
    comparison["required_benefit_neutral_harm_deterministic"] = dict(Counter(
        "benefit" if on["external_coverage_deterministic"] > off["external_coverage_deterministic"] else
        "harm" if on["external_coverage_deterministic"] < off["external_coverage_deterministic"] else "neutral"
        for off, on in required))
    comparison["strong_python_benefit_deterministic"] = sum(strong_benefit(off, on) for off, on in required)
    comparison["weak_unattributed_numeric_improvement"] = sum(weak_numeric_improvement(off, on) for off, on in required)
    comparison["identical_answer_pairs"] = sum(off["answer_sha256"] == on["answer_sha256"] for off, on in pairs)
    comparison["identical_citation_pairs"] = sum(off["citation_mapping_sha256"] == on["citation_mapping_sha256"] for off, on in pairs)
    comparison["trace_integrity_error_count"] = sum(len(row["trace_integrity_errors"]) for row in rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{PREFIX}_deterministic.json"
    if target.exists():
        raise FileExistsError("Deterministic result already exists; raw baseline may not be rescored in place")
    target.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(output_dir / f"{PREFIX}_bindings.csv", [{key: row[key] for key in (
        "task_id", "condition", "binding_required", "binding_bound", "binding_correct", "binding_complete",
        "binding_missing_count", "binding_ambiguous_count", "binding_unit_mismatch_count", "cross_scenario_binding_errors")}
        for row in rows])
    _write_csv(output_dir / f"{PREFIX}_recovery.csv", [{key: row[key] for key in (
        "task_id", "condition", "initial_source_complete_external", "recovery_triggered", "recovery_round_count",
        "recovery_round_1_required_gain", "recovery_round_2_required_gain", "recovery_success",
        "post_recovery_source_complete_external", "source_complete_false_positive_count",
        "source_complete_false_negative_count", "recovery_rounds_external")}
        for row in rows])
    _write_csv(output_dir / f"{PREFIX}_contracts.csv", [{key: row[key] for key in (
        "task_id", "condition", "checklist_output_recall", "checklist_scenario_coverage", "contract_generated",
        "product_contract_complete", "external_contract_complete", "contract_output_recall",
        "contract_output_precision", "contract_unit_accuracy", "contract_scenario_coverage")}
        for row in rows])
    _write_csv(output_dir / f"{PREFIX}_calcs.csv", [{key: row[key] for key in (
        "task_id", "condition", "assumption_guard_pass", "assumption_guard_false_negative", "calc_created",
        "product_validated_calc", "externally_contract_complete_calc", "externally_valid_calc", "gt_correct_calc",
        "calc_numeric_correct", "calc_unit_correct", "calc_typed_correct", "calc_ranking_correct",
        "grounded_adoption", "adoption_coverage", "calc_best")}
        for row in rows])
    _write_csv(output_dir / f"{PREFIX}_funnel.csv", [
        {"population": name, "stage": stage, "python_on_count": count,
         "n": comparison["populations"][name]["python_on"]["n"]}
        for name, stages in comparison["funnel"].items() for stage, count in stages.items()])
    _write_csv(output_dir / f"{PREFIX}_iterations.csv", [
        {"task_id": task["task_id"], "condition": name, "iteration": item.get("iteration"),
         "python_seconds": item.get("timing", {}).get("python_seconds", 0), **(item.get("python_trace") or {})}
        for name in ("python_off", "python_on") for task, raw_row in zip(benchmark["tasks"], raw[name]["results"])
        for item in (raw_row.get("response") or {}).get("iterations", [])])
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluation/review")
    args = parser.parse_args()
    result = score(args.run_dir, args.output_dir)
    print(json.dumps({"run_id": result["run_id"], "populations": result["populations"],
                      "strong_python_benefit_deterministic": result["strong_python_benefit_deterministic"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
