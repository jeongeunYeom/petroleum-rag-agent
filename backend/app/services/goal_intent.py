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


class FormulaOrigin(str, Enum):
    USER_DEFINED = "user_defined"
    KB_REFERENCED = "kb_referenced"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GoalIntent:
    kind: GoalIntentKind
    source_requirement: SourceRequirement
    user_equation: str | None = None
    reason: str = ""
    premise_cue_detected: bool = False
    formula_origin: FormulaOrigin = FormulaOrigin.UNKNOWN


_CALC = re.compile(r"\b(?:calculat\w*|comput\w*|determine|mean|average|sum|ratio|difference|slope|multiplication|division|rank\w*|median|variance|deviation|interpolat\w*|integrat\w*|percentage?\s+(?:increase|decrease))\b|계산|산출|구해|구하|평균|합계|총합|비율|차이|순위|중앙값|표준편차|분산|보간|적분|경과\s*시간|배정|할당|증가율|감소율|얼마(?:인가|야|입니까|니)|몇(?:인가|이야|입니까|니)|값은", re.I)
_EXPLICIT_CALC = re.compile(r"\b(?:calculat\w*|comput\w*|convert|determine|solve)\b|계산|산출|구해|구하|환산", re.I)
_SIMULATION = re.compile(r"\b(?:sweep|vary\w*|sensitiv\w*|optim\w*|parameter\s+range|over\s+(?:a|the)\s+range)\b|"
                         r"\bfrom\s+[-+]?\d+(?:\.\d+)?\s+to\s+[-+]?\d+(?:\.\d+)?\b|"
                         r"최적|간격|변화시키|바꿔가며|바꾸면서|여러\s*값으로|매개변수\s*변화|부터.{0,30}까지", re.I)
_FORMULA_REQUEST = re.compile(r"(?<![A-Za-z0-9_])(?:formula|equation|correlation|relation|law|model|coupling)(?![A-Za-z0-9_])|공식|수식|관계식|식(?:을|이|의)?\s*(?:찾|확인)|관계(?:를|식을)?\s*찾|내부\s*식|원문\s*식|(?:교재|자료)에\s*나온\s*(?:식|관계)|모델", re.I)
_KB_ORIGIN = re.compile(r"내부\s*(?:자료|식|교재)|교재(?:의|에)|문서에서|자료에서\s*확인|원문|식(?:을|이|의)?\s*(?:찾|확인)|관계(?:를|식을)?\s*찾|(?:교재|자료)에\s*나온|\b(?:textbook|internal source|cited relation|source equation)\b", re.I)
_USER_ORIGIN = re.compile(r"내가\s*(?:정의한|준|지정한)(?:\s*식)?|사용자\s*식|\b(?:my formula|use this equation|scenario equation|user[- ]defined equation)\b", re.I)
_PREMISE = re.compile(r"(?:맞(?:지|나요|습니까|아)?|옳(?:지|나요)?|(?:되|하|인|없|않)는?\s*거지|"
                      r"보면\s*되나|보면\s*되지|거지\s*\?|없지|않지|항상|언제나|필요\s*없지|무관하지|단점\s*없지|"
                      r"라고\s*보면\s*되지|그렇(?:지|습니까)|"
                      r"\b(?:is\s+it\s+(?:true|correct)|isn['’]?t\s+it\s+true\s+that|"
                      r"can\s+i\s+assume|always)\b|\b(?:right|correct)\s*\?)", re.I)
_DIRECT = re.compile(r"\b(?:calculate|compute|convert|conversion|cylinder\s+volume|energy\s+use|mass\s+concentration|linear\s+regression\s+slope|finite\s+difference|centered\s+difference|sum|total|average|mean|median|variance|standard\s+deviation|"
                     r"rank|std|interpolate|trapezoid|geometric\s+mean|elapsed\s+time|allocate|weighted\s+average|"
                     r"combined\s+rate|repeated\s+percent|percent\s+change|piecewise\s+cost|"
                     r"percent\s+to\s+fraction|fraction\s+to\s+percent|percent(?:age)?\s+decrease)\b|"
                     r"평균|중앙값|표준편차|분산|합계|총합|순위|보간|사다리꼴|기하평균|경과\s*시간|비례\s*배분|"
                     r"몇\s*개|얼마|이\s*값들로|사용자\s*값만|자료\s*검색하지\s*마|"
                     r"단위\s*변환|시간당|원기둥\s*부피|소비\s*에너지|질량\s*농도|중심\s*차분|압력\s*변화율|감소율|순\s*변화|"
                     r"%\s*(?:증가|감소|increase|decrease)", re.I)
_NO_KB = re.compile(r"사용자\s*값만|자료\s*검색하지\s*마|외부\s*식\s*검색\s*필요\s*없|내가\s*지정한|"
                    r"\b(?:using\s+only\s+(?:my|the\s+given)\s+values|no\s+retrieval|given\s+values\s+only)\b", re.I)
_FIGURE = re.compile(r"\b(?:figure|fig\.|diagram|plot|image)\b|그림|도표|도식", re.I)
_AMBIGUOUS_ASSERTION = re.compile(r"\b(?:can\s+we\s+(?:treat|regard)|would\s+it\s+be\s+fair\s+to\s+say|"
                                  r"is\s+the\s+assumption\s+that)\b|라고\s*이해해도|라고\s*가정해도|"
                                  r"것으로\s*봐도", re.I)


def ambiguous_premise_candidate(text: str) -> bool:
    return bool(_AMBIGUOUS_ASSERTION.search(text))


def user_equation(text: str) -> str | None:
    """Return one literal arithmetic equation, not a numeric input assignment."""
    equations = []
    for match in EQUATION.finditer(text):
        value = match.group("equation").rstrip(" .\t")
        if expression_variables(value) is None:
            for boundary in reversed([item.start() for item in re.finditer(r"\s+", value)]):
                prefix = value[:boundary].rstrip(" .\t")
                if expression_variables(prefix) is not None:
                    value = prefix
                    break
        if expression_variables(value) and re.search(r"[+*/×÷−]|(?<![eE])-", value.split("=", 1)[1]):
            equations.append(value)
    return equations[0] if len({re.sub(r"\s+", "", row) for row in equations}) == 1 else None


def formula_origin(text: str) -> FormulaOrigin:
    # An explicit source request outranks a coincidentally quoted equation.
    if _KB_ORIGIN.search(text):
        return FormulaOrigin.KB_REFERENCED
    if _USER_ORIGIN.search(text):
        return FormulaOrigin.USER_DEFINED
    return FormulaOrigin.UNKNOWN


def explicitly_underdetermined(text: str) -> bool:
    """Only explicit missing-data requests; never infer unavailable engineering values."""
    return bool(re.search(r"\b(?:exact|optimal|specific)\b|정확한|최적", text, re.I)
                and re.search(r"\b(?:no|without|not\s+(?:provided|known|available)|missing|unspecified)\b|"
                              r"없(?:다|는|고|음|어)|미제공|모르|주어지지|제공되지", text, re.I))


def classify_goal_intent(request: GoalResearchRequest, *, has_user_facts: bool,
                         has_simulation_spec: bool = False) -> GoalIntent:
    """Choose the execution route from the request before the action planner runs."""
    text = " ".join(filter(None, (request.topic, request.goal)))
    equation = user_equation(text)
    origin = formula_origin(text)
    sweep = bool(_SIMULATION.search(text) or has_simulation_spec)
    if equation and sweep and origin != FormulaOrigin.KB_REFERENCED:
        return GoalIntent(GoalIntentKind.USER_FORMULA_SIMULATION, SourceRequirement.USER_FORMULA,
                          equation, "literal_formula_and_sweep", formula_origin=origin)
    if equation and (_CALC.search(text) or origin == FormulaOrigin.USER_DEFINED or has_user_facts) and origin != FormulaOrigin.KB_REFERENCED:
        return GoalIntent(GoalIntentKind.USER_FORMULA_CALC, SourceRequirement.USER_FORMULA,
                          equation, "literal_user_formula", formula_origin=origin)
    if not equation and not has_simulation_spec and explicitly_underdetermined(text):
        return GoalIntent(GoalIntentKind.KNOWLEDGE_QA, SourceRequirement.NONE,
                          reason="check_source_answerability_before_numeric_routing")
    premise = bool(_PREMISE.search(text)) and not bool(re.search(
        r"몇|얼마|무엇|어떻게|\b(?:how\s+many|how\s+much|what\s+is)\b", text, re.I))
    if premise:
        return GoalIntent(GoalIntentKind.PREMISE_CHECK, SourceRequirement.NONE,
                          reason="assertion_verification_cue", premise_cue_detected=True)
    kb_formula = bool(asks_for_api_gravity_calculation(request) or _FORMULA_REQUEST.search(text)
                      or (origin == FormulaOrigin.KB_REFERENCED and re.search(r"식(?:으로|을|에|의)|equation|formula", text, re.I))
                      or (equation and origin == FormulaOrigin.KB_REFERENCED))
    if (not kb_formula and re.search(r"\b(?:explain|describe|define|why)\b|설명|정의|왜", text, re.I)
            and not _EXPLICIT_CALC.search(text)):
        return GoalIntent(GoalIntentKind.KNOWLEDGE_QA, SourceRequirement.NONE, reason="concept_not_numeric_request")
    if _NO_KB.search(text) or (has_user_facts and _DIRECT.search(text) and not kb_formula and not sweep):
        return GoalIntent(GoalIntentKind.DIRECT_CALC, SourceRequirement.NONE,
                          reason="user_requested_generic_operation")
    if has_user_facts and re.search(r"\b(?:minimum|maximum|min|max)\b|최댓값|최솟값", text, re.I) and not kb_formula and not sweep:
        return GoalIntent(GoalIntentKind.DIRECT_CALC, SourceRequirement.NONE, reason="user_requested_extremum")
    if kb_formula and (_CALC.search(text) or sweep or asks_for_api_gravity_calculation(request)):
        return GoalIntent(GoalIntentKind.KB_FORMULA_CALC, SourceRequirement.KB_FORMULA,
                          reason="requested_sourced_relation", formula_origin=origin)
    if sweep:
        return GoalIntent(GoalIntentKind.KB_FORMULA_CALC, SourceRequirement.KB_FORMULA,
                          reason="requested_parameter_sweep")
    if _CALC.search(text) and (has_user_facts or _EXPLICIT_CALC.search(text)):
        if re.search(r"\b(?:explain|describe|define|why)\b|설명|정의|왜", text, re.I) and not _EXPLICIT_CALC.search(text):
            return GoalIntent(GoalIntentKind.KNOWLEDGE_QA, SourceRequirement.NONE, reason="concept_not_numeric_request")
        return GoalIntent(GoalIntentKind.DIRECT_CALC, SourceRequirement.NONE,
                          reason="calculation_request_pending_fact_readiness")
    if _FIGURE.search(text):
        return GoalIntent(GoalIntentKind.FIGURE_QA, SourceRequirement.NONE, reason="figure_request")
    return GoalIntent(GoalIntentKind.KNOWLEDGE_QA, SourceRequirement.NONE, reason="knowledge_question")


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
