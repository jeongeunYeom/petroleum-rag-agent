"""Deterministic source readiness for a selected calculation, not scientific evidence."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.services.evidence_fact_registry import EvidenceFactRegistry
from app.services.formula_source_registry import FormulaSourceRegistry, FormulaSourceRecord, expression_variables
from app.services.goal_tool_planner import InputFact, PythonAnalysisPlan
from app.services.user_fact_registry import UNIT


ALIASES: dict[str, tuple[str, ...]] = {
    "q": ("rate", "flow_rate", "production_rate"),
    "pr": ("reservoir_pressure", "initial_reservoir_pressure"),
    "pwf": ("flowing_pressure", "bottomhole_flowing_pressure"),
    "k": ("permeability",),
    "h": ("thickness",),
    "t": ("time",),
    "p0": ("initial_pressure",),
}
SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def normalize_symbol(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.translate(SUBSCRIPTS).casefold())


def select_formula_candidate(evidence: list[dict[str, Any]], intent: str,
                             fact_names: list[str]) -> FormulaSourceRecord | None:
    """Accept only one clearly relevant parsed source formula; ties remain unresolved."""
    tokens = {normalize_symbol(token) for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*", intent)}
    facts = {normalize_symbol(name) for name in fact_names}
    ranked: list[tuple[int, FormulaSourceRecord]] = []
    for record in FormulaSourceRegistry.from_evidence(evidence).records:
        if not record.expression_candidate:
            continue
        lhs = normalize_symbol(record.expression_candidate.split("=", 1)[0])
        variables = expression_variables(record.expression_candidate) or set()
        overlap = sum(any(name == normalize_symbol(variable) or name.endswith(normalize_symbol(variable))
                          for name in facts) for variable in variables)
        score = (4 if lhs in tokens else 0) + overlap
        if score >= 2:
            ranked.append((score, record))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked[0][1] if ranked and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]) else None


class FormulaVariableRequirement(BaseModel):
    variable_name: str
    normalized_name: str
    scenario_id: str | None = None
    aliases: list[str] = Field(default_factory=list)
    expected_unit: str | None = None
    candidate_fact_ids: list[str] = Field(default_factory=list)
    bound_fact_id: str | None = None
    binding_method: str | None = None
    binding_confidence: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    unit_check: str = "not_specified"
    status: str = "missing"


class CalculationRequirementGraph(BaseModel):
    requirement_id: str = "CRG-1"
    schema_version: int = 1
    formula_id: str | None = None
    formula_source_available: bool = False
    formula_variables: list[FormulaVariableRequirement] = Field(default_factory=list)
    additional_required_fact_ids: list[str] = Field(default_factory=list)
    missing_variables: list[str] = Field(default_factory=list)
    ambiguous_variables: list[str] = Field(default_factory=list)
    unit_mismatch_variables: list[str] = Field(default_factory=list)
    required_evidence_ids: list[str] = Field(default_factory=list)
    scenario_bindings: dict[str, dict[str, str]] = Field(default_factory=dict)
    dependency_formulas: list[str] = Field(default_factory=list)
    source_complete: bool = False

    @property
    def required_variable_count(self) -> int:
        return len(self.formula_variables)

    @property
    def bound_variable_count(self) -> int:
        return sum(item.status == "bound" for item in self.formula_variables)


def _catalog(evidence: list[dict[str, Any]]) -> list[InputFact]:
    users = [InputFact(
        name=str(item["name"]), value=float(item["value"]), unit=str(item.get("unit") or ""),
        evidence_id=str(item["evidence_id"]), source_excerpt=str(item["source_span"]),
        source_type="user_fact", canonical_fact_id=str(item["evidence_id"]),
    ) for item in evidence if item.get("source_type") == "user_fact" and "name" in item]
    facts = [InputFact(
        name=item.name, value=item.value, unit=item.unit, evidence_id=item.source_id,
        source_excerpt=item.source_span,
        source_type={"knowledge_base": "kb", "figure": "figure", "web": "web"}[item.source_type],
        canonical_fact_id=item.fact_id, span_start=item.span_start, span_end=item.span_end,
    ) for item in EvidenceFactRegistry.from_evidence(evidence).records]
    return users + facts


def _scenarios(facts: list[InputFact], variables: set[str]) -> list[str | None]:
    suffixes = {normalize_symbol(value) for variable in variables for value in (variable, *ALIASES.get(variable.casefold(), ()))}
    found: set[str] = set()
    for fact in facts:
        if fact.source_type != "user_fact" and not re.match(r"^(?:Layer|Well)_", fact.name, re.I):
            continue
        parts = fact.name.split("_")
        for index in range(1, len(parts)):
            prefix, suffix = "_".join(parts[:-index]), "_".join(parts[-index:])
            if prefix and normalize_symbol(suffix) in suffixes and normalize_symbol(fact.name) not in suffixes:
                found.add(prefix)
    # A single common set of variables has no scenario dimension.
    return sorted(found) if found else [None]


def _bind(variable: str, scenario: str | None, facts: list[InputFact], source_id: str | None,
          expected_unit: str | None) -> FormulaVariableRequirement:
    aliases = list(ALIASES.get(variable.casefold(), ()))
    terms = [variable, *aliases]
    normalized = normalize_symbol(variable)
    requirement = FormulaVariableRequirement(variable_name=variable, normalized_name=normalized,
                                             scenario_id=scenario, aliases=aliases, expected_unit=expected_unit)
    levels: list[tuple[str, list[InputFact]]] = []
    if scenario is None:
        levels = [
            ("exact", [fact for fact in facts if normalize_symbol(fact.name) == normalized]),
            ("alias", [fact for fact in facts if normalize_symbol(fact.name) in {normalize_symbol(a) for a in aliases}]),
        ]
    else:
        prefix = normalize_symbol(scenario)
        levels = [
            ("scenario_exact", [fact for fact in facts if normalize_symbol(fact.name) == prefix + normalized]),
            ("scenario_alias", [fact for fact in facts if normalize_symbol(fact.name) in {prefix + normalize_symbol(a) for a in aliases}]),
        ]
    if source_id:
        levels.append(("source_label", [fact for fact in facts if fact.evidence_id == source_id and
                        normalize_symbol(fact.name) in {normalize_symbol(term) for term in terms}]))
    if scenario is None:
        suffixes = {normalize_symbol(term) for term in terms}
        levels.append(("evidence_label_suffix", [fact for fact in facts if fact.source_type != "user_fact"
                       and len(fact.name.split("_")) > 1 and normalize_symbol(fact.name.split("_")[-1]) in suffixes]))
    if scenario is not None:
        levels.append(("shared_exact", [fact for fact in facts if normalize_symbol(fact.name) == normalized]))
        levels.append(("shared_alias", [fact for fact in facts if normalize_symbol(fact.name) in {normalize_symbol(a) for a in aliases}]))
    for method, candidates in levels:
        if not candidates:
            continue
        requirement.candidate_fact_ids = [fact.canonical_fact_id or fact.evidence_id for fact in candidates]
        requirement.binding_method = method
        if expected_unit and any(fact.unit.casefold() != expected_unit.casefold() for fact in candidates):
            requirement.unit_check = "mismatch"
            requirement.status = "unit_mismatch"
        elif len(candidates) != 1:
            requirement.status = "ambiguous"
        else:
            fact = candidates[0]
            requirement.bound_fact_id = fact.canonical_fact_id or fact.evidence_id
            requirement.binding_confidence = "deterministic"
            requirement.source_type = fact.source_type
            requirement.source_id = fact.evidence_id
            requirement.unit_check = "matched" if expected_unit else "not_specified"
            requirement.status = "bound"
        return requirement
    return requirement


def build_requirement_graph(plan: PythonAnalysisPlan | None, evidence: list[dict[str, Any]], *,
                            formula_id: str | None = None, formula_required: bool = False,
                            expected_units: dict[str, str] | None = None,
                            require_all_scenarios: bool = False) -> CalculationRequirementGraph:
    formulas = {item.formula_id: item for item in FormulaSourceRegistry.from_evidence(evidence).records}
    formula_id = formula_id or (plan.formula_source_id if plan else None)
    record = formulas.get(formula_id) if formula_id else None
    graph = CalculationRequirementGraph(formula_id=formula_id,
        formula_source_available=bool(record and record.expression_candidate))
    if plan is None:
        graph.missing_variables.append("calculation_plan")
    if formula_required and not graph.formula_source_available:
        graph.missing_variables.append("formula_source")
    if formula_id and not graph.formula_source_available:
        graph.missing_variables.append("formula_source")
    if record:
        graph.required_evidence_ids.append(record.source_id)
    variables = expression_variables(record.expression_candidate) if record and record.expression_candidate else None
    if record and variables is None:
        graph.missing_variables.append("formula_not_parseable")
    if record and variables:
        same_source = [item for item in formulas.values() if item.source_id == record.source_id and
                       item.formula_id != record.formula_id and item.expression_candidate]
        dependency_by_lhs: dict[str, list[FormulaSourceRecord]] = {}
        for item in same_source:
            lhs = normalize_symbol(item.expression_candidate.split("=", 1)[0])
            dependency_by_lhs.setdefault(lhs, []).append(item)
        visiting: set[str] = set()

        def leaves(variable: str) -> set[str]:
            matches = dependency_by_lhs.get(normalize_symbol(variable), [])
            if not matches:
                return {variable}
            if len(matches) != 1 or variable in visiting:
                graph.ambiguous_variables.append(f"dependency:{variable}")
                return {variable}
            dependency = matches[0]
            visiting.add(variable)
            children = set().union(*(leaves(child) for child in
                                     (expression_variables(dependency.expression_candidate or "") or set())))
            visiting.remove(variable)
            if dependency.expression_candidate not in graph.dependency_formulas:
                graph.dependency_formulas.append(dependency.expression_candidate)
            return children

        variables = set().union(*(leaves(variable) for variable in variables))
    unit_hints = dict(expected_units or {})
    if record and variables:
        source_text = next((str(item.get("text") or "") for item in evidence
                            if item.get("evidence_id") == record.source_id), "")
        for variable in variables:
            match = re.search(rf"\b{re.escape(variable)}\s*\((?P<unit>{UNIT})\)", source_text, re.I)
            if match:
                unit_hints.setdefault(variable, match.group("unit"))
    facts = _catalog(evidence)
    if plan:
        by_id = {fact.canonical_fact_id or fact.evidence_id: fact for fact in facts}
        by_id.update({fact.canonical_fact_id or fact.evidence_id: fact for fact in plan.input_facts})
        facts = list(by_id.values())
    if variables:
        for scenario in _scenarios(facts, variables):
            key = scenario or "default"
            graph.scenario_bindings[key] = {}
            for variable in sorted(variables):
                bound = _bind(variable, scenario, facts, record.source_id if record else None,
                              unit_hints.get(variable))
                graph.formula_variables.append(bound)
                label = f"{key}:{variable}"
                if bound.status == "bound" and bound.bound_fact_id:
                    graph.scenario_bindings[key][variable] = bound.bound_fact_id
                    fact = next(item for item in facts if (item.canonical_fact_id or item.evidence_id) == bound.bound_fact_id)
                    if fact.source_type != "user_fact":
                        graph.required_evidence_ids.append(fact.evidence_id)
                elif bound.status == "ambiguous":
                    graph.ambiguous_variables.append(label)
                elif bound.status == "unit_mismatch":
                    graph.unit_mismatch_variables.append(label)
                else:
                    graph.missing_variables.append(label)
    elif not formula_id and plan:
        selected_facts = plan.input_facts
        if require_all_scenarios:
            user_facts = [fact for fact in facts if fact.source_type == "user_fact"]
            pairs: dict[str, dict[str, str]] = {}
            for fact in user_facts:
                prefix, separator, suffix = fact.name.rpartition("_")
                if separator and suffix.casefold() in {"baseline", "observed"}:
                    pairs.setdefault(prefix, {})[suffix.casefold()] = fact.canonical_fact_id or fact.evidence_id
            if len(pairs) >= 2 and all(set(pair) == {"baseline", "observed"} for pair in pairs.values()):
                graph.scenario_bindings = pairs
                selected_facts = user_facts
        graph.additional_required_fact_ids = [fact.canonical_fact_id or fact.evidence_id for fact in selected_facts]
        if not graph.additional_required_fact_ids:
            graph.missing_variables.append("numeric_facts")
        if not graph.scenario_bindings:
            graph.scenario_bindings["default"] = {fact.name: fact.canonical_fact_id or fact.evidence_id for fact in selected_facts}
    graph.required_evidence_ids = list(dict.fromkeys(graph.required_evidence_ids))
    graph.source_complete = not (graph.missing_variables or graph.ambiguous_variables or graph.unit_mismatch_variables)
    return graph


def augment_plan_with_bindings(plan: PythonAnalysisPlan, graph: CalculationRequirementGraph,
                               evidence: list[dict[str, Any]]) -> None:
    """Add only uniquely bound canonical facts; never manufacture a numeric value."""
    selected = {fact.canonical_fact_id or fact.evidence_id for fact in plan.input_facts}
    catalog = {fact.canonical_fact_id or fact.evidence_id: fact for fact in _catalog(evidence)}
    for requirement in graph.formula_variables:
        fact_id = requirement.bound_fact_id
        if fact_id and fact_id not in selected and fact_id in catalog:
            plan.input_facts.append(catalog[fact_id])
            selected.add(fact_id)
    for fact_id in graph.additional_required_fact_ids:
        if fact_id not in selected and fact_id in catalog:
            plan.input_facts.append(catalog[fact_id])
            selected.add(fact_id)


def required_recovery_gain(before: CalculationRequirementGraph, after: CalculationRequirementGraph,
                           added_source_ids: list[str]) -> list[str]:
    """A source counts only when it fills a previously missing canonical requirement."""
    added = set(added_source_ids)
    gain: set[str] = set()
    if (not before.formula_source_available and after.formula_source_available
            and after.required_evidence_ids and after.required_evidence_ids[0] in added):
        gain.add("formula_source")
    missing = set(before.missing_variables)
    for item in after.formula_variables:
        label = f"{item.scenario_id or 'default'}:{item.variable_name}"
        if label in missing and item.status == "bound" and item.bound_fact_id and item.bound_fact_id.startswith("EFACT") and item.source_id in added:
            gain.add(label)
    return sorted(gain)
