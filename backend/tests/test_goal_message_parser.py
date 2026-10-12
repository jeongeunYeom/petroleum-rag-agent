from __future__ import annotations

import asyncio
import pytest

from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_execution_state import GoalExecutionState, GoalActionType
from app.services.goal_message_parser import GoalMessageRequest, parse_goal_message
from app.services.goal_planner import GoalPlanner
from app.services.user_fact_registry import UserFactRegistry, validate_original_operands
from app.models.goal_research_schemas import CriterionStatus, GoalCriterion
from app.services.goal_evaluator import GoalEvaluator


def parsed(message: str, context: str | None = None):
    return parse_goal_message(GoalMessageRequest(message=message, context_message=context))


def test_single_message_research_and_calculation_intents_preserve_user_facts():
    research = parsed("API gravity와 원유의 무거움 관계를 내부 자료로 설명해줘.")
    assert research.execution_mode == "autonomous_goal_execution"
    assert research.use_internal and not research.use_external
    assert research.success_criteria == [] and research.expected_result is None
    assert UserFactRegistry.from_topic(research.topic).records == []
    assert len(GoalExecutionAgent._explicit_numeric_criteria(research, UserFactRegistry.from_topic(research.topic), None)) == 1

    arithmetic = parsed("A 187, B 234, C 163 stb/d야. 평균과 순위, 가장 높은 값을 구해줘.")
    assert [(item.name, item.value, item.unit) for item in UserFactRegistry.from_topic(arithmetic.topic).records] == [
        ("A_rate", 187, "stb/d"), ("B_rate", 234, "stb/d"), ("C_rate", 163, "stb/d")]
    ready = arithmetic.model_copy(update={"allow_python_execution": True, "python_execution_approved": True})
    state = GoalExecutionState.from_criteria("GR-TEST", ready.goal or "", [GoalCriterion(criterion_id="C1", description="평균과 순위")])
    assert GoalActionPlanner.select(ready, state, user_fact_ids=["USERF1", "USERF2", "USERF3"],
                                    formula_ready=False, simulation_spec=None).action_type == GoalActionType.CALCULATE


def test_sourced_api_formula_and_missing_simulation_model_are_not_invented():
    calculation = parsed("SG가 0.918인 원유의 API gravity를 내부 교재의 식을 찾아 계산해줘.")
    assert [(item.name, item.value) for item in UserFactRegistry.from_topic(calculation.topic).records] == [("SG", 0.918)]
    assert calculation.simulation_spec is None and calculation.expected_result is None
    assert GoalExecutionAgent._explicit_numeric_criteria(calculation, UserFactRegistry.from_topic(calculation.topic), None)

    simulation = parsed("공극률을 0.10부터 0.30까지 0.02 간격으로 바꿔가며 결과를 계산하고 최적 조건을 찾아줘.")
    assert simulation.simulation_spec is None
    state = GoalExecutionState.from_criteria("GR-TEST", simulation.goal or "", [GoalCriterion(criterion_id="C1", description="최적 조건")])
    approved = simulation.model_copy(update={"allow_python_execution": True, "python_execution_approved": True})
    action = GoalActionPlanner.select(approved, state, user_fact_ids=[], formula_ready=False, simulation_spec=None)
    assert action.action_type == GoalActionType.RETRIEVE and action.reason_code == "simulation_model_or_inputs_missing"


def test_deliverables_context_hypothesis_and_web_are_explicit_only():
    context = "API gravity와 원유의 무거움 관계를 내부 자료로 설명해줘."
    deliverable = parsed("이 주제로 조사해서 보고서랑 발표자료까지 만들어줘.", context)
    assert deliverable.topic == context and deliverable.goal == f"{context}\n이 주제로 조사해서 보고서랑 발표자료까지 만들어줘."
    assert deliverable.deliverables == ["docx", "pptx"]
    assert not deliverable.use_external and deliverable.expected_result is None
    assert len(GoalExecutionAgent._explicit_numeric_criteria(deliverable, UserFactRegistry.from_topic(deliverable.topic), None)) == 1
    with pytest.raises(ValueError, match="이전 연구 주제"):
        parsed("이 주제로 보고서 만들어줘.")

    assert parsed("최신 자료를 웹에서 찾아줘.").use_external
    assert not parsed("최신 자료를 웹 없이 내부에서 찾아줘.").use_external
    assert parsed("가설: radial flow는 unit-slope이다. 근거로 확인해줘.").expected_result.startswith("radial flow")
    assert parsed("결과는 소수 둘째 자리까지 보여줘.").expected_result is None


def test_unsupported_equation_request_preserves_no_formula_or_result():
    request = parsed("Xq=31 psi야. 출처 있는 Kappa-Zeta 관계식을 찾아 Zeta를 계산해줘. 관계식이 없으면 추측하지 마.")
    assert request.expected_result is None and request.simulation_spec is None
    assert request.success_criteria == [] and request.use_internal and not request.use_external
    assert [(item.name, item.value) for item in UserFactRegistry.from_topic(request.topic).records] == [("Xq", 31)]
    descriptions = [item.description for item in GoalExecutionAgent._explicit_numeric_criteria(
        request, UserFactRegistry.from_topic(request.topic), None)]
    assert any("출처" in description for description in descriptions)
    assert any("계산" in description and "검증" in description for description in descriptions)
    state = GoalExecutionState.from_criteria("GR-TEST", request.goal or "", [GoalCriterion(criterion_id="C1", description="관계식 근거 확인")])
    approved = request.model_copy(update={"allow_python_execution": True, "python_execution_approved": True})
    assert GoalActionPlanner.select(approved, state, user_fact_ids=["USERF1"], formula_ready=False,
                                    simulation_spec=None).action_type == GoalActionType.RETRIEVE
    assert GoalExecutionAgent._safe_unavailable_answer(
        "Kappa-Zeta 관계식은 존재하지 않습니다.", state, reason="missing_validated_formula", korean=True
    ) == "요청한 계산을 뒷받침할 출처 있는 관계식과 검증된 계산 결과를 함께 확보하지 못했습니다. 값을 추측하지 않습니다."


def test_graph_and_range_words_select_tool_paths_without_inventing_a_model():
    graph = parsed("A 187, B 234, C 163 stb/d야. 그래프로 보여줘.")
    state = GoalExecutionState.from_criteria("GR-GRAPH", graph.goal or "", [GoalCriterion(criterion_id="C1", description="그래프")])
    approved = graph.model_copy(update={"allow_python_execution": True, "python_execution_approved": True})
    assert GoalActionPlanner.select(approved, state, user_fact_ids=["USERF1", "USERF2", "USERF3"],
                                    formula_ready=False, simulation_spec=None).action_type == GoalActionType.CALCULATE

    sweep = parsed("공극률을 0.1~0.3 범위로 계산해서 최적 조건을 찾아줘.")
    state = GoalExecutionState.from_criteria("GR-SWEEP", sweep.goal or "", [GoalCriterion(criterion_id="C1", description="최적 조건")])
    approved = sweep.model_copy(update={"allow_python_execution": True, "python_execution_approved": True})
    action = GoalActionPlanner.select(approved, state, user_fact_ids=[], formula_ready=False, simulation_spec=None)
    assert action.action_type == GoalActionType.RETRIEVE and action.reason_code == "simulation_model_or_inputs_missing"


def test_inferred_criteria_do_not_invent_an_unprovided_hypothesis():
    class FakeOllama:
        async def chat_structured(self, *args, **kwargs):
            return ('{"criteria": [{"description": "Explain API gravity using internal evidence"}, '
                    '{"description": "Assess whether the expected hypothesis is supported"}]}')

    criteria = asyncio.run(GoalPlanner(FakeOllama()).infer_criteria(
        parsed("API gravity와 원유의 무거움 관계를 내부 자료로 설명해줘.")))
    assert [item.description for item in criteria] == ["Explain API gravity using internal evidence"]


def test_evaluator_uses_only_known_evidence_ids_mentioned_in_its_reason():
    evaluated = GoalEvaluator._normalize_criteria(
        [GoalCriterion(criterion_id="C1", description="관계를 근거와 함께 설명")],
        [{"criterion_id": "C1", "status": "met", "reason": "KB2에서 관계를 확인했습니다. KB999는 무시합니다.",
          "supporting_evidence": []}],
        {"KB2"},
    )
    assert evaluated[0].status == CriterionStatus.MET
    assert evaluated[0].supporting_evidence == ["KB2"]


def test_unified_chat_bounded_context_and_user_fact_correction():
    from app.services.goal_message_parser import ContextMessage

    prior = "SG=0.918인 원유의 API gravity를 교재 식으로 계산해줘."
    request = parse_goal_message(GoalMessageRequest(
        message="그럼 0.85면?", context_messages=[
            ContextMessage(role="user", content=prior),
            ContextMessage(role="assistant", content="SG=9.99; API=999 [KB999]"),
        ]))
    assert request.entrypoint == "unified_chat"
    assert request.max_iterations == 8
    assert request.context_user_messages == [prior]
    assert request.context_message_count == 2
    assert request.contextual_fact_name == "SG"
    assert "KB999" not in request.topic
    facts = UserFactRegistry.from_messages(request.context_user_messages)
    assert facts.apply_contextual_correction(request.current_message, request.contextual_fact_name)
    assert [(fact.name, fact.value, fact.source_span) for fact in facts.records] == [
        ("SG", .85, "그럼 0.85면?")]
    validate_original_operands(f"{prior}\n{request.current_message}", facts)


def test_unified_chat_named_correction_and_ambiguous_value_are_safe():
    from app.services.goal_message_parser import ContextMessage

    prior = "phi=0.22, Sw=0.35, Rw=2 ohm*m일 때 Rt를 계산해줘."
    context = [ContextMessage(role="user", content=prior)]
    request = parse_goal_message(GoalMessageRequest(message="Sw만 0.40으로 바꾸면?", context_messages=context))
    assert request.contextual_fact_name == "Sw"
    facts = UserFactRegistry.from_messages(request.context_user_messages)
    assert facts.apply_contextual_correction(request.current_message, "Sw")
    assert next(item.value for item in facts.records if item.name == "Sw") == .40
    with pytest.raises(ValueError, match="변수명"):
        parse_goal_message(GoalMessageRequest(message="그럼 0.40이면?", context_messages=context))


def test_followup_uses_latest_user_goal_not_unrelated_older_numbers():
    from app.services.goal_message_parser import ContextMessage

    context = [ContextMessage(role="user", content="A=8 kg의 평균은?"),
               ContextMessage(role="assistant", content="8 kg"),
               ContextMessage(role="user", content="SG=0.918인 원유의 API도를 계산해줘.")]
    request = parse_goal_message(GoalMessageRequest(message="그럼 0.85면?", context_messages=context))
    assert request.context_user_messages == ["SG=0.918인 원유의 API도를 계산해줘."]
    assert "A=8" not in request.topic
    explicit = parse_goal_message(GoalMessageRequest(message="SG=0.85", context_messages=context))
    assert explicit.context_user_messages == request.context_user_messages
    assert explicit.contextual_fact_name is None


def test_followup_after_clarification_keeps_original_goal_and_latest_user_fact():
    from app.services.goal_message_parser import ContextMessage

    goal = "SG를 교재 식으로 API gravity로 계산해줘."
    context = [ContextMessage(role="user", content=goal),
               ContextMessage(role="assistant", content="SG 값을 알려주세요."),
               ContextMessage(role="user", content="SG=0.918")]
    request = parse_goal_message(GoalMessageRequest(message="그럼 0.85면?", context_messages=context))
    assert request.context_user_messages == [goal, "SG=0.918"]
    assert request.contextual_fact_name == "SG"
    assert request.goal.startswith(goal)


def test_unified_chat_web_policy_and_context_bounds():
    from app.services.goal_message_parser import ContextMessage

    assert parse_goal_message(GoalMessageRequest(message="최신 OPEC 자료를 웹에서 확인해줘")).use_external
    assert not parse_goal_message(GoalMessageRequest(message="웹 검색 없이 내부 자료로 설명해줘")).use_external
    with pytest.raises(ValueError):
        GoalMessageRequest(message="다시?", context_messages=[
            ContextMessage(role="user", content="x" * 500) for _ in range(6)])


def test_arithmetic_relation_outranks_clipped_pdf_alias_without_input_value():
    from app.services.calculation_requirements import rank_formula_candidates

    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "document": "guide.pdf",
                 "text": "API = (141.5 / SG) - 131.5. SG = specific gravity."}]
    selected, selection = rank_formula_candidates(evidence, "Find SG-API equation and calculate API gravity", [])
    assert selected is not None
    assert selected.expression_candidate.startswith("API =")
    assert selection.selection_reason == "unique_structural_match"


def test_clipped_prose_definition_is_not_a_dependency_formula():
    from app.services.formula_source_registry import FormulaSourceRegistry

    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "API = (141.5 / SG) - 131.5. SG = specific gravity."}]
    records = FormulaSourceRegistry.from_evidence(evidence).records
    assert any(record.expression_candidate.startswith("API =") for record in records)
    assert all(record.expression_candidate != "SG = specific" for record in records)
