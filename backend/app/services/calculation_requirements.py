"""Deterministic source readiness for a selected calculation, not scientific evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.services.evidence_fact_registry import EvidenceFactRegistry
from app.services.formula_source_registry import FormulaSourceRegistry, FormulaSourceRecord, expression_variables
from app.services.goal_tool_planner import InputFact, PythonAnalysisPlan
from app.services.user_fact_registry import UNIT, normalize_unit


ALIASES: dict[str, tuple[str, ...]] = {
    "q": ("rate", "flow_rate", "production_rate"),
    "pr": ("reservoir_pressure", "initial_reservoir_pressure"),
    "pwf": ("flowing_pressure", "bottomhole_flowing_pressure"),
    "k": ("permeability",),
    "h": ("thickness",),
    "t": ("time",),
    "p0": ("initial_pressure",),
    "td": ("dimensionless_time",),
    "cd": ("dimensionless_storage", "dimensionless_wellbore_storage"),
    "pd": ("dimensionless_pressure",),
    "wob": ("weight_on_bit", "bit_weight"),
    "w": ("buoyant_unit_weight", "unit_weight"),
    "kh": ("horizontal_permeability",),
    "kv": ("vertical_permeability",),
    "sim": ("initial_saturation", "initial_movable_saturation", "saturation_fraction"),
    "qt": ("total_rate", "total_flow_rate"),
    "qw": ("water_rate", "water_flow_rate"),
    "psc": ("surface_pressure", "surface_casing_pressure"),
    "pb": ("back_pressure",),
    "pa": ("annular_pressure",),
    "kfw": ("fracture_permeability_width",),
    "klf": ("lateral_fracture_permeability",),
    "pf": ("power_factor",),
}
SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def normalize_symbol(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.translate(SUBSCRIPTS).casefold())


def symbol_names(variable: str) -> set[str]:
    return {normalize_symbol(value) for value in (variable, *ALIASES.get(variable.casefold(), ()))}


def infer_dimensionless(variable: str, source_text: str, user_label: str = "") -> dict[str, Any] | None:
    """Only a local definition or explicit semantic role can waive a unit requirement."""
    name = normalize_symbol(variable)
    if name in {"sg", "phi", "porosity", "fraction", "ratio", "sw", "saturation"}:
        return {"variable": variable, "dimension": "dimensionless", "source": "known_semantic_role",
                "confidence": .95}
    if re.search(r"fraction|ratio|saturation|dimensionless|공극률|포화도|비율|무차원", user_label, re.I):
        return {"variable": variable, "dimension": "dimensionless", "source": "user_label",
                "confidence": .9}
    local = re.search(rf"\b{re.escape(variable)}\b.{{0,55}}?\b(?:fraction|ratio|saturation|dimensionless)\b|"
                      rf"\b(?:fraction|ratio|saturation|dimensionless)\b.{{0,55}}?\b{re.escape(variable)}\b",
                      source_text, re.I | re.S)
    if local:
        return {"variable": variable, "dimension": "dimensionless", "source": "source_definition",
                "confidence": .85}
    quotient = re.search(rf"\b{re.escape(variable)}\s*=\s*([A-Za-z][A-Za-z0-9_]*)\s*/\s*"
                         r"([A-Za-z][A-Za-z0-9_]*)\b", source_text)
    if quotient:
        units = []
        for operand in quotient.groups():
            mention = re.search(rf"\b{re.escape(operand)}\s*\((?P<unit>{UNIT})\)", source_text, re.I)
            units.append(normalize_unit(mention["unit"]) if mention else None)
        if units[0] and units[0] == units[1]:
            return {"variable": variable, "dimension": "dimensionless",
                    "source": "same_dimension_quotient", "confidence": .8}
    return None


def scenario_fact_match(name: str, scenario: str) -> bool:
    """Match a complete scenario prefix, never the `C` inside `case`."""
    normalized, key = normalize_symbol(name), normalize_symbol(scenario)
    for prefix in ("case", "well", "layer", "sample"):
        if normalized.startswith(prefix):
            return normalized.startswith(prefix + key) and len(normalized) > len(prefix + key)
    return normalized.startswith(key) and len(normalized) > len(key)


@dataclass(frozen=True)
class FormulaSelectionRecord:
    formula_id: str | None
    score: int
    lhs_score: int
    variable_overlap_score: int
    context_score: int
    heading_score: int
    ambiguity_margin: int
    selection_reason: str
    candidates_found: int
    candidate_scores: dict[str, int] = field(default_factory=dict)
    lhs_match: bool = False
    required_variable_match: int = 0
    extra_variable_penalty: int = 0
    term_count_match: bool = False
    requested_structure_match: bool = False
    negative_constraint_penalty: int = 0
    nearby_definition_match: bool = False
    same_sentence_match: bool = False
    same_paragraph_match: bool = False
    equation_number: str | None = None


def _requested_term_count(text: str) -> int | None:
    found = re.search(r"\b([2-9])[- ]?(?:term|component)\b|([2-9])\s*성분|"
                      r"(두|세|네|다섯)\s*성분|"
                      r"\b(two|three|four|five)[- ](?:term|component)\b", text, re.I)
    if not found:
        return None
    return int(found.group(1) or found.group(2)) if found.group(1) or found.group(2) else {
        "두": 2, "세": 3, "네": 4, "다섯": 5,
        "two": 2, "three": 3, "four": 4, "five": 5}[(found.group(3) or found.group(4)).casefold()]


def _additive_terms(formula: str) -> int:
    import ast
    try:
        tree = ast.parse(formula.split("=", 1)[1].strip(), mode="eval").body
    except (SyntaxError, IndexError):
        return 0
    def count(node: ast.AST) -> int:
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            return count(node.left) + count(node.right)
        return 1
    return count(tree)


def rank_formula_candidates(evidence: list[dict[str, Any]], intent: str,
                            fact_names: list[str]) -> tuple[FormulaSourceRecord | None, FormulaSelectionRecord]:
    """Rank literal source spans; weak or conflicting matches remain unresolved."""
    tokens = {normalize_symbol(token) for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*|[가-힣]{2,}", intent)}
    if re.search(r"API도", intent, re.I):
        tokens.add("api")
    facts = {normalize_symbol(name) for name in fact_names}
    stopwords = {"from", "with", "calculate", "compute", "equation", "formula", "the", "for", "and",
                 "using", "find", "given", "what", "식으로", "계산해줘", "내부", "자료에서"}
    context_tokens = {token for token in tokens if len(token) > 2 and token not in stopwords}
    generic_context = stopwords | {"internal", "locate", "model", "assume", "result", "value",
                                   "values", "input", "units", "source", "sourced", "relation",
                                   "please", "expression", "number", "without", "known", "needed"}
    source_by_id = {str(row.get("evidence_id")): str(row.get("text") or "") for row in evidence}
    requested_terms = _requested_term_count(intent)
    excludes_reduced = bool(re.search(r"축약식\s*말고|두\s*성분.{0,12}혼동하지\s*마|"
                                      r"not\s+(?:the\s+)?(?:two[- ]term|reduced\s+form)|simplified\s+form\s*말고|"
                                      r"exclude\s+.{0,20}form|do\s+not\s+use", intent, re.I))
    ranked: list[tuple[tuple[int, ...], FormulaSourceRecord, dict[str, Any]]] = []
    for record in FormulaSourceRegistry.from_evidence(evidence).records:
        if not record.expression_candidate:
            continue
        lhs = normalize_symbol(record.expression_candidate.split("=", 1)[0])
        variables = expression_variables(record.expression_candidate) or set()
        if not variables:
            # A worked numeric example is not a reusable relation to bind.
            continue
        overlap = sum(any(name in symbol_names(variable) or name.endswith(normalize_symbol(variable))
                          for name in facts) for variable in variables)
        source_text = source_by_id.get(record.source_id, "")
        line_start = source_text.rfind("\n", 0, record.span_start) + 1
        line_end = source_text.find("\n", record.span_end)
        line_end = len(source_text) if line_end < 0 else line_end
        nearby = source_text[line_start:line_end]
        heading = [source_text[line_start:record.span_start]]
        heading_tokens = {normalize_symbol(word) for line in heading for word in
                          re.findall(r"[A-Za-z][A-Za-z0-9_]*|[가-힣]{2,}", line)}
        nearby_tokens = {normalize_symbol(word) for word in
                         re.findall(r"[A-Za-z][A-Za-z0-9_]*|[가-힣]{2,}", nearby)}
        descriptor_tokens = context_tokens - generic_context - facts - {lhs} - {
            normalize_symbol(variable) for variable in variables}
        local_context = source_text[max(0, record.span_start - 180):record.span_end + 180]
        local_tokens = {normalize_symbol(word) for word in
                        re.findall(r"[A-Za-z][A-Za-z0-9_]*|[가-힣]{2,}", local_context)}
        raw_lhs = record.expression_candidate.split("=", 1)[0].strip()
        explicit_symbol_binding = (raw_lhs.isupper() and len(lhs) >= 3 and lhs in tokens
                                   and overlap == len(variables))
        if (len(descriptor_tokens) >= 2 and not (descriptor_tokens & local_tokens)
                and not explicit_symbol_binding):
            # A matching output symbol alone cannot identify a named engineering model.
            continue
        lhs_score = 6 if lhs in tokens else 0
        variable_score = 2 * overlap
        heading_score = min(4, len(context_tokens & heading_tokens))
        context_score = min(4, len(context_tokens & nearby_tokens))
        terms = _additive_terms(record.expression_candidate)
        term_match = requested_terms is not None and terms == requested_terms
        extra = (sum(not any(name in symbol_names(variable) for name in facts)
                     and normalize_symbol(variable) not in tokens for variable in variables)
                 if facts else 0)
        negative = 6 if excludes_reduced and terms == 2 else 0
        structure = 4 if term_match else 0
        score = lhs_score + variable_score + heading_score + context_score + structure - negative
        details = {"lhs_match": bool(lhs_score), "required_variable_match": overlap,
                   "extra_variable_penalty": extra, "term_count_match": term_match,
                   "requested_structure_match": term_match, "negative_constraint_penalty": negative,
                   "nearby_definition_match": bool(context_score),
                   "same_sentence_match": bool(context_score), "same_paragraph_match": bool(heading_score),
                   "equation_number": (re.search(r"\((\d{1,3})\)\s*$", source_text[:record.span_start]) or [None, None])[1]}
        if score >= 2:
            key = (score, lhs_score, overlap, -extra, int(term_match), -negative,
                   context_score, heading_score)
            ranked.append((key, record, details))
    ranked.sort(key=lambda row: row[0], reverse=True)
    if not ranked:
        return None, FormulaSelectionRecord(None, 0, 0, 0, 0, 0, 0, "no_relevant_literal_formula", 0)
    top = ranked[0]
    runner = next((row for row in ranked[1:] if row[1].equation_ast != top[1].equation_ast), None)
    margin = top[0][0] - runner[0][0] if runner else top[0][0]
    selected = top[1] if top[0][0] >= 2 and (runner is None or top[0] > runner[0]) else None
    reason = "unique_structural_match" if selected else "ambiguous_literal_formulas"
    return selected, FormulaSelectionRecord(
        selected.formula_id if selected else None, top[0][0], top[0][1], top[0][2] * 2,
        top[0][6], top[0][7], margin, reason, len(ranked),
        {row[1].formula_id: row[0][0] for row in ranked}, **top[2])


def select_formula_candidate(evidence: list[dict[str, Any]], intent: str,
                             fact_names: list[str]) -> FormulaSourceRecord | None:
    return rank_formula_candidates(evidence, intent, fact_names)[0]


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
    suffixes = set().union(*(symbol_names(variable) for variable in variables))
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
        prefixes = {prefix, *(f"{kind}{prefix}" for kind in ("case", "well", "layer", "sample"))}
        levels = [
            ("scenario_exact", [fact for fact in facts if normalize_symbol(fact.name) in {p + normalized for p in prefixes}]),
            ("scenario_alias", [fact for fact in facts if normalize_symbol(fact.name) in
             {p + normalize_symbol(a) for p in prefixes for a in aliases}]),
        ]
    if source_id and scenario is None:
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
        if expected_unit and any(normalize_symbol(fact.unit) != normalize_symbol(expected_unit) for fact in candidates):
            requirement.unit_check = "mismatch"
            requirement.status = "unit_mismatch"
        elif len(candidates) != 1:
            requirement.status = "ambiguous"
        else:
            fact = candidates[0]
            requirement.bound_fact_id = fact.canonical_fact_id or fact.evidence_id
            requirement.binding_confidence = "deterministic_exact" if method in {"exact", "scenario_exact"} else (
                "scenario_match" if method.startswith("scenario") else "deterministic_alias")
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
    if (before.formula_source_available and after.formula_id != before.formula_id
            and after.bound_variable_count > before.bound_variable_count
            and after.required_evidence_ids and after.required_evidence_ids[0] in added):
        gain.add("formula_replacement")
    missing = set(before.missing_variables)
    for item in after.formula_variables:
        label = f"{item.scenario_id or 'default'}:{item.variable_name}"
        if label in missing and item.status == "bound" and item.bound_fact_id and item.bound_fact_id.startswith("EFACT") and item.source_id in added:
            gain.add(label)
    for missing_scenario in (value for value in before.missing_variables if value.startswith("scenario:")):
        key = normalize_symbol(missing_scenario.split(":", 1)[1])
        bindings = next((value for scenario, value in after.scenario_bindings.items()
                         if normalize_symbol(scenario).endswith(key)), {})
        if bindings and any(item.source_id in added for item in after.formula_variables
                            if item.bound_fact_id in bindings.values()):
            gain.add(missing_scenario)
    return sorted(gain)
