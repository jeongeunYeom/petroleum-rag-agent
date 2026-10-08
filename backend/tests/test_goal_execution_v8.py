from __future__ import annotations

import asyncio
import time

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import (
    CriterionEvaluation, CriterionStatus, ExpectedResultStatus, GoalCriterion,
    GoalResearchRequest, GoalResearchResponse, GoalRunStatus, GoalStatus, GoalStopReason,
)
from app.models.research_schemas import (
    EvidenceCounts, InternalEvidence, ResearchRequest, ResearchResponse, ResearchTiming,
)
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_evaluator import GoalEvaluationResult
from app.services.goal_execution_agent import GoalExecutionAgent, _EvidenceSnapshot
from app.services.goal_execution_state import (
    ActionRecord, DerivedFact, GoalActionType, GoalExecutionState, SimulationParameter, SimulationSpec,
)
from app.services.goal_research_agent import EvidenceAccumulator
from app.services.goal_research_service import GoalResearchService
from app.services.goal_simulation import validate_expression
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
                                      user_fact_ids=["USERF1"], formula_ready=True,
                                      simulation_spec=None)
    assert action.action_type == GoalActionType.CALCULATE
    current.completed_actions[-1].evidence_added = []
    action = GoalActionPlanner.select(request("Calculate with cited formula"), current,
                                      user_fact_ids=["USERF1"], formula_ready=True,
                                      simulation_spec=None)
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
