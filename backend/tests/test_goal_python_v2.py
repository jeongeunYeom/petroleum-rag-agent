"""Dev-only Python v2 regressions; never rerun the frozen agentic benchmark."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.goal_research_routes import get_goal_research_service
from app.agents.permission_manager import AgentPermissionError, PermissionManager
from app.core.config import Settings
from app.core.run_ids import validate_workspace_run_id
from app.main import app
from app.models.goal_research_schemas import (
    ComputationRecord, CriterionStatus, GoalCriterion, GoalIterationRecord,
    GoalResearchRequest, GoalResearchResponse, PythonExecutionTrace,
)
from app.models.research_schemas import EvidenceCounts, InternalEvidence, ResearchResponse, ResearchTiming
from app.services.goal_evaluator import GoalEvaluator
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_research_agent import GoalResearchAgent
from app.services.goal_research_service import GoalResearchRunNotFound, GoalResearchService
from app.services.goal_tool_planner import GoalToolPlanner, PythonAnalysisPlan, ToolDecision, AnalysisPlanRequest
from app.services.user_fact_registry import UserFactRegistry
from scripts.diagnose_python_tool_execution import FIXTURE, FixtureCodeGenerator


CASES = {item["id"]: item for item in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}
CRITERION = GoalCriterion(criterion_id="C1", description="Calculate the requested result")


def prepared(case_id: str):
    case = CASES[case_id]
    evidence = [dict(item) for item in case["evidence"]]
    plan = PythonAnalysisPlan.model_validate(case["plan"])
    if case_id in {"D2", "D3"}:
        evidence.append({"evidence_id": "USER1", "source_type": "user_fact", "locator": "request.topic", "text": case["topic"]})
        for fact in plan.input_facts:
            fact.evidence_id = "USER1"
            fact.source_type = "user_fact"
    return case, plan, evidence


@pytest.mark.parametrize("run_id", [
    "GR-20261004-061740-510BBA",
    "agentic-v1-20261004T075903Z-AG-Q-006-full_agent",
    "agentic-v2-smoke-Q1-full_agent",
])
def test_safe_workspace_run_ids_accept_service_and_runner_names(tmp_path, run_id):
    assert validate_workspace_run_id(run_id) == run_id
    assert GoalPythonAnalysis(Settings(data_dir=tmp_path), object(), run_id).run_id == run_id


@pytest.mark.parametrize("run_id", [
    "../x", r"..\x", "/x", "x/y", r"x\y", "x y", ".", "..", "", "x\x00y", "C:\\test", "x" * 129,
])
def test_workspace_run_id_rejects_path_escape_and_invalid_components(tmp_path, run_id):
    with pytest.raises(ValueError, match="Invalid goal research workspace run ID"):
        GoalPythonAnalysis(Settings(data_dir=tmp_path), object(), run_id)
    assert not (tmp_path / "workspace" / "results").exists()


@pytest.mark.parametrize("case_id,expected", [
    ("D1", "validated"), ("D2", "validated"), ("D3", "validated"),
    ("D4", "validated"), ("D5", "input_fact_verification_failed"),
    ("D6", "formula_provenance_failed"), ("D7", "permission_not_approved"),
])
def test_diagnostic_cases_under_v2_provenance_and_gates(tmp_path, case_id, expected):
    case, plan, evidence = prepared(case_id)
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    request = GoalResearchRequest(topic=case["topic"], allow_python_execution=True, python_execution_approved=case_id != "D7")
    analysis = GoalPythonAnalysis(settings, FixtureCodeGenerator(), f"agentic-v2-smoke-{case_id}")
    trace = PythonExecutionTrace(tool_selected=True, plan_present=True)
    record, _ = asyncio.run(analysis.execute(request, plan, evidence, trace))
    assert trace.blocked_stage == expected
    assert trace.call_boundary_reached is (case_id in {"D1", "D2", "D3", "D4"})
    assert trace.subprocess_reached is (case_id in {"D1", "D2", "D3", "D4"})
    if expected == "validated":
        assert record and record.validation_passed and trace.computation_id == "CALC1"
        assert trace.code_generated and trace.sandbox_validation_passed and trace.result_validation_passed
    else:
        assert record is None and analysis.calls == 0
    if case_id in {"D2", "D3"}:
        assert record.source_input_ids == ["USER1"]
        assert record.source_evidence_ids == []
    if case_id == "D3":
        assert record.formula_evidence_ids == ["KB1"]


def test_d8_cache_reuses_validated_result_without_second_subprocess(tmp_path):
    case, plan, evidence = prepared("D1")
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"), FixtureCodeGenerator(), "agentic-v2-cache")
    request = GoalResearchRequest(topic=case["topic"], allow_python_execution=True, python_execution_approved=True)
    first, executed = asyncio.run(analysis.execute(request, plan, evidence))
    trace = PythonExecutionTrace()
    second, executed_again = asyncio.run(analysis.execute(request, plan, evidence, trace))
    assert executed and not executed_again and first is second
    assert analysis.calls == 1 and analysis.attempts == 1
    assert trace.blocked_stage == "cache_hit" and not trace.subprocess_reached


def test_user_fact_cannot_ground_specialist_formula_or_spoof_kb_type():
    case, plan, evidence = prepared("D4")
    evidence.append({"evidence_id": "USER1", "source_type": "user_fact", "text": plan.formula})
    plan.supporting_evidence_ids = ["USER1"]
    assert GoalPythonAnalysis.verification_failure(plan, evidence) == "formula_provenance_failed"
    user_plan = PythonAnalysisPlan.model_validate(CASES["D2"]["plan"])
    for fact in user_plan.input_facts:
        fact.evidence_id = "USER1"
    user_evidence = [{"evidence_id": "USER1", "source_type": "user_fact", "text": CASES["D2"]["topic"]}]
    assert GoalPythonAnalysis.verification_failure(user_plan, user_evidence) == "input_fact_verification_failed"


def test_basic_arithmetic_may_reference_user_input_without_formula_evidence(tmp_path):
    case, plan, evidence = prepared("D2")
    plan.supporting_evidence_ids = ["USER1"]
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"), FixtureCodeGenerator(), "agentic-v2-basic")
    request = GoalResearchRequest(topic=case["topic"], allow_python_execution=True, python_execution_approved=True)
    record, _ = asyncio.run(analysis.execute(request, plan, evidence))
    assert record.validation_passed and record.formula_evidence_ids == []


def test_planner_receives_user_fact_as_input_source_not_expected_hypothesis():
    case, plan, evidence = prepared("D2")
    evidence = [*evidence[:-1], *UserFactRegistry.from_topic(case["topic"]).evidence()]

    class PlannerOllama:
        prompt = None

        async def chat_structured(self, messages, schema, **_kwargs):
            self.prompt = json.loads(messages[-1]["content"])
            if "tool_needed" in schema["properties"]:
                return json.dumps({"tool_needed": True, "tool_type": "python_calculation", "reason": "calculate"})
            return AnalysisPlanRequest(
                purpose=plan.purpose,
                user_fact_refs=[{"fact_id": "USERF1", "alias": "A"}, {"fact_id": "USERF2", "alias": "B"}],
                formula=plan.formula,
            ).model_dump_json()

    ollama = PlannerOllama()
    request = GoalResearchRequest(topic=case["topic"], expected_result="999 mD")
    decision = asyncio.run(GoalToolPlanner(ollama).decide(request, [CRITERION], evidence, None))
    assert decision.tool_needed and decision.plan.input_facts[0].source_type == "user_fact"
    user_source = next(item for item in ollama.prompt["evidence"] if item["source_type"] == "user_fact")
    assert user_source["evidence_id"] == "USERF1" and user_source["text"] == "A = 10 mD"
    assert "999" not in json.dumps(ollama.prompt)


@pytest.mark.parametrize("model_reply,stage", [
    ("not JSON", "code_generation_failed"),
    (json.dumps({"code": "import requests"}), "sandbox_validation_failed"),
    (json.dumps({"code": "import json\nwith open('analysis_001.json', 'w') as f:\n    json.dump({'inputs': {'A': 10, 'B': 20}, 'result': {'difference': 999, 'percent_change': 100}, 'summary': 'wrong'}, f)\n"}), "result_validation_failed"),
])
def test_failure_trace_names_actual_codegen_sandbox_or_result_stage(tmp_path, model_reply, stage):
    case, plan, evidence = prepared("D1")

    class ReplyOllama:
        async def chat_structured(self, *_args, **_kwargs):
            return model_reply

    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"), ReplyOllama(), "agentic-v2-stage")
    request = GoalResearchRequest(topic=case["topic"], allow_python_execution=True, python_execution_approved=True, max_python_attempts_per_call=1)
    trace = PythonExecutionTrace()
    record, _ = asyncio.run(analysis.execute(request, plan, evidence, trace))
    assert trace.blocked_stage == stage and trace.call_boundary_reached
    assert not trace.result_validation_passed and not record.validation_passed
    assert trace.subprocess_reached is (stage == "result_validation_failed")


def test_budget_and_permission_manager_trace_without_subprocess(tmp_path, monkeypatch):
    case, plan, evidence = prepared("D1")
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    budget = GoalPythonAnalysis(settings, FixtureCodeGenerator(), "agentic-v2-budget")
    trace = PythonExecutionTrace()
    request = GoalResearchRequest(topic=case["topic"], allow_python_execution=True, python_execution_approved=True, max_python_calls=0)
    record, _ = asyncio.run(budget.execute(request, plan, evidence, trace))
    assert record is None and trace.blocked_stage == "budget_exhausted" and not trace.call_boundary_reached

    def reject(self, level, tool):
        raise AgentPermissionError("not approved")

    monkeypatch.setattr(PermissionManager, "require_tool_level", reject)
    denied = GoalPythonAnalysis(settings, FixtureCodeGenerator(), "agentic-v2-permission")
    trace = PythonExecutionTrace()
    with pytest.raises(AgentPermissionError):
        asyncio.run(denied.execute(GoalResearchRequest(topic=case["topic"], allow_python_execution=True, python_execution_approved=True), plan, evidence, trace))
    assert trace.blocked_stage == "permission_manager_rejected"
    assert trace.call_boundary_reached and not trace.subprocess_reached


class StaticResearch:
    def __init__(self, case):
        self.case = case

    async def research(self, request):
        sources = [InternalEvidence(
            evidence_id=item["evidence_id"], document="dev-fixture.pdf", page=1,
            chunk_id=f"dev-{index}", score=1.0, excerpt=item["text"],
        ) for index, item in enumerate(self.case["evidence"], 1)]
        return ResearchResponse(
            query=request.query, answer="dev fixture", internal_sources=sources,
            web_sources=[], figures=[], provenance=[], model=request.model,
            inference_used=True, evidence_counts=EvidenceCounts(internal=len(sources), external=0),
            routing_mode="internal_only", retrieval_mode="legacy",
            timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0), validation={},
        )


class StaticToolPlanner:
    def __init__(self, plan):
        self.plan = plan
        self.seen = []

    async def decide(self, request, criteria, evidence, coverage, prior):
        self.seen = evidence
        plan = self.plan.model_copy(deep=True)
        canonical = {item["name"]: item for item in evidence if item["source_type"] == "user_fact"}
        for fact in plan.input_facts:
            if fact.source_type == "user_fact":
                item = canonical[fact.name]
                fact.evidence_id = item["evidence_id"]
                fact.source_excerpt = item["source_span"]
        return ToolDecision(tool_needed=True, tool_type="python_calculation", reason="dev fixture", plan=plan)


class LocalFixtureOllama(FixtureCodeGenerator):
    async def chat_structured(self, messages, schema, **kwargs):
        if "code" in schema["properties"]:
            return await super().chat_structured(messages, schema, **kwargs)
        if "claims" in schema["properties"]:
            payload = json.loads(messages[-1]["content"])
            calc = next((item for item in payload["untrusted_evidence"] if item["source_type"] == "calculation"), None)
            citations = [calc["evidence_id"]] if calc else ["KB1"]
            return json.dumps({"claims": [{"claim": "Using the values provided in the task, the calculated result is available.", "citations": citations}], "hypothesis_assessment": {"claim": "", "citations": []}, "limitations": []})
        return json.dumps({"criteria": [{"criterion_id": "C1", "status": "met", "reason": "validated calculation", "supporting_evidence": ["CALC1"]}], "expected_result_status": "not_provided", "gaps": [], "next_research_need": None, "goal_conflicts_with_evidence": False})


def agent_for_case(settings, case_id):
    case, plan, _ = prepared(case_id)
    plan.target_criteria = ["C1"]
    ollama = LocalFixtureOllama()
    tool_planner = StaticToolPlanner(plan)
    agent = GoalResearchAgent(
        StaticResearch(case), ollama, tool_planner=tool_planner,
        analysis_factory=lambda run_id: GoalPythonAnalysis(settings, ollama, run_id),
    )
    return agent, tool_planner


@pytest.mark.parametrize("case_id,run_id", [
    ("D1", "agentic-v2-smoke-Q1-full_agent"),
    ("D3", "agentic-v2-smoke-Q2-full_agent"),
])
def test_runner_style_full_goal_agent_reaches_validated_calc(tmp_path, case_id, run_id):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    agent, tool_planner = agent_for_case(settings, case_id)
    case = CASES[case_id]
    request = GoalResearchRequest(topic=case["topic"], expected_result="hypothesis 999", success_criteria=[CRITERION], max_iterations=1, allow_python_execution=True, python_execution_approved=True, engineering_validation=False)
    result = asyncio.run(agent.run(run_id, request))
    trace = result.iterations[0].python_trace
    assert result.iterations[0].python_requested and trace.tool_selected and trace.plan_present
    assert trace.facts_verified and trace.call_boundary_reached and trace.subprocess_reached
    assert trace.result_validation_passed and trace.computation_id == "CALC1"
    assert result.python_calls_total == 1 and result.computations[0].validation_passed
    assert "[CALC1]" in result.final_answer
    assert len(result.internal_sources) == len(case["evidence"]) and not result.web_sources
    if case_id == "D3":
        assert "[USERF1]" in result.final_answer and "[KB1]" in result.final_answer
        assert [item for item in tool_planner.seen if item["source_type"] == "user_fact"][0]["text"] == "k1=10 mD"
        assert "999" not in json.dumps([item for item in tool_planner.seen if item["source_type"] == "user_fact"])


def test_runner_style_permission_denial_records_stage_and_never_calls_python(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    agent, _ = agent_for_case(settings, "D1")
    result = asyncio.run(agent.run("agentic-v2-smoke-denied", GoalResearchRequest(
        topic=CASES["D1"]["topic"], success_criteria=[CRITERION], max_iterations=1,
        allow_python_execution=True, python_execution_approved=False, engineering_validation=False,
    )))
    assert result.python_calls_total == 0 and not result.computations
    assert result.iterations[0].python_trace.blocked_stage == "permission_not_approved"
    assert not result.iterations[0].python_trace.call_boundary_reached


def test_analysis_initialization_error_is_traced_without_crashing_goal_loop(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    agent, _ = agent_for_case(settings, "D1")
    agent.analysis_factory = lambda _run_id: (_ for _ in ()).throw(ValueError("bad workspace ID"))
    result = asyncio.run(agent.run("agentic-v2-init-fail", GoalResearchRequest(
        topic=CASES["D1"]["topic"], success_criteria=[CRITERION], max_iterations=1,
        allow_python_execution=True, python_execution_approved=True, engineering_validation=False,
    )))
    assert result.run_status.value != "failed"
    assert result.python_calls_total == 0
    assert result.iterations[0].python_trace.blocked_stage == "analysis_initialization_failed"
    assert result.iterations[0].python_trace.error_summary == "ValueError"


def test_safe_id_cannot_follow_workspace_symlink_outside_root(tmp_path, monkeypatch):
    case, plan, evidence = prepared("D1")
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    parent = settings.agent_workspace_dir / "results" / "goal-research"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, parent / "agentic-v2-symlink", target_is_directory=True)
    except OSError:
        original_resolve = Path.resolve
        redirected = parent / "agentic-v2-symlink" / "analysis"

        def resolve(path, *args, **kwargs):
            return outside / "analysis" if path == redirected else original_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
    analysis = GoalPythonAnalysis(settings, FixtureCodeGenerator(), "agentic-v2-symlink")
    request = GoalResearchRequest(topic=case["topic"], allow_python_execution=True, python_execution_approved=True)
    trace = PythonExecutionTrace()
    with pytest.raises(ValueError, match="escapes its root"):
        asyncio.run(analysis.execute(request, plan, evidence, trace))
    assert trace.blocked_stage == "workspace_escape_rejected" and not trace.subprocess_reached
    assert list(outside.iterdir()) == []


def test_user_fact_is_not_standalone_scientific_evidence_or_goal_support():
    class EvaluatorOllama:
        async def chat_structured(self, *_args, **_kwargs):
            return json.dumps({"criteria": [{"criterion_id": "C1", "status": "met", "reason": "user said it", "supporting_evidence": ["USER1"]}], "expected_result_status": "not_provided", "gaps": [], "next_research_need": None, "goal_conflicts_with_evidence": False})

    user = {"evidence_id": "USER1", "source_type": "user_fact", "locator": "request.topic", "text": "k=80 mD"}
    request = GoalResearchRequest(topic="k=80 mD", success_criteria=[CRITERION], engineering_validation=False)
    result = asyncio.run(GoalEvaluator(EvaluatorOllama()).evaluate(request, [CRITERION], "A claim [USER1]", [user], {}))
    assert result.criteria[0].status != CriterionStatus.MET and not result.achieved


def test_public_gr_api_persists_trace_and_calc_without_expanding_gr_policy(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    agent, _ = agent_for_case(settings, "D1")
    service = GoalResearchService(settings, agent)
    app.dependency_overrides[get_goal_research_service] = lambda: service
    try:
        with TestClient(app) as client:
            created = client.post("/api/research/goal-runs", json={
                "topic": CASES["D1"]["topic"], "success_criteria": [CRITERION.model_dump()],
                "max_iterations": 1, "allow_python_execution": True,
                "python_execution_approved": True, "engineering_validation": False,
            })
            assert created.status_code == 201
            run_id = created.json()["run_id"]
            assert run_id.startswith("GR-")
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                polled = client.get(f"/api/research/goal-runs/{run_id}")
                if polled.json()["run_status"] not in {"planned", "running"}:
                    break
                time.sleep(0.02)
            assert polled.status_code == 200
            body = polled.json()
            assert body["run_status"] == "completed" and body["python_calls_total"] == 1
            assert body["iterations"][0]["python_trace"]["blocked_stage"] == "validated"
            assert body["computations"][0]["computation_id"] == "CALC1"
            saved = json.loads((settings.goal_research_runs_dir / f"{run_id}.json").read_text(encoding="utf-8"))
            assert saved["response"]["iterations"][0]["python_trace"]["subprocess_reached"] is True
            assert (settings.agent_workspace_dir / body["computations"][0]["output_files"][0]).is_file()
            with pytest.raises(GoalResearchRunNotFound):
                service.get("agentic-v2-smoke-Q1-full_agent")
    finally:
        app.dependency_overrides.clear()


def test_old_goal_response_without_trace_reopens():
    old_iteration = {
        "iteration": 1, "research_query": "x", "plan": {"research_question": "x", "focus_criteria": [], "reason": "initial"},
        "candidate_answer": "x", "criteria": [], "goal_coverage": 0,
        "expected_result_status": "not_provided", "engineering_validation_passed": True,
    }
    assert GoalIterationRecord.model_validate(old_iteration).python_trace is None
    old_response = GoalResearchResponse.model_validate({"run_id": "GR-OLD", "topic": "x", "max_iterations": 1, "iterations": [old_iteration], "computations": [{"computation_id": "CALC1", "analysis_id": "PA-001", "purpose": "old"}]})
    assert old_response.iterations[0].python_trace is None
    assert old_response.computations[0].source_input_ids == []
