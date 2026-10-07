"""Evidence-backed formula selection; planner hints never override compatibility."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.services.calculation_requirements import normalize_symbol, symbol_names
from app.services.formula_source_registry import FormulaSourceRecord, FormulaSourceRegistry, expression_variables, normalize_formula


@dataclass(frozen=True)
class FormulaIntent:
    desired_output_names: tuple[str, ...]
    concept_terms: tuple[str, ...]
    available_input_semantics: tuple[str, ...]
    scenario_pattern: str | None = None
    expected_unit_family: str | None = None


@dataclass
class FormulaResolution:
    record: FormulaSourceRecord | None
    reason: str
    candidates: list[dict[str, Any]]


def _fact_match(variable: str, names: tuple[str, ...]) -> bool:
    terms = symbol_names(variable)
    for name in names:
        normalized = normalize_symbol(name)
        if normalized in terms:
            return True
        # Only structured scenario prefixes, never arbitrary substrings (t != tD).
        if any(normalized.endswith(term) and (normalized[:-len(term)].startswith(("case", "well", "layer", "sample"))
                or len(normalized[:-len(term)]) == 1)
               for term in terms if term):
            return True
    return False


def resolve_formula(evidence: list[dict[str, Any]], intent: FormulaIntent) -> FormulaResolution:
    rows: list[tuple[float, FormulaSourceRecord, dict[str, Any]]] = []
    desired = {normalize_symbol(value) for value in intent.desired_output_names + intent.concept_terms if value}
    source_text = {str(item.get("evidence_id")): str(item.get("text") or "") for item in evidence}
    for record in FormulaSourceRegistry.from_evidence(evidence).records:
        expression = record.expression_candidate
        variables = expression_variables(expression) if expression else None
        if variables is None:
            continue
        lhs = normalize_symbol(expression.split("=", 1)[0])
        lhs_score = 4 if lhs in desired else (2 if any(lhs in term or term in lhs for term in desired if len(term) > 2) else 0)
        matched = [name for name in variables if _fact_match(name, intent.available_input_semantics)]
        missing = sorted(variables - set(matched))
        overlap_score = 2 * len(matched)
        extra_penalty = 3 * len(missing)
        context = normalize_symbol(source_text.get(record.source_id, "") + " " + str(record.locator or ""))
        context_score = sum(1 for term in intent.concept_terms if len(normalize_symbol(term)) > 3
                            and normalize_symbol(term) in context)
        unit_match = re.search(rf"\b{re.escape(expression.split('=', 1)[0].strip())}\s*\(([^()]+)\)",
                               source_text.get(record.source_id, ""), re.I)
        observed_unit = normalize_symbol(unit_match.group(1)) if unit_match else None
        expected_unit = normalize_symbol(intent.expected_unit_family or "")
        unit_score = 1 if observed_unit and observed_unit == expected_unit else 0
        score = lhs_score + overlap_score + context_score + unit_score - extra_penalty
        reason = "accepted"
        if not lhs_score:
            reason = "lhs_mismatch"
        elif variables and not matched and intent.available_input_semantics:
            reason = "rhs_no_input_overlap"
        elif len(missing) > 1 and len(missing) >= len(matched):
            reason = "excess_unavailable_variables"
        elif observed_unit and expected_unit and observed_unit != expected_unit:
            reason = "unit_mismatch"
        trace = {"formula_id": record.formula_id, "equation": expression, "lhs": lhs,
                 "rhs_variables": sorted(variables), "lhs_score": lhs_score,
                 "input_overlap_score": overlap_score, "extra_variable_penalty": extra_penalty,
                 "context_score": context_score, "unit_score": unit_score, "total_score": score,
                 "missing_variables": missing, "reason": reason}
        if reason == "accepted":
            rows.append((score, record, trace))
        else:
            rows.append((float("-inf"), record, trace))
    traces = [row[2] for row in sorted(rows, key=lambda row: row[2]["total_score"], reverse=True)]
    accepted = sorted((row for row in rows if row[2]["reason"] == "accepted"), key=lambda row: row[0], reverse=True)
    if not accepted:
        return FormulaResolution(None, "formula_source_unavailable", traces)
    if len(accepted) > 1 and accepted[0][0] - accepted[1][0] < 1 and normalize_formula(
            accepted[0][1].expression_candidate or "") != normalize_formula(accepted[1][1].expression_candidate or ""):
        return FormulaResolution(None, "formula_selection_ambiguous", traces)
    return FormulaResolution(accepted[0][1], "resolved", traces)
