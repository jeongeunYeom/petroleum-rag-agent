"""Synthetic, paraphrased development regressions; no frozen benchmark items."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import (CriterionEvaluation, CriterionStatus, ExpectedResultStatus,
                                              GoalCriterion, GoalResearchRequest, GoalStatus)
from app.models.research_schemas import EvidenceCounts, InternalEvidence, ResearchResponse, ResearchTiming
from app.services.formula_source_registry import FormulaSourceRegistry, source_contains_equation
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_clarification import parse_user_simulation_spec
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_evaluator import GoalEvaluationResult
from app.services.goal_execution_state import ActionRecord, GoalActionType, GoalExecutionState
from app.services.goal_intent import GoalIntentKind, SourceRequirement, classify_goal_intent
from app.services.goal_simulation import (direct_operation_operands, run_user_formula_calculation,
                                          user_formula_bindings)
from app.services.user_fact_registry import UserFactRegistry


def request(text: str) -> GoalResearchRequest:
    return GoalResearchRequest(topic=text, goal=text, execution_mode="autonomous_goal_execution",
                               success_criteria=[GoalCriterion(criterion_id="C1", description="Provide the requested result")])


def first_action(text: str, *, evidence: bool = False, formula_ready: bool = False,
                 formula_inputs_ready: bool = True):
    req = request(text)
    users = UserFactRegistry.from_topic(text)
    spec = parse_user_simulation_spec(text)
    intent = classify_goal_intent(req, has_user_facts=bool(users.records), has_simulation_spec=spec is not None)
    if intent.kind == GoalIntentKind.USER_FORMULA_CALC and intent.user_equation:
        formula_inputs_ready = formula_inputs_ready and not user_formula_bindings(intent.user_equation, users)[1]
    state = GoalExecutionState.from_criteria("DEV", text, req.success_criteria)
    if evidence:
        state.evidence_ids = ["KB1"]
        state.completed_actions.append(ActionRecord(
            iteration=1, action_id="A1", action_type=GoalActionType.RETRIEVE,
            target_criteria=["C1"], status="completed", reason_code="source_evidence_needed",
            evidence_added=["KB1"], new_evidence_count=1))
        state.iteration = 1
    selected = GoalActionPlanner.select(
        req.model_copy(update={"allow_python_execution": True, "python_execution_approved": True}),
        state, user_fact_ids=[row.fact_id for row in users.records], evidence_fact_ids=[],
        formula_ready=formula_ready, formula_id="FORMULA1" if formula_ready else None,
        simulation_spec=spec, formula_inputs_ready=formula_inputs_ready, intent=intent)
    return intent, selected


@pytest.mark.parametrize("text", [
    "A=11 stb/d, B=17 stb/d, C=23 stb/d. Compute their mean.",
    "P=6 psi, Q=2 psi. Calculate the difference.",
    "x=13, y=7. 합계를 계산해줘.",
    "well1=40 stb/d, well2=35 stb/d. 순위를 구해줘.",
    "a=8, b=4. Find their ratio.",
    "u=4, v=9. 평균을 산출해줘.",
])
def test_direct_arithmetic_routes_to_calculate_without_retrieval(text):
    intent, action = first_action(text)
    assert intent.kind == GoalIntentKind.DIRECT_CALC
    assert intent.source_requirement == SourceRequirement.NONE
    assert action.action_type == GoalActionType.CALCULATE


@pytest.mark.parametrize("text,expected", [
    ("x=4, y=7. z = x + y 식으로 계산해줘.", "z=x+y"),
    ("a=12, b=3. result = a / b. Calculate result.", "result=a/b"),
    ("mass=5 kg, volume=2 m3. density = mass / volume 관계식으로 구해줘.", "density=mass/volume"),
    ("p=2, q=9. score = p * q + 1. Compute score.", "score=p*q+1"),
])
def test_user_formula_routes_without_kb(text, expected):
    intent, action = first_action(text)
    assert intent.kind == GoalIntentKind.USER_FORMULA_CALC
    assert intent.source_requirement == SourceRequirement.USER_FORMULA
    assert "".join(intent.user_equation.split()) == expected
    assert action.action_type == GoalActionType.CALCULATE


@pytest.mark.parametrize("text", [
    "Vary phi from 0.1 to 0.3 in steps of 0.1. score = phi * 10 + 2. Find best.",
    "porosity를 0.10부터 0.30까지 0.05 간격으로 변화시켜. score = porosity * 20 + 1.",
    "Sweep x from 1 to 3 with steps of 1. output = x * x. Optimize output.",
    "x를 2부터 6까지 2 간격으로 바꿔가며 y = x / 2 + 3을 계산해줘.",
])
def test_user_formula_sweep_routes_directly(text):
    intent, action = first_action(text)
    assert intent.kind == GoalIntentKind.USER_FORMULA_SIMULATION
    assert intent.source_requirement == SourceRequirement.USER_FORMULA
    assert action.action_type == GoalActionType.SIMULATE


@pytest.mark.parametrize("text", [
    "SG=0.91일 때 교재의 API 변환식을 찾아 계산해줘.",
    "Use the reference equation to calculate API gravity for SG=0.87.",
    "pressure=230 psi. 내부 자료의 보정 관계식을 찾아 계산해줘.",
    "k=15 mD. Find a sourced permeability correlation and calculate the output.",
    "phi=0.22. 문헌 공식으로 저장량을 산출해줘.",
    "rate=100 stb/d. Locate the textbook equation and compute the index.",
])
def test_kb_formula_requires_retrieval(text):
    intent, action = first_action(text)
    assert intent.source_requirement == SourceRequirement.KB_FORMULA
    assert action.action_type == GoalActionType.RETRIEVE
    assert "equation" in action.query


@pytest.mark.parametrize("text,equation", [
    ("SG=0.91. Find and calculate API gravity.", "API=141.5/SG-131.5"),
    ("x=4. Find the correction formula and calculate result.", "result=x*2+1"),
    ("p=3. 교재 관계식으로 response를 계산해줘.", "response=p+7"),
    ("rate=6 stb/d. Find formula for score and calculate.", "score=rate*3"),
])
def test_exact_span_and_formula_to_calculate_transition(text, equation):
    source = {"evidence_id": "KB1", "source_type": "knowledge_base", "text": f"The relation is {equation}."}
    records = FormulaSourceRegistry.from_evidence([source]).records
    assert any(source_contains_equation(row, source["text"], equation) for row in records)
    intent, action = first_action(text, evidence=True, formula_ready=True)
    assert intent.source_requirement == SourceRequirement.KB_FORMULA
    assert action.action_type == GoalActionType.CALCULATE


@pytest.mark.parametrize("text,missing", [
    ("x=3. result = x + y. 계산해줘.", "y"),
    ("a=2. output = a * b. Compute it.", "b"),
    ("q=5. result = p / q. 구해줘.", "p"),
    ("m=7. score = m - n. Calculate score.", "n"),
])
def test_missing_user_formula_input_waits_for_same_run_reply(text, missing):
    req = request(text)
    facts = UserFactRegistry.from_topic(text)
    intent, action = first_action(text)
    assert intent.kind == GoalIntentKind.USER_FORMULA_CALC
    assert action.action_type == GoalActionType.STOP
    assert action.reason_code == "calculation_blocked"
    assert missing in ",".join(user_formula_bindings(intent.user_equation, facts)[1])
    updated = UserFactRegistry.from_topic(text + f"\n{missing}=4")
    assert not user_formula_bindings(intent.user_equation, updated)[1]


@pytest.mark.parametrize("text", [
    "Mud pressure is greater than pore pressure, so kick occurs, right?",
    "이수압이 지층압보다 높은 것이 킥 조건인 거지?",
    "Does a radial derivative rise at unit slope, correct?",
    "방사 유동의 도함수가 단위 기울기라는 거 맞지?",
    "If porosity falls, pore volume rises, right?",
    "공극률이 감소하면 공극 부피가 늘어나는 거 맞나요?",
])
def test_premise_check_precedes_calculation_keywords(text):
    intent, action = first_action(text)
    assert intent.kind == GoalIntentKind.PREMISE_CHECK
    assert action.action_type == GoalActionType.RETRIEVE


def test_korean_numeric_question_is_not_mistaken_for_a_premise_check():
    intent, action = first_action("SG=0.92일 때 API gravity가 몇인가요?")
    assert intent.kind == GoalIntentKind.KB_FORMULA_CALC
    assert action.action_type == GoalActionType.RETRIEVE


@pytest.mark.parametrize("text,operation,order", [
    ("A=12, B=3. Calculate A/B ratio.", "ratio", ("A", "B")),
    ("A=12, B=3. A minus B 차이를 계산해줘.", "difference", ("A", "B")),
    ("A=12, B=3. A를 B로 나눈 비율을 계산해줘.", "ratio", ("A", "B")),
    ("A=12, B=3. A에서 B를 뺀 차이를 구해줘.", "difference", ("A", "B")),
])
def test_noncommutative_direct_arithmetic_requires_explicit_order(text, operation, order):
    facts = UserFactRegistry.from_topic(text)
    bound, missing = direct_operation_operands(text, facts, [operation])
    assert bound[operation] == order and not missing
    intent, action = first_action(text)
    assert intent.kind == GoalIntentKind.DIRECT_CALC
    assert action.action_type == GoalActionType.CALCULATE


def test_ambiguous_ratio_asks_once_and_resumes_same_run(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    text = "A=12, B=3. 두 값의 비율을 계산해줘."
    agent = GoalExecutionAgent(NoResearch(), object(), evaluator=PassingEvaluator())
    req = request(text)
    waiting = asyncio.run(agent.run("DEV-RATIO-RESUME", req))
    assert waiting.run_status.value == "waiting_for_user_input"
    assert "분자/분모" in waiting.clarification_question
    checkpoint = dict(waiting.resume_checkpoint)
    checkpoint["user_replies"] = ["A/B"]
    done = asyncio.run(agent.run(waiting.run_id, req, resume_state=checkpoint, resume_result=waiting))
    assert done.run_id == waiting.run_id and done.status == GoalStatus.ACHIEVED
    assert done.action_history[0]["action_type"] == "calculate"
    assert done.computations[0].output_manifest["OUT_ratio"]["value"] == 4
    assert "비율" in done.final_answer and "USER_REQUEST" not in done.final_answer


@pytest.mark.parametrize("text", [
    "Find an unprovided theta-zeta coupling law and calculate zeta for x=3.",
    "x=4. 내부 문서에서 없는 Omega relation을 찾아 계산해줘.",
    "Find a sourced calibration equation for p=6 psi and compute output.",
    "a=8. Locate the proprietary transfer formula and calculate response.",
])
def test_unsupported_formula_never_executes_without_source(text):
    intent, action = first_action(text)
    assert intent.source_requirement == SourceRequirement.KB_FORMULA
    assert action.action_type == GoalActionType.RETRIEVE
    _, later = first_action(text, evidence=True, formula_ready=False)
    assert later.action_type == GoalActionType.RETRIEVE


@pytest.mark.parametrize("text", [
    "Explain capillary pressure using an internal reference.",
    "저류층의 상대투과도 의미를 근거로 설명해줘.",
    "What is a pressure transient test?",
    "비중과 밀도의 관계를 설명해줘.",
    "Summarize formation damage mechanisms.",
    "코어 분석에서 포화도의 정의를 알려줘.",
])
def test_literature_request_retrieves_then_verifies(text):
    intent, first = first_action(text)
    assert intent.kind == GoalIntentKind.KNOWLEDGE_QA
    assert first.action_type == GoalActionType.RETRIEVE
    _, after = first_action(text, evidence=True)
    assert after.action_type == GoalActionType.VERIFY


def test_user_equation_runs_in_sandbox_with_complete_provenance(tmp_path):
    text = "x=4, y=7. z = x + y 식으로 계산해줘."
    req = request(text).model_copy(update={"allow_python_execution": True,
                                   "python_execution_approved": True})
    facts = UserFactRegistry.from_topic(text)
    intent = classify_goal_intent(req, has_user_facts=True)
    result = asyncio.run(run_user_formula_calculation(
        Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"),
        req, "DEV-USER-FORMULA", intent.user_equation, facts, "CALC1", "USERF3"))
    assert result.validation_passed and result.output_manifest["OUT_RESULT"]["value"] == 11
    assert result.formula_source_ids == ["USERF3"]
    assert set(result.bound_variables.values()) == set(result.input_fact_ids)
    assert GoalExecutionAgent._provenance_complete(result, facts.evidence() + [{
        "evidence_id": "USERF3", "source_type": "user_fact", "text": intent.user_equation}], text)


def test_no_progress_retrieval_stops_instead_of_repeating():
    text = "Explain saturation. "
    req = request(text)
    state = GoalExecutionState.from_criteria("DEV", text, req.success_criteria)
    state.completed_actions.append(ActionRecord(
        iteration=1, action_id="A1", action_type=GoalActionType.RETRIEVE,
        target_criteria=["C1"], status="blocked", reason_code="source_evidence_needed"))
    state.iteration = 1
    intent = classify_goal_intent(req, has_user_facts=False)
    action = GoalActionPlanner.select(req, state, user_fact_ids=[], evidence_fact_ids=[],
                                      formula_ready=False, simulation_spec=None, intent=intent)
    assert action.action_type == GoalActionType.STOP
    assert action.reason_code == "retrieve_no_progress"


def test_identical_formula_retrieval_query_is_not_reissued():
    text = "x=3. Find a sourced transfer equation and calculate y."
    req = request(text)
    intent = classify_goal_intent(req, has_user_facts=True)
    state = GoalExecutionState.from_criteria("DEV", text, req.success_criteria)
    query = GoalActionPlanner.query(req, state, intent)
    state.evidence_ids = ["KB1"]
    state.completed_actions.append(ActionRecord(
        iteration=1, action_id="A1", action_type=GoalActionType.RETRIEVE,
        target_criteria=["C1"], status="completed", reason_code="formula_source_missing",
        evidence_added=["KB1"], new_evidence_count=1, details={"query": query}))
    state.iteration = 1
    action = GoalActionPlanner.select(req.model_copy(update={"allow_python_execution": True,
                                                    "python_execution_approved": True}),
                                      state, user_fact_ids=["USERF1"], evidence_fact_ids=[],
                                      formula_ready=False, simulation_spec=None, intent=intent)
    assert action.action_type == GoalActionType.STOP
    assert action.reason_code == "formula_source_unavailable"


class NoResearch:
    async def research(self, _request):
        raise AssertionError("direct calculation must not retrieve")


class SourceResearch:
    def __init__(self, text):
        self.text = text

    async def research(self, request):
        source = InternalEvidence(evidence_id="KB1", document="synthetic.pdf", page=3,
                                  chunk_id="c1", score=1, excerpt=self.text)
        return ResearchResponse(query=request.query, answer="", internal_sources=[source], web_sources=[],
                                figures=[], provenance=[], model=request.model, inference_used=False,
                                evidence_counts=EvidenceCounts(internal=1, external=0),
                                routing_mode="internal_only", retrieval_mode="hybrid",
                                timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0),
                                validation={})


class PassingEvaluator:
    async def evaluate(self, _request, criteria, _answer, evidence, _validation, **_kwargs):
        ids = [str(item["evidence_id"]) for item in evidence]
        return GoalEvaluationResult(
            criteria=[CriterionEvaluation(criterion_id=item.criterion_id, status=CriterionStatus.MET,
                                          reason="supported", supporting_evidence=ids) for item in criteria],
            coverage=1, achieved=True, expected_result_status=ExpectedResultStatus.NOT_PROVIDED,
            gaps=[], next_research_need=None, engineering_validation_passed=True,
            engineering_contradiction_count=0, unsupported_engineering_claim_count=0,
            goal_conflicts_with_evidence=False)


def test_user_formula_full_agent_runs_python_without_retrieval(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    text = "x=4, y=7. z = x + y 식으로 계산해줘."
    agent = GoalExecutionAgent(NoResearch(), object(), evaluator=PassingEvaluator())
    result = asyncio.run(agent.run("DEV-FORMULA-END-TO-END", request(text)))
    assert result.status == GoalStatus.ACHIEVED
    assert [row["action_type"] for row in result.action_history] == [
        "calculate", "verify", "synthesize", "stop"]
    assert result.python_calls_total == 1
    assert result.computations[0].validation_passed
    assert "11" in result.final_answer and "[CALC1]" in result.final_answer


def test_direct_arithmetic_full_agent_uses_validated_python_without_retrieval(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    text = "P=14 stb/d, Q=26 stb/d, R=20 stb/d. 평균과 순위를 계산해줘."
    agent = GoalExecutionAgent(NoResearch(), object(), evaluator=PassingEvaluator())
    result = asyncio.run(agent.run("DEV-DIRECT-END-TO-END", request(text)))
    assert result.status == GoalStatus.ACHIEVED
    assert result.action_history[0]["action_type"] == "calculate"
    assert all(row["action_type"] != "retrieve" for row in result.action_history)
    assert result.python_calls_total == 1
    assert result.computations[0].validation_passed
    assert "20" in result.final_answer and "Q > R > P" in result.final_answer


class PremiseModel:
    async def chat_structured(self, messages, schema, **_kwargs):
        if "verdict" in schema["properties"]:
            return json.dumps({"verdict": "contradicts", "source_id": "KB1",
                               "quote": "At fixed bulk volume, pore volume increases with porosity."})
        return json.dumps({"claims": [{"index": 0, "supported": True, "source_ids": ["KB1"]}]})


def test_source_grounded_premise_correction_is_explicit_and_cited():
    text = "At fixed bulk volume, decreasing porosity increases pore volume, right?"
    source = "At fixed bulk volume, pore volume increases with porosity."
    agent = GoalExecutionAgent(SourceResearch(source), PremiseModel(), evaluator=PassingEvaluator())
    result = asyncio.run(agent.run("DEV-PREMISE", request(text)))
    assert result.status == GoalStatus.ACHIEVED
    assert [row["action_type"] for row in result.action_history] == [
        "retrieve", "verify", "synthesize", "stop"]
    assert "contradicted" in result.final_answer and source in result.final_answer
    assert "[KB1]" in result.final_answer


def test_premise_quote_must_be_literal_source_text():
    text = "At fixed bulk volume, decreasing porosity increases pore volume, right?"
    agent = GoalExecutionAgent(SourceResearch("Unrelated source text on fluid properties."),
                               PremiseModel(), evaluator=PassingEvaluator())
    result = asyncio.run(agent.run("DEV-PREMISE-NO-SOURCE", request(text)))
    assert result.status != GoalStatus.ACHIEVED
    assert "At fixed bulk volume, pore volume increases" not in result.final_answer


def test_extractive_fallback_keeps_only_relevant_literal_source_span():
    req = request("Explain relative permeability and water saturation.")
    source = "Relative permeability to water varies with water saturation in this reservoir sample."
    answer = GoalExecutionAgent._extractive_source_answer(req, [{
        "evidence_id": "KB2", "source_type": "knowledge_base", "text": source}])
    assert source in answer and "[KB2]" in answer
    assert GoalExecutionAgent._extractive_source_answer(req, [{
        "evidence_id": "KB9", "source_type": "knowledge_base", "text":
        "Unrelated drilling inventory was recorded on a separate visit."}]) is None
    ocr = "The relative permeabilities are a function of saturation and reflect the surface, and \n"
    ocr += "wettability forces of the fluid-rock system. Figure 3 has axes."
    extracted = GoalExecutionAgent._extractive_source_answer(req, [{
        "evidence_id": "KB3", "source_type": "knowledge_base", "text": ocr}])
    # Exact citation spans preserve source whitespace, including OCR line breaks.
    assert ocr.split(" Figure 3")[0] in extracted


def test_fixed_bulk_pore_volume_premise_uses_actual_definition_span():
    from app.services.premise_grounding import assess_premise
    from app.services.engineering_validator import EngineeringValidator

    req = request("At fixed bulk volume, lower porosity means larger pore volume, right?")
    quote = "Total porosity is defined as the ratio of pore volume to the bulk volume of a material."
    assessment = asyncio.run(assess_premise(object(), req, [{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": quote}]))
    assert assessment.verdict == "contradicts"
    assert assessment.method == "source_ratio"
    assert quote in assessment.answer and "[KB1]" in assessment.answer
    assert EngineeringValidator().validate_claim(assessment.answer, quote, query=req.topic).passed
