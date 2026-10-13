"""Frozen user-request obligations; retrieved text cannot add new goals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.models.goal_research_schemas import GoalResearchRequest
from app.services.calculation_requirements import normalize_symbol
from app.services.goal_execution_state import RequiredGoal
from app.services.source_answerability import SupportStatus, evaluate_claim_support, grounded_answer


_CALCULATE = re.compile(r"\b(?:calculat\w*|comput\w*|determin\w*)\b|계산|산출|구해|구하", re.I)
_EXPLAIN = re.compile(r"\b(?:explain|describe|define|state|find)\b|설명|관계식.{0,4}찾|의미|해석", re.I)
_COMPARE = re.compile(r"\b(?:compare|rank|higher|lower)\b|비교|순위|높은|낮은", re.I)
_UNIT = re.compile(r"(?<![A-Za-z])(?:psi|psia|kPa|ppg|mD|cP|stb/d|ohm-m)(?![A-Za-z])", re.I)


def _goal(kind: str, target: str, span: str, index: int) -> RequiredGoal:
    unit = _UNIT.search(span)
    return RequiredGoal(goal_id=f"G{index}", goal_type=kind, semantic_target=target.strip(" .,:;"),
                        source_text_span=span.strip(), requested_unit=unit.group() if unit else None,
                        requires_evidence=kind.startswith("knowledge"),
                        requires_calculation=kind == "numeric_calculation")


def parse_required_goals(request: GoalResearchRequest, intent_kind: str,
                         numeric_target: str | None) -> list[RequiredGoal]:
    """Split only explicit output obligations, never bare noun conjunctions."""
    text = (request.current_message or request.goal or request.topic).strip()
    if intent_kind == "direct_calc":
        # A single arithmetic run can satisfy several explicit outputs. Freeze
        # each requested output separately instead of treating the whole prompt
        # as an output name that no CALC manifest can ever match.
        from app.services.calculation_request_ir import parse_request_ir
        outputs = parse_request_ir(request, []).requested_outputs
        aggregate_names = {"mean", "sum", "ranking", "maximum", "minimum", "median", "range",
                           "std_population", "std_sample", "variance", "variance_population"}
        names = list(dict.fromkeys(item.semantic_name for item in outputs
                                   if item.semantic_name in aggregate_names))
        if len(names) >= 2:
            return [_goal("numeric_calculation", name, text, index)
                    for index, name in enumerate(names, 1)]
    # Values in an earlier sentence are context, not another requested output.
    clause = re.split(r"[.!?]\s*", text)[-1].strip() or text
    goals: list[RequiredGoal] = []
    paired = re.search(
        r"(?P<first>[가-힣A-Za-z][가-힣A-Za-z_-]{0,40})\s*(?:와|과)\s*"
        r"(?P<second>[가-힣A-Za-z][가-힣A-Za-z_-]{0,40})\s+"
        r"(?P<relation>관계식|관계|정의)을?\s*각각\s*(?:찾|설명)", clause, re.I)
    if paired and _CALCULATE.search(clause[paired.end():]):
        # "X와 Y 관계식을 각각 찾아 Y를 계산" asks for X's relation and Y's value.
        first = paired.group("first")
        goals.append(_goal("knowledge_relation", f"{first} {paired.group('relation')}",
                           paired.group(), 1))
        goals.append(_goal("numeric_calculation", numeric_target or paired.group("second"),
                           clause[paired.end():], 2))
        return goals

    separate = re.search(
        r"\b(?P<verb>calculate|compute|explain|describe|define)\s+"
        r"(?P<first>[A-Za-z][A-Za-z_ -]{0,35}?)\s+and\s+"
        r"(?P<second>[A-Za-z][A-Za-z_ -]{0,35}?)\s+(?:separately|each)\b|"
        r"(?P<ko_first>[가-힣A-Za-z][가-힣A-Za-z_ -]{0,35}?)\s*(?:와|과)\s*"
        r"(?P<ko_second>[가-힣A-Za-z][가-힣A-Za-z_ -]{0,35}?)\s*를?\s*"
        r"각각\s*(?P<ko_verb>계산|설명)", clause, re.I)
    if separate:
        verb = (separate.group("verb") or separate.group("ko_verb")).casefold()
        kind = "numeric_calculation" if verb in {"calculate", "compute", "계산"} else "knowledge_explanation"
        return [_goal(kind, separate.group("first") or separate.group("ko_first"),
                      separate.group(), 1),
                _goal(kind, separate.group("second") or separate.group("ko_second"),
                      separate.group(), 2)]

    # Verb coordination is an explicit pair of obligations; "oil and gas flow" is not.
    boundaries = list(re.finditer(r"\b(?:then|and)\s+(?=(?:calculat\w*|comput\w*|explain|describe|define|compare|rank|give)\b)|"
                                  r"(?:하고|한\s*뒤|한\s*후|하며|해서)\s*(?=[^,.]{0,70}(?:계산|설명|비교|순위|차이))",
                                  clause, re.I))
    if boundaries:
        split = boundaries[0]
        pieces = [clause[:split.start()].strip(), clause[split.end():].strip()]
        # Looking up the formula for the same requested value is a dependency of
        # its calculation, not a second user-facing explanation obligation.
        lookup_only = bool(re.search(r"\bfind\b", pieces[0], re.I) and
                           not re.search(r"\b(?:explain|describe|define)\b", pieces[0], re.I) and
                           not re.search(r"\brelation\s+between\b", pieces[0], re.I))
        if all(pieces) and all(_CALCULATE.search(part) or _EXPLAIN.search(part) or _COMPARE.search(part)
                               or re.search(r"\bgive\s+(?:the\s+)?(?:percentage\s+)?difference\b", part, re.I)
                               for part in pieces) and not lookup_only:
            for part in pieces:
                kind = ("numeric_calculation" if _CALCULATE.search(part) or
                        re.search(r"\b(?:percentage\s+)?difference\b|차이", part, re.I)
                        else "comparison" if _COMPARE.search(part) else "knowledge_explanation")
                goals.append(_goal(kind, numeric_target or part if kind == "numeric_calculation" else part,
                                   part, len(goals) + 1))
            if len(goals) == 2 and (goals[0].goal_type != goals[1].goal_type or
                                    goals[0].semantic_target != goals[1].semantic_target):
                return goals
    kind = ("numeric_calculation" if intent_kind in {"direct_calc", "user_formula_calc", "kb_formula_calc"}
            else "simulation" if intent_kind == "user_formula_simulation"
            else "premise_check" if intent_kind == "premise_check"
            else "knowledge_explanation")
    return [_goal(kind, numeric_target or clause, clause, 1)]


@dataclass(frozen=True)
class GoalProof:
    status: str
    supporting_ids: list[str]
    repair_segment: str = ""


def check_required_goals(goals: list[RequiredGoal], request: GoalResearchRequest,
                         answer: str, evidence: list[dict[str, Any]],
                         computations: list[Any]) -> tuple[list[RequiredGoal], dict[str, GoalProof]]:
    """A retrieved passage is not a completed answer; the answer must adopt it."""
    checked: list[RequiredGoal] = []
    proofs: dict[str, GoalProof] = {}
    for goal in goals:
        if goal.requires_evidence:
            focused = request.model_copy(update={"topic": goal.semantic_target,
                                                 "goal": goal.semantic_target, "success_criteria": []})
            support = evaluate_claim_support(focused, evidence)
            ids = list(dict.fromkeys(sid for claim in support.claims
                                     for sid in claim.supporting_evidence_ids))
            spans = [span for claim in support.claims for span in claim.supporting_spans]
            represented = bool(spans and all(span in answer for span in spans)
                               and all(f"[{sid}]" in answer for sid in ids))
            status = "MET" if support.all_required_supported and represented else (
                "PARTIAL" if support.some_supported else "UNMET")
            repair = grounded_answer(focused, support) if support.all_required_supported else ""
        elif goal.requires_calculation:
            target = normalize_symbol(goal.semantic_target)
            matching = [(calc, row) for calc in computations
                        if calc.validation_passed and calc.contract_validation_passed
                        for row in calc.output_manifest.values()
                        if normalize_symbol(str(row.get("name") or "")) == target]
            ids = [calc.computation_id for calc, _ in matching]
            represented = any(f"[{calc.computation_id}]" in answer and
                              (str(row.get("value")) in answer or
                               isinstance(row.get("value"), list) and
                               " > ".join(str(value) for value in row["value"]) in answer) and
                              (not row.get("unit") or str(row["unit"]) in answer)
                              for calc, row in matching)
            status = "MET" if represented else "PARTIAL" if matching else "UNMET"
            repair = ""  # Existing validated-calculation finalizer supplies numeric segments.
        elif goal.goal_type in {"comparison", "ranking"}:
            cited = [calc.computation_id for calc in computations
                     if calc.validation_passed and calc.contract_validation_passed
                     and f"[{calc.computation_id}]" in answer
                     and any(re.search(r"rank|order|max|min|difference|percent", str(row.get("name") or ""), re.I)
                             for row in calc.output_manifest.values())]
            conclusion = bool(re.search(r"\b(?:higher|lower|greater|smaller|rank|difference)\b|"
                                        r"더\s*(?:높|낮|크|작)|차이|순위|\s>\s", answer, re.I))
            ids, repair = cited, ""
            status = "MET" if cited and conclusion else "PARTIAL" if cited else "UNMET"
        else:
            ids, repair = [], ""
            status = "MET" if answer.strip() else "UNMET"
        checked.append(goal.model_copy(update={"status": status, "supporting_ids": ids}))
        proofs[goal.goal_id] = GoalProof(status, ids, repair)
    return checked, proofs


def repair_required_answer(answer: str, missing_goal_ids: list[str],
                           proofs: dict[str, GoalProof]) -> tuple[str, bool]:
    """One append-only repair from already verified literal source spans."""
    additions = list(dict.fromkeys(proofs[goal_id].repair_segment for goal_id in missing_goal_ids
                                   if proofs[goal_id].repair_segment))
    if not additions:
        return answer, False
    return answer.rstrip() + "\n" + "\n".join(additions), True
