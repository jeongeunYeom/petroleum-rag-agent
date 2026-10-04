"""Synthetic development cases only; frozen held-out tasks are not fixtures here."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.goal_research_routes import get_goal_research_service
from app.core.config import Settings
from app.main import app
from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest, PythonExecutionTrace
from app.models.research_schemas import EvidenceCounts, InternalEvidence, ResearchResponse, ResearchTiming
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_research_agent import GoalResearchAgent
from app.services.goal_research_service import GoalResearchService
from app.services.goal_tool_planner import (
    AnalysisPlanRequest, GoalToolPlanner, PlanFactRef, ToolNeedDecision,
    materialize_analysis_plan,
)
from app.services.user_fact_registry import UserFactRegistry


CRITERION = GoalCriterion(criterion_id="C1", description="Calculate the requested derived result")
TOPIC = "q=620 stb/d, pr=3150 psi, pwf=2710 psi. Calculate productivity index."
FORMULA = "PI = q / (pr - pwf)"
KB = {"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "synthetic.pdf p.1", "text": f"For the synthetic case, {FORMULA}."}


def user_evidence(topic=TOPIC):
    return UserFactRegistry.from_topic(topic).evidence()


def proposed(refs=("USERF1", "USERF2", "USERF3"), formula=FORMULA, supporting=("KB1",)):
    return AnalysisPlanRequest(
        purpose="Calculate productivity index", target_criteria=["C1"],
        user_fact_refs=[PlanFactRef(fact_id=value, alias="") for value in refs],
        formula=formula, supporting_evidence_ids=list(supporting),
        expected_outputs=["analysis.json"],
    )


class PlannerReplies:
    def __init__(self, decisions, plans=()):
        self.decisions = list(decisions)
        self.plans = list(plans)
        self.decision_calls = 0
        self.plan_calls = 0

    async def chat_structured(self, _messages, schema, **_kwargs):
        if "tool_needed" in schema["properties"]:
            self.decision_calls += 1
            return self.decisions.pop(0)
        self.plan_calls += 1
        return self.plans.pop(0)


def yes():
    return ToolNeedDecision(tool_needed=True, tool_type="python_calculation", reason="Calculation needed").model_dump_json()


def no():
    return ToolNeedDecision(tool_needed=False, tool_type="none", reason="Conceptual task").model_dump_json()


def decide(fake, topic=TOPIC, evidence=None):
    return asyncio.run(GoalToolPlanner(fake).decide(
        GoalResearchRequest(topic=topic, goal="Calculate derived result"), [CRITERION],
        evidence if evidence is not None else [KB, *user_evidence(topic)], None,
    ))


def test_decision_schema_and_retry_succeeds():
    fake = PlannerReplies(["invalid JSON", yes()], [proposed().model_dump_json()])
    result = decide(fake)
    assert result.tool_needed and result.plan is not None
    assert result.decision_attempts == 2 and result.decision_status == "selected"
    assert result.plan_attempts == 1 and result.selected_user_fact_ids == ["USERF1", "USERF2", "USERF3"]


def test_permanent_decision_parse_failure_is_not_legitimate_none():
    result = decide(PlannerReplies(["bad", "still bad"]))
    assert not result.tool_needed and result.plan is None
    assert result.decision_attempts == 2 and result.decision_status == "planner_decision_parse_failed"
    assert result.plan_attempts == 0


def test_plan_parse_retry_and_exhaustion():
    repaired = decide(PlannerReplies([yes()], ["bad", proposed().model_dump_json()]))
    assert repaired.plan and repaired.plan_attempts == 2 and repaired.plan_status == "materialized"
    failed = decide(PlannerReplies([yes()], ["bad", "still bad"]))
    assert failed.tool_needed and failed.plan is None and failed.plan_attempts == 2
    assert failed.plan_status == "planner_plan_parse_failed"


def test_conceptual_task_skips_plan_call():
    fake = PlannerReplies([no()])
    result = decide(fake)
    assert result.decision_status == "legitimate_not_selected"
    assert result.plan_attempts == 0 and fake.plan_calls == 0


def test_labeled_key_value_and_numeric_identity():
    topic = "Layer A permeability = 73 mD\nLayer B permeability = 181 mD\nA=1,000 acres, phi=2.2e-1"
    records = UserFactRegistry.from_topic(topic).records
    assert [(item.name, item.value, item.unit) for item in records] == [
        ("Layer_A_permeability", 73, "mD"), ("Layer_B_permeability", 181, "mD"),
        ("A", 1000, "acres"), ("phi", 0.22, ""),
    ]
    assert all(topic[item.topic_start:item.topic_end] == item.source_span for item in records)
    assert [item.fact_id for item in records] == ["USERF1", "USERF2", "USERF3", "USERF4"]


def test_tuple_header_extracts_distinct_units_and_preserves_raw_span():
    topic = "(thickness ft, permeability mD):\nX1=(7,42)\nX2=(13,165)\nX3=(19,88)"
    records = UserFactRegistry.from_topic(topic).records
    assert len(records) == 6
    assert [(item.name, item.value, item.unit) for item in records[:2]] == [
        ("X1_thickness", 7, "ft"), ("X1_permeability", 42, "mD"),
    ]
    assert records[1].source_span == "X1=(7,42)" and records[1].context_span == "(thickness ft, permeability mD)"
    assert records[-1].name == "X3_permeability" and records[-1].value == 88


def test_multi_well_rows_have_unique_names_and_ids():
    topic = "Well P:\nq=620 stb/d\npr=3150 psi\npwf=2710 psi\nWell R: q=725 stb/d, pr=3370 psi, pwf=2825 psi"
    records = UserFactRegistry.from_topic(topic).records
    assert len(records) == 6
    assert len({item.name for item in records}) == 6
    assert records[0].name == "Well_P_q" and records[-1].name == "Well_R_pwf"
    assert [item.fact_id for item in records] == [f"USERF{i}" for i in range(1, 7)]


def test_untyped_numbers_are_not_engineering_facts():
    assert UserFactRegistry.from_topic("Measurements: 12, 17, 29").records == []
    assert UserFactRegistry.from_topic("10, 20, 30").records == []
    assert UserFactRegistry.from_topic("pressure=3500 bar").records == []


def test_unknown_fact_and_value_override_are_rejected():
    unknown = decide(PlannerReplies([yes()], [proposed(refs=("USERF999",)).model_dump_json()]))
    assert unknown.plan is None and unknown.verification_failures == ["fact_id_unknown"]
    assert unknown.plan_status == "materialization_failed"
    with pytest.raises(ValidationError):
        PlanFactRef.model_validate({"fact_id": "USERF2", "alias": "q", "value": 999})
    plan = materialize_analysis_plan(proposed(refs=("USERF2",)), user_evidence())
    assert plan.input_facts[0].value == 3150 and plan.input_facts[0].unit == "psi"
    assert plan.input_facts[0].name == "pr"
    contaminated = AnalysisPlanRequest(
        purpose="Calculate PI", user_fact_refs=[PlanFactRef(fact_id="USERF2")],
        evidence_facts=[{
            "name": "pr", "value": 999, "unit": "mD", "evidence_id": "USERF2",
            "source_excerpt": "invented", "source_type": "evidence",
        }],
    )
    assert materialize_analysis_plan(contaminated, user_evidence()).input_facts[0].value == 3150


def test_registry_ignores_goal_and_expected_result():
    request = GoalResearchRequest(topic="q=620 stb/d", goal="pr=9999 psi", expected_result="pwf=1 psi")
    assert [item.name for item in UserFactRegistry.from_topic(request.topic).records] == ["q"]


def test_user_fact_is_not_formula_evidence_and_missing_formula_blocks():
    plan = materialize_analysis_plan(proposed(supporting=()), user_evidence())
    assert GoalPythonAnalysis.verification_failure_detail(plan, user_evidence()) == (
        "formula_provenance_failed", "formula_source_missing",
    )
    bad = materialize_analysis_plan(proposed(supporting=("USERF1",)), user_evidence())
    assert GoalPythonAnalysis.verification_failure(bad, user_evidence()) == "formula_provenance_failed"


def test_missing_formula_blocks_before_python_call(tmp_path):
    plan = materialize_analysis_plan(proposed(supporting=()), user_evidence())
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"), SyntheticOllama(), "agentic-v3-missing-formula")
    trace = PythonExecutionTrace(tool_selected=True, plan_present=True)
    record, executed = asyncio.run(analysis.execute(
        GoalResearchRequest(topic=TOPIC, allow_python_execution=True, python_execution_approved=True),
        plan, user_evidence(), trace,
    ))
    assert record is None and not executed and analysis.calls == 0
    assert trace.blocked_stage == "formula_provenance_failed"
    assert trace.verification_failures == ["formula_source_missing"]


def test_six_tuple_facts_materialize_and_execute_weighted_formula(tmp_path):
    topic = "(thickness ft, permeability mD):\nX1=(7,42)\nX2=(13,165)\nX3=(19,88)"
    facts = user_evidence(topic)
    formula = "k_eff = (X1_permeability * X1_thickness + X2_permeability * X2_thickness + X3_permeability * X3_thickness) / (X1_thickness + X2_thickness + X3_thickness)"
    source = {"evidence_id": "KB1", "source_type": "knowledge_base", "text": formula}
    plan = materialize_analysis_plan(AnalysisPlanRequest(
        purpose="Calculate thickness-weighted effective permeability", target_criteria=["C1"],
        user_fact_refs=[PlanFactRef(fact_id=f"USERF{i}") for i in range(1, 7)],
        formula=formula, supporting_evidence_ids=["KB1"],
    ), [source, *facts])

    class WeightedCode:
        async def chat_structured(self, messages, _schema, **_kwargs):
            payload = json.loads(messages[-1]["content"])
            values = {item["name"]: item["value"] for item in payload["input_facts"]}
            numerator = sum(values[f"X{i}_thickness"] * values[f"X{i}_permeability"] for i in range(1, 4))
            denominator = sum(values[f"X{i}_thickness"] for i in range(1, 4))
            result = {"inputs": values, "result": {"k_eff": numerator / denominator}, "summary": "Weighted result."}
            return json.dumps({"code": f"import json\nwith open({payload['output_json']!r}, 'w') as f:\n    json.dump({result!r}, f)\n"})

    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"), WeightedCode(), "agentic-v3-six-facts")
    trace = PythonExecutionTrace()
    record, executed = asyncio.run(analysis.execute(
        GoalResearchRequest(topic=topic, allow_python_execution=True, python_execution_approved=True),
        plan, [source, *facts], trace,
    ))
    assert executed and record.validation_passed and trace.subprocess_reached
    assert record.source_input_ids == [f"USERF{i}" for i in range(1, 7)]
    assert record.formula_evidence_ids == ["KB1"]


def test_detailed_verification_reasons_for_canonical_facts():
    evidence = user_evidence()
    plan = materialize_analysis_plan(proposed(formula=None, supporting=()), evidence)
    plan.input_facts[0].value = 999
    assert GoalPythonAnalysis.verification_failure_detail(plan, evidence)[1] == "value_mismatch"
    plan.input_facts[0].value = 620
    plan.input_facts[0].unit = "psi"
    assert GoalPythonAnalysis.verification_failure_detail(plan, evidence)[1] == "unit_mismatch"
    plan.input_facts[0].unit = "stb/d"
    plan.input_facts[0].source_excerpt = "invented"
    assert GoalPythonAnalysis.verification_failure_detail(plan, evidence)[1] == "source_span_mismatch"


class SyntheticOllama:
    def __init__(self, topic=TOPIC):
        self.topic = topic

    async def chat_structured(self, messages, schema, **_kwargs):
        properties = schema["properties"]
        if "tool_needed" in properties:
            return yes()
        if "purpose" in properties:
            return proposed().model_dump_json()
        if "code" in properties:
            payload = json.loads(messages[-1]["content"])
            facts = {item["name"]: item["value"] for item in payload["input_facts"]}
            value = facts["q"] / (facts["pr"] - facts["pwf"])
            result = {"inputs": facts, "result": {"PI": value}, "summary": "Synthetic PI calculation validated."}
            code = f"import json\nwith open({payload['output_json']!r}, 'w') as f:\n    json.dump({result!r}, f)\n"
            return json.dumps({"code": code})
        if "claims" in properties:
            return json.dumps({"claims": [{"claim": "The validated calculation gives a productivity index.", "citations": ["CALC1"]}], "hypothesis_assessment": {"claim": "", "citations": []}, "limitations": []})
        return json.dumps({"criteria": [{"criterion_id": "C1", "status": "met", "reason": "Validated calculation", "supporting_evidence": ["CALC1"]}], "expected_result_status": "not_provided", "gaps": [], "next_research_need": None, "goal_conflicts_with_evidence": False})


class MalformedPlannerOllama(SyntheticOllama):
    def __init__(self, *, fail_decision=False):
        self.fail_decision = fail_decision

    async def chat_structured(self, messages, schema, **kwargs):
        if self.fail_decision and "tool_needed" in schema["properties"]:
            return "invalid"
        if not self.fail_decision and "purpose" in schema["properties"]:
            return "invalid"
        return await super().chat_structured(messages, schema, **kwargs)


class NoToolOllama(SyntheticOllama):
    async def chat_structured(self, messages, schema, **kwargs):
        if "tool_needed" in schema["properties"]:
            return no()
        if "purpose" in schema["properties"]:
            raise AssertionError("Plan generation must not run for a legitimate none decision")
        return await super().chat_structured(messages, schema, **kwargs)


class SyntheticResearch:
    async def research(self, request):
        return ResearchResponse(
            query=request.query, answer="synthetic source",
            internal_sources=[InternalEvidence(evidence_id="KB1", document="synthetic.pdf", page=1, chunk_id="synthetic-1", score=1.0, excerpt=KB["text"])],
            web_sources=[], figures=[], provenance=[], model=request.model, inference_used=True,
            evidence_counts=EvidenceCounts(internal=1, external=0), routing_mode="internal_only",
            retrieval_mode="legacy", timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0), validation={},
        )


def test_full_goal_agent_materializes_user_facts_and_validates_calc(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    ollama = SyntheticOllama()
    agent = GoalResearchAgent(
        SyntheticResearch(), ollama,
        analysis_factory=lambda run_id: GoalPythonAnalysis(settings, ollama, run_id),
    )
    request = GoalResearchRequest(
        topic=TOPIC, success_criteria=[CRITERION], max_iterations=1,
        allow_python_execution=True, python_execution_approved=True, engineering_validation=False,
    )
    result = asyncio.run(agent.run("agentic-v3-synthetic-PI", request))
    trace = result.iterations[0].python_trace
    assert trace.tool_selected and trace.plan_present
    assert trace.planner_decision_attempts == trace.planner_plan_attempts == 1
    assert trace.available_user_fact_ids == trace.selected_user_fact_ids == ["USERF1", "USERF2", "USERF3"]
    assert trace.facts_verified and trace.call_boundary_reached and trace.subprocess_reached
    assert trace.result_validation_passed and trace.computation_id == "CALC1"
    assert result.computations[0].formula_evidence_ids == ["KB1"]
    assert result.status.value == "achieved"
    assert all(value in result.final_answer for value in ("[CALC1]", "[USERF1]", "[USERF2]", "[USERF3]", "[KB1]"))
    assert PythonExecutionTrace.model_validate_json(trace.model_dump_json()).plan_summary["fact_refs"] == ["USERF1", "USERF2", "USERF3"]


def test_goal_api_persists_v3_trace_and_calc(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    ollama = SyntheticOllama()
    agent = GoalResearchAgent(
        SyntheticResearch(), ollama,
        analysis_factory=lambda run_id: GoalPythonAnalysis(settings, ollama, run_id),
    )
    service = GoalResearchService(settings, agent)
    app.dependency_overrides[get_goal_research_service] = lambda: service
    try:
        with TestClient(app) as client:
            created = client.post("/api/research/goal-runs", json={
                "topic": TOPIC, "success_criteria": [CRITERION.model_dump()],
                "max_iterations": 1, "allow_python_execution": True,
                "python_execution_approved": True, "engineering_validation": False,
            })
            assert created.status_code == 201
            run_id = created.json()["run_id"]
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                response = client.get(f"/api/research/goal-runs/{run_id}")
                if response.json()["run_status"] not in {"planned", "running"}:
                    break
                time.sleep(0.02)
            assert response.status_code == 200
            body = response.json()
            trace = body["iterations"][0]["python_trace"]
            assert body["python_calls_total"] == 1 and trace["blocked_stage"] == "validated"
            assert trace["available_user_fact_ids"] == ["USERF1", "USERF2", "USERF3"]
            assert trace["planner_plan_status"] == "materialized"
            saved = json.loads((settings.goal_research_runs_dir / f"{run_id}.json").read_text(encoding="utf-8"))
            assert saved["response"]["iterations"][0]["python_trace"]["selected_user_fact_ids"] == ["USERF1", "USERF2", "USERF3"]
    finally:
        app.dependency_overrides.clear()


def test_conceptual_none_has_distinct_agent_blocked_stage(tmp_path):
    ollama = NoToolOllama()
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    agent = GoalResearchAgent(SyntheticResearch(), ollama, analysis_factory=lambda run_id: GoalPythonAnalysis(settings, ollama, run_id))
    result = asyncio.run(agent.run("agentic-v3-conceptual-none", GoalResearchRequest(
        topic="Explain the physical meaning of reservoir flow regimes.",
        success_criteria=[GoalCriterion(criterion_id="C1", description="Explain the concept")],
        max_iterations=1, allow_python_execution=True, python_execution_approved=True,
        engineering_validation=False,
    )))
    trace = result.iterations[0].python_trace
    assert trace.blocked_stage == "planner_not_selected"
    assert trace.planner_decision_status == "legitimate_not_selected"
    assert trace.planner_decision_attempts == 1 and trace.planner_plan_attempts == 0
    assert result.python_calls_total == 0


@pytest.mark.parametrize("fail_decision,stage", [
    (True, "planner_decision_parse_failed"),
    (False, "planner_plan_parse_failed"),
])
def test_full_agent_parse_failures_never_cross_python_boundary(tmp_path, fail_decision, stage):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    ollama = MalformedPlannerOllama(fail_decision=fail_decision)
    agent = GoalResearchAgent(SyntheticResearch(), ollama, analysis_factory=lambda run_id: GoalPythonAnalysis(settings, ollama, run_id))
    result = asyncio.run(agent.run(f"agentic-v3-malformed-{stage}", GoalResearchRequest(
        topic=TOPIC, success_criteria=[CRITERION], max_iterations=1,
        allow_python_execution=True, python_execution_approved=True, engineering_validation=False,
    )))
    trace = result.iterations[0].python_trace
    assert trace.blocked_stage == stage and not trace.call_boundary_reached
    assert result.python_calls_total == 0 and not result.computations
    assert trace.planner_decision_attempts == (2 if fail_decision else 1)
    assert trace.planner_plan_attempts == (0 if fail_decision else 2)
