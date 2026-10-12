"""Fresh synthetic dependency graphs; no benchmark or production KB is loaded."""

import asyncio

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import GoalRunStatus, GoalStatus
from app.services.formula_dependency import resolve_formula_dependencies
from app.services.formula_source_registry import FormulaSourceRegistry
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.user_fact_registry import UserFactRegistry
from test_agent_reliability_v19_dev import (PassingEvaluator, SyntheticResearch,
                                            actions, no_synthesis, request)


def run_case(tmp_path, monkeypatch, text, source):
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    research = SyntheticResearch([[(3, source)]])
    agent = GoalExecutionAgent(research, object(), evaluator=PassingEvaluator(), synthesizer=no_synthesis)
    req = request(text)
    return asyncio.run(agent.run("dependency-synthetic", req)), agent, req


def test_dependency_then_target_and_provenance(tmp_path, monkeypatch):
    result, _, _ = run_case(tmp_path, monkeypatch,
        "A=2 ft; B=12 kg; C=3 kg. Find the internal Q equation and calculate Q.",
        "Q=X*A. X=B/C. A (ft); B (kg); C (kg).")
    assert result.status == GoalStatus.ACHIEVED
    assert actions(result)[:5] == ["retrieve", "calculate", "calculate", "verify", "synthesize"]
    assert len(result.computations) == 2
    assert result.computations[0].output_manifest["OUT_RESULT"]["name"] == "X"
    assert result.computations[1].output_manifest["OUT_RESULT"]["value"] == pytest.approx(8)
    assert any(value.startswith("CALC1:") for value in result.computations[1].input_fact_ids)
    assert result.telemetry["formula_dependency_resolution_success"]
    assert result.telemetry["clarification_avoided_by_dependency_resolution"]
    assert result.action_history[1]["details"]["output_variable"] == "X"
    assert result.action_history[2]["details"]["output_variable"] == "Q"


def test_two_level_chain_executes_in_order(tmp_path, monkeypatch):
    result, _, _ = run_case(tmp_path, monkeypatch,
        "Base=3 kg. Find the internal Z equation and calculate Z.",
        "Z=Y+Y. Y=X*2. X=Base*2. Base (kg).")
    assert result.status == GoalStatus.ACHIEVED
    assert [calc.output_manifest["OUT_RESULT"]["name"] for calc in result.computations] == ["X", "Y", "Z"]
    assert result.computations[-1].output_manifest["OUT_RESULT"]["value"] == 24
    assert result.telemetry["formula_dependency_depth"] == 2


def test_cycle_blocks_without_python(tmp_path, monkeypatch):
    result, _, _ = run_case(tmp_path, monkeypatch,
        "Find the internal A equation and calculate A.",
        "A=B+1. B=A-1.")
    assert result.status != GoalStatus.ACHIEVED
    assert result.python_calls_total == 0
    assert result.telemetry["formula_dependency_cycle_detected"]
    assert result.telemetry["formula_dependency_block_reason"] == "formula_dependency_cycle"


def test_missing_base_input_not_intermediate(tmp_path, monkeypatch):
    result, _, _ = run_case(tmp_path, monkeypatch,
        "A=2 ft; B=12 kg. Find the internal Q equation and calculate Q.",
        "Q=X*A. X=B/C. A (ft); B (kg); C (kg).")
    assert result.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT
    assert "C" in " ".join(result.required_inputs)
    assert "X 값" not in " ".join(result.required_inputs)
    assert not result.computations


def test_unverified_dependency_span_cannot_be_used():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "Q=X*A. A (ft)."},
                {"evidence_id": "KB2", "source_type": "knowledge_base",
                 "text": "X=B/C. B (kg); C (kg)."}]
    target = FormulaSourceRegistry.from_evidence(evidence).records[0]
    # An adjacent passage discussing the variables is not an equation source.
    altered = [evidence[0], {**evidence[1], "text": "X depends on B and C; equation absent."}]
    plan = resolve_formula_dependencies(target, altered,
        UserFactRegistry.from_topic("A=2 ft; B=12 kg; C=3 kg"), [], [])
    assert plan.next_formula is None
    assert plan.missing_inputs == ["X"]


def test_tampered_formula_locator_is_not_executed():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "Q=X*A. X=B/C. A (ft); B (kg); C (kg)."}]
    target = FormulaSourceRegistry.from_evidence(evidence).records[0]
    tampered = target.model_copy(update={"span_start": target.span_start + 1})
    plan = resolve_formula_dependencies(tampered, evidence,
        UserFactRegistry.from_topic("A=2 ft; B=12 kg; C=3 kg"), [], [])
    assert plan.next_formula is None
    assert plan.block_reason == "formula_dependency_source_unverified"


def test_competing_equations_remain_ambiguous(tmp_path, monkeypatch):
    result, _, _ = run_case(tmp_path, monkeypatch,
        "A=2 ft; B=12 kg; C=3 kg. Find the internal Q equation and calculate Q.",
        "Q=X*A. X=B/C. X=B+C. A (ft); B (kg); C (kg).")
    assert result.status != GoalStatus.ACHIEVED
    assert result.python_calls_total == 0
    assert result.telemetry["formula_dependency_block_reason"] == "formula_dependency_ambiguous"


def test_depth_limit_blocks_long_chain_before_python(tmp_path, monkeypatch):
    result, _, _ = run_case(tmp_path, monkeypatch,
        "Base=1 kg. Find the internal A equation and calculate A.",
        "A=B*2. B=C*2. C=D*2. D=E*2. E=Base*2.")
    assert result.python_calls_total == 0
    assert result.telemetry["formula_dependency_block_reason"] == "formula_dependency_depth_exceeded"


def test_missing_intermediate_relation_gets_bounded_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    research = SyntheticResearch([[(4, "Q=X*A. A (ft).")],
                                  [(5, "X=B/C. B (kg); C (kg).")]])
    agent = GoalExecutionAgent(research, object(), evaluator=PassingEvaluator(), synthesizer=no_synthesis)
    req = request("A=2 ft; B=12 kg; C=3 kg. Find the internal Q equation and calculate Q.")
    result = asyncio.run(agent.run("dependency-recovery", req))
    assert result.status == GoalStatus.ACHIEVED
    assert actions(result)[:4] == ["retrieve", "retrieve", "calculate", "calculate"]
    assert research.calls == 2
    assert "X" in research.queries[1]


def test_resume_base_input_executes_both_in_same_run(tmp_path, monkeypatch):
    first, agent, req = run_case(tmp_path, monkeypatch,
        "A=2 ft; B=12 kg. Find the internal Q equation and calculate Q.",
        "Q=X*A. X=B/C. A (ft); B (kg); C (kg).")
    assert first.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT
    checkpoint = dict(first.resume_checkpoint)
    checkpoint["user_replies"] = ["C=3 kg"]
    result = asyncio.run(agent.run(first.run_id, req, resume_state=checkpoint, resume_result=first))
    assert result.run_id == first.run_id
    assert result.status == GoalStatus.ACHIEVED
    assert result.run_status == GoalRunStatus.COMPLETED
    assert len(result.computations) == 2
    assert not result.clarification_question


def test_explicit_source_values_bind_only_to_literal_evidence_facts(tmp_path, monkeypatch):
    result, _, _ = run_case(tmp_path, monkeypatch,
        "Using the source values, find the internal Q equation and calculate Q.",
        "Q=B/C.\nB=12 kg\nC=3 kg")
    assert result.status == GoalStatus.ACHIEVED
    assert result.computations[0].output_manifest["OUT_RESULT"]["value"] == 4
    assert set(result.computations[0].input_fact_ids) == {"EFACT1", "EFACT2"}
