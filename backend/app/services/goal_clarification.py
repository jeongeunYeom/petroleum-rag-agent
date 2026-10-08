"""Source-bound simulation readiness and batched, non-guessing clarifications."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.calculation_requirements import normalize_symbol
from app.services.evidence_fact_registry import EvidenceFactRegistry
from app.services.formula_source_registry import FormulaSourceRecord, FormulaSourceRegistry, expression_variables
from app.services.goal_execution_state import DerivedFact, SimulationParameter, SimulationSpec
from app.services.goal_simulation import validate_expression
from app.services.user_fact_registry import UserFactRegistry


_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_RANGE = re.compile(rf"(?P<start>{_NUMBER})\s*(?:~|∼|부터|에서|to)\s*(?P<stop>{_NUMBER})", re.I)
_STEP = re.compile(rf"(?P<step>{_NUMBER})\s*(?:간격|씩|step)", re.I)
_ENGLISH_RANGE = re.compile(rf"(?P<name>[A-Za-z][A-Za-z0-9_]*)\s+from\s+"
                            rf"(?P<start>{_NUMBER})\s+to\s+(?P<stop>{_NUMBER})", re.I)


@dataclass
class SimulationReadiness:
    spec: SimulationSpec | None = None
    missing: list[str] = field(default_factory=list)
    formula_source_id: str | None = None
    input_ids: list[str] = field(default_factory=list)


def _requested_parameter(text: str, formula_variables: set[str]) -> str | None:
    if re.search(r"공극률|\bporosity\b", text, re.I):
        matches = [name for name in formula_variables if normalize_symbol(name) in {"porosity", "phi"}]
        return matches[0] if len(matches) == 1 else None
    found = _ENGLISH_RANGE.search(text)
    if found:
        matches = [name for name in formula_variables if normalize_symbol(name) == normalize_symbol(found["name"])]
        return matches[0] if len(matches) == 1 else None
    return None


def _formula_for_goal(text: str, evidence: list[dict[str, Any]]):
    candidates = []
    words = {normalize_symbol(word) for word in re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)}
    if re.search(r"CO₂?|이산화탄소", text, re.I) and re.search(r"저장량|저장\s*용량", text):
        words.update({"co2storage", "co2capacity", "co2storagecapacity"})
    for record in FormulaSourceRegistry.from_evidence(evidence).records:
        if record.expression_candidate:
            lhs = normalize_symbol(record.expression_candidate.split("=", 1)[0])
            if lhs in words:
                candidates.append(record)
    unique = {record.normalized_span: record for record in candidates}
    return next(iter(unique.values())) if len(unique) == 1 else None


def simulation_readiness(text: str, evidence: list[dict[str, Any]],
                         users: UserFactRegistry,
                         derived_facts: list[DerivedFact] | None = None) -> SimulationReadiness:
    """Build a sweep only from a literal retrieved equation and explicit numeric facts."""
    missing: list[str] = []
    formula = _formula_for_goal(text, evidence)
    if formula is None:
        missing.append("출처가 확인된 시뮬레이션 모델/관계식")
    found_range = _RANGE.search(text)
    if not found_range:
        missing.append("변화시킬 변수와 시작·종료 값")
    found_step = _STEP.search(text)
    if not found_step:
        missing.append("변수 변화 간격")
    if formula is None:
        return SimulationReadiness(missing=missing)

    variables = expression_variables(formula.expression_candidate or "") or set()
    parameter = _requested_parameter(text, variables)
    if parameter is None:
        return SimulationReadiness(missing=["관계식에서 변화시킬 변수 이름"])
    # A textbook example's reservoir values are not automatically this user's reservoir.
    use_source_case = bool(re.search(r"자료의\s*값|문서에\s*나온\s*값|교재\s*예시|"
                                     r"(?:use|using)\s+(?:the\s+)?(?:source|document|example)\s+values",
                                     text, re.I))
    facts = [*users.records, *(derived_facts or []),
             *(EvidenceFactRegistry.from_evidence(evidence).records if use_source_case else [])]
    bindings: dict[str, float] = {}
    input_ids: list[str] = []
    for variable in sorted(variables - {parameter}):
        matches = [fact for fact in facts if normalize_symbol(fact.name) == normalize_symbol(variable)]
        if len(matches) != 1:
            missing.append(f"{variable} 값" if not matches else f"{variable} 값 확인(여러 값 발견)")
            continue
        fact = matches[0]
        normalized_unit = fact.unit.casefold().replace("^", "")
        if ("volume" in variable.casefold() and normalized_unit != "m3") or (
                "density" in variable.casefold() and normalized_unit != "kg/m3"):
            missing.append(f"{variable} 값과 호환 단위")
            continue
        bindings[variable] = fact.value
        input_ids.append(fact.parent_calc_id if isinstance(fact, DerivedFact) else fact.fact_id)
    if missing:
        return SimulationReadiness(missing=missing, formula_source_id=formula.source_id)

    rhs = (formula.expression_candidate or "").split("=", 1)[1].strip()
    tree = ast.parse(rhs, mode="eval")

    class Bind(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.AST:
            return ast.copy_location(ast.Constant(value=bindings[node.id]), node) if node.id in bindings else node

    expression = ast.unparse(Bind().visit(tree))
    spec = SimulationSpec(
        parameter=SimulationParameter(name=parameter, start=float(found_range["start"]),
                                      stop=float(found_range["stop"]), step=float(found_step["step"])),
        expression=expression, output_name=(formula.expression_candidate or "").split("=", 1)[0].strip(),
        objective="min" if re.search(r"최소|\bminimi[sz]e\b", text, re.I) else "max",
    )
    validate_expression(spec)
    return SimulationReadiness(spec=spec, formula_source_id=formula.source_id,
                               input_ids=input_ids)


def clarification_question(missing: list[str], korean: bool) -> str:
    items = list(dict.fromkeys(missing))
    if korean:
        return "계산을 계속하려면 " + ", ".join(items) + "이(가) 필요합니다. 값과 단위를 한 번에 알려주세요."
    return "To continue, please provide: " + ", ".join(items) + ". Include units where applicable."


def calculation_missing(formula: FormulaSourceRecord | None, evidence: list[dict[str, Any]],
                        users: UserFactRegistry, derived_facts: list[DerivedFact]) -> list[str]:
    if formula is None:
        return ["출처가 확인된 계산 관계식"]
    available = {normalize_symbol(fact.name) for fact in [
        *users.records, *EvidenceFactRegistry.from_evidence(evidence).records, *derived_facts]}
    variables = expression_variables(formula.expression_candidate or "") or set()
    return [f"{variable} 값과 단위" for variable in sorted(variables)
            if normalize_symbol(variable) not in available]
