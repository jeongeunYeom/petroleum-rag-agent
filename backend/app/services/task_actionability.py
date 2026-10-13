"""Deterministic liveness check before an agent may stop or ask for input.

This module describes what is executable; it does not relax provenance,
dimension validation, tool permissions, or the normal calculation gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from app.services.calculation_requirements import source_variable_unit
from app.services.goal_execution_state import GoalExecutionState
from app.services.goal_intent import GoalIntentKind
from app.services.formula_source_registry import FormulaSourceRecord, expression_variables
from app.services.user_fact_registry import UserFactRecord


@dataclass(frozen=True)
class FormulaVariableBinding:
    source_symbol: str
    bound_fact_id: str | None
    binding_method: str | None
    source_definition: str | None = None
    source_unit: str | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class FormulaExecutionContract:
    target_symbol: str
    normalized_equation: str
    rhs_variables: tuple[FormulaVariableBinding, ...]
    missing_variables: tuple[str, ...]
    ambiguous_variables: tuple[str, ...]
    dimension_validation: str
    source_verified: bool

    @property
    def executable(self) -> bool:
        return (self.source_verified and not self.missing_variables and
                not self.ambiguous_variables and self.dimension_validation == "PASS")


def formula_contract(formula: FormulaSourceRecord | None,
                     bindings: dict[str, UserFactRecord], missing: list[str],
                     *, source_verified: bool, dimension_valid: bool,
                     source_text: str = "") -> FormulaExecutionContract | None:
    if formula is None or not formula.expression_candidate:
        return None
    variables = expression_variables(formula.expression_candidate) or set()
    def definition(symbol: str) -> str | None:
        match = re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}\s+"
                          r"(?:is|denotes|means|represents)\s+[^\n.;]{1,100}",
                          source_text, re.I)
        return match.group(0).strip() if match else None

    rows = tuple(FormulaVariableBinding(
        source_symbol=symbol,
        bound_fact_id=bindings[symbol].fact_id if symbol in bindings else None,
        binding_method=bindings[symbol].extraction_method if symbol in bindings else None,
        source_definition=definition(symbol),
        source_unit=source_variable_unit(source_text, symbol) if source_text else None,
        confidence=bindings[symbol].confidence if symbol in bindings else 0.0,
    ) for symbol in sorted(variables))
    absent = tuple(symbol for symbol in sorted(variables) if symbol not in bindings)
    ambiguous = tuple(reason for reason in missing if "확인" in reason or "ambiguous" in reason)
    return FormulaExecutionContract(
        target_symbol=formula.lhs or "", normalized_equation=formula.expression_candidate,
        rhs_variables=rows, missing_variables=absent, ambiguous_variables=ambiguous,
        dimension_validation="PASS" if dimension_valid else "FAIL", source_verified=source_verified,
    )


@dataclass(frozen=True)
class ActionabilityAssessment:
    direct_calculation_ready: bool = False
    user_formula_ready: bool = False
    kb_formula_ready: bool = False
    derivation_ready: bool = False
    evidence_answer_ready: bool = False
    unresolved_user_inputs: tuple[str, ...] = ()
    unresolved_source_requirements: tuple[str, ...] = ()
    remaining_required_goal_ids: tuple[str, ...] = ()
    executable_goal_ids: tuple[str, ...] = ()
    safe_stop_allowed: bool = True
    clarification_allowed: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def calculation_ready(self) -> bool:
        return self.direct_calculation_ready or self.user_formula_ready or self.kb_formula_ready


def assess_actionability(state: GoalExecutionState, intent: GoalIntentKind, *,
                         direct_ready: bool = False, user_formula_ready: bool = False,
                         kb_formula_ready: bool = False, derivation_ready: bool = False,
                         evidence_answer_ready: bool = False,
                         missing_user_inputs: list[str] | None = None,
                         missing_source: list[str] | None = None,
                         calculation_budget_available: bool = True,
                         unchanged_failed_calculation: bool = False) -> ActionabilityAssessment:
    remaining = tuple(goal.goal_id for goal in state.required_goals
                      if goal.required and goal.status != "MET")
    work = calculation_budget_available and not unchanged_failed_calculation
    direct = direct_ready and work and intent == GoalIntentKind.DIRECT_CALC
    user = user_formula_ready and work and intent == GoalIntentKind.USER_FORMULA_CALC
    kb = kb_formula_ready and work and intent == GoalIntentKind.KB_FORMULA_CALC
    executable = remaining if direct or user or kb or derivation_ready or evidence_answer_ready else ()
    unresolved = tuple(dict.fromkeys(missing_user_inputs or []))
    source = tuple(dict.fromkeys(missing_source or []))
    reasons = tuple(name for name, value in (("direct_calculation", direct),
                    ("user_formula", user), ("kb_formula", kb),
                    ("derivation", derivation_ready), ("evidence_answer", evidence_answer_ready)) if value)
    return ActionabilityAssessment(
        direct_calculation_ready=direct, user_formula_ready=user,
        kb_formula_ready=kb, derivation_ready=derivation_ready,
        evidence_answer_ready=evidence_answer_ready,
        unresolved_user_inputs=unresolved, unresolved_source_requirements=source,
        remaining_required_goal_ids=remaining, executable_goal_ids=executable,
        safe_stop_allowed=not bool(executable),
        clarification_allowed=bool(unresolved) and not bool(executable) and not bool(source),
        reasons=reasons,
    )
