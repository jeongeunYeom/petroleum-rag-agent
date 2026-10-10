"""Synthetic development regressions, not frozen benchmark examples or scores."""

from __future__ import annotations

import asyncio
import hashlib
import pytest

from app.models.goal_research_schemas import (ComputationRecord, CriterionEvaluation, CriterionStatus,
                                             ExpectedResultStatus, GoalCriterion, GoalResearchRequest)
from app.services.calculation_requirements import select_formula_candidate
from app.services.engineering_validator import EngineeringValidator
from app.services.engineering.drilling import DrillingValidator
from app.services.formula_source_registry import FormulaSourceRegistry, source_contains_equation
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_clarification import calculation_readiness, parse_user_simulation_spec
from app.services.goal_evaluator import GoalEvaluationResult, GoalEvaluator
from app.services.goal_execution_agent import GoalExecutionAgent, _V8ToolPlanner
from app.services.goal_execution_state import ActionRecord, GoalActionType, GoalExecutionState
from app.services.user_fact_registry import UserFactRegistry


FORMULA_EVIDENCE = [
    {"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "textbook p.89",
     "text": "Worked example: convert a measured specific gravity to API gravity."},
    {"evidence_id": "KB2", "source_type": "knowledge_base", "locator": "textbook p.90",
     "text": "The conversion is API = (141.5 / SG) - 131.5 for oil specific gravity."},
]


@pytest.mark.parametrize("intent", ["Calculate API gravity from SG", "비중으로 API도를 계산", "Find SG API relation"])
def test_equation_source_is_the_actual_span_not_neighbor(intent):
    selected = select_formula_candidate(FORMULA_EVIDENCE, intent, ["SG"])
    assert selected and selected.source_id == "KB2"
    assert source_contains_equation(selected, FORMULA_EVIDENCE[1]["text"], "API=(141.5/SG)-131.5")
    assert not source_contains_equation(selected, FORMULA_EVIDENCE[0]["text"])
    assert not source_contains_equation(selected, FORMULA_EVIDENCE[1]["text"], "API=(142.5/SG)-131.5")


def _record(**changes):
    values = dict(computation_id="CALC1", analysis_id="PA-1", purpose="API gravity",
                  formula="API=(141.5/SG)-131.5", source_formula="API=(141.5/SG)-131.5",
                  formula_evidence_ids=["KB2"], formula_source_ids=["KB2"],
                  source_input_ids=["USERF1"], input_fact_ids=["USERF1"],
                  bound_variables={"SG": "USERF1"}, normalized_formula="api=(141.5/sg)-131.5",
                  units={"SG": "", "OUT_api": "°API"},
                  execution_hash=hashlib.sha256(b"print(22.64)").hexdigest(),
                  attempt_records=[{"attempt": 1, "code": "print(22.64)", "validation_passed": True}],
                  output={"OUT_api": 22.64}, output_manifest={"OUT_api": {"name": "API_gravity",
                      "value": 22.64, "unit": "°API", "semantic_type": "numeric"}},
                  validation_passed=True, contract_validation_passed=True)
    values.update(changes)
    return ComputationRecord(**values)


def test_complete_calculation_chain_and_numeric_claim_gate():
    evidence = [*FORMULA_EVIDENCE, {"evidence_id": "USERF1", "source_type": "user_fact",
                                   "text": "SG=0.918", "name": "SG", "value": 0.918}]
    assert GoalExecutionAgent._provenance_complete(_record(), evidence, "Calculate API gravity")
    assert not GoalExecutionAgent._provenance_complete(_record(formula_source_ids=["KB1"]), evidence,
                                                       "Calculate API gravity")
    assert not GoalExecutionAgent._provenance_complete(_record(execution_hash=None), evidence,
                                                       "Calculate API gravity")
    answer, removed = GoalExecutionAgent._filter_numeric_claims(
        "API gravity is 22.64 °API. [CALC1] [KB2]\nAPI gravity is 99 °API. [KB2]",
        evidence, [_record()])
    assert removed == 1 and "22.64" in answer and "99" not in answer


@pytest.mark.parametrize("question", [
    "Kick occurs when mud pressure exceeds formation pressure, right?",
    "Is a kick caused by mud hydrostatic pressure being higher than pore pressure?",
    "Kick은 mud pressure가 formation pressure보다 높을 때 생기는 거지?",
])
def test_false_premise_requires_explicit_cited_evidence_backed_correction(question):
    validator = EngineeringValidator()
    assert validator.detect_false_premises(question)
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "A kick may occur when formation pressure exceeds mud hydrostatic pressure."}]
    request = GoalResearchRequest(topic=question, goal=question)
    evaluator = GoalEvaluator(object())
    agreement = evaluator._validate_candidate(request,
        "Yes, a kick occurs when mud pressure exceeds formation pressure. [KB1]", evidence)
    assert not agreement["false_premise_corrected"]
    correction = "No, that premise is incorrect. A kick may occur when formation pressure exceeds mud pressure. [KB1]"
    checked = evaluator._validate_candidate(request, correction, evidence)
    assert checked["false_premise_corrected"] and checked["unsupported_engineering_claim_count"] == 0
    split_correction = "No, that premise is incorrect.\nA kick may occur when formation pressure exceeds mud pressure. [KB1]"
    assert evaluator._validate_candidate(request, split_correction, evidence)["false_premise_corrected"]
    assert not evaluator._validate_candidate(request, correction.replace(" [KB1]", ""), evidence)["false_premise_corrected"]
    bad_evidence = [{**evidence[0], "text": "This page discusses drilling fluid composition."}]
    assert evaluator._validate_candidate(request, correction, bad_evidence)["unsupported_engineering_claim_count"] > 0
    assert DrillingValidator().grounded_correction(question, evidence, korean=False).endswith("[KB1]")
    assert DrillingValidator().grounded_correction(question, bad_evidence, korean=False) is None


def _state(goal):
    return GoalExecutionState.from_criteria("DEV-RUN", goal,
        [GoalCriterion(criterion_id="C1", description="Provide the requested result")])


@pytest.mark.parametrize("goal", [
    "Calculate the mean and sum of these rates",
    "이 값들의 평균과 합계를 구해줘",
    "A와 B의 비율과 차이를 계산해줘",
])
def test_user_values_start_with_calculate_not_retrieve(goal):
    request = GoalResearchRequest(topic="A=187 stb/d, B=234 stb/d", goal=goal,
                                  execution_mode="autonomous_goal_execution",
                                  allow_python_execution=True, python_execution_approved=True)
    facts = UserFactRegistry.from_topic(request.topic)
    action = GoalActionPlanner.select(request, _state(goal), user_fact_ids=[r.fact_id for r in facts.records],
                                      formula_ready=False, simulation_spec=None)
    assert action.action_type == GoalActionType.CALCULATE


@pytest.mark.parametrize("goal", ["Compute A/B ratio and A-B difference",
                                      "A/B 비율과 A-B 차이를 계산해줘"])
def test_generic_arithmetic_survives_llm_no_tool_decision(goal):
    class DecliningOllama:
        async def chat_structured(self, *_args, **_kwargs):
            return '{"tool_needed":false,"tool_type":"none","reason":"No tool needed"}'

    request = GoalResearchRequest(topic="A=12 stb/d, B=4 stb/d", goal=goal,
                                  allow_python_execution=True, python_execution_approved=True)
    evidence = UserFactRegistry.from_topic(request.topic).evidence()
    decision = asyncio.run(_V8ToolPlanner(DecliningOllama()).decide(
        request, [GoalCriterion(criterion_id="C1", description="Calculate requested ratio and difference")],
        evidence, None))
    assert decision.tool_needed and decision.tool_type == "python_calculation"
    assert decision.selected_user_fact_ids == ["USERF1", "USERF2"]


@pytest.mark.parametrize("message", [
    "Sweep porosity from 0.10 to 0.30 in steps of 0.02; score = porosity * 50 + 10",
    "porosity를 0.10부터 0.30까지 0.02 간격으로 변화시키며 score = porosity * 50 + 10을 계산해줘",
])
def test_user_equation_sweep_skips_kb(message):
    spec = parse_user_simulation_spec(message)
    assert spec and spec.expression == "porosity * 50 + 10"
    request = GoalResearchRequest(topic=message, goal=message,
                                  allow_python_execution=True, python_execution_approved=True)
    action = GoalActionPlanner.select(request, _state(message), user_fact_ids=[],
                                      formula_ready=False, simulation_spec=spec)
    assert action.action_type == GoalActionType.SIMULATE


def test_korean_maximum_request_analyzes_validated_sweep():
    goal = "porosity를 0.12부터 0.22까지 변화시키며 response = porosity * 40 + 3의 최댓값을 찾아줘"
    request = GoalResearchRequest(topic=goal, goal=goal,
                                  allow_python_execution=True, python_execution_approved=True)
    state = _state(goal)
    state.computation_ids.append("CALC1")
    state.completed_actions.append(ActionRecord(iteration=1, action_id="A1", action_type=GoalActionType.SIMULATE,
                                                target_criteria=[], status="completed", reason_code="simulation_inputs_ready"))
    action = GoalActionPlanner.select(request, state, user_fact_ids=[], formula_ready=False,
                                      simulation_spec=parse_user_simulation_spec(
                                          goal.replace("변화시키며", "0.02 간격으로 변화시키며")))
    assert action.action_type == GoalActionType.ANALYZE


def test_missing_formula_variable_gates_python_and_repeated_blocker_stops():
    formula = FormulaSourceRegistry.from_evidence(FORMULA_EVIDENCE).records[0]
    users = UserFactRegistry.from_topic("Find API gravity from the internal equation")
    assert calculation_readiness(formula, FORMULA_EVIDENCE, users, []) == ["SG 값"]
    request = GoalResearchRequest(topic="Use the textbook equation", goal="Calculate API gravity",
                                  allow_python_execution=True, python_execution_approved=True)
    state = _state(request.goal)
    state.completed_actions.append(ActionRecord(iteration=1, action_id="A1", action_type=GoalActionType.RETRIEVE,
                                                target_criteria=[], status="completed", reason_code="source_found"))
    state.evidence_ids.append("KB2")
    blocked = GoalActionPlanner.select(request, state, user_fact_ids=[], formula_ready=True,
                                       formula_inputs_ready=False, simulation_spec=None)
    assert blocked.action_type == GoalActionType.STOP and blocked.reason_code == "calculation_blocked"
    state.completed_actions.extend([
        ActionRecord(iteration=2, action_id="A2", action_type=GoalActionType.CALCULATE,
                     target_criteria=[], status="blocked", reason_code="calculation_inputs_ready"),
        ActionRecord(iteration=3, action_id="A3", action_type=GoalActionType.RETRIEVE,
                     target_criteria=[], status="blocked", reason_code="calculation_failed_replan"),
    ])
    assert GoalActionPlanner.select(request, state, user_fact_ids=[], formula_ready=True,
                                    formula_inputs_ready=False, simulation_spec=None).reason_code == "calculation_blocked"


@pytest.mark.parametrize("goal", ["Find the undocumented Kappa-Zeta formula and calculate Zeta",
                                      "근거 없는 새로운 Kappa-Zeta 관계식으로 Zeta를 계산해줘"])
def test_unsupported_specialist_formula_never_starts_python(goal):
    request = GoalResearchRequest(topic="Xq=31 psi", goal=goal,
                                  allow_python_execution=True, python_execution_approved=True,
                                  max_retrieval_actions=1)
    state = _state(goal)
    state.completed_actions.append(ActionRecord(iteration=1, action_id="A1", action_type=GoalActionType.RETRIEVE,
                                                target_criteria=[], status="completed", reason_code="formula_search"))
    action = GoalActionPlanner.select(request, state, user_fact_ids=["USERF1"],
                                      formula_ready=False, simulation_spec=None)
    assert action.action_type == GoalActionType.STOP


def test_false_premise_inferred_criteria_are_correction_not_wrong_assumption():
    request = GoalResearchRequest(topic="Kick은 이수압이 지층압보다 높으면 생기는 거지?",
                                  goal="내부 자료로 확인해줘")
    criteria = GoalExecutionAgent._premise_criteria(request)
    assert len(criteria) == 3 and all("이수압이 지층압보다 높" not in item.description for item in criteria)
    baseline = GoalEvaluationResult(
        criteria=[CriterionEvaluation(criterion_id=item.criterion_id, status=CriterionStatus.UNMET,
                                      reason="model grading failed", supporting_evidence=[]) for item in criteria],
        coverage=0.0, achieved=False, expected_result_status=ExpectedResultStatus.NOT_PROVIDED,
        gaps=["model grading failed"], next_research_need=None,
        engineering_validation_passed=True, engineering_contradiction_count=0,
        unsupported_engineering_claim_count=0, goal_conflicts_with_evidence=False)
    answer = ("그 전제는 잘못되었습니다.\nKick은 지층압이 이수압보다 높을 때 "
              "발생할 수 있습니다. [KB1]")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "Kicks occur when formation pressure is greater than mud hydrostatic pressure."}]
    corrected = GoalExecutionAgent._validated_premise_criteria(baseline, criteria, request, answer, evidence)
    assert corrected.achieved and corrected.coverage == 1.0
    assert all(row.status == CriterionStatus.MET for row in corrected.criteria)
    assert not GoalExecutionAgent._validated_premise_criteria(
        baseline, criteria, request, answer.replace(" [KB1]", ""), evidence).achieved
    assert not GoalExecutionAgent._validated_premise_criteria(
        baseline, criteria, request, answer,
        [{**evidence[0], "text": "This passage only mentions drilling fluid."}]).achieved
