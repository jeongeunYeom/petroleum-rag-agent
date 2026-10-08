from __future__ import annotations

import asyncio
import json
import time

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import (
    ComputationRecord, CriterionEvaluation, CriterionStatus, ExpectedResultStatus, GoalCriterion,
    GoalResearchRequest, GoalResearchResponse, GoalRunStatus, GoalStatus, GoalStopReason,
)
from app.models.research_schemas import (
    EvidenceCounts, InternalEvidence, ResearchRequest, ResearchResponse, ResearchTiming,
)
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_evaluator import GoalEvaluationResult, GoalEvaluator
from app.services.calculation_request_ir import parse_request_ir
from app.services.calculation_requirements import select_formula_candidate
from app.services.goal_clarification import calculation_missing, simulation_readiness
from app.services.citation_semantics import ground_research_claims
from app.services.goal_execution_agent import GoalExecutionAgent, _EvidenceSnapshot, _V8ToolPlanner
from app.services.goal_execution_state import (
    ActionRecord, DerivedFact, GoalActionType, GoalExecutionState, SimulationParameter, SimulationSpec,
)
from app.services.goal_research_agent import EvidenceAccumulator
from app.services.goal_research_service import GoalResearchService
from app.services.goal_simulation import validate_expression
from app.services.goal_message_parser import GoalMessageRequest, parse_goal_message
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_tool_planner import ToolDecision
from app.services.user_fact_registry import UserFactRegistry


def request(goal: str, *, approved: bool = True, simulation_spec: dict | None = None) -> GoalResearchRequest:
    return GoalResearchRequest(topic="A_x = 7 psi; B_x = 11 psi", goal=goal,
                               allow_python_execution=approved, python_execution_approved=approved,
                               simulation_spec=simulation_spec,
                               execution_mode="autonomous_goal_execution")


def state() -> GoalExecutionState:
    return GoalExecutionState.from_criteria("GR-TEST", "test goal", [GoalCriterion(
        criterion_id="C1", description="Report the supported result")])


def record(kind: GoalActionType, status: str = "completed") -> ActionRecord:
    return ActionRecord(iteration=1, action_id="ACT-1", action_type=kind,
                        target_criteria=["C1"], status=status, reason_code="test")


def test_direct_user_facts_choose_calculate_without_retrieval():
    action = GoalActionPlanner.select(request("Calculate the mean and rank A and B"), state(),
                                      user_fact_ids=["USERF1", "USERF2"], formula_ready=False,
                                      simulation_spec=None)
    assert action.action_type == GoalActionType.CALCULATE


def test_goal_only_numeric_decomposition_adds_no_unrequested_hypothesis():
    req = GoalResearchRequest(topic="A_rate=179 stb/d, B_rate=263 stb/d.",
                              goal="Calculate the mean rate and identify the top case.")
    criteria = GoalExecutionAgent._explicit_numeric_criteria(
        req, UserFactRegistry.from_topic(req.topic), None)
    assert len(criteria) == 2
    assert "mean" in criteria[0].description.casefold()
    assert "top" in criteria[1].description.casefold()
    assert not any("hypothesis" in item.description.casefold() for item in criteria)


def test_missing_specialist_formula_chooses_retrieve_then_calculate():
    req = request("Calculate with the cited formula for each case")
    current = state()
    first = GoalActionPlanner.select(req, current, user_fact_ids=["USERF1"],
                                     formula_ready=False, simulation_spec=None)
    assert first.action_type == GoalActionType.RETRIEVE
    current.completed_actions.append(record(GoalActionType.RETRIEVE))
    current.evidence_ids.append("KB1")
    second = GoalActionPlanner.select(req, current, user_fact_ids=["USERF1"],
                                      formula_ready=True, simulation_spec=None)
    assert second.action_type == GoalActionType.CALCULATE


@pytest.mark.parametrize("topic,goal", [
    ("SG=0.918.", "Calculate API gravity for this crude oil."),
    ("SG=0.918일 때 API gravity를 계산해줘", "API gravity를 계산해줘"),
    ("비중 0.918인 원유", "API도를 구해줘."),
    ("SG=0.918.", "내부 교재의 SG-API 관계식을 찾아 계산해줘."),
    ("SG=0.918인 원유", "내부 교재의 SG-API 관계식을 찾아 계산해줘."),
])
def test_api_gravity_wording_preserves_sourced_formula_and_user_input(topic, goal):
    req = GoalResearchRequest(
        topic=topic,
        goal=goal,
        execution_mode="autonomous_goal_execution",
        allow_python_execution=True,
        python_execution_approved=True,
    )
    users = UserFactRegistry.from_topic(topic)
    assert [(fact.name, fact.value) for fact in users.records] == [("SG", 0.918)]
    ir = parse_request_ir(req, [])
    assert ir.specialist_relation_required
    assert ir.requested_outputs[0].semantic_name == "API_gravity"
    current = state()
    current.goal = goal
    first = GoalActionPlanner.select(req, current, user_fact_ids=["USERF1"],
                                     formula_ready=False, simulation_spec=None)
    assert first.action_type == GoalActionType.RETRIEVE
    assert "specific gravity SG API gravity" in first.query
    evidence = [{"evidence_id": source_id, "source_type": "knowledge_base",
                 "locator": f"book.pdf p.{page}", "text": "API = (141.5 / SG) - 131.5"}
                for source_id, page in (("KB1", 90), ("KB2", 177))]
    selected = select_formula_candidate(evidence, f"{goal} {topic}", ["SG"])
    assert selected is not None and selected.source_id in {"KB1", "KB2"}
    current.completed_actions.append(record(GoalActionType.RETRIEVE))
    current.evidence_ids.append("KB1")
    second = GoalActionPlanner.select(req, current, user_fact_ids=["USERF1"],
                                      formula_ready=True, simulation_spec=None)
    assert second.action_type == GoalActionType.CALCULATE


def test_api_gravity_does_not_guess_missing_input_or_conflicting_formula():
    req = GoalResearchRequest(topic="내부 교재의 SG-API 관계식", goal="API도를 계산해줘.")
    assert not UserFactRegistry.from_topic(req.topic).records
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "book p.1",
                 "text": "API = (141.5 / SG) - 131.5"},
                {"evidence_id": "KB2", "source_type": "knowledge_base", "locator": "book p.2",
                 "text": "API = (140 / SG) - 130"}]
    assert select_formula_candidate(evidence, f"{req.goal} {req.topic}", ["SG"]) is None
    current = state()
    current.completed_actions.append(record(GoalActionType.RETRIEVE))
    assert GoalActionPlanner.select(req, current, user_fact_ids=[], formula_ready=True,
                                    simulation_spec=None).action_type != GoalActionType.CALCULATE


def test_missing_user_sg_asks_after_finding_symbolic_formula_not_using_book_example():
    req = parse_goal_message(GoalMessageRequest(
        message="내부 교재의 SG-API 관계식을 찾아 API gravity를 계산해줘."))
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text":
                 "API = (141.5 / SG) -131.5\nAPI = (141.5 / 0.744) -131.5\nSG = 0.744"}]
    selected = select_formula_candidate(evidence, f"{req.goal} {req.topic}", [])
    assert selected is not None and selected.expression_candidate == "API = (141.5 / SG) -131.5"
    current = state()
    current.completed_actions.append(record(GoalActionType.RETRIEVE))
    current.evidence_ids.append("KB1")
    effective = req.model_copy(update={"allow_python_execution": True, "python_execution_approved": True})
    action = GoalActionPlanner.select(effective, current, user_fact_ids=[], evidence_fact_ids=["EFACT1"],
                                      formula_ready=True, formula_id=selected.formula_id,
                                      simulation_spec=None)
    assert (action.action_type, action.reason_code) == (GoalActionType.STOP, "calculation_blocked")
    assert calculation_missing(selected, evidence, UserFactRegistry.from_topic(req.topic), []) == [
        "SG 값과 단위"]


def test_api_gravity_uses_canonical_plan_when_llm_declines_explicit_calculation():
    class DecliningOllama:
        async def chat_structured(self, *_args, **_kwargs):
            return '{"tool_needed":false,"tool_type":"none","reason":"No tool needed"}'

    req = GoalResearchRequest(topic="비중 0.918인 원유", goal="API도를 구해줘.",
                              allow_python_execution=True, python_execution_approved=True)
    evidence = UserFactRegistry.from_topic(req.topic).evidence() + [
        {"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "book p.90",
         "text": "API = (141.5 / SG) - 131.5"}]
    criteria = GoalExecutionAgent._explicit_numeric_criteria(req, UserFactRegistry.from_topic(req.topic), None)
    decision = asyncio.run(_V8ToolPlanner(DecliningOllama()).decide(req, criteria, evidence, None))
    assert decision.tool_needed and decision.plan is not None
    assert decision.plan.input_facts[0].value == 0.918
    assert decision.plan.formula_source_id is not None
    assert decision.plan.supporting_evidence_ids == ["KB1"]

    without_formula = asyncio.run(_V8ToolPlanner(DecliningOllama()).decide(req, criteria, evidence[:1], None))
    assert not without_formula.tool_needed


def test_api_gravity_korean_answer_uses_only_validated_calc_and_source():
    req = GoalResearchRequest(topic="비중 0.918인 원유", goal="API도를 구해줘.")
    calc = ComputationRecord(computation_id="CALC1", analysis_id="PA-1", purpose="API gravity",
                             source_input_ids=["USERF1"], formula_evidence_ids=["KB1"],
                             formula="API = (141.5 / SG) - 131.5", validation_passed=True,
                             output_manifest={"OUT_default_API_gravity": {"name": "default_API_gravity",
                                 "value": 22.639433551198238, "unit": "dimensionless",
                                 "source_fact_ids": ["USERF1"], "semantic_type": "numeric"}})
    evidence = UserFactRegistry.from_topic(req.topic).evidence() + [
        {"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "book p.90",
         "text": calc.formula}]
    answer = GoalExecutionAgent._api_gravity_answer(req, [calc], evidence)
    assert answer and "검증된 API도" in answer and "22.64 °API" in answer
    assert calc.output_manifest["OUT_default_API_gravity"]["value"] == 22.639433551198238
    assert "[CALC1]" in answer and "[USERF1]" in answer and "[KB1]" in answer
    assert GoalEvaluator(None)._validate_candidate(req, answer, evidence, {"CALC1": calc})[
        "unsupported_engineering_claim_count"] == 0
    inverse_source = [evidence[0], {**evidence[1], "text": "SG = 141.5 / (API + 131.5)"}]
    cautious = GoalExecutionAgent._api_gravity_answer(req, [calc], inverse_source)
    assert cautious is None
    assert GoalExecutionAgent._api_gravity_answer(req, [calc.model_copy(update={"validation_passed": False})], evidence) is None


def test_criterion_reason_rejects_unvalidated_number_and_follows_korean():
    class ReasonOllama:
        async def chat_structured(self, *_args, **_kwargs):
            return json.dumps({"criteria": [{"criterion_id": "C1", "status": "partial",
                "reason": "API = (141.5 / 0.918) - 131.5 = 44.75", "supporting_evidence": ["KB1"]}],
                "expected_result_status": "not_provided", "gaps": [], "next_research_need": None,
                "goal_conflicts_with_evidence": False})

    req = GoalResearchRequest(topic="비중 0.918인 원유", goal="API도를 계산해줘.")
    criterion = GoalCriterion(criterion_id="C1", description="API도를 계산")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "book p.90",
                 "text": "API = (141.5 / SG) - 131.5"}]
    result = asyncio.run(GoalEvaluator(ReasonOllama()).evaluate(req, [criterion], "", evidence, {}))
    assert result.criteria[0].status == CriterionStatus.PARTIAL
    assert result.criteria[0].reason == "계산 결과가 아직 검증되지 않았습니다."
    assert "44.75" not in result.criteria[0].reason

    calc = ComputationRecord(computation_id="CALC1", analysis_id="PA-1", purpose="API gravity",
                             source_input_ids=["USERF1"], formula_evidence_ids=["KB1"],
                             validation_passed=True,
                             output_manifest={"OUT_default_API_gravity": {"name": "default_API_gravity",
                                 "value": 22.639433551198238, "unit": "dimensionless"}})
    supported = CriterionEvaluation(criterion_id="C1", status=CriterionStatus.MET,
                                    reason="검증된 API도는 22.64입니다.", supporting_evidence=["KB1", "CALC1"])
    assert GoalEvaluator._ground_reasons(req, [supported], evidence, {"CALC1": calc})[0].reason == supported.reason


def test_simulation_precedes_retrieval_and_is_bounded():
    spec = SimulationSpec(parameter=SimulationParameter(name="porosity", start=0.1,
                                                        stop=0.3, step=0.02),
                          expression="porosity * 100")
    action = GoalActionPlanner.select(request("Sweep porosity and maximize result"), state(),
                                      user_fact_ids=[], formula_ready=False,
                                      simulation_spec=spec)
    assert action.action_type == GoalActionType.SIMULATE
    assert action.simulation_spec is not None
    with pytest.raises(ValueError, match="case budget"):
        SimulationSpec(parameter=SimulationParameter(name="x", start=0, stop=200,
                                                     step=1), expression="x")


def test_validated_derived_output_enables_later_analysis():
    current = state()
    current.completed_actions.append(record(GoalActionType.CALCULATE))
    current.computation_ids.append("CALC1")
    current.derived_facts.append(DerivedFact(fact_id="CALC1:OUT_A", parent_calc_id="CALC1",
                                             output_id="OUT_A", name="A_result", value=3.0,
                                             underlying_provenance_ids=["USERF1"]))
    action = GoalActionPlanner.select(request("Calculate values and rank the best case"), current,
                                      user_fact_ids=["USERF1"], formula_ready=False,
                                      simulation_spec=None)
    assert action.action_type == GoalActionType.ANALYZE


def test_goal_achieved_synthesizes_then_stops_and_no_progress_stops():
    current = state()
    current.goal_achieved = True
    current.criteria[0].status = CriterionStatus.MET
    req = request("Explain the result")
    assert GoalActionPlanner.select(req, current, user_fact_ids=[], formula_ready=False,
                                    simulation_spec=None).action_type == GoalActionType.SYNTHESIZE
    current.synthesized = True
    assert GoalActionPlanner.select(req, current, user_fact_ids=[], formula_ready=False,
                                    simulation_spec=None).action_type == GoalActionType.STOP
    current.goal_achieved = False
    current.no_progress_count = req.no_progress_patience
    assert GoalActionPlanner.select(req, current, user_fact_ids=[], formula_ready=False,
                                    simulation_spec=None).reason_code == "no_progress"


def test_state_fingerprint_tracks_progress_and_action_fingerprint_is_stable():
    current = state()
    first = current.fingerprint()
    current.evidence_ids.append("KB1")
    assert current.fingerprint() != first
    action = GoalActionPlanner.select(request("Explain the relation"), current,
                                      user_fact_ids=[], formula_ready=False, simulation_spec=None)
    assert action.fingerprint(["KB1"]) == action.fingerprint(["KB1"])
    assert action.fingerprint(["KB1"]) != action.fingerprint(["KB2"])


def test_permission_and_expression_guard():
    req = request("Calculate the mean", approved=False)
    action = GoalActionPlanner.select(req, state(), user_fact_ids=["USERF1"],
                                      formula_ready=False, simulation_spec=None)
    assert action.action_type == GoalActionType.STOP
    assert action.reason_code == "calculation_permission_required"
    specialist = request("Calculate with the cited formula", approved=False)
    research_first = GoalActionPlanner.select(specialist, state(), user_fact_ids=["USERF1"],
                                              formula_ready=False, simulation_spec=None)
    assert research_first.action_type == GoalActionType.RETRIEVE
    current = state()
    current.completed_actions.append(record(GoalActionType.RETRIEVE))
    stopped = GoalActionPlanner.select(specialist, current, user_fact_ids=["USERF1"],
                                       formula_ready=True, simulation_spec=None)
    assert stopped.reason_code == "calculation_permission_required"
    bad = SimulationSpec(parameter=SimulationParameter(name="x", start=0, stop=1, step=.1),
                         expression="__import__('os').system('whoami')")
    with pytest.raises(ValueError, match="unsupported operations"):
        validate_expression(bad)
    huge_power = SimulationSpec(parameter=SimulationParameter(name="x", start=1, stop=2, step=1),
                                expression="x ** 999999")
    with pytest.raises(ValueError, match="exponent exceeds safe bounds"):
        validate_expression(huge_power)
    exhausted = request("Calculate the mean")
    exhausted.max_python_calls = 1
    stopped = GoalActionPlanner.select(exhausted, state(), user_fact_ids=["USERF1"],
                                       formula_ready=False, simulation_spec=None,
                                       python_calls_used=1)
    assert stopped.reason_code == "python_call_budget_exhausted"


def test_calculation_retries_only_after_new_retrieval_evidence():
    current = state()
    current.completed_actions.append(record(GoalActionType.CALCULATE, "blocked"))
    current.completed_actions.append(ActionRecord(iteration=2, action_id="ACT-2",
                                                  action_type=GoalActionType.RETRIEVE,
                                                  target_criteria=["C1"], status="completed",
                                                  reason_code="missing_source", evidence_added=["KB1"]))
    action = GoalActionPlanner.select(request("Calculate with cited formula"), current,
                                      user_fact_ids=["USERF1"], formula_ready=True, formula_id="FORMULA1",
                                      simulation_spec=None)
    assert action.action_type == GoalActionType.CALCULATE
    current.completed_actions[-1].evidence_added = []
    action = GoalActionPlanner.select(request("Calculate with cited formula"), current,
                                      user_fact_ids=["USERF1"], formula_ready=True, formula_id="FORMULA1",
                                      simulation_spec=None)
    assert action.action_type != GoalActionType.CALCULATE


def test_unrelated_unit_equation_and_unchanged_blocker_do_not_retry_calculation():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "psi = 4. Another unrelated equation is z = 0.745."}]
    assert select_formula_candidate(evidence, "Find Kappa-Zeta coupling and calculate Zeta for Xq=31 psi",
                                    ["Xq"]) is None
    current = state()
    current.completed_actions.append(ActionRecord(
        iteration=1, action_id="ACT-1", action_type=GoalActionType.CALCULATE,
        target_criteria=["C1"], status="blocked", reason_code="calculation_inputs_ready",
        failure_reason="planner_not_selected", details={"formula_id": None,
                                                        "user_fact_ids": ["USERF1"],
                                                        "evidence_fact_ids": []}))
    current.completed_actions.append(ActionRecord(
        iteration=2, action_id="ACT-2", action_type=GoalActionType.RETRIEVE,
        target_criteria=["C1"], status="completed", reason_code="calculation_failed_replan",
        evidence_added=["KB1"]))
    req = request("Find Kappa-Zeta coupling formula and calculate Zeta from Xq")
    action = GoalActionPlanner.select(req, current, user_fact_ids=["USERF1"],
                                      formula_ready=False, simulation_spec=None)
    assert action.action_type != GoalActionType.CALCULATE


def test_research_snapshot_keeps_only_exact_retrieved_formula_span():
    accumulator = EvidenceAccumulator()
    accumulator.add(ResearchResponse(
        query="source", answer="", internal_sources=[InternalEvidence(
            evidence_id="KB1", document="book.pdf", page=1, chunk_id="c1", score=1,
            excerpt="API = 141.5 / SG - 131.5. SG = 0.8.")],
        web_sources=[], figures=[], provenance=[], model="qwen3:8b", inference_used=False,
        evidence_counts=EvidenceCounts(internal=1, external=0), routing_mode="internal_only",
        retrieval_mode="hybrid", timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0,
                                                        elapsed_seconds=0), validation={},
    ))
    response = asyncio.run(_EvidenceSnapshot(accumulator, "qwen3:8b", "KB1",
                                             "API = 141.5 / SG - 131.5").research(
                                                 ResearchRequest(query="API gravity", use_external=False)))
    assert response.internal_sources[0].excerpt == "API = 141.5 / SG - 131.5"
    assert accumulator.internal[0].excerpt.endswith("SG = 0.8.")


class NoResearch:
    async def research(self, _request):
        raise AssertionError("research must not run")


class PassingEvaluator:
    async def evaluate(self, _request, criteria, _candidate, evidence, _validation, **_kwargs):
        ids = [str(item["evidence_id"]) for item in evidence]
        return GoalEvaluationResult(
            criteria=[CriterionEvaluation(criterion_id=item.criterion_id,
                                          status=CriterionStatus.MET, reason="supported",
                                          supporting_evidence=ids) for item in criteria],
            coverage=1.0, achieved=True, expected_result_status=ExpectedResultStatus.NOT_PROVIDED,
            gaps=[], next_research_need=None, engineering_validation_passed=True,
            engineering_contradiction_count=0, unsupported_engineering_claim_count=0,
            goal_conflicts_with_evidence=False,
        )


def test_simulation_integrates_real_sandbox_and_stops_after_verification(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    req = request("Simulate parameter sweep and identify best and mean", simulation_spec={
        "parameter": {"name": "porosity", "start": 0.1, "stop": 0.3, "step": 0.02},
        "expression": "porosity * 50 + 10", "output_name": "score",
    })
    req.success_criteria = [GoalCriterion(criterion_id="C1", description="Report all simulated cases")]
    req.max_iterations = 5
    req.allow_python_execution = req.python_execution_approved = False
    agent = GoalExecutionAgent(NoResearch(), object(), evaluator=PassingEvaluator())
    result = asyncio.run(agent.run("GR-TEST-SIM", req))
    assert result.status == GoalStatus.ACHIEVED
    assert [row["action_type"] for row in result.action_history] == [
        "simulate", "analyze", "verify", "synthesize", "stop",
    ]
    assert result.computations[0].validation_passed
    assert sum(key.startswith("OUT_CASE_") for key in result.computations[0].output_manifest) == 11
    assert result.python_calls_total == 1
    assert result.telemetry["python_authorization_source"] == "autonomous_execution_mode"
    assert result.action_history[0]["details"]["subprocess_reached"] is True


class StaticResearch:
    def __init__(self, text: str = ""):
        self.text = text

    async def research(self, request):
        sources = [InternalEvidence(evidence_id="KB1", document="source.pdf", page=1,
                                    chunk_id="c1", score=1, excerpt=self.text)] if self.text else []
        return ResearchResponse(query=request.query, answer=self.text, internal_sources=sources,
                                web_sources=[], figures=[], provenance=[], model=request.model,
                                inference_used=False, evidence_counts=EvidenceCounts(internal=len(sources), external=0),
                                routing_mode="internal_only", retrieval_mode="hybrid",
                                timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0),
                                validation={})


async def synthetic_synthesis(*_args):
    return "Source-supported result. [KB1] [CALC1]"


def test_autonomous_research_only_uses_no_python_without_client_flags():
    req = GoalResearchRequest(topic="API gravity and crude oil types",
                              goal="Explain the relation between API gravity and heavy or light crude",
                              success_criteria=[GoalCriterion(criterion_id="C1", description="Explain the relation")],
                              execution_mode="autonomous_goal_execution")
    agent = GoalExecutionAgent(StaticResearch("Higher API gravity indicates lighter crude."), object(),
                               evaluator=PassingEvaluator(), synthesizer=synthetic_synthesis)
    result = asyncio.run(agent.run("GR-TEST-RESEARCH", req))
    assert result.status == GoalStatus.ACHIEVED
    assert result.python_calls_total == 0
    assert all(item["action_type"] != "calculate" for item in result.action_history)
    assert result.telemetry["python_authorization_source"] == "autonomous_execution_mode"
    assert result.timing["planning_seconds"] >= 0
    assert result.timing["retrieval_seconds"] >= 0
    assert result.timing["synthesis_seconds"] >= 0
    assert result.timing["evaluation_seconds"] >= 0


def test_autonomous_user_fact_calculation_reaches_sandbox_without_client_flags(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)

    class ComputePlanner:
        async def decide(self, *_args):
            return ToolDecision(tool_needed=True, tool_type="python_calculation", reason="requested arithmetic")

    req = GoalResearchRequest(topic="A_rate=187 stb/d, B_rate=234 stb/d, C_rate=163 stb/d.",
                              goal="Calculate the mean rate, descending rank and top case.",
                              success_criteria=[GoalCriterion(criterion_id="C1", description="Calculate mean and ranking")],
                              execution_mode="autonomous_goal_execution", max_iterations=5)
    agent = GoalExecutionAgent(NoResearch(), object(), evaluator=PassingEvaluator(),
                               synthesizer=synthetic_synthesis, tool_planner=ComputePlanner(),
                               analysis_factory=lambda run_id: GoalPythonAnalysis(settings, object(), run_id))
    result = asyncio.run(agent.run("GR-TEST-AUTO-CALC", req))
    assert result.action_history[0]["action_type"] == "calculate"
    assert result.action_history[0]["details"]["subprocess_reached"] is True
    assert result.python_calls_total == 1
    assert result.computations[0].validation_passed
    assert result.computations[0].output_manifest["OUT_mean"]["value"] == pytest.approx(194.66666666666666)
    assert result.computations[0].output_manifest["OUT_mean"]["unit"] == "stb/d"
    evidence = agent._evidence(EvidenceAccumulator(), UserFactRegistry.from_topic(req.topic),
                               result.computations, None, "USERF4")
    answer = agent._simple_user_fact_answer(req, result.computations, evidence)
    assert answer is not None and "194.66666666666666" in answer
    assert "B > A > C" in answer
    assert "[CALC1]" in answer and "[USERF2]" in answer
    checked = GoalEvaluator(object())._validate_candidate(
        req, answer, evidence, {result.computations[0].computation_id: result.computations[0]})
    assert checked["unsupported_engineering_claim_count"] == 0
    wrong_order = answer.replace("B > A > C; top: B", "A > B > C; top: A")
    checked_wrong = GoalEvaluator(object())._validate_candidate(
        req, wrong_order, evidence, {result.computations[0].computation_id: result.computations[0]})
    assert checked_wrong["unsupported_engineering_claim_count"] > 0


def test_sourced_api_formula_retrieves_then_calculates_without_clarification(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)

    class DecliningOllama:
        async def chat_structured(self, *_args, **_kwargs):
            return '{"tool_needed":false,"tool_type":"none","reason":"No tool needed"}'

    req = GoalResearchRequest(
        topic="SG=0.918인 원유의 API gravity를 내부 교재 식으로 계산해줘.",
        goal="내부 교재의 SG-API 관계식을 찾아 API gravity를 계산해줘.",
        success_criteria=[GoalCriterion(criterion_id="C1", description="Calculate validated API gravity")],
        execution_mode="autonomous_goal_execution", max_iterations=5,
    )
    agent = GoalExecutionAgent(
        StaticResearch("API = (141.5 / SG) - 131.5"), DecliningOllama(),
        evaluator=PassingEvaluator(), synthesizer=synthetic_synthesis,
        analysis_factory=lambda run_id: GoalPythonAnalysis(settings, DecliningOllama(), run_id),
    )
    result = asyncio.run(agent.run("GR-API-SOURCE", req))
    assert result.run_status == GoalRunStatus.COMPLETED
    assert [item["action_type"] for item in result.action_history] == [
        "retrieve", "calculate", "verify", "synthesize", "stop"]
    assert result.computations[0].validation_passed
    assert result.computations[0].formula_evidence_ids == ["KB1"]
    assert result.computations[0].output_manifest["OUT_default_API_gravity"]["value"] == pytest.approx(22.64, abs=0.01)


def test_autonomous_missing_specialist_formula_stops_without_python():
    req = GoalResearchRequest(topic="Xq=31 psi", goal="Find a cited equation for fictional Kappa-Zeta coupling, then calculate Zeta in psi.",
                              success_criteria=[GoalCriterion(criterion_id="C1", description="Calculate with a cited equation")],
                              execution_mode="autonomous_goal_execution", max_retrieval_actions=1)
    result = asyncio.run(GoalExecutionAgent(StaticResearch(), object()).run("GR-TEST-MISSING-FORMULA", req))
    assert result.status != GoalStatus.ACHIEVED
    assert result.python_calls_total == 0
    assert not any(item.validation_passed for item in result.computations)


def test_research_answer_drops_tangential_cited_claims():
    candidate = ("Water has an API gravity of 10. [KB1]\n"
                 "Light crude is near 40 API; heavy crude is below 20 API. [KB1]\n"
                 "An unrelated exercise converts another sample. [KB2]")
    focused = GoalExecutionAgent._focus_research_answer(candidate, [
        GoalCriterion(criterion_id="C1", description="State the water API reference"),
        GoalCriterion(criterion_id="C2", description="Compare light and heavy crude API"),
    ])
    assert "Water has" in focused and "Light crude" in focused
    assert "unrelated exercise" not in focused


def test_deterministic_simulation_criteria_corrects_partial_semantic_grade():
    criteria = [GoalCriterion(criterion_id="C1", description="Report all simulated cases and best case")]
    partial = GoalEvaluationResult(
        criteria=[CriterionEvaluation(criterion_id="C1", status=CriterionStatus.PARTIAL,
                                      reason="uncertain", supporting_evidence=["CALC1"])],
        coverage=0.5, achieved=False, expected_result_status=ExpectedResultStatus.NOT_PROVIDED,
        gaps=["uncertain"], next_research_need=None, engineering_validation_passed=True,
        engineering_contradiction_count=0, unsupported_engineering_claim_count=0,
        goal_conflicts_with_evidence=False,
    )

    class Calculation:
        validation_passed = True
        computation_id = "CALC1"
        source_input_ids = ["USERF1"]
        output_manifest = {"OUT_CASE_001": {}, "OUT_CASE_002": {}}

    result = GoalExecutionAgent._deterministic_simulation_criteria(
        partial, criteria, "x=1, y=2 [CALC1] [USERF1]\nx=2, y=3 [CALC1] [USERF1]\n"
        "Best x=2, y=3 [CALC1] [USERF1]", Calculation())
    assert result.achieved
    assert result.criteria[0].status == CriterionStatus.MET


def test_service_dispatches_autonomous_mode_without_legacy_fallback(tmp_path):
    called = []

    class Controller:
        async def run(self, run_id, request, *, is_canceled, on_progress):
            called.append("autonomous")
            return GoalResearchResponse(run_id=run_id, topic=request.topic,
                                        max_iterations=request.max_iterations,
                                        run_status=GoalRunStatus.COMPLETED,
                                        status=GoalStatus.ACHIEVED,
                                        stop_reason=GoalStopReason.GOAL_ACHIEVED,
                                        final_answer="done")

    class Legacy:
        async def run(self, *_args, **_kwargs):
            raise AssertionError("legacy controller was selected")

    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    service = GoalResearchService(settings, Legacy(), Controller())
    created = service.start(request("Explain the result"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        result = service.get(created.run_id)
        if result.run_status == GoalRunStatus.COMPLETED:
            break
        time.sleep(0.01)
    assert result.status == GoalStatus.ACHIEVED
    assert called == ["autonomous"]


def test_missing_simulation_model_searches_kb_before_clarification():
    req = GoalResearchRequest(topic="공극률을 0.1~0.3으로 바꿔가며 CO2 저장량을 계산해줘",
                              goal="공극률을 바꿔가며 CO2 저장량을 계산해줘",
                              execution_mode="autonomous_goal_execution",
                              allow_python_execution=True, python_execution_approved=True)
    current = state()
    first = GoalActionPlanner.select(req, current, user_fact_ids=[], formula_ready=False,
                                     simulation_spec=None)
    assert first.action_type == GoalActionType.RETRIEVE
    current.completed_actions.extend([record(GoalActionType.RETRIEVE), record(GoalActionType.RETRIEVE)])
    assert GoalActionPlanner.select(req, current, user_fact_ids=[], formula_ready=False,
                                    simulation_spec=None).reason_code == "simulation_spec_missing"


def test_clarification_batches_missing_step_and_all_sourced_formula_inputs():
    text = "공극률을 0.1~0.3으로 바꾸면서 CO2 저장량을 계산해줘"
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "book p.1",
                 "text": "CO2_storage = porosity * bulk_volume * CO2_density"}]
    readiness = simulation_readiness(text, evidence, UserFactRegistry.from_topic(text))
    assert readiness.spec is None
    assert readiness.formula_source_id == "KB1"
    assert readiness.missing == ["변수 변화 간격", "CO2_density 값", "bulk_volume 값"]
    example = [{**evidence[0], "text": evidence[0]["text"] +
                "\nWorked example: bulk_volume=1000 m3; CO2_density=700 kg/m3"}]
    assert simulation_readiness(text, example, UserFactRegistry.from_topic(text)).missing == readiness.missing


def test_clarification_resumes_same_run_with_sourced_formula_and_real_sandbox(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    source = StaticResearch("CO2_storage = porosity * bulk_volume * CO2_density")
    agent = GoalExecutionAgent(source, object(), evaluator=PassingEvaluator())
    service = GoalResearchService(settings, agent, agent)
    req = GoalResearchRequest(
        topic="공극률을 0.1~0.3으로 0.02 간격으로 바꿔가며 CO2 저장량을 계산하고 최적 조건을 찾아줘.",
        goal="공극률을 바꿔가며 CO2 저장량을 계산하고 최적 조건을 찾아줘.",
        success_criteria=[GoalCriterion(criterion_id="C1", description="Report all simulated cases and best case")],
        execution_mode="autonomous_goal_execution", max_iterations=6,
    )

    def wait_for(*statuses):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            current = service.get(run_id)
            if current.run_status in statuses:
                return current
            time.sleep(0.02)
        pytest.fail(f"run did not reach {statuses}: {current.run_status}")

    run_id = service.start(req).run_id
    waiting = wait_for(GoalRunStatus.WAITING_FOR_USER_INPUT, GoalRunStatus.FAILED)
    assert waiting.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT, waiting.error
    assert "bulk_volume" in waiting.clarification_question
    assert "CO2_density" in waiting.clarification_question
    assert [item["action_type"] for item in waiting.action_history] == ["retrieve", "retrieve"]
    assert waiting.internal_sources[0].evidence_id == "KB1"
    assert waiting.computations == []
    checkpoint = json.loads(service._path(run_id).read_text(encoding="utf-8"))["checkpoint"]
    assert checkpoint["state"]["evidence_ids"] == ["KB1"]
    assert "private_chain_of_thought" not in json.dumps(checkpoint)

    # A new service instance proves the checkpoint survives a backend restart.
    service = GoalResearchService(settings, agent, agent)
    service.resume(run_id, "부피는 1000 m3, 밀도는 700 kg/m3.")
    done = wait_for(GoalRunStatus.COMPLETED, GoalRunStatus.STOPPED, GoalRunStatus.FAILED)
    assert done.run_id == run_id
    assert done.run_status == GoalRunStatus.COMPLETED, done.error or done.final_answer
    assert [item["action_type"] for item in done.action_history] == [
        "retrieve", "retrieve", "simulate", "analyze", "verify", "synthesize", "stop"]
    assert done.computations[0].validation_passed
    assert done.computations[0].formula_evidence_ids == ["KB1"]
    assert set(done.computations[0].source_input_ids) >= {"USERF1", "USERF2"}
    assert done.computations[0].output_manifest["OUT_BEST_RESULT"]["value"] == pytest.approx(210000)
    assert "최적 porosity=" in done.final_answer
    assert "요청한 결과가 검증된" in done.criteria[0].reason
    assert json.loads(service._path(run_id).read_text(encoding="utf-8"))["checkpoint"] == {}


def test_missing_kb_formula_waits_without_inventing_one(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    agent = GoalExecutionAgent(StaticResearch("No storage equation is present."), object(),
                               evaluator=PassingEvaluator())
    req = GoalResearchRequest(topic="공극률을 0.1~0.3으로 바꿔가며 CO2 저장량을 계산해줘",
                              goal="공극률을 바꿔가며 CO2 저장량을 계산해줘",
                              success_criteria=[GoalCriterion(criterion_id="C1", description="Report a sourced result")],
                              execution_mode="autonomous_goal_execution", max_iterations=6)
    result = asyncio.run(agent.run("GR-NO-FORMULA", req))
    assert result.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT
    assert "모델/관계식" in result.clarification_question
    assert not result.computations


def test_user_cannot_supply_missing_model_and_ends_same_run_without_guessing(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    agent = GoalExecutionAgent(StaticResearch("No storage equation is present."), object(),
                               evaluator=PassingEvaluator())
    service = GoalResearchService(settings, agent, agent)
    req = GoalResearchRequest(topic="공극률을 0.1~0.3으로 바꾸면서 CO2 저장량을 계산해줘",
                              goal="공극률을 바꾸면서 CO2 저장량을 계산해줘",
                              success_criteria=[GoalCriterion(criterion_id="C1", description="Report a sourced result")],
                              execution_mode="autonomous_goal_execution", max_iterations=6,
                              deliverables=["docx"])
    run_id = service.start(req).run_id
    deadline = time.monotonic() + 5
    while service.get(run_id).run_status != GoalRunStatus.WAITING_FOR_USER_INPUT and time.monotonic() < deadline:
        time.sleep(0.02)
    stopped = service.resume(run_id, "모르겠어요")
    assert stopped.run_id == run_id
    assert stopped.run_status == GoalRunStatus.STOPPED
    assert stopped.stop_reason == GoalStopReason.INSUFFICIENT_EVIDENCE
    assert "추측하지" in stopped.final_answer
    assert not stopped.computations
    assert stopped.deliverable_status == {"docx": "skipped"}
    assert json.loads(service._path(run_id).read_text(encoding="utf-8"))["checkpoint"] == {}


@pytest.mark.parametrize("message", [
    "A는 187 stb/d, B는 234 stb/d, C는 163 stb/d야. 평균과 순위를 계산해줘.",
    "A의 유량은 187 stb/d; B의 유량은 234 stb/d; C의 유량은 163 stb/d. 평균과 순위를 계산해줘.",
    "A가 187 stb/d이고 B가 234 stb/d, C가 163 stb/d일 때 평균과 순위를 계산해줘.",
])
def test_korean_user_rates_enter_direct_calculation_without_client_python_flags(message):
    req = parse_goal_message(GoalMessageRequest(message=message))
    facts = UserFactRegistry.from_topic(req.topic)
    assert [(row.name, row.value, row.unit) for row in facts.records] == [
        ("A_rate", 187, "stb/d"), ("B_rate", 234, "stb/d"), ("C_rate", 163, "stb/d")]
    assert req.execution_mode == "autonomous_goal_execution"
    assert not req.python_execution_approved
    effective = req.model_copy(update={"allow_python_execution": True, "python_execution_approved": True})
    assert GoalActionPlanner.select(effective, state(), user_fact_ids=[row.fact_id for row in facts.records],
                                    formula_ready=False, simulation_spec=None).action_type == GoalActionType.CALCULATE


@pytest.mark.parametrize("message", [
    "porosity를 0.10부터 0.30까지 0.02 간격으로 변화시켜. score = porosity * 50 + 10일 때 최적 조건을 찾아줘.",
    "porosity는 0.10~0.30에서 0.02씩 변화시키며 결과식 score = porosity * 50 + 10을 계산해줘.",
    "Vary porosity from 0.10 to 0.30 in steps of 0.02; model score = porosity * 50 + 10. Find the best.",
])
def test_user_equation_and_range_build_bounded_simulation_without_kb(message):
    req = parse_goal_message(GoalMessageRequest(message=message))
    assert req.simulation_spec is not None
    spec = SimulationSpec.model_validate(req.simulation_spec)
    assert (spec.parameter.name, spec.parameter.start, spec.parameter.stop, spec.parameter.step) == (
        "porosity", 0.1, 0.3, 0.02)
    assert spec.expression == "porosity * 50 + 10"
    effective = req.model_copy(update={"allow_python_execution": True, "python_execution_approved": True})
    assert GoalActionPlanner.select(effective, state(), user_fact_ids=[], formula_ready=False,
                                    simulation_spec=spec).action_type == GoalActionType.SIMULATE


@pytest.mark.parametrize("message", [
    "공극률을 0.1~0.3으로 변화시키면서 CO₂ 저장량을 계산하고 최적 조건을 찾아줘.",
    "공극률을 0.1부터 0.3까지 변화시키며 CO2 저장량을 시뮬레이션해줘.",
    "공극률을 0.1~0.3으로 바꾸면서 이산화탄소 저장 용량을 계산해줘.",
])
def test_missing_simulation_input_variants_retrieve_before_question(message):
    req = parse_goal_message(GoalMessageRequest(message=message))
    effective = req.model_copy(update={"allow_python_execution": True, "python_execution_approved": True})
    assert GoalActionPlanner.select(effective, state(), user_fact_ids=[], formula_ready=False,
                                    simulation_spec=None).action_type == GoalActionType.RETRIEVE
    assert simulation_readiness(message, [], UserFactRegistry.from_topic(message)).missing


@pytest.mark.parametrize("message", [
    "Xq=31 psi야. Kappa-Zeta coupling 식을 찾아 Zeta를 계산해줘.",
    "Xq=31 psi. Kappa-Zeta coupling 공식을 찾아서 Zeta를 계산해줘.",
    "Xq=31 psi이고 Zeta 계산용 Kappa-Zeta 관계식을 찾아줘.",
])
def test_unknown_formula_variants_do_not_start_calculation(message):
    req = parse_goal_message(GoalMessageRequest(message=message))
    effective = req.model_copy(update={"allow_python_execution": True, "python_execution_approved": True})
    users = UserFactRegistry.from_topic(message)
    assert GoalActionPlanner.select(effective, state(), user_fact_ids=[row.fact_id for row in users.records],
                                    formula_ready=False, simulation_spec=None).action_type == GoalActionType.RETRIEVE


def test_formula_source_survives_nested_run_id_renumbering(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)

    class TwoPages:
        async def research(self, req):
            return ResearchResponse(
                query=req.query, answer="", internal_sources=[
                    InternalEvidence(evidence_id="KB1", document="book.pdf", page=89, chunk_id="c89", score=1,
                                     excerpt="Exercise: convert SG=0.744 to API gravity."),
                    InternalEvidence(evidence_id="KB2", document="book.pdf", page=90, chunk_id="c90", score=1,
                                     excerpt="API = (141.5 / SG) - 131.5"),
                ], web_sources=[], figures=[], provenance=[], model=req.model, inference_used=False,
                evidence_counts=EvidenceCounts(internal=2, external=0), routing_mode="internal_only",
                retrieval_mode="hybrid", timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0,
                                                                 elapsed_seconds=0), validation={})

    class DecliningOllama:
        async def chat_structured(self, *_args, **_kwargs):
            return '{"tool_needed":false,"tool_type":"none","reason":"No tool needed"}'

    req = parse_goal_message(GoalMessageRequest(message="비중 0.918인 원유의 API도를 교재 식으로 계산해줘."))
    agent = GoalExecutionAgent(TwoPages(), DecliningOllama(), evaluator=PassingEvaluator(),
                               analysis_factory=lambda run_id: GoalPythonAnalysis(settings, DecliningOllama(), run_id))
    result = asyncio.run(agent.run("GR-RENUMBER", req))
    assert result.computations[0].validation_passed
    assert result.computations[0].formula_evidence_ids == ["KB2"]
    assert "22.64 °API" in result.final_answer
    assert "[KB2]" in result.final_answer


def test_missing_formula_input_resumes_same_run_with_new_user_fact(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)

    class DecliningOllama:
        async def chat_structured(self, *_args, **_kwargs):
            return '{"tool_needed":false,"tool_type":"none","reason":"No tool needed"}'

    req = parse_goal_message(GoalMessageRequest(
        message="내부 교재의 SG-API 관계식을 찾아 API gravity를 계산해줘."))
    agent = GoalExecutionAgent(StaticResearch("API = (141.5 / SG) - 131.5"), DecliningOllama(),
                               evaluator=PassingEvaluator(),
                               analysis_factory=lambda run_id: GoalPythonAnalysis(settings, DecliningOllama(), run_id))
    paused = asyncio.run(agent.run("GR-MISSING-SG", req))
    assert paused.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT
    assert "SG" in paused.clarification_question
    assert paused.python_calls_total == 0
    checkpoint = paused.resume_checkpoint.model_copy(deep=True) if hasattr(paused.resume_checkpoint, "model_copy") else dict(paused.resume_checkpoint)
    checkpoint["user_replies"] = ["SG는 0.918입니다."]
    resumed = asyncio.run(agent.run(paused.run_id, req, resume_state=checkpoint, resume_result=paused))
    assert resumed.run_id == paused.run_id
    assert resumed.status == GoalStatus.ACHIEVED
    assert resumed.computations[0].validation_passed
    assert "22.64 °API" in resumed.final_answer


@pytest.mark.parametrize("claim", [
    "API gravity가 낮으면 무거운 원유다. [KB1] [FIG1]",
    "낮은 API도는 더 무거운 원유를 뜻한다. [KB1] [FIG1]",
    "Heavy crude has lower API gravity. [KB1] [FIG1]",
])
def test_citation_semantics_uses_relevant_evidence_not_merely_valid_ids(claim):
    class JudgingOllama:
        async def chat_structured(self, *_args, **_kwargs):
            return json.dumps({"claims": [{"index": 0, "supported": True, "source_ids": ["KB2"]}]})

    req = GoalResearchRequest(topic="API gravity와 원유 무거움 관계", goal="설명해줘")
    evidence = [
        {"evidence_id": "KB1", "source_type": "knowledge_base", "text": "API gravity is related to specific gravity."},
        {"evidence_id": "FIG1", "source_type": "figure", "text": "API Gravity versus Watson Characterization Factor."},
        {"evidence_id": "KB2", "source_type": "knowledge_base", "text": "Light crude is 40 API; heavy crude is below 20 API."},
    ]
    grounded, rejected = asyncio.run(ground_research_claims(JudgingOllama(), req, claim, evidence))
    assert not rejected and "[KB2]" in grounded and "[KB1]" not in grounded and "[FIG1]" not in grounded


@pytest.mark.parametrize("message", [
    "API gravity와 원유의 무거움 관계를 내부 자료를 근거로 설명해줘.",
    "내부 교재를 바탕으로 API도가 낮은 원유가 왜 더 무거운지 설명해줘.",
    "Explain how API gravity relates to heavy and light crude using the internal KB.",
])
def test_oil_weight_research_variants_retrieve_before_answering(message):
    req = parse_goal_message(GoalMessageRequest(message=message))
    assert GoalActionPlanner.select(req, state(), user_fact_ids=[], formula_ready=False,
                                    simulation_spec=None).action_type == GoalActionType.RETRIEVE


def test_citation_semantics_removes_unsupported_claim_and_accepts_joint_kb_support():
    class JudgingOllama:
        async def chat_structured(self, messages, *_args, **_kwargs):
            sources = json.loads(messages[1]["content"])["sources"]
            support = [row["id"] for row in sources if row["id"].startswith("KB")]
            return json.dumps({"claims": [{"index": 0, "supported": len(support) == 2,
                                            "source_ids": support}]})

    req = GoalResearchRequest(topic="API gravity and oil weight", goal="Explain")
    claim = "Lower API gravity indicates heavier crude. [KB1]"
    first = [{"evidence_id": "KB1", "source_type": "knowledge_base",
              "text": "API gravity is related to specific gravity."}]
    grounded, rejected = asyncio.run(ground_research_claims(JudgingOllama(), req, claim, first))
    assert grounded == "" and len(rejected) == 1
    second = [*first, {"evidence_id": "KB2", "source_type": "knowledge_base",
                       "text": "Light crude is 40 API, heavy crude below 20 API."}]
    grounded, rejected = asyncio.run(ground_research_claims(JudgingOllama(), req, claim, second))
    assert not rejected and grounded.endswith("[KB1] [KB2]")


def test_citation_semantics_checks_uncited_limitations_as_claims():
    class JudgingOllama:
        async def chat_structured(self, messages, *_args, **_kwargs):
            claims = json.loads(messages[1]["content"])["claims"]
            assert len(claims) == 2
            return json.dumps({"claims": [
                {"index": 0, "supported": True, "source_ids": ["KB1"]},
                {"index": 1, "supported": False, "source_ids": []},
            ]})

    req = GoalResearchRequest(topic="API gravity", goal="Explain")
    answer = ("The source gives an API gravity equation. [KB1]\n"
              "Unresolved: the source gives no quantitative relation.")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "API = (141.5 / SG) - 131.5"}]
    grounded, rejected = asyncio.run(ground_research_claims(JudgingOllama(), req, answer, evidence))
    assert "Unresolved" not in grounded
    assert rejected == ["Unresolved: the source gives no quantitative relation."]


def test_research_goal_can_finish_after_unsupported_line_is_pruned():
    class JudgingOllama:
        async def chat_structured(self, *_args, **_kwargs):
            return json.dumps({"claims": [
                {"index": 0, "supported": True, "source_ids": ["KB1"]},
                {"index": 1, "supported": False, "source_ids": []},
            ]})

    async def synthesize(*_args):
        return ("Higher API gravity indicates lighter crude. [KB1]\n"
                "Unresolved: the source gives no relation.")

    req = GoalResearchRequest(topic="API gravity and crude weight",
                              goal="Explain the relation between API gravity and crude weight",
                              success_criteria=[GoalCriterion(criterion_id="C1", description="Explain the relation")],
                              execution_mode="autonomous_goal_execution")
    agent = GoalExecutionAgent(StaticResearch("Higher API gravity indicates lighter crude."),
                               JudgingOllama(), evaluator=PassingEvaluator(), synthesizer=synthesize)
    result = asyncio.run(agent.run("GR-PRUNE", req))
    assert result.status == GoalStatus.ACHIEVED
    assert result.validation["citation_semantic_passed"] is True
    assert result.validation["unsupported_citation_claim_count"] == 1
    assert "Unresolved" not in result.final_answer
    assert result.final_answer.endswith("[KB1]")
