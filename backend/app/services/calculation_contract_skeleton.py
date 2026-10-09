"""Immutable output/provenance shape assembled from request intent and bound facts."""

from __future__ import annotations

import re

from app.models.goal_research_schemas import CalculationContract, CalculationOutputSpec, CalculationScenario
from app.services.calculation_request_ir import CalculationRequestIR
from app.services.calculation_requirements import CalculationRequirementGraph, normalize_symbol, scenario_fact_match
from app.services.goal_tool_planner import PythonAnalysisPlan
from app.services.required_outputs import RequiredOutputIntent


def _unit(intent: RequiredOutputIntent, common: str | None) -> str | None:
    if intent.output_type != "numeric":
        return None
    if intent.semantic_name == "normalize_by_max":
        return "dimensionless"
    if intent.semantic_name in {"coefficient_of_variation", "percent_change"}:
        return "percent"
    if intent.requested_unit:
        return intent.requested_unit
    if intent.semantic_name == "variance_population" and common:
        return f"{common}^2"
    return common


def _scenario_bindings(ir: CalculationRequestIR, plan: PythonAnalysisPlan,
                       graph: CalculationRequirementGraph) -> dict[str, dict[str, str]]:
    if graph.formula_id and graph.scenario_bindings:
        return graph.scenario_bindings
    if ir.scenarios:
        rows: dict[str, dict[str, str]] = {}
        for scenario in ir.scenarios:
            key = normalize_symbol(scenario.scenario_id)
            matches = {fact.name: fact.canonical_fact_id or fact.evidence_id for fact in plan.input_facts
                       if scenario_fact_match(fact.name, key)}
            if matches:
                rows[scenario.scenario_id] = matches
        if rows:
            return rows
    return {"default": {fact.name: fact.canonical_fact_id or fact.evidence_id for fact in plan.input_facts}}


def build_contract_skeleton(ir: CalculationRequestIR, checklist: list[RequiredOutputIntent],
                            plan: PythonAnalysisPlan, graph: CalculationRequirementGraph) -> CalculationContract:
    ids = [fact.canonical_fact_id or fact.evidence_id for fact in plan.input_facts]
    bindings = _scenario_bindings(ir, plan, graph)
    scenarios = [CalculationScenario(scenario_id=key, input_bindings=value) for key, value in bindings.items()]
    units = {fact.unit for fact in plan.input_facts if fact.unit}
    common = next(iter(units)) if len(units) == 1 else None
    x_units = {fact.unit for fact in plan.input_facts if re.fullmatch(r"(?i)(?:x_?\d+|[A-Za-z0-9]+_x)", fact.name) and fact.unit}
    y_units = {fact.unit for fact in plan.input_facts if re.fullmatch(r"(?i)(?:y_?\d+|[A-Za-z0-9]+_y)", fact.name) and fact.unit}
    outputs: list[CalculationOutputSpec] = []
    for intent in checklist:
        scenario = intent.scenario_id
        if (scenario is None and graph.formula_id and len(bindings) == 1 and
                intent.semantic_name in ir.target_concepts):
            scenario = next(iter(bindings))
        if scenario is not None and scenario not in bindings:
            matched = [key for key in bindings if normalize_symbol(key).endswith(normalize_symbol(scenario))]
            scenario = matched[0] if len(matched) == 1 else scenario
        source_ids = list(dict.fromkeys(bindings[scenario].values() if scenario in bindings else ids))
        name = f"{scenario}_{intent.semantic_name}" if scenario else intent.semantic_name
        output_unit = _unit(intent, common)
        if intent.semantic_name == "r_squared":
            output_unit = "dimensionless"
        elif intent.semantic_name in {"ratio", "divide"}:
            input_units = [fact.unit for fact in plan.input_facts[:2]]
            output_unit = ("dimensionless" if len(input_units) == 2 and input_units[0].casefold() == input_units[1].casefold()
                           else f"{input_units[0]}/{input_units[1]}" if len(input_units) == 2 and all(input_units) else None)
        elif intent.semantic_name == "percent_change" and len(units) != 1:
            output_unit = None
        elif intent.semantic_name == "multiply" and common and len(plan.input_facts) > 1:
            output_unit = f"{common}^{len(plan.input_facts)}"
        elif len(x_units) == len(y_units) == 1:
            x_unit, y_unit = next(iter(x_units)), next(iter(y_units))
            if intent.semantic_name == "slope":
                output_unit = "dimensionless" if x_unit.casefold() == y_unit.casefold() else f"{y_unit}/{x_unit}"
            elif intent.semantic_name == "intercept":
                output_unit = y_unit
        outputs.append(CalculationOutputSpec(output_id="OUT_" + re.sub(r"[^A-Za-z0-9_]", "_", name),
            name=name, semantic_type=intent.output_type, unit=output_unit,
            scenario_id=scenario, source_fact_ids=source_ids,
            formula_id=graph.formula_id if scenario and graph.formula_id else None))
    return CalculationContract(contract_id="CC-V7", purpose=plan.purpose,
        target_criteria=plan.target_criteria, input_fact_ids=ids, formula_id=graph.formula_id,
        operation_type="source_formula" if graph.formula_id else ir.computation_class,
        scenarios=scenarios, required_outputs=outputs)


def skeleton_diff(skeleton: CalculationContract, candidate: CalculationContract) -> list[str]:
    """Any mutation of system-authoritative fields is a hard execution stop."""
    differences = []
    for field in ("input_fact_ids", "formula_id", "operation_type", "scenarios", "required_outputs"):
        if getattr(skeleton, field) != getattr(candidate, field):
            differences.append(field)
    return differences
