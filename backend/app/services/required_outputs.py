"""User-goal-derived output requirements, independent of benchmark answers."""

from __future__ import annotations

import re

from pydantic import BaseModel

from app.models.goal_research_schemas import CalculationContract, GoalResearchRequest
from app.services.calculation_requirements import CalculationRequirementGraph
from app.services.calculation_requirements import normalize_symbol
from app.services.calculation_request_ir import CalculationRequestIR


class RequiredOutputIntent(BaseModel):
    semantic_name: str
    output_type: str
    scenario_id: str | None = None
    requested_unit: str | None = None
    required: bool = True


def checklist_from_ir(ir: CalculationRequestIR) -> list[RequiredOutputIntent]:
    """Freeze output shape before any evidence or plan is inspected."""
    return [RequiredOutputIntent(semantic_name=item.semantic_name, output_type=item.output_type,
                                 scenario_id=item.scenario_id, requested_unit=item.unit)
            for item in ir.requested_outputs]


def required_output_checklist(request: GoalResearchRequest, graph: CalculationRequirementGraph) -> list[RequiredOutputIntent]:
    text = " ".join([request.goal or request.topic, *(item.description for item in request.success_criteria if item.required)]).casefold()
    outputs: list[RequiredOutputIntent] = []
    scenarios = [key for key in graph.scenario_bindings if key != "default"]
    if re.search(r"\b(?:each|per[- ](?:well|case|scenario|layer|sample)|every)\b|각각|각\s*(?:시나리오|우물|사례|층)", text):
        outputs.extend(RequiredOutputIntent(semantic_name="per_case", output_type="numeric", scenario_id=key)
                       for key in scenarios)
    patterns = {
        "mean": r"\b(?:mean|average|averaged)\b|평균",
        "maximum": r"\b(?:max(?:imum)?|largest|highest)\b|최대",
        "minimum": r"\b(?:min(?:imum)?|smallest|lowest)\b|최소",
        "ranking": r"\b(?:rank(?:ing|ed)?|order(?:ing)?)\b|순위|정렬",
        "rms": r"\b(?:rms|root[- ]mean[- ]square)\b|제곱평균제곱근",
        "sum": r"\b(?:sum|total)\b|합계|총합",
    }
    for name, pattern in patterns.items():
        if re.search(pattern, text):
            outputs.append(RequiredOutputIntent(semantic_name=name,
                output_type="ranking" if name == "ranking" else "numeric"))
    return outputs


def missing_checklist_outputs(contract: CalculationContract, checklist: list[RequiredOutputIntent]) -> list[str]:
    missing: list[str] = []
    for intent in checklist:
        candidates = [item for item in contract.required_outputs if item.required and
                      (intent.scenario_id is None or item.scenario_id == intent.scenario_id or
                       (item.scenario_id and normalize_symbol(item.scenario_id).endswith(normalize_symbol(intent.scenario_id))))]
        if intent.semantic_name == "per_case":
            matches = [item for item in candidates if item.semantic_type == "numeric"]
        else:
            terms = {
                "mean": ("mean", "average"), "maximum": ("max", "largest", "highest"),
                "minimum": ("min", "smallest", "lowest"), "ranking": ("rank", "order"),
                "rms": ("rms", "root_mean_square"), "sum": ("sum", "total"),
            }.get(intent.semantic_name, (intent.semantic_name,))
            matches = [item for item in candidates if any(term.casefold() in (item.name + " " + item.output_id).casefold()
                       for term in terms) and (intent.semantic_name != "ranking" or item.semantic_type in {"ranking", "list"})]
        if not matches:
            missing.append(f"{intent.scenario_id or 'aggregate'}:{intent.semantic_name}")
    return missing
