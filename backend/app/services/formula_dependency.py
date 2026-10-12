"""Bounded, literal-source-only planning for dependent formula calculations."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from app.services.calculation_requirements import (normalize_symbol, source_variable_unit,
                                                   symbol_names, unit_compatibility_score)
from app.services.formula_source_registry import (FormulaSourceRecord, FormulaSourceRegistry,
                                                  expression_variables, normalize_formula, source_contains_equation)
from app.services.goal_execution_state import DerivedFact
from app.services.user_fact_registry import UserFactRegistry


@dataclass
class DependencyPlan:
    next_formula: FormulaSourceRecord | None = None
    missing_inputs: list[str] = field(default_factory=list)
    block_reason: str | None = None
    depth: int = 0
    formula_ids: list[str] = field(default_factory=list)
    complete: bool = False


def resolve_formula_dependencies(target: FormulaSourceRecord, evidence: list[dict[str, Any]],
                                 users: UserFactRegistry, derived: list[DerivedFact],
                                 completed: list[Any], *, max_depth: int = 3) -> DependencyPlan:
    """Choose one executable equation, never an inferred or ambiguous dependency."""
    plan = DependencyPlan()
    sources = {str(row.get("evidence_id")): str(row.get("text") or "") for row in evidence}
    if not source_contains_equation(target, sources.get(target.source_id, "")):
        plan.block_reason = "formula_dependency_source_unverified"
        return plan
    records = [row for row in FormulaSourceRegistry.from_evidence(evidence).records
               if row.expression_candidate and expression_variables(row.expression_candidate)
               and source_contains_equation(row, sources.get(row.source_id, ""))]
    completed_keys = {(source, row.normalized_formula) for row in completed
                      if row.validation_passed and row.contract_validation_passed
                      for source in row.formula_source_ids}
    facts = [*users.records, *derived]

    def bound(variable: str) -> bool:
        matches = [row for row in facts if normalize_symbol(row.name) in symbol_names(variable)]
        exact = [row for row in matches if normalize_symbol(row.name) == normalize_symbol(variable)]
        return len(exact or matches) == 1

    def candidate(variable: str) -> FormulaSourceRecord | None:
        names = symbol_names(variable)
        matches = [row for row in records if row.lhs and normalize_symbol(row.lhs) in names]
        if not matches:
            return None
        exact = [row for row in matches if normalize_symbol(row.lhs or "") == normalize_symbol(variable)]
        matches = exact or matches

        target_context = {word.casefold() for word in re.findall(r"[A-Za-z]{4,}", target.context)
                          if word.casefold() not in {"equation", "formula", "relation", "internal", "source"}}

        def score(row: FormulaSourceRecord) -> tuple[int, int, int]:
            variables = expression_variables(row.expression_candidate or "") or set()
            overlap = sum(bound(name) for name in variables)
            source = sources[row.source_id]
            local = source[max(0, row.span_start - 180):row.span_end + 180]
            unit_score = 0
            for name in variables:
                source_unit = source_variable_unit(local, name)
                matches_for_name = [fact for fact in facts if normalize_symbol(fact.name) in symbol_names(name)]
                if source_unit and len(matches_for_name) == 1 and matches_for_name[0].unit:
                    unit_score += unit_compatibility_score(source_unit, matches_for_name[0].unit)
            context = min(2, len(target_context & {word.casefold() for word in
                re.findall(r"[A-Za-z]{4,}", row.context)}))
            same_document = int(bool(target.source_document and
                                     target.source_document == row.source_document))
            return (overlap * 4 + unit_score + context + same_document,
                    overlap, unit_score)

        ranked = sorted(matches, key=lambda row: (score(row), row.source_id), reverse=True)
        best = ranked[0]
        if (len(ranked) > 1 and ranked[1].equation_ast != best.equation_ast
                and score(best)[0] - score(ranked[1])[0] < 3):
            plan.block_reason = "formula_dependency_ambiguous"
            return None
        return best

    def visit(row: FormulaSourceRecord, depth: int, active: set[str]) -> None:
        if plan.block_reason:
            return
        if depth > max_depth:
            plan.block_reason = "formula_dependency_depth_exceeded"
            return
        key = row.equation_ast or row.formula_id
        if key in active:
            plan.block_reason = "formula_dependency_cycle"
            return
        if (row.source_id, normalize_formula(row.expression_candidate or "")) in completed_keys:
            return
        plan.depth = max(plan.depth, depth)
        plan.formula_ids.append(row.formula_id)
        active.add(key)
        for variable in sorted(expression_variables(row.expression_candidate or "") or set()):
            if bound(variable):
                continue
            producer = candidate(variable)
            if plan.block_reason:
                break
            if producer is None:
                plan.missing_inputs.append(variable)
            else:
                visit(producer, depth + 1, active)
        active.remove(key)
        if not plan.block_reason and not plan.missing_inputs and plan.next_formula is None:
            plan.next_formula = row

    visit(target, 0, set())
    plan.missing_inputs = list(dict.fromkeys(plan.missing_inputs))
    plan.formula_ids = list(dict.fromkeys(plan.formula_ids))
    plan.complete = not plan.block_reason and not plan.missing_inputs and plan.next_formula is None
    return plan
