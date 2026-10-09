"""Fresh synthetic v4 cases; frozen held-out questions are not used."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.models.goal_research_schemas import ComputationRecord, GoalCriterion, GoalResearchRequest, PythonExecutionTrace
from app.models.research_schemas import EvidenceCounts, InternalEvidence, ResearchResponse, ResearchTiming
from app.api.goal_research_routes import get_goal_research_service
from app.main import app
from app.services.goal_research_agent import GoalResearchAgent
from app.services.goal_research_service import GoalResearchService
from app.services.evidence_fact_registry import EvidenceFactRegistry
from app.services.formula_source_registry import FormulaSourceRegistry, normalize_formula
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_tool_planner import (
    AnalysisPlanSelection, GoalToolPlanner, PLAN_SCHEMA, ToolNeedDecision,
    materialize_analysis_plan_v4, PlanMaterializationError,
)
from app.services.user_fact_registry import UserFactRegistry


def source(text: str, source_id: str = "KB1") -> dict:
    return {"evidence_id": source_id, "source_type": "knowledge_base", "locator": "new-synthetic.pdf p.4", "text": text}


def select(refs: list[str], formula: str | None = None, operation: str | None = None) -> AnalysisPlanSelection:
    return AnalysisPlanSelection(
        purpose="Calculate the requested result", target_criteria=["C1"], fact_refs=refs,
        formula_ref=formula, operation_hint=operation, expected_outputs=["analysis.json"], create_chart=False,
    )


def materialize(selection: AnalysisPlanSelection, evidence: list[dict]):
    return materialize_analysis_plan_v4(
        selection, evidence, EvidenceFactRegistry.from_evidence(evidence), FormulaSourceRegistry.from_evidence(evidence),
    )


def test_evidence_fact_registry_exact_spans_multiple_rows_and_ambiguity():
    text = ("Core permeability = 147 mD and pressure = 2840 psi.\n"
            "Layer A: thickness=9 ft, permeability=61 mD\n"
            "Layer B: thickness=17 ft, permeability=153 mD\n"
            "Layer C: thickness=12 ft, permeability=97 mD\n"
            "Reservoir pressure was 3050 psi. Values were 12, 18, and 31.")
    records = EvidenceFactRegistry.from_evidence([source(text)]).records
    assert len(records) == 9
    assert [item.fact_id for item in records] == [f"EFACT{i}" for i in range(1, 10)]
    assert records[0].name == "Core_permeability" and records[0].value == 147
    assert records[1].name == "pressure" and records[1].value == 2840
    assert records[2].name == "Layer_A_thickness" and records[7].name == "Layer_C_permeability"
    assert records[-1].name == "Reservoir_pressure" and records[-1].value == 3050
    assert all(item.source_id == "KB1" and text[item.span_start:item.span_end] == item.source_span for item in records)
    assert EvidenceFactRegistry.from_evidence([source("Values were 12, 18, and 31.")]).records == []


@pytest.mark.parametrize("source_type,source_id,plan_type", [
    ("knowledge_base", "KB1", "kb"), ("figure", "FIG1", "figure"), ("web", "WEB1", "web"),
])
def test_registry_links_each_scientific_source_class(source_type, source_id, plan_type):
    evidence = [{"evidence_id": source_id, "source_type": source_type, "text": "pressure: 3120 psi, depth: 75 ft"}]
    records = EvidenceFactRegistry.from_evidence(evidence).records
    assert len(records) == 2 and all(item.source_id == source_id for item in records)
    plan = materialize(select(["EFACT1", "EFACT2"], operation="ratio"), evidence)
    assert [item.source_type for item in plan.input_facts] == [plan_type, plan_type]


def test_formula_registry_normalizes_only_literal_equations():
    first = FormulaSourceRegistry.from_evidence([source("For this relation, PI = q/(pr−pwf).")]).records
    second = FormulaSourceRegistry.from_evidence([source("PI = q / ( pr - pwf )")]).records
    assert len(first) == len(second) == 1
    assert first[0].raw_span == "PI = q/(pr−pwf)"
    assert first[0].expression_candidate == "PI = q/(pr-pwf)"
    assert first[0].normalized_span == second[0].normalized_span == normalize_formula("PI = q/(pr-pwf)")
    assert normalize_formula("P₁ = Q × R") == normalize_formula("P1=Q*R")
    assert FormulaSourceRegistry.from_evidence([source("P₁ = Q × R")]).records[0].expression_candidate == "P1 = Q * R"
    assert FormulaSourceRegistry.from_evidence([source("Productivity is influenced by flow rate and drawdown.")]).records == []
    ambiguous = FormulaSourceRegistry.from_evidence([source("X = a/(b -)")]).records
    assert len(ambiguous) == 1 and ambiguous[0].expression_candidate is None
    assert FormulaSourceRegistry.from_evidence([source("pressure = 147 mD")]).records == []


def test_plan_schema_has_ids_only_and_materialization_is_canonical():
    for forbidden in ("value", "unit", "source_excerpt", "evidence_facts", "formula"):
        assert forbidden not in PLAN_SCHEMA["properties"]
    with pytest.raises(ValidationError):
        AnalysisPlanSelection.model_validate({**select(["USERF1"]).model_dump(), "source_excerpt": "invented"})
    with pytest.raises(ValidationError):
        AnalysisPlanSelection.model_validate({**select(["USERF1"]).model_dump(), "value": 999})
    topic = "q=710 stb/d, pr=3260 psi, pwf=2740 psi"
    evidence = [source("For the test well, PI = q/(pr-pwf)."), *UserFactRegistry.from_topic(topic).evidence()]
    plan = materialize(select(["USERF1", "USERF2", "USERF3"], "FORMULA1"), evidence)
    assert [item.value for item in plan.input_facts] == [710, 3260, 2740]
    assert plan.input_facts[0].source_excerpt == "q=710 stb/d"
    assert plan.formula_source_id == "FORMULA1" and plan.formula_source_span == "PI = q/(pr-pwf)"
    assert plan.supporting_evidence_ids == ["KB1"]


@pytest.mark.parametrize("selection,reason,field", [
    (select(["USERF999"], "FORMULA1"), "fact_id_unknown", "fact_id"),
    (select(["EFACT999"], "FORMULA1"), "fact_id_unknown", "fact_id"),
    (select(["USERF1"], "FORMULA999"), "formula_id_unknown", "formula_id"),
    (select(["USERF1", "USERF2"], "FORMULA1"), "formula_variable_missing", "formula_id"),
    (select(["USERF1", "USERF2", "USERF3"]), "required_source_unavailable", None),
])
def test_invalid_ids_missing_variable_or_source_never_materialize(selection, reason, field):
    evidence = [source("PI = q/(pr-pwf)"), *UserFactRegistry.from_topic("q=710 stb/d, pr=3260 psi, pwf=2740 psi").evidence()]
    with pytest.raises(PlanMaterializationError) as error:
        materialize(selection, evidence)
    assert error.value.reason == reason
    if field:
        assert getattr(error.value.failure, field)


def test_unparseable_equation_anchor_is_recorded_but_never_executed():
    evidence = [source("X = a/(b -)"), *UserFactRegistry.from_topic("a=7 ft, b=2 ft").evidence()]
    with pytest.raises(PlanMaterializationError) as error:
        materialize(select(["USERF1", "USERF2"], "FORMULA1"), evidence)
    assert error.value.reason == "formula_not_parseable"
    assert error.value.failure.formula_id == "FORMULA1" and error.value.failure.source_id == "KB1"


def test_evidence_fact_and_formula_materialize_and_trace_exact_failure(tmp_path):
    evidence = [source("P_top=3460 psi, P_bottom=3020 psi, depth=80 ft. gradient = (P_top - P_bottom)/depth.")]
    plan = materialize(select(["EFACT1", "EFACT2", "EFACT3"], "FORMULA1"), evidence)
    assert [item.canonical_fact_id for item in plan.input_facts] == ["EFACT1", "EFACT2", "EFACT3"]
    assert [item.evidence_id for item in plan.input_facts] == ["KB1"] * 3
    assert all(evidence[0]["text"][item.span_start:item.span_end] == item.source_excerpt for item in plan.input_facts)
    assert GoalPythonAnalysis.verification_failure_detail(plan, evidence) is None
    bad = plan.model_copy(deep=True)
    bad.input_facts[1].source_excerpt = "wrong"
    trace = PythonExecutionTrace()
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"), object(), "v4-fact-failure")
    record, executed = asyncio.run(analysis.execute(GoalResearchRequest(topic="Calculate gradient", allow_python_execution=True, python_execution_approved=True), bad, evidence, trace))
    assert record is None and not executed and analysis.calls == 0
    assert trace.verification_failures_structured[0].fact_id == "EFACT2"
    assert trace.verification_failures_structured[0].source_id == "KB1"
    bad = plan.model_copy(deep=True)
    bad.formula_source_span = "invented"
    trace = PythonExecutionTrace()
    asyncio.run(analysis.execute(GoalResearchRequest(topic="Calculate gradient", allow_python_execution=True, python_execution_approved=True), bad, evidence, trace))
    assert trace.facts_verified and not trace.formula_verified
    assert trace.verification_failures_structured[0].formula_id == "FORMULA1"
    assert trace.verification_failures_structured[0].source_id == "KB1"


class Replies:
    def __init__(self, plans: list[str]):
        self.plans = plans[:]
        self.messages: list = []

    async def chat_structured(self, messages, schema, **_kwargs):
        if "tool_needed" in schema["properties"]:
            return ToolNeedDecision(tool_needed=True, tool_type="python_calculation", reason="needed").model_dump_json()
        self.messages.append(messages)
        return self.plans.pop(0)


def test_plan_parse_and_unknown_id_repair_are_bounded():
    evidence = [source("PI = q/(pr-pwf)"), *UserFactRegistry.from_topic("q=710 stb/d, pr=3260 psi, pwf=2740 psi").evidence()]
    request = GoalResearchRequest(topic="q=710 stb/d, pr=3260 psi, pwf=2740 psi")
    criterion = [GoalCriterion(criterion_id="C1", description="Calculate PI")]
    valid = select(["USERF1", "USERF2", "USERF3"], "FORMULA1").model_dump_json()
    for first in ("malformed", select(["EFACT999"], "FORMULA1").model_dump_json()):
        replies = Replies([first, valid])
        result = asyncio.run(GoalToolPlanner(replies).decide(request, criterion, evidence, None))
        assert result.plan_attempts == 2 and result.plan_status == "materialized" and result.plan
        assert len(replies.messages) == 2
    invalid = select(["EFACT999"], "FORMULA1").model_dump_json()
    exhausted = asyncio.run(GoalToolPlanner(Replies([invalid, invalid])).decide(request, criterion, evidence, None))
    assert exhausted.plan is None and exhausted.plan_attempts == 2
    assert exhausted.verification_failures_structured[0].fact_id == "EFACT999"


class FixedCode:
    async def chat_structured(self, messages, _schema, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        values = {item["name"]: item["value"] for item in payload["input_facts"]}
        if "gradient" in str(payload["formula"]):
            result = {"gradient": (values["P_top"] - values["P_bottom"]) / values["depth"]}
        elif "PV" in str(payload["formula"]):
            result = {"PV": 7758 * values["A"] * values["h"] * values["phi"]}
        elif "k_eff" in str(payload["formula"]):
            numerator = sum(values[f"Layer_{letter}_permeability"] * values[f"Layer_{letter}_thickness"] for letter in "ABCD")
            denominator = sum(values[f"Layer_{letter}_thickness"] for letter in "ABCD")
            result = {"k_eff": numerator / denominator}
        else:
            result = {"difference": values["Core_B_porosity"] - values["Core_A_porosity"],
                      "percent_change": (values["Core_B_porosity"] - values["Core_A_porosity"]) / values["Core_A_porosity"] * 100}
        output = {"inputs": values, "result": result, "summary": "Synthetic calculation validated."}
        code = f"import json\nwith open({payload['output_json']!r}, 'w') as f:\n    json.dump({output!r}, f)\n"
        return json.dumps({"code": code})


def selected_plan(topic: str, evidence: list[dict], selection: AnalysisPlanSelection):
    request = GoalResearchRequest(topic=topic)
    criterion = [GoalCriterion(criterion_id="C1", description="Calculate the requested numeric result")]
    decision = asyncio.run(GoalToolPlanner(Replies([selection.model_dump_json()])).decide(request, criterion, evidence, None))
    assert decision.tool_needed and decision.decision_status == "selected"
    assert decision.plan_status == "materialized" and decision.plan is not None
    assert decision.selected_fact_ids == selection.fact_refs and decision.selected_formula_id == selection.formula_ref
    return decision.plan


@pytest.mark.parametrize("topic,kb,refs,formula,operation", [
    ("Core A porosity=14 %, Core B porosity=21 %", "Context only.", ["USERF1", "USERF2"], None, "difference_and_percent_change"),
    ("A=83 acres, h=26 ft, phi=0.22", "PV = 7758 * A * h * phi.", ["USERF1", "USERF2", "USERF3"], "FORMULA1", None),
    ("Calculate a pressure gradient from the source table.", "P_top=3460 psi, P_bottom=3020 psi, depth=80 ft. gradient = (P_top - P_bottom)/depth.", ["EFACT1", "EFACT2", "EFACT3"], "FORMULA1", None),
])
def test_three_new_synthetic_paths_reach_validated_calc(tmp_path, topic, kb, refs, formula, operation):
    evidence = [source(kb), *UserFactRegistry.from_topic(topic).evidence()]
    plan = selected_plan(topic, evidence, select(refs, formula, operation))
    trace = PythonExecutionTrace()
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"), FixedCode(), "v4-new-path")
    record, executed = asyncio.run(analysis.execute(
        GoalResearchRequest(topic=topic, allow_python_execution=True, python_execution_approved=True), plan, evidence, trace,
    ))
    assert executed and record and record.validation_passed and record.computation_id == "CALC1"
    assert trace.facts_verified and trace.formula_verified and trace.call_boundary_reached
    assert trace.subprocess_reached and trace.result_validation_passed
    assert record.canonical_fact_ids == refs
    assert record.formula_source_id == formula
    if refs[0].startswith("EFACT"):
        assert record.source_evidence_ids == ["KB1"] and not record.source_input_ids


def test_eight_fact_multirow_source_formula_reaches_calc(tmp_path):
    text = ("Layer A: thickness=8 ft, permeability=64 mD\n"
            "Layer B: thickness=11 ft, permeability=142 mD\n"
            "Layer C: thickness=16 ft, permeability=88 mD\n"
            "Layer D: thickness=13 ft, permeability=210 mD\n"
            "k_eff = (Layer_A_thickness*Layer_A_permeability + Layer_B_thickness*Layer_B_permeability + Layer_C_thickness*Layer_C_permeability + Layer_D_thickness*Layer_D_permeability)/(Layer_A_thickness + Layer_B_thickness + Layer_C_thickness + Layer_D_thickness).")
    evidence = [source(text)]
    plan = selected_plan("Calculate weighted permeability from all four layers", evidence,
                         select([f"EFACT{i}" for i in range(1, 9)], "FORMULA1"))
    trace = PythonExecutionTrace()
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"), FixedCode(), "v4-eight-facts")
    record, _ = asyncio.run(analysis.execute(GoalResearchRequest(topic="Calculate weighted k", allow_python_execution=True, python_execution_approved=True), plan, evidence, trace))
    assert record and record.validation_passed and trace.subprocess_reached and len(record.canonical_fact_ids) == 8


class SyntheticResearch:
    async def research(self, request):
        return ResearchResponse(
            query=request.query, answer="Synthetic equation source.",
            internal_sources=[InternalEvidence(
                evidence_id="KB1", document="new-synthetic.pdf", page=4, chunk_id="new-4",
                score=1.0, excerpt="PV = 7758 * A * h * phi.",
            )], web_sources=[], figures=[], provenance=[], model=request.model, inference_used=True,
            evidence_counts=EvidenceCounts(internal=1, external=0), routing_mode="internal_only",
            retrieval_mode="legacy", timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0),
            validation={},
        )


class AgentReplies(FixedCode):
    async def chat_structured(self, messages, schema, **kwargs):
        fields = schema["properties"]
        if "tool_needed" in fields:
            return ToolNeedDecision(tool_needed=True, tool_type="python_calculation", reason="Need numeric result").model_dump_json()
        if "contract_id" in fields:
            return json.dumps({"contract_id": "CC1", "purpose": "Calculate pore volume", "target_criteria": ["C1"],
                               "input_fact_ids": ["USERF1", "USERF2", "USERF3"], "formula_id": "FORMULA1",
                               "operation_type": "formula", "scenarios": [{"scenario_id": "case", "input_bindings":
                               {"A": "USERF1", "h": "USERF2", "phi": "USERF3"}}],
                               "required_outputs": [{"output_id": "OUT_PV", "name": "PV", "semantic_type": "numeric",
                               "unit": "bbl", "required": True, "scenario_id": "case",
                               "source_fact_ids": ["USERF1", "USERF2", "USERF3"], "formula_id": "FORMULA1"}]})
        if "purpose" in fields:
            return select(["USERF1", "USERF2", "USERF3"], "FORMULA1").model_dump_json()
        if "code" in fields:
            payload = json.loads(messages[-1]["content"])
            values = {item["name"]: item["value"] for item in payload["input_facts"]}
            output = {"contract_id": "CC1", "outputs": {"OUT_PV": {"value": 7758 * values["A"] * values["h"] * values["phi"], "unit": "bbl"}},
                      "used_input_ids": ["USERF1", "USERF2", "USERF3"], "used_formula_id": "FORMULA1", "summary": "Synthetic pore volume."}
            return json.dumps({"code": f"import json\nwith open({payload['output_json']!r}, 'w') as f:\n    json.dump({output!r}, f)\n"})
        if "claims" in fields:
            payload = json.loads(messages[-1]["content"])
            value = next(item for item in payload["untrusted_evidence"] if item["source_type"] == "calculation")["output_manifest"]["OUT_PV"]["value"]
            return json.dumps({"claims": [{"claim": f"PV is {value} bbl.", "citations": ["CALC1"], "output_ids": ["OUT_PV"]}],
                               "hypothesis_assessment": {"claim": "", "citations": []}, "limitations": []})
        return json.dumps({"criteria": [{"criterion_id": "C1", "status": "met", "reason": "validated calculation",
                                          "supporting_evidence": ["CALC1"]}], "expected_result_status": "not_provided",
                           "gaps": [], "next_research_need": None, "goal_conflicts_with_evidence": False})


def new_agent(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    ollama = AgentReplies()
    return settings, GoalResearchAgent(
        SyntheticResearch(), ollama,
        analysis_factory=lambda run_id: GoalPythonAnalysis(settings, ollama, run_id),
    )


def new_request():
    return GoalResearchRequest(
        topic="A=83 acres, h=26 ft, phi=0.22", goal="Calculate pore volume using the cited equation.",
        success_criteria=[GoalCriterion(criterion_id="C1", description="Calculate pore volume")],
        max_iterations=1, allow_python_execution=True, python_execution_approved=True, engineering_validation=False,
    )


def test_full_goal_agent_and_service_preserve_source_citations(tmp_path):
    settings, agent = new_agent(tmp_path)
    result = asyncio.run(agent.run("v4-full-agent", new_request()))
    trace = result.iterations[0].python_trace
    assert trace.tool_selected and trace.planner_plan_status == "materialized"
    assert trace.selected_fact_ids == ["USERF1", "USERF2", "USERF3"] and trace.selected_formula_id == "FORMULA1"
    assert trace.facts_verified and trace.formula_verified and trace.subprocess_reached and trace.result_validation_passed
    assert result.computations[0].formula_source_id == "FORMULA1"
    assert all(citation in result.final_answer for citation in ("[CALC1]", "[USERF1]", "[KB1]"))
    service = GoalResearchService(settings, agent)
    app.dependency_overrides[get_goal_research_service] = lambda: service
    try:
        with TestClient(app) as client:
            created = client.post("/api/research/goal-runs", json=new_request().model_dump(mode="json"))
            assert created.status_code == 201
            run_id = created.json()["run_id"]
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                response = client.get(f"/api/research/goal-runs/{run_id}")
                if response.json()["run_status"] not in {"planned", "running"}:
                    break
                time.sleep(0.02)
            body = response.json()
            assert body["computations"][0]["validation_passed"]
            assert body["iterations"][0]["python_trace"]["selected_formula_id"] == "FORMULA1"
    finally:
        app.dependency_overrides.clear()


def test_canonical_permission_cache_security_and_old_json(tmp_path):
    evidence = [source("PV = 7758 * A * h * phi."), *UserFactRegistry.from_topic("A=83 acres, h=26 ft, phi=0.22").evidence()]
    plan = materialize(select(["USERF1", "USERF2", "USERF3"], "FORMULA1"), evidence)
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    analysis = GoalPythonAnalysis(settings, FixedCode(), "v4-security-cache")
    denied = PythonExecutionTrace()
    record, executed = asyncio.run(analysis.execute(GoalResearchRequest(topic="Pore volume"), plan, evidence, denied))
    assert record is None and not executed and denied.blocked_stage == "permission_not_approved" and analysis.calls == 0
    request = GoalResearchRequest(topic="Pore volume", allow_python_execution=True, python_execution_approved=True)
    first, executed = asyncio.run(analysis.execute(request, plan, evidence))
    trace = PythonExecutionTrace()
    second, repeated = asyncio.run(analysis.execute(request, plan, evidence, trace))
    assert executed and not repeated and first is second and trace.blocked_stage == "cache_hit"
    assert analysis.calls == 1
    old_trace = PythonExecutionTrace.model_validate({"tool_selected": True, "facts_verified": True})
    old_record = ComputationRecord.model_validate({"computation_id": "CALC1", "analysis_id": "PA-001", "purpose": "old"})
    assert not old_trace.formula_verified and old_record.formula_source_id is None
    with pytest.raises(ValueError):
        GoalPythonAnalysis(settings, FixedCode(), "../workspace-escape")


def test_canonical_network_import_stays_blocked(tmp_path):
    class UnsafeCode:
        async def chat_structured(self, *_args, **_kwargs):
            return json.dumps({"code": "import requests"})

    evidence = [source("PV = 7758 * A * h * phi."), *UserFactRegistry.from_topic("A=83 acres, h=26 ft, phi=0.22").evidence()]
    plan = materialize(select(["USERF1", "USERF2", "USERF3"], "FORMULA1"), evidence)
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"), UnsafeCode(), "v4-network")
    trace = PythonExecutionTrace()
    record, _ = asyncio.run(analysis.execute(GoalResearchRequest(
        topic="Pore volume", allow_python_execution=True, python_execution_approved=True,
        max_python_attempts_per_call=1,
    ), plan, evidence, trace))
    assert record and not record.validation_passed and trace.blocked_stage == "sandbox_validation_failed"
    assert not trace.subprocess_reached


def test_source_formula_numeric_result_is_checked_not_just_echoed(tmp_path):
    class WrongResult:
        async def chat_structured(self, messages, _schema, **_kwargs):
            payload = json.loads(messages[-1]["content"])
            values = {item["name"]: item["value"] for item in payload["input_facts"]}
            data = {"inputs": values, "result": {"PV": 1}, "summary": "Incorrect output"}
            return json.dumps({"code": f"import json\nwith open({payload['output_json']!r}, 'w') as f:\n    json.dump({data!r}, f)\n"})

    evidence = [source("PV = 7758 * A * h * phi."), *UserFactRegistry.from_topic("A=83 acres, h=26 ft, phi=0.22").evidence()]
    plan = materialize(select(["USERF1", "USERF2", "USERF3"], "FORMULA1"), evidence)
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"), WrongResult(), "v4-wrong-result")
    trace = PythonExecutionTrace()
    record, _ = asyncio.run(analysis.execute(GoalResearchRequest(
        topic="Pore volume", allow_python_execution=True, python_execution_approved=True,
        max_python_attempts_per_call=1,
    ), plan, evidence, trace))
    assert record and not record.validation_passed and trace.facts_verified and trace.formula_verified
    assert trace.blocked_stage == "result_validation_failed" and not trace.result_validation_passed
