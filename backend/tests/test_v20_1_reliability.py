"""Synthetic reliability regressions; no sealed benchmark or production KB reads."""

import asyncio
import json

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import GoalRunStatus, GoalStatus
from app.services.calculation_requirements import rank_formula_candidates, requested_semantic_target
from app.services.formula_source_registry import FormulaSourceRegistry, source_contains_equation
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_knowledge_retrieval import plan_query
from app.services.goal_message_parser import GoalMessageRequest, ContextMessage, parse_goal_message
from app.services.user_fact_registry import UserFactRegistry, validate_original_operands
from test_agent_reliability_v19_dev import PassingEvaluator, SyntheticResearch, actions, no_synthesis, request
from test_formula_dependency_v19 import ARCHIE_STACK_SOURCE


def run_agent(tmp_path, monkeypatch, text, source=""):
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
                        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    class NoToolModel:
        async def chat_structured(self, *_args, **_kwargs):
            return '{"tool_needed":false,"tool_type":"none","reason":"No additional tool"}'
    agent = GoalExecutionAgent(SyntheticResearch([[(360, source)]] if source else []), NoToolModel(),
                               evaluator=PassingEvaluator(), synthesizer=no_synthesis)
    return asyncio.run(agent.run("v20-1-synthetic", request(text))), agent


@pytest.mark.parametrize("raw", ["Ω·m", "Ω m", "Ωm", "ohm-m", "ohm m", "ohm·m",
                                      "ohm-meter", "ohm metre", "ohm meter"])
def test_bounded_resistivity_unit_variants(raw):
    text = f"Rw=0.08 {raw}"
    facts = UserFactRegistry.from_topic(text)
    assert [(row.name, row.value, row.unit, row.extraction_method) for row in facts.records] == [
        ("Rw", .08, "ohm-m", "explicit_assignment")]
    validate_original_operands(text, facts)


@pytest.mark.parametrize("text", ["Rw=0.08 ohm--m", "Rw=0.08 Ω//m", "Rw=0.08 ohm prose"])
def test_malformed_resistivity_not_accepted(text):
    assert all(row.unit != "ohm-m" for row in UserFactRegistry.from_topic(text).records)


def test_archie_unicode_unit_chain(tmp_path, monkeypatch):
    text = ("phi=0.22, Sw=0.35, Rw=0.08 Ω·m, a=1, m=2, n=2. "
            "Find the internal formation-factor and saturation relation; calculate Rt.")
    result, _ = run_agent(tmp_path, monkeypatch, text, ARCHIE_STACK_SOURCE)
    assert result.status == GoalStatus.ACHIEVED
    assert actions(result) == ["retrieve", "calculate", "calculate", "verify", "synthesize", "stop"]
    assert result.telemetry["required_target_outputs"] == ["Rt"]
    assert not result.state_history[1]["goal_achieved"]
    assert result.telemetry["target_output_satisfied"]
    assert not result.clarification_question
    assert [row.output_manifest["OUT_RESULT"]["name"] for row in result.computations] == ["F", "Rt"]
    assert result.computations[0].output_manifest["OUT_RESULT"]["value"] == pytest.approx(20.661157)
    target = result.computations[1].output_manifest["OUT_RESULT"]
    assert target["value"] == pytest.approx(13.493, rel=1e-4)
    assert target["unit"] == "ohm-m"
    assert all(row.validation_passed for row in result.computations)


HYDRO_SOURCE = ("The pressure in the wellbore will be equal to:\n"
                "P = 0.052 x MW x TVD\nwhere P = hydrostatic pressure (psi), "
                "MW = mud weight (ppg), TVD = true vertical depth (ft).")


def test_hydrostatic_literal_layout_and_target_semantics():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": HYDRO_SOURCE},
                {"evidence_id": "KB2", "source_type": "knowledge_base",
                 "text": "Equivalent circulating density: ECD = MW + Pd."}]
    rows = FormulaSourceRegistry.from_evidence(evidence).records
    hydro = next(row for row in rows if row.lhs == "P")
    assert hydro.raw_span == "P = 0.052 x MW x TVD"
    assert hydro.expression_candidate == "P = 0.052*MW*TVD"
    assert source_contains_equation(hydro, HYDRO_SOURCE)
    selected, _ = rank_formula_candidates(evidence,
        "Find the internal mud weight and TVD hydrostatic pressure relation and calculate pressure",
        ["MW"], {"MW": "ppg"})
    assert selected and selected.lhs == "P" and selected.source_id == "KB1"
    assert requested_semantic_target("calculate hydrostatic head from MW and TVD") == "hydrostatic_pressure"
    assert requested_semantic_target("calculate ECD") == "ecd"


def test_hydrostatic_missing_tvd_and_same_run_resume(tmp_path, monkeypatch):
    first, agent = run_agent(tmp_path, monkeypatch,
        "내부 Drilling Engineering 자료에서 mud weight와 TVD의 hydrostatic pressure 관계식을 찾아 MW=10.1 ppg의 압력을 계산해줘.",
        HYDRO_SOURCE)
    assert first.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT, (actions(first), first.telemetry, first.final_answer)
    assert "TVD" in " ".join(first.required_inputs)
    assert "Pd" not in " ".join(first.required_inputs)
    checkpoint = dict(first.resume_checkpoint)
    checkpoint["user_replies"] = ["TVD는 8000 ft야."]
    resumed = asyncio.run(agent.run(first.run_id, request(first.topic),
                                    resume_state=checkpoint, resume_result=first))
    assert resumed.run_id == first.run_id
    assert resumed.status == GoalStatus.ACHIEVED
    assert resumed.computations[-1].validation_passed
    output = resumed.computations[-1].output_manifest["OUT_RESULT"]
    assert output["value"] == pytest.approx(4201.6)
    assert output["unit"] == "psi"
    assert "Pd" not in " ".join(resumed.required_inputs)


@pytest.mark.parametrize("text,expected", [
    ("A=187, B=234, C=163 stb/d의 평균과 순위를 구해줘", "stb/d"),
    ("Q1=10, Q2=20, Q3=30 m3/d의 평균을 구해줘", "m3/d"),
])
def test_homogeneous_trailing_unit_propagation(text, expected):
    facts = UserFactRegistry.from_topic(text)
    assert len(facts.records) == 3
    assert {row.unit for row in facts.records} == {expected}
    assert sum(row.extraction_method == "grouped_assignment" for row in facts.records) == 2
    validate_original_operands(text, facts)


@pytest.mark.parametrize("text", ["Pressure=3000, Rate=500 stb/d", "A=10 psi, B=20 stb/d",
                                      "phi=0.2, k=100 mD"])
def test_mixed_or_unrelated_assignment_units_not_propagated(text):
    facts = UserFactRegistry.from_topic(text)
    assert all(row.extraction_method != "grouped_assignment" for row in facts.records)


def test_direct_mean_and_ranking_without_retrieval(tmp_path, monkeypatch):
    result, _ = run_agent(tmp_path, monkeypatch,
        "A=187, B=234, C=163 stb/d의 평균을 구하고 큰 순서대로 정렬해줘.")
    assert result.status == GoalStatus.ACHIEVED
    assert actions(result)[0] == "calculate"
    assert actions(result)[:3] == ["calculate", "analyze", "verify"]
    assert "retrieve" not in actions(result)
    assert result.computations and result.computations[0].validation_passed
    outputs = result.computations[0].output_manifest
    assert any(row.get("name") == "mean" and row.get("value") == pytest.approx(194.6666667)
               and row.get("unit") == "stb/d" for row in outputs.values())
    assert any(row.get("name") == "ranking" and row.get("value") == ["B", "A", "C"]
               for row in outputs.values())


def test_internal_calculation_exception_never_becomes_missing_input(tmp_path, monkeypatch):
    async def broken(*_args, **_kwargs):
        raise ValueError("private calculation detail")
    monkeypatch.setattr("app.services.goal_execution_agent.run_direct_arithmetic", broken)
    result, _ = run_agent(tmp_path, monkeypatch,
        "A=187, B=234, C=163 stb/d의 평균을 구해줘.")
    visible = result.final_answer + " ".join(result.required_inputs) + str(result.clarification_question or "")
    assert "ValueError" not in visible and "private calculation detail" not in visible
    assert result.telemetry["internal_calculation_error_type"] == "ValueError"


def test_monel_refinement_changes_query_without_answer_injection():
    question = "방향 측정기 근처에 Monel drill collar를 사용하는 이유를 내부 자료에 근거해 설명해줘."
    initial = plan_query(question)
    refined = plan_query(question, refined=True)
    assert initial.search_text != refined.search_text
    assert "non-magnetic drill collar" in refined.search_text
    assert "magnetic interference" in refined.search_text
    assert "because" not in refined.search_text.casefold()


def test_api_gravity_and_contextual_sg_correction(tmp_path, monkeypatch):
    source = "API = (141.5 / SG) - 131.5"
    first, _ = run_agent(tmp_path, monkeypatch,
        "SG=0.918인 원유의 API gravity를 내부 관계식으로 계산해줘.", source)
    assert first.status == GoalStatus.ACHIEVED
    assert first.computations[0].output_manifest["OUT_default_API_gravity"]["value"] == pytest.approx(22.63943355)
    parsed = parse_goal_message(GoalMessageRequest(message="그럼 0.85면?", context_messages=[
        ContextMessage(role="user", content="SG=0.918인 원유의 API gravity를 내부 관계식으로 계산해줘.")]))
    facts = UserFactRegistry.from_topic(parsed.topic)
    assert facts.apply_contextual_correction(parsed.current_message, parsed.contextual_fact_name)
    assert [(row.name, row.value) for row in facts.records] == [("SG", .85)]
    assert 141.5 / facts.records[0].value - 131.5 == pytest.approx(34.970588235)
