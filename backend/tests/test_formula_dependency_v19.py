"""Fresh synthetic dependency graphs; no benchmark or production KB is loaded."""

import asyncio
import json

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import GoalRunStatus, GoalStatus
from app.services.formula_dependency import resolve_formula_dependencies
from app.services.formula_source_registry import FormulaSourceRegistry
from app.services.formula_source_registry import source_contains_equation
from app.services.calculation_requirements import symbol_names
from app.services.compound_units import unit_factors
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_research_agent import EvidenceAccumulator
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_execution_state import GoalActionType, GoalExecutionState
from app.services.goal_evaluator import GoalEvaluator
from app.services.goal_intent import classify_goal_intent
from app.services.user_fact_registry import UserFactRegistry
from test_agent_reliability_v19_dev import (PassingEvaluator, SyntheticResearch,
                                            actions, no_synthesis, request)


def run_case(tmp_path, monkeypatch, text, source, on_progress=None):
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    research = SyntheticResearch([[(3, source)]])
    agent = GoalExecutionAgent(research, object(), evaluator=PassingEvaluator(), synthesizer=no_synthesis)
    req = request(text)
    return asyncio.run(agent.run("dependency-synthetic", req, on_progress=on_progress)), agent, req


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


def test_worked_constant_examples_are_not_dependency_producers():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "document": "guide.pdf",
                 "text": "API = (141.5 / SG) - 131.5. Sg = 141.5 / (131.5 + 38). SG = 0.835."}]
    target = next(row for row in FormulaSourceRegistry.from_evidence(evidence).records
                  if row.expression_candidate and row.expression_candidate.startswith("API ="))
    plan = resolve_formula_dependencies(target, evidence, UserFactRegistry(), [], [])
    assert plan.block_reason is None
    assert plan.missing_inputs == ["SG"]
    assert plan.next_formula is None


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


POROSITY_LAYOUT_SOURCE = (
    "Formation factor is obtained from measured porosity.\n"
    "F = a/fm\n"
    "where m is the cementation factor and a is a constant."
)


def test_sourced_porosity_layout_keeps_raw_span_and_rejects_tampering():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": POROSITY_LAYOUT_SOURCE}]
    record = FormulaSourceRegistry.from_evidence(evidence).records[0]
    assert record.raw_span == "F = a/fm"
    assert record.expression_candidate == "F = a/phi**m"
    assert record.required_variables == ["a", "m", "phi"]
    assert source_contains_equation(record, POROSITY_LAYOUT_SOURCE)
    assert not source_contains_equation(record.model_copy(update={"expression_candidate": "F=a/phi**(m+1)"}),
                                        POROSITY_LAYOUT_SOURCE)
    assert not source_contains_equation(record, "F = a/fm", record.expression_candidate)
    assert {"phi", "porosity"} <= symbol_names("φ")
    assert {"phi", "porosity"} <= symbol_names("phi")


def test_unrelated_fm_is_never_rewritten():
    for source in ("F=a/fm. fm is the measured frequency multiplier.",
                   "Formation factor is obtained from measured porosity.\nF=a/fm\n"
                   "where fm is the flow multiplier and m is the cementation factor and a is a constant.",
                   "F=a/fm. m is the cementation factor and a is a constant."):
        record = FormulaSourceRegistry.from_evidence([{
            "evidence_id": "KB1", "source_type": "knowledge_base", "text": source,
        }]).records[0]
        assert record.expression_candidate.replace(" ", "") == "F=a/fm"
        assert record.required_variables == ["a", "fm"]


@pytest.mark.parametrize("porosity_symbol", ["phi", "porosity", "φ"])
def test_porosity_layout_full_agent_calculates_without_fm_clarification(
        tmp_path, monkeypatch, porosity_symbol):
    result, _, _ = run_case(tmp_path, monkeypatch,
        f"{porosity_symbol}=0.22, a=1, m=2. Find the internal formation factor equation and calculate F.",
        POROSITY_LAYOUT_SOURCE)
    assert result.status == GoalStatus.ACHIEVED
    assert actions(result)[:5] == ["retrieve", "calculate", "verify", "synthesize", "stop"], [
        (row["action_type"], row.get("status"), row.get("details", {}).get("error"),
         row.get("details", {}).get("blocked_stage")) for row in result.action_history]
    assert not result.clarification_question
    assert "fm" not in " ".join(result.required_inputs).casefold()
    calc = result.computations[0]
    assert calc.validation_passed
    assert calc.output_manifest["OUT_RESULT"]["value"] == pytest.approx(20.66115702479339)
    assert calc.output_manifest["OUT_RESULT"]["unit"] == "dimensionless"
    assert calc.source_formula == "F = a/phi**m"
    assert calc.formula_source_ids == ["KB1"]


def test_literal_greek_phi_equation_uses_safe_alias():
    text = "Formation factor F=a/φ. Porosity φ is measured."
    record = FormulaSourceRegistry.from_evidence([{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": text,
    }]).records[0]
    assert record.raw_span == "F=a/φ"
    assert record.expression_candidate == "F=a/phi"
    assert source_contains_equation(record, text)


def test_layout_with_pdf_equation_caption_keeps_the_exact_anchor():
    text = ("F is the formation resistivity factor.\n"
            "F is usually obtained from the measured porosity of the formation.\n"
            "F  = a/fm\tEquation 2 Formation Resistivity Factor\n"
            "where\nm is the cementation factor,\na is a constant.")
    record = next(row for row in FormulaSourceRegistry.from_evidence([{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": text,
    }]).records if "fm" in row.raw_span)
    assert record.raw_span == "F  = a/fm"
    assert record.expression_candidate == "F  = a/phi**m"
    assert source_contains_equation(record, text)


def test_validated_formation_factor_feeds_downstream_formula(tmp_path, monkeypatch):
    result, _, _ = run_case(tmp_path, monkeypatch,
        "phi=0.22, a=1, m=2, V=3 kg. Find the internal Q equation and calculate Q.",
        "Q=F*V. V (kg).\n" + POROSITY_LAYOUT_SOURCE)
    assert result.status == GoalStatus.ACHIEVED
    assert [calc.output_manifest["OUT_RESULT"]["name"] for calc in result.computations] == ["F", "Q"]
    assert result.computations[0].output_manifest["OUT_RESULT"]["value"] == pytest.approx(20.66115702479339)
    assert result.computations[1].output_manifest["OUT_RESULT"]["value"] == pytest.approx(61.98347107438016)
    assert result.computations[1].validation_passed
    assert any(value.startswith("CALC1:") for value in result.computations[1].input_fact_ids)


ARCHIE_STACK_SOURCE = (
    "Saturation Determination\n"
    "All water saturation determinations are based on Archie's water saturation equation. "
    "The equation is:\n\n"
    "Sw\nn  =  F Rw\nRt\n\n"
    "Equation 1 Archies water saturation equation\nwhere\n"
    "Rw is the formation water resistivity,\n"
    "Rt is the true formation resistivity,\n"
    "F is the formation resistivity factor.\n"
    "F is usually obtained from the measured porosity of the formation.\n"
    "F = a/fm\nEquation 2 Formation Resistivity Factor\nwhere\n"
    "m is the cementation factor,\na is a constant."
)


def test_stacked_archie_span_reconstructs_without_false_n_equals_f():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": ARCHIE_STACK_SOURCE}]
    records = FormulaSourceRegistry.from_evidence(evidence).records
    assert not any(row.lhs == "n" for row in records)
    target = next(row for row in records if row.lhs == "Rt")
    assert target.raw_span == "Sw\nn  =  F Rw\nRt"
    assert target.source_equation == "Sw**n = (F*Rw)/Rt"
    assert target.formula_derivation == "algebraic_isolation"
    assert target.expression_candidate == "Rt = (F * Rw)/(Sw ** n)"
    assert source_contains_equation(target, ARCHIE_STACK_SOURCE)
    assert not source_contains_equation(
        target.model_copy(update={"expression_candidate": "Rt=F*Rw*Sw**n"}), ARCHIE_STACK_SOURCE)
    assert not source_contains_equation(
        target.model_copy(update={"source_equation": "Sw**n = Rt/(F*Rw)"}), ARCHIE_STACK_SOURCE)


def test_stacked_layout_without_context_or_with_conflict_is_not_rewritten():
    random = "Sw\nn = F Rw\nRt\nSome unrelated observations."
    conflicting = ARCHIE_STACK_SOURCE.replace(
        "Equation 1 Archies water saturation equation",
        "Sw**n = Rt/(F*Rw)\nEquation 1 Archies water saturation equation")
    for text in (random, conflicting):
        rows = FormulaSourceRegistry.from_evidence([{
            "evidence_id": "KB1", "source_type": "knowledge_base", "text": text,
        }]).records
        assert not any(row.lhs == "Rt" and row.formula_derivation for row in rows)
        assert not any(row.lhs == "n" for row in rows)


def test_resistivity_unit_stays_bounded():
    assert unit_factors("ohm-m") == {"ohm-m": 1}
    with pytest.raises(ValueError):
        unit_factors("ohm--m")


def test_stacked_archie_full_agent_chain(tmp_path, monkeypatch):
    progress = []
    def capture(row):
        progress.append((len(row.computations), row.telemetry.get("target_output_satisfied"),
                         list(row.telemetry.get("target_output_computation_ids", [])),
                         row.telemetry.get("target_calculation_ready")))
    result, _, _ = run_case(tmp_path, monkeypatch,
        "phi=0.22, Sw=0.35, Rw=0.08 ohm-m, a=1, m=2, n=2. "
        "Find the internal Archie equation and calculate Rt.",
        ARCHIE_STACK_SOURCE, on_progress=capture)
    assert result.status == GoalStatus.ACHIEVED
    assert actions(result) == ["retrieve", "calculate", "calculate", "verify", "synthesize", "stop"]
    assert (1, False, [], True) in progress
    assert (2, True, ["CALC2"], False) in progress
    assert result.state_history[1]["goal_achieved"] is False
    assert result.telemetry["required_target_outputs"] == ["Rt"]
    assert result.telemetry["target_output_satisfied"]
    assert result.telemetry["target_output_computation_ids"] == ["CALC2"]
    assert result.telemetry["target_formula_source_verified"]
    assert result.telemetry["target_completion_guard_checked"]
    assert result.telemetry["target_unit_propagation_result"] == "ohm-m"
    assert result.telemetry["formula_dependency_resolution_success"]
    assert not result.clarification_question
    assert "fm" not in " ".join(result.required_inputs).casefold()
    assert [calc.output_manifest["OUT_RESULT"]["name"] for calc in result.computations] == ["F", "Rt"]
    assert all(calc.validation_passed and calc.formula_source_ids == ["KB1"]
               for calc in result.computations)
    assert result.computations[0].output_manifest["OUT_RESULT"]["value"] == pytest.approx(20.66115702479339)
    target = result.computations[1]
    assert target.output_manifest["OUT_RESULT"]["value"] == pytest.approx(13.493000, rel=1e-4)
    assert target.output_manifest["OUT_RESULT"]["unit"] == "ohm-m"
    assert GoalExecutionAgent._derived(target)[0].unit == "ohm-m"
    assert "13.49" in result.final_answer and "ohm-m" in result.final_answer
    assert result.telemetry["formula_layout_normalization_used"]
    assert "stacked_fraction" in result.telemetry["formula_layout_transformations"]
    assert result.telemetry["unit_propagation_success"]
    assert result.telemetry["unit_propagation_result"] == "ohm-m"
    assert result.telemetry["unit_propagation_inputs"]["Rw"] == "ohm-m"
    assert result.telemetry["unit_propagation_inputs"]["F"] == "dimensionless"
    assert target.raw_formula_span == "Sw\nn  =  F Rw\nRt"
    assert target.source_equation == "Sw**n = (F*Rw)/Rt"
    assert target.formula_derivation == "algebraic_isolation"
    assert any(value.startswith("CALC1:") for value in target.input_fact_ids)


def test_intermediate_output_cannot_promote_a_false_success(tmp_path, monkeypatch):
    result, _, req = run_case(tmp_path, monkeypatch,
        "A=2 ft; B=12 kg; C=3 kg. Find the internal Z equation and calculate Z.",
        "Z=Y*A. Y=B/C. A (ft); B (kg); C (kg).")
    assert result.status == GoalStatus.ACHIEVED
    assert [row["name"] for calc in result.computations for row in calc.output_manifest.values()] == ["Y", "Z"]
    assert result.state_history[1]["goal_achieved"] is False
    evaluator = asyncio.run(PassingEvaluator().evaluate(
        req, req.success_criteria, "Y is computed", [], {}, computations=result.computations[:1]))
    assert evaluator.achieved and evaluator.coverage == 1
    guarded = GoalExecutionAgent._guard_target_evaluation(evaluator, req.success_criteria, False)
    assert not guarded.achieved and guarded.coverage < 1
    assert all(item.status.value != "met" for item in guarded.criteria)
    assert result.telemetry["required_target_outputs"] == ["Z"]
    assert result.telemetry["target_output_computation_ids"] == ["CALC2"]


def test_iteration_budget_after_dependency_is_not_goal_success(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    agent = GoalExecutionAgent(SyntheticResearch([[(3, "Z=Y*A. Y=B/C. A (ft); B (kg); C (kg).")]]),
                               object(), evaluator=PassingEvaluator(), synthesizer=no_synthesis)
    req = request("A=2 ft; B=12 kg; C=3 kg. Find the internal Z equation and calculate Z.",
                  max_iterations=2)
    result = asyncio.run(agent.run("dependency-budget", req))
    assert [row["name"] for calc in result.computations for row in calc.output_manifest.values()] == ["Y"]
    assert actions(result) == ["retrieve", "calculate", "stop"]
    assert result.status != GoalStatus.ACHIEVED
    assert not result.telemetry["target_output_satisfied"]
    assert not result.telemetry["formula_dependency_resolution_success"]


def test_ready_target_takes_priority_over_verify_after_intermediate_calc():
    req = request("A=2 ft; B=12 kg; C=3 kg. Find the internal Z equation and calculate Z.")
    req.allow_python_execution = req.python_execution_approved = True
    state = GoalExecutionState.from_criteria("target-priority", req.goal or req.topic, req.success_criteria)
    state.computation_ids = ["CALC1"]
    selected = GoalActionPlanner.select(
        req, state, user_fact_ids=["USERF1", "CALC1:OUT_RESULT"], evidence_fact_ids=[],
        formula_ready=True, formula_id="FORMULA_TARGET", simulation_spec=None,
        formula_inputs_ready=True, formula_source_verified=True,
        target_output_satisfied=False,
        intent=classify_goal_intent(req, has_user_facts=True))
    assert selected.action_type == GoalActionType.CALCULATE
    assert selected.formula_id == "FORMULA_TARGET"


def test_target_requires_pinned_equation_and_source(tmp_path, monkeypatch):
    text = "A=2 ft; B=12 kg; C=3 kg. Find the internal Z equation and calculate Z."
    result, _, req = run_case(tmp_path, monkeypatch, text,
        "Z=Y*A. Y=B/C. A (ft); B (kg); C (kg).")
    evidence = GoalExecutionAgent._evidence(
        EvidenceAccumulator.restore(result.internal_sources, [], []),
        UserFactRegistry.from_topic(text), result.computations, None, "USERF4")
    target = result.telemetry["formula_dependency_target"]
    assert [row.computation_id for row in GoalExecutionAgent._target_calculations(
        result.computations, ["Z"], target, evidence, req.topic)] == ["CALC2"]
    assert not GoalExecutionAgent._target_calculations(
        result.computations, ["Z"], {**target, "equation_ast": "different"}, evidence, req.topic)
    assert not GoalExecutionAgent._target_calculations(
        result.computations, ["Z"], {**target, "source_id": "KB999"}, evidence, req.topic)


@pytest.mark.parametrize("text,target", [
    ("Find the internal equation and calculate Rt.", "Rt"),
    ("내부 관계식으로 Rt를 계산해줘.", "Rt"),
    ("비중 0.918의 API gravity를 내부 교재 식으로 계산해줘.", "API_gravity"),
])
def test_calculation_criteria_name_requested_target(text, target):
    req = request(text)
    assert GoalExecutionAgent._requested_target(req) == target
    criteria = GoalExecutionAgent._explicit_numeric_criteria(req, UserFactRegistry.from_topic(text), None)
    display_target = "API" if target == "API_gravity" else target
    assert criteria and all(display_target in item.description for item in criteria)


def test_unrelated_layout_ambiguity_does_not_block_verified_target(tmp_path, monkeypatch):
    result, _, _ = run_case(tmp_path, monkeypatch,
        "A=2 ft; B=3 ft. Find the internal Q equation and calculate Q.",
        "Q=A+B. A (ft); B (ft).\nV = A B\nC")
    assert result.status == GoalStatus.ACHIEVED
    assert result.telemetry["formula_layout_ambiguous"]
    assert not result.telemetry["target_formula_layout_ambiguous"]
    assert result.telemetry["target_formula_source_verified"]


def test_evaluator_prompt_tolerates_evidence_without_locator():
    req = request("Find the sourced relation and calculate Rt.")
    prompt = GoalEvaluator._prompt(req, req.success_criteria, "", [
        {"evidence_id": "EFACT1", "source_type": "knowledge_base", "text": "Rw=0.08 ohm-m"},
        {"evidence_id": "USERF1", "source_type": "user_fact", "text": "Sw=0.35"},
    ])
    rows = json.loads(prompt)["untrusted_evidence"]
    assert [row["locator"] for row in rows] == [None, None]


def test_stacked_archie_chain_verifies_with_derived_evidence(tmp_path, monkeypatch):
    class StructuredEvaluatorModel:
        def __init__(self):
            self.evidence = []

        async def chat_structured(self, messages, _schema, **_kwargs):
            self.evidence = json.loads(messages[-1]["content"])["untrusted_evidence"]
            return json.dumps({"criteria": [{"criterion_id": "C1", "status": "met",
                                     "reason": "Validated sourced calculation",
                                     "supporting_evidence": ["KB1", "CALC2"]}],
                               "expected_result_status": "not_provided", "gaps": [],
                               "next_research_need": None, "goal_conflicts_with_evidence": False})

    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    model = StructuredEvaluatorModel()
    agent = GoalExecutionAgent(SyntheticResearch([[(3, ARCHIE_STACK_SOURCE)]]), object(),
                               evaluator=GoalEvaluator(model), synthesizer=no_synthesis)
    text = ("phi=0.22, Sw=0.35, Rw=0.08 ohm-m, a=1, m=2, n=2. "
            "Find the internal Archie equation and calculate Rt.")
    result = asyncio.run(agent.run("archie-verify-derived", request(text)))

    assert result.status == GoalStatus.ACHIEVED
    assert actions(result) == ["retrieve", "calculate", "calculate", "verify", "synthesize", "stop"]
    assert len(result.computations) == 2
    assert all(calc.validation_passed for calc in result.computations)
    assert any(value.startswith("CALC1:") for value in result.computations[1].input_fact_ids)
    assert result.computations[0].formula_source_ids == ["KB1"]
    assert result.computations[1].formula_source_ids == ["KB1"]
    assert result.computations[1].output_manifest["OUT_RESULT"]["value"] == pytest.approx(13.493, rel=1e-4)
    assert "13.49" in result.final_answer and "ohm-m" in result.final_answer
    assert "[CALC1]" in result.final_answer and "[CALC2]" in result.final_answer
    assert {"CALC1", "CALC2"}.issubset({row["evidence_id"] for row in model.evidence})
    assert any(row["evidence_id"] == "CALC1:OUT_RESULT" and
               row["locator"] == "CALC1:OUT_RESULT" for row in model.evidence)
    assert all("locator" in row for row in model.evidence)
