"""Small, request-only language and quantity cues; never a source of formulas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.models.goal_research_schemas import GoalResearchRequest
from app.services.formula_source_registry import EQUATION, expression_variables


class GoalIntentKind(str, Enum):
    PREMISE_CHECK = "premise_check"
    DIRECT_CALC = "direct_calc"
    USER_FORMULA_CALC = "user_formula_calc"
    USER_FORMULA_SIMULATION = "user_formula_simulation"
    KB_FORMULA_CALC = "kb_formula_calc"
    KNOWLEDGE_QA = "knowledge_qa"
    FIGURE_QA = "figure_qa"
    UNSUPPORTED = "unsupported"


class SourceRequirement(str, Enum):
    NONE = "none"
    USER_FORMULA = "user_formula"
    KB_FORMULA = "kb_formula"


@dataclass(frozen=True)
class GoalIntent:
    kind: GoalIntentKind
    source_requirement: SourceRequirement
    user_equation: str | None = None


_CALC = re.compile(r"\b(?:calculat\w*|comput\w*|determine|mean|average|sum|ratio|difference|rank\w*)\b|계산|산출|구해|구하|평균|합계|총합|비율|차이|순위", re.I)
_SIMULATION = re.compile(r"\b(?:simulat\w*|sweep|vary\w*|optim\w*)\b|시뮬레이션|최적|간격|변화시키|바꿔가며|범위", re.I)
_FORMULA_REQUEST = re.compile(r"(?<![A-Za-z0-9_])(?:formula|equation|correlation|relation|law|model|coupling)(?![A-Za-z0-9_])|공식|수식|관계식|식(?:을|이|의)?\s*찾|모델", re.I)
_PREMISE = re.compile(r"(?:맞(?:지|나요|습니까|아)?|옳(?:지|나요)?|인가요|이라는\s*거|인\s*거지|그렇(?:지|습니까)|\bis\s+it\s+(?:true|correct)\b|\bisn['’]?t\s+it\b|\bright\?|\bcorrect\?|\bdoes\s+.+\s+(?:mean|imply)\b)", re.I)
_FIGURE = re.compile(r"\b(?:figure|fig\.|diagram|plot|image)\b|그림|도표|도식", re.I)


def user_equation(text: str) -> str | None:
    """Return one literal arithmetic equation, not a numeric input assignment."""
    equations = []
    for match in EQUATION.finditer(text):
        value = match.group("equation").rstrip(" .\t")
        if expression_variables(value) and re.search(r"[+*/×÷−]|(?<![eE])-", value.split("=", 1)[1]):
            equations.append(value)
    return equations[0] if len({re.sub(r"\s+", "", row) for row in equations}) == 1 else None


def classify_goal_intent(request: GoalResearchRequest, *, has_user_facts: bool,
                         has_simulation_spec: bool = False) -> GoalIntent:
    """Choose the execution route from the request before the action planner runs."""
    text = " ".join(filter(None, (request.topic, request.goal)))
    equation = user_equation(text)
    if _PREMISE.search(text) and not re.search(r"몇|얼마|무엇|어떻게|\b(?:how\s+many|how\s+much|what\s+is)\b", text, re.I):
        return GoalIntent(GoalIntentKind.PREMISE_CHECK, SourceRequirement.NONE)
    if _FIGURE.search(text) and not _CALC.search(text):
        return GoalIntent(GoalIntentKind.FIGURE_QA, SourceRequirement.NONE)
    if has_simulation_spec or (_SIMULATION.search(text) and equation):
        return GoalIntent(GoalIntentKind.USER_FORMULA_SIMULATION if equation or has_simulation_spec
                          else GoalIntentKind.KB_FORMULA_CALC,
                          SourceRequirement.USER_FORMULA if equation or has_simulation_spec
                          else SourceRequirement.KB_FORMULA, equation)
    if _SIMULATION.search(text):
        return GoalIntent(GoalIntentKind.KB_FORMULA_CALC, SourceRequirement.KB_FORMULA)
    if equation and _CALC.search(text):
        return GoalIntent(GoalIntentKind.USER_FORMULA_CALC, SourceRequirement.USER_FORMULA, equation)
    if _CALC.search(text) or asks_for_api_gravity_calculation(request):
        if asks_for_api_gravity_calculation(request) or _FORMULA_REQUEST.search(text):
            return GoalIntent(GoalIntentKind.KB_FORMULA_CALC, SourceRequirement.KB_FORMULA)
        if has_user_facts:
            return GoalIntent(GoalIntentKind.DIRECT_CALC, SourceRequirement.NONE)
        return GoalIntent(GoalIntentKind.KB_FORMULA_CALC, SourceRequirement.KB_FORMULA)
    return GoalIntent(GoalIntentKind.KNOWLEDGE_QA, SourceRequirement.NONE)


def prefers_korean(request: GoalResearchRequest) -> bool:
    return bool(re.search(r"[가-힣]", " ".join((request.topic, request.goal or ""))))


def asks_for_api_gravity(request: GoalResearchRequest) -> bool:
    text = " ".join((request.topic, request.goal or ""))
    return bool(re.search(r"(?<![A-Za-z0-9])API(?:\s+gravity)?(?![A-Za-z0-9])|API도", text, re.I)
                and re.search(r"(?<![A-Za-z0-9])SG(?![A-Za-z0-9])|specific\s+gravity|비중", text, re.I))


def asks_for_api_gravity_calculation(request: GoalResearchRequest) -> bool:
    text = " ".join((request.topic, request.goal or ""))
    return asks_for_api_gravity(request) and bool(re.search(
        r"\b(?:calculat\w*|comput\w*|convert|determine)\b|계산|산출|구해|구하|몇(?:인가요|이야|입니까)|얼마", text, re.I))
