"""User-request-only calculation intent. Retrieved passages cannot change outputs."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest
from app.services.goal_intent import FormulaOrigin, asks_for_api_gravity_calculation, formula_origin, user_equation
from app.services.user_fact_registry import UserFactRegistry
from app.services.user_fact_registry import UNIT


class RequestedScenario(BaseModel):
    scenario_id: str


class RequestedOutput(BaseModel):
    semantic_name: str
    output_type: Literal["numeric", "ranking", "list"] = "numeric"
    scenario_id: str | None = None
    unit: str | None = None


class OperationNode(BaseModel):
    operator: str
    input_fact_ids: list[str] = Field(default_factory=list)
    output_name: str
    output_unit: str | None = None
    conversion_steps: list[str] = Field(default_factory=list)


class CalculationRequestIR(BaseModel):
    schema_version: int = 3
    request_id: str = "CRI-1"
    computation_class: Literal["generic_arithmetic", "generic_statistics", "specialist_formula", "mixed"]
    requested_operation_types: list[str] = Field(default_factory=list)
    scenarios: list[RequestedScenario] = Field(default_factory=list)
    requested_outputs: list[RequestedOutput] = Field(default_factory=list)
    requested_aggregates: list[str] = Field(default_factory=list)
    requested_ranking: bool = False
    requested_extrema: list[str] = Field(default_factory=list)
    specialist_relation_required: bool = False
    target_concepts: list[str] = Field(default_factory=list)
    requested_units: dict[str, str] = Field(default_factory=dict)
    evidence_requirements: list[str] = Field(default_factory=list)
    operation_family: str = ""
    operands: list[str] = Field(default_factory=list)
    series: list[str] = Field(default_factory=list)
    weights: list[str] = Field(default_factory=list)
    time_points: list[str] = Field(default_factory=list)
    piecewise_segments: list[str] = Field(default_factory=list)
    requires_domain_formula: bool = False
    requires_user_formula: bool = False
    requires_external_evidence: bool = False
    operation_nodes: list[OperationNode] = Field(default_factory=list)


OPERATIONS = {
    "unit_conversion": r"\b(?:convert|conversion|per hour|per day)\b|시간당|일당|단위\s*변환|으로\s*바꿔",
    "centered_difference": r"\b(?:centered|central)\s+(?:difference|derivative)\b|중심\s*(?:차분|미분)",
    "finite_difference": r"\bfinite\s+difference\b|\b(?:pressure|rate)\s+(?:change\s+)?rate\b|유한\s*차분|압력\s*변화율|변화\s*속도",
    "linear_regression_slope": r"\b(?:linear\s+regression\s+slope|least[- ]squares\s+slope)\b|선형\s*회귀\s*기울기",
    "cylinder_volume": r"\b(?:cylinder|cylindrical)\s+volume\b|원기둥\s*부피|원통\s*부피",
    "power_times_duration": r"\b(?:energy\s+use|power\s*(?:times|×|\*)\s*time|power\s+consumption)\b|전력.{0,16}(?:시간|에너지)|소비\s*에너지",
    "concentration_mass_per_volume": r"\b(?:mass\s+concentration|concentration\s+from\s+mass)\b|질량\s*농도|농도를\s*계산",
    "weighted_average_by_duration": r"\b(?:time[- ]weighted|duration[- ]weighted)\s+(?:average|mean)\b|시간\s*가중\s*평균|가중\s*시간\s*평균",
    "percentage_decrease": r"\bpercent(?:age)?\s+decrease\b|감소율|몇\s*퍼센트\s*감소",
    "percentage_increase": r"\bpercent(?:age)?\s+increase\b|증가율",
    "recovery_percent": r"\b(?:recovery|recovered)\s+(?:rate|percent(?:age)?)\b|회수율",
    "net_difference": r"\bnet\s+(?:difference|change)\b|순\s*변화|순\s*차이",
    "add": r"\b(?:add|addition)\b|더하기",
    "subtract": r"\b(?:subtract|subtraction)\b|빼기",
    "multiply": r"\b(?:multiply|multiplication|product)\b|곱하기",
    "divide": r"\b(?:divide|division|quotient)\b|나누기",
    "mean": r"\b(?:mean|average)\b|평균",
    "median": r"\bmedian\b|중앙값",
    "std_population": r"\b(?:population standard deviation|population std)\b|모표준편차",
    "std_sample": r"\b(?:sample standard deviation|sample std)\b|표본표준편차",
    "std_unspecified": r"\b(?:standard deviation|std)\b|표준편차",
    "rms": r"\brms\b|root[- ]mean[- ]square|제곱평균제곱근",
    "variance_population": r"\bpopulation variance\b|모분산",
    "variance": r"\bvariance\b|분산",
    "coefficient_of_variation": r"\b(?:coefficient of variation|cv)\b|변동계수",
    "range": r"\brange\b|범위",
    "sum": r"\b(?:sum|total)\b|합계|총합",
    "maximum": r"\b(?:maximum|max|highest|largest)\b|최댓값|최대",
    "minimum": r"\b(?:minimum|min|lowest|smallest)\b|최솟값|최소",
    "ranking": r"\b(?:ranking|rank|order(?:ing)?)\b|순위|정렬",
    "percent_change": r"\b(?:percent(?:age)? change|percent(?:age)? difference)\b|변화율",
    "ratio": r"\bratio\b|비율",
    "difference": r"\b(?:difference|subtract|pressure\s+drop)\b|차이|차감|압력\s*강하량",
    "normalize_by_max": r"\bnormaliz\w*\s+by\s+(?:the\s+)?max\w*|최대값\s*정규화",
    "linear_regression": r"\b(?:linear regression|least[- ]squares line)\b|선형회귀",
    "weighted_average": r"\bweighted\s+(?:average|mean)\b|가중\s*평균",
    "combined_rate": r"\b(?:combined|overall)\s+(?:rate|speed)\b|전체\s*(?:평균\s*)?속도|총\s*거리.{0,20}총\s*시간",
    "interpolation": r"\binterpolat\w*\b|보간",
    "trapezoid": r"\btrapezoid\w*\b|사다리꼴\s*(?:적분|면적)",
    "geometric_mean": r"\bgeometric\s+mean\b|기하\s*평균",
    "repeated_percent": r"\b(?:repeated|successive)\s+percent\b|%\s*(?:증가|감소|increase|decrease).{0,25}(?:번|회|times?)|반복\s*(?:증가|감소)",
    "elapsed_time": r"\belapsed\s+time\b|경과\s*시간|걸린\s*시간",
    "allocation": r"\b(?:proportional\s+allocation|allocate\s+by\s+weight)\b|비례\s*(?:할당|배분)",
    "piecewise_cost": r"\bpiecewise\s+(?:cost|price)\b|구간별\s*(?:비용|요금)|추가.{0,20}(?:단가|요금)",
    "percent_conversion": r"\b(?:percent\s+to\s+fraction|fraction\s+to\s+percent)\b|퍼센트.{0,12}소수|소수.{0,12}퍼센트",
}
AGGREGATES = {"mean", "median", "std_population", "std_sample", "std_unspecified", "rms",
              "variance_population", "coefficient_of_variation", "range", "sum", "maximum", "minimum"}
GENERIC = set(OPERATIONS)


def validate_ir(ir: CalculationRequestIR) -> list[str]:
    errors: list[str] = []
    if ir.requires_domain_formula and ir.requires_user_formula:
        errors.append("conflicting_formula_source_requirements")
    scenarios = [item.scenario_id for item in ir.scenarios]
    if len(scenarios) != len(set(scenarios)):
        errors.append("duplicate_scenario")
    outputs = [(item.semantic_name, item.scenario_id) for item in ir.requested_outputs]
    if not outputs:
        errors.append("empty_required_outputs")
    if len(outputs) != len(set(outputs)):
        errors.append("duplicate_output")
    if any(re.search(r"\b(?:KB|USERF|EFACT|FORMULA)\d+\b", value, re.I)
           for value in [*ir.target_concepts, *(item.semantic_name for item in ir.requested_outputs)]):
        errors.append("source_id_in_request_ir")
    if ir.requested_ranking and not scenarios:
        errors.append("ranking_without_scenarios")
    if ir.requested_aggregates and not (scenarios or ir.requested_operation_types):
        errors.append("aggregate_without_base")
    if "std_unspecified" in ir.requested_operation_types:
        errors.append("standard_deviation_convention_ambiguous")
    if any(key not in {item.semantic_name for item in ir.requested_outputs} for key in ir.requested_units):
        errors.append("conflicting_units")
    for name in {item.semantic_name for item in ir.requested_outputs}:
        if len({item.unit.casefold() for item in ir.requested_outputs if item.semantic_name == name and item.unit}) > 1:
            errors.append("conflicting_units")
    return errors


def _scenarios(topic: str, goal: str) -> list[str]:
    text = f"{topic} {goal}"
    labels: list[str] = []
    for match in re.finditer(r"\b(?:case|well|layer|sample|scenario)\s+([A-Z])(?:\s*[-–]\s*([A-Z]))?\b", text):
        first, last = match.group(1), match.group(2)
        values = [chr(code) for code in range(ord(first), ord(last) + 1)] if last and ord(last) - ord(first) <= 12 else [first]
        labels.extend(values)
    if not labels:
        for fact in UserFactRegistry.from_topic(topic).records:
            match = re.match(r"^(?:Well_|Case_|Layer_)?([A-Z])_", fact.name)
            if match:
                labels.append(match.group(1))
    return list(dict.fromkeys(labels))


def parse_request_ir(request: GoalResearchRequest, criteria: list[GoalCriterion]) -> CalculationRequestIR:
    if asks_for_api_gravity_calculation(request):
        # This fixes only the requested output shape. The formula and SG value
        # must still come from validated source evidence and user facts.
        return CalculationRequestIR(
            computation_class="specialist_formula", requested_operation_types=["convert"],
            requested_outputs=[RequestedOutput(semantic_name="API_gravity", unit="dimensionless")],
            specialist_relation_required=True, target_concepts=["API_gravity", "API"],
            requested_units={"API_gravity": "dimensionless"},
            evidence_requirements=["formula", "numeric_facts"],
            operation_family="specialist_formula", requires_domain_formula=True,
            requires_external_evidence=bool(request.use_external),
        )
    goal = " ".join([request.goal or request.topic, *(item.description for item in criteria if item.required)])
    literal_user_formula = user_equation(f"{request.topic} {request.goal or ''}")
    if formula_origin(f"{request.topic} {request.goal or ''}") == FormulaOrigin.KB_REFERENCED:
        literal_user_formula = None
    found = [name for name, pattern in OPERATIONS.items() if re.search(pattern, goal, re.I)]
    for dominant, subsumed in (("weighted_average_by_duration", "weighted_average"),
                               ("cylinder_volume", "unit_conversion"),
                               ("weighted_average_by_duration", "mean"),
                               ("unit_conversion", "mean"),
                               ("finite_difference", "percent_change"),
                               ("finite_difference", "difference"),
                               ("centered_difference", "finite_difference"),
                               ("centered_difference", "difference"),
                               ("linear_regression_slope", "linear_regression"),
                               ("percentage_decrease", "percent_change"),
                               ("percentage_increase", "percent_change"),
                               ("net_difference", "difference")):
        if dominant in found and subsumed in found:
            found.remove(subsumed)
    if "std_population" in found or "std_sample" in found:
        found = [name for name in found if name != "std_unspecified"]
    if "variance_population" in found:
        found = [name for name in found if name != "variance"]
    if "weighted_average" in found:
        found = [name for name in found if name != "mean"]
    if "geometric_mean" in found:
        found = [name for name in found if name != "mean"]
    scenarios = _scenarios(request.topic, goal)
    target_match = re.search(r"\b(?:calculate|compute|estimate|derive|report)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]*)(?:\s+(?:for|in|per|using|then)\b|\s*[,.;]|$)", goal, re.I)
    target = target_match.group(1) if target_match else "result"
    phrase_match = re.search(r"\b(?:calculate|compute|estimate|derive|report)\s+(?:the\s+)?"
                             r"([A-Za-z][A-Za-z0-9_]*(?:\s+[A-Za-z][A-Za-z0-9_]*){0,2})"
                             r"(?=\s+(?:using|from|for|in|then|with)\b|[,.;]|$)", goal, re.I)
    explicit_specialist = bool(re.search(r"\b(?:equation|formula|correlation|scientific relation|productivity index|dimensionless pressure)\b|공식|수식|관계식", goal, re.I)
                               or formula_origin(goal) == FormulaOrigin.KB_REFERENCED)
    specialist = explicit_specialist or (target != "result" and target.casefold() not in GENERIC
                                          and target.casefold() not in {"values", "measurements", "statistics", "results",
                                                                          "addition", "subtraction", "multiplication", "division",
                                                                          "product", "quotient", "normalize"})
    if any(item in found for item in {"linear_regression", "unit_conversion", "linear_regression_slope",
                                      "finite_difference", "centered_difference", "percentage_decrease", "percentage_increase",
                                      "net_difference", "cylinder_volume", "power_times_duration",
                                      "concentration_mass_per_volume", "weighted_average_by_duration"}) and not explicit_specialist:
        specialist = False
    concepts = [target] if target != "result" else []
    if specialist and phrase_match:
        words = phrase_match.group(1).split()
        if len(words) > 1 and "and" not in (word.casefold() for word in words):
            concepts.extend(["_".join(words), "".join(word[0].upper() for word in words)])
            target = "_".join(words)
    aggregates = [name for name in found if name in AGGREGATES]
    ranked = "ranking" in found
    per_case = bool(re.search(r"\b(?:each|every|per[- ](?:case|well|layer|scenario))\b|각각", goal, re.I)) and bool(scenarios)
    outputs = [RequestedOutput(semantic_name=target, scenario_id=scenario) for scenario in scenarios] if per_case else []
    outputs += [RequestedOutput(semantic_name=name, output_type="list" if name == "normalize_by_max" else "numeric")
                for name in found if name not in {"ranking", "linear_regression"}]
    if "linear_regression" in found:
        outputs += [RequestedOutput(semantic_name=name) for name in ("slope", "intercept", "r_squared")]
    if ranked:
        outputs.append(RequestedOutput(semantic_name="ranking", output_type="ranking"))
    if "maximum" in found and scenarios:
        outputs.append(RequestedOutput(semantic_name="leader_ids", output_type="list"))
    if not outputs and specialist:
        outputs.append(RequestedOutput(semantic_name=target))
    if not outputs and found:
        outputs.append(RequestedOutput(semantic_name=found[0]))
    unit_match = re.search(rf"\bin\s+(?P<unit>{UNIT}|dimensionless|percent|percentage_point)\b", goal, re.I)
    if unit_match:
        for output in outputs:
            if output.output_type == "numeric":
                output.unit = unit_match.group("unit")
    for output in outputs:
        if output.semantic_name in {"coefficient_of_variation", "percent_change", "recovery_percent",
                                    "percentage_increase", "percentage_decrease"}:
            output.unit = "percent"
        elif output.semantic_name in {"ratio", "normalize_by_max", "r_squared"}:
            output.unit = "dimensionless"
        elif output.semantic_name in {"variance_population", "slope"}:
            # These dimensions differ from the input unit; leave them unspecified
            # until the full dimensional relationship is available.
            output.unit = None
    computation_class = ("mixed" if specialist and found else "specialist_formula" if specialist else
                         "generic_statistics" if any(name in AGGREGATES | {"ranking", "linear_regression"} for name in found)
                         else "generic_arithmetic")
    parsed_facts = UserFactRegistry.from_topic(request.topic).records
    return CalculationRequestIR(computation_class=computation_class, requested_operation_types=found,
        scenarios=[RequestedScenario(scenario_id=value) for value in scenarios], requested_outputs=outputs,
        requested_aggregates=aggregates, requested_ranking=ranked,
        requested_extrema=[name for name in ("maximum", "minimum") if name in found],
        specialist_relation_required=specialist, target_concepts=list(dict.fromkeys(concepts)),
        requested_units={item.semantic_name: item.unit for item in outputs if item.unit},
        evidence_requirements=(["user_formula", "numeric_facts"] if literal_user_formula else
                               ["formula", "numeric_facts"] if specialist else ["numeric_facts"]),
        operation_family=("specialist_formula" if specialist else "generic_statistics" if aggregates else "generic_arithmetic"),
        operands=[row.fact_id for row in parsed_facts],
        series=[row.fact_id for row in parsed_facts if row.name.startswith("day_")],
        weights=[row.fact_id for row in parsed_facts if row.name.endswith("_weight")],
        time_points=[row.fact_id for row in parsed_facts if row.name in {"start_time", "end_time"}],
        requires_domain_formula=specialist and not bool(literal_user_formula),
        requires_user_formula=bool(literal_user_formula),
        requires_external_evidence=bool(request.use_external),
        operation_nodes=[OperationNode(operator=name, input_fact_ids=[row.fact_id for row in parsed_facts],
                                       output_name=name) for name in found])


async def resolve_request_ir(request: GoalResearchRequest, criteria: list[GoalCriterion], ollama: object) -> CalculationRequestIR | None:
    """Only repair an invalid deterministic parse; never provide numbers or source IDs."""
    ir = parse_request_ir(request, criteria)
    if "standard_deviation_convention_ambiguous" in validate_ir(ir):
        return ir  # Require an explicit population/sample convention; never guess.
    if not validate_ir(ir):
        return ir
    messages = [{"role": "system", "content": "Extract requested calculation outputs from user wording only. Do not invent numbers, formulas or source IDs. Return JSON matching schema."},
                {"role": "user", "content": json.dumps({"goal": request.goal or request.topic,
                    "criteria": [item.description for item in criteria], "parser_errors": validate_ir(ir)}, ensure_ascii=False)}]
    for attempt in range(2):
        try:
            raw = await ollama.chat_structured(messages, CalculationRequestIR.model_json_schema(),
                                               model=request.model, temperature=0, seed=request.seed)
            repaired = CalculationRequestIR.model_validate_json(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
            if not validate_ir(repaired):
                return repaired
        except (ValueError, TypeError, AttributeError, RuntimeError):
            pass
        messages.append({"role": "user", "content": "Repair schema/consistency only; do not invent data."})
    return None
