"""Fresh synthetic V22 routing, binding, provenance and liveness cases."""

import asyncio
import math
import re

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import GoalResearchRequest
from app.services.calculation_request_ir import OPERATIONS
from app.services.calculation_requirements import (infer_dimensionless, formula_target_contract,
                                                   rank_formula_candidates)
from app.services.formula_layout_normalizer import normalize_extracted_equation
from app.services.formula_source_registry import FormulaSourceRegistry
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_execution_state import GoalActionType, GoalExecutionState, RequiredGoal
from app.services.goal_intent import GoalIntentKind, classify_goal_intent
from app.services.goal_simulation import (direct_operation_operands, direct_readiness,
                                          formula_input_readiness, run_direct_arithmetic)
from app.services.required_goals import parse_required_goals
from app.services.task_actionability import assess_actionability, formula_contract
from app.services.user_fact_registry import UserFactRegistry, validate_original_operands
from test_goal_execution_v8 import NoResearch, PassingEvaluator, StaticResearch


def request(text):
    return GoalResearchRequest(topic=text, goal=text, allow_python_execution=True,
                               python_execution_approved=True,
                               execution_mode="autonomous_goal_execution")


def operations(text):
    found = [name for name, pattern in OPERATIONS.items() if re.search(pattern, text, re.I)]
    for dominant, subsumed in (("weighted_average", "mean"), ("multi_difference", "difference"),
                               ("amount_per_time", "unit_conversion"),
                               ("percentage_decrease", "percent_change"),
                               ("combined_rate", "sum")):
        if dominant in found and subsumed in found:
            found.remove(subsumed)
    if "amount_per_time" in found and not {"amount", "duration"} <= {
            row.name for row in UserFactRegistry.from_topic(text).records}:
        found.remove("amount_per_time")
    return found


@pytest.mark.parametrize("text", [
    "A=41 psi, B=25 psi. Calculate the difference A-B.",
    "A=15 bbl, B=28 bbl. Calculate the sum.",
    "A=17 stb/d, B=22 stb/d. Calculate the mean.",
    "A=21 kg, B=7 kg. Calculate the ratio A/B.",
    "A=33 m, B=12 m. Calculate the maximum.",
    "A=18 psi, B=5 psi. Calculate the minimum.",
    "A=9 bbl, B=6 bbl. Calculate the product.",
    "A=99 psi, B=33 psi. Calculate the quotient A/B.",
    "A=83 stb/d, B=11 stb/d. Calculate the total.",
    "A=17 bbl, B=19 bbl. Calculate the average.",
    "A=45 psi, B=23 psi. Calculate the range.",
    "A=28 stb/d, B=54 stb/d. Calculate the ranking.",
])
def test_fully_specified_direct_routing(text):
    facts = UserFactRegistry.from_topic(text)
    assert len(facts.records) == 2
    assert classify_goal_intent(request(text), has_user_facts=True).kind == GoalIntentKind.DIRECT_CALC
    assert operations(text)


@pytest.mark.parametrize("weights,values,unit", [
    ((83, 117, 94), (10.2, 10.8, 11.1), "ppg"),
    ((25, 42, 33), (8.7, 9.0, 9.4), "ppg"),
    ((41, 35, 29), (2.1, 2.4, 2.8), "kg/m3"),
    ((9, 12, 15), (1.2, 1.5, 1.8), "ppg"),
    ((123, 77, 55), (9.5, 9.8, 10.3), "ppg"),
    ((11, 19, 27), (6.4, 6.8, 7.1), "ppg"),
])
def test_weighted_pair_literals_survive_numeric_list_detection(weights, values, unit):
    text = ", ".join(f"{weight} bbl at {value} {unit}" for weight, value in zip(weights, values))
    text += ". Calculate weighted average density."
    facts = UserFactRegistry.from_topic(text)
    assert len(facts.records) == 6
    assert [(facts.records[i].value, facts.records[i + 1].value)
            for i in (0, 2, 4)] == list(zip(weights, values))
    validate_original_operands(text, facts, list_operation=True)
    assert direct_readiness(text, facts, ["weighted_average"]) == []


@pytest.mark.parametrize("text,initial,final", [
    ("Rate falls from 914 to 782 stb/d. Calculate percentage decline.", 914, 782),
    ("Rate drops from 527 to 391 stb/d. Calculate percentage decrease.", 527, 391),
    ("Pressure declines from 2610 to 2320 psi. Calculate percentage decline.", 2610, 2320),
    ("Rate rises from 75 to 105 bbl/d. Calculate percentage increase.", 75, 105),
    ("Pressure increases from 1500 to 1800 psi. Calculate percentage increase.", 1500, 1800),
    ("Rate changes from 120 to 132 stb/d. Calculate percent change.", 120, 132),
    ("압력이 950 psi에서 810 psi로 감소했다. 감소율을 계산해줘.", 950, 810),
    ("초기 압력 1760 psi, 최종 압력 1690 psi. 감소율을 계산해줘.", 1760, 1690),
])
def test_temporal_roles_are_bound_from_language(text, initial, final):
    facts = UserFactRegistry.from_topic(text)
    roles = {row.semantic_role: row.value for row in facts.records}
    assert roles["initial"] == initial
    assert roles["final"] == final
    assert classify_goal_intent(request(text), has_user_facts=True).kind == GoalIntentKind.DIRECT_CALC


@pytest.mark.parametrize("a,b,c", [(2810, 2450, 2600), (1900, 1770, 1845),
                                     (3500, 3110, 3290), (980, 760, 870), (4100, 3900, 3980)])
def test_three_temporal_states_define_two_differences(a, b, c):
    text = f"Pressure starts at {a} psi, falls to {b} psi, recovers to {c} psi. Calculate drawdown and recovery."
    facts = UserFactRegistry.from_topic(text)
    assert {row.name: row.value for row in facts.records} == {
        "start": a, "trough": b, "recovered": c}
    assert direct_readiness(text, facts, ["multi_difference"]) == []


@pytest.mark.parametrize("text,left,right", [
    ("Gas 2550 scf and oil 85 stb. Calculate gas-to-oil ratio.", "gas", "oil"),
    ("Water 165 bbl and oil 55 stb. Calculate water-to-oil ratio.", "water", "oil"),
    ("Produced 120 bbl and injected 240 bbl. Calculate produced-to-injected ratio.", "produced", "injected"),
    ("A=42 psi, B=14 psi. Calculate A/B ratio.", "A", "B"),
    ("X=64 kg, Y=16 kg. Calculate X-to-Y ratio.", "X", "Y"),
])
def test_named_ratio_defines_numerator_and_denominator(text, left, right):
    facts = UserFactRegistry.from_topic(text)
    selected, missing = direct_operation_operands(text, facts, ["ratio"])
    assert not missing
    assert selected["ratio"] == (left, right)


@pytest.mark.parametrize("amount,unit,duration,duration_unit,target", [
    (735, "bbl", 15, "hours", "bbl/day"),
    (126, "m3", 7, "hours", "m3/day"),
    (93, "stb", 3, "days", "stb/h"),
    (48, "scf", 30, "minutes", "scf/hour"),
])
def test_amount_duration_is_direct_rate(amount, unit, duration, duration_unit, target):
    text = f"{amount} {unit} collected over {duration} {duration_unit}. Give {target}."
    facts = UserFactRegistry.from_topic(text)
    assert {row.name for row in facts.records} == {"amount", "duration"}
    assert operations(text) == ["amount_per_time"]
    assert direct_readiness(text, facts, ["amount_per_time"]) == []


@pytest.mark.parametrize("values", [(31, 47, 22), (115, 62, 99), (7, 13, 19), (205, 311, 88)])
def test_same_unit_rates_are_direct_combined_sum(values):
    text = ", ".join(f"{name}={value} stb/d" for name, value in zip("ABC", values))
    text += ". Calculate combined rate."
    facts = UserFactRegistry.from_topic(text)
    assert len(facts.records) == 3
    assert direct_readiness(text, facts, ["combined_rate"]) == []


@pytest.mark.parametrize("text,name,value", [
    ("Pe=2370 psi", "Pe", 2370),
    ("external pressure Pe=2210 psi", "Pe", 2210),
    ("grain diameter Dp=0.00031 m", "Dp", 0.00031),
    ("Sor=0.21", "Sor", 0.21),
    ("connate saturation Swc=0.18", "Swc", 0.18),
    ("ρe=2.36 g/cm3", "rhoe", 2.36),
    ("φ=0.24", "phi", 0.24),
    ("μ=1.7 cP", "mu", 1.7),
])
def test_explicit_engineering_symbol_keeps_literal_provenance(text, name, value):
    facts = UserFactRegistry.from_topic(text)
    assert len(facts.records) == 1
    assert facts.records[0].name == name
    assert facts.records[0].value == value
    assert facts.records[0].extraction_method == "explicit_assignment"
    validate_original_operands(text, facts)


@pytest.mark.parametrize("symbol,definition", [
    ("Sor", "Sor is residual oil saturation."),
    ("Swc", "Swc denotes connate water saturation."),
    ("c", "c represents the coefficient."),
    ("x", "x is the fraction."),
])
def test_source_defined_dimensionless_variable_does_not_need_written_unit(symbol, definition):
    assert infer_dimensionless(symbol, definition)["dimension"] == "dimensionless"


@pytest.mark.parametrize("kind,ready_flag", [
    (GoalIntentKind.DIRECT_CALC, "direct_ready"),
    (GoalIntentKind.USER_FORMULA_CALC, "user_formula_ready"),
    (GoalIntentKind.KB_FORMULA_CALC, "kb_formula_ready"),
    (GoalIntentKind.DIRECT_CALC, "direct_ready"),
    (GoalIntentKind.USER_FORMULA_CALC, "user_formula_ready"),
    (GoalIntentKind.KB_FORMULA_CALC, "kb_formula_ready"),
    (GoalIntentKind.DIRECT_CALC, "direct_ready"),
    (GoalIntentKind.KB_FORMULA_CALC, "kb_formula_ready"),
])
def test_ready_required_work_forbids_stop(kind, ready_flag):
    state = GoalExecutionState(run_id="SYNTHETIC", goal="complete task", criteria=[],
                               required_goals=[RequiredGoal(goal_id="G1", goal_type="numeric_calculation",
                                                            semantic_target="result", source_text_span="result")],
                               no_progress_count=9)
    assessment = assess_actionability(state, kind, **{ready_flag: True})
    assert assessment.calculation_ready
    assert not assessment.safe_stop_allowed
    assert not assessment.clarification_allowed
    assert assessment.executable_goal_ids == ("G1",)


@pytest.mark.parametrize("operator", ["+", "-", "/", "*", "×"])
def test_clipped_equation_is_not_a_verified_source(operator):
    text = f"The relation is\nY = A\n{operator} B\nwhere A and B are measured."
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "document": "synthetic",
                 "page": 3, "text": text}]
    records = FormulaSourceRegistry.from_evidence(evidence).records
    assert not any(row.lhs == "Y" and row.expression_candidate == "Y = A" for row in records)


@pytest.mark.parametrize("text", [
    "A=3 psi, B=7 bbl. Calculate A/B ratio.",
    "A=4 kg, B=9 psi. Calculate A/B ratio.",
    "A=11 psi, B=2 m. Calculate A/B ratio.",
    "A=5 bbl, B=2 kW. Calculate A/B ratio.",
    "A=8 psi, B=6 stb. Calculate A/B ratio.",
    "A=2 kg, B=3 L. Calculate A/B ratio.",
    "A=12 ft, B=4 psi. Calculate A/B ratio.",
    "A=14 kPa, B=5 bbl. Calculate A/B ratio.",
])
def test_unnamed_heterogeneous_ratio_is_not_guessed(text):
    orders, missing = direct_operation_operands(text, UserFactRegistry.from_topic(text), ["ratio"])
    assert not orders
    assert missing


@pytest.mark.parametrize("text,operation,expected,unit", [
    ("83 bbl at 9.3 ppg, 117 bbl at 10.4 ppg, 100 bbl at 11.1 ppg. Calculate weighted average density.",
     "weighted_average", (83*9.3 + 117*10.4 + 100*11.1)/300, "ppg"),
    ("Rate falls from 914 to 782 stb/d. Calculate percentage decline.",
     "percentage_decrease", (914-782)/914*100, "%"),
    ("Gas 2550 scf and oil 85 stb. Calculate gas-to-oil ratio.", "ratio", 30, "scf/stb"),
    ("735 bbl collected over 15 hours. Give bbl/day.", "amount_per_time", 1176, "bbl/d"),
    ("Pressure starts at 2810 psi, falls to 2450 psi, recovers to 2600 psi. Calculate drawdown and recovery.",
     "multi_difference", 360, "psi"),
    ("A=31 stb/d, B=47 stb/d, C=22 stb/d. Calculate combined rate.", "combined_rate", 100, "stb/d"),
])
def test_real_sandbox_executes_fresh_direct_tasks(text, operation, expected, unit, tmp_path):
    facts = UserFactRegistry.from_topic(text)
    orders, missing = direct_operation_operands(text, facts, [operation])
    assert not missing
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    result = asyncio.run(run_direct_arithmetic(settings, request(text), "SYNTHETIC",
                                               facts, [operation], "CALC1", orders, original_text=text))
    assert result.validation_passed and result.contract_validation_passed
    row = result.output_manifest[f"OUT_{'drawdown' if operation == 'multi_difference' else operation}"]
    assert math.isclose(row["value"], expected, rel_tol=1e-9)
    assert row["unit"] == unit
    assert len(result.input_fact_ids) == len(facts.records)


@pytest.mark.parametrize("text,output_name", [
    ("83 bbl at 9.3 ppg, 117 bbl at 10.4 ppg, 100 bbl at 11.1 ppg. Calculate weighted average density.",
     "weighted_average"),
    ("Rate falls from 914 to 782 stb/d. Calculate percentage decline.", "percentage_decrease"),
    ("Gas 2550 scf and oil 85 stb. Calculate gas-to-oil ratio.", "ratio"),
    ("735 bbl collected over 15 hours. Give bbl/day.", "amount_per_time"),
    ("Pressure starts at 2810 psi, falls to 2450 psi, recovers to 2600 psi. Calculate drawdown and recovery.",
     "drawdown"),
    ("A=31 stb/d, B=47 stb/d, C=22 stb/d. Calculate combined rate.", "combined_rate"),
])
def test_full_agent_completes_actionable_direct_task_without_retrieval(text, output_name,
                                                                        tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    req = request(text)
    req.max_iterations = 6
    result = asyncio.run(GoalExecutionAgent(NoResearch(), object(), evaluator=PassingEvaluator())
                         .run("GR-V22-DIRECT", req))
    assert result.run_status.value == "completed", result.final_answer
    assert [row["action_type"] for row in result.action_history] == [
        "calculate", "verify", "synthesize", "stop"]
    assert result.computations[0].validation_passed
    assert f"OUT_{output_name}" in result.computations[0].output_manifest
    assert result.python_calls_total == 1


@pytest.mark.parametrize("a,b", [(4, 5), (7, 11), (13, 17), (22, 9), (8, 14), (19, 6)])
def test_missing_input_resume_reuses_run_and_executes_once(a, b, tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    text = f"A={a} psi. Find Y from the internal formula and calculate it."
    req = request(text)
    req.max_iterations = 8
    agent = GoalExecutionAgent(StaticResearch("Y = A + B. A and B are pressures in psi."),
                               object(), evaluator=PassingEvaluator())
    waiting = asyncio.run(agent.run("GR-V22-RESUME", req))
    assert waiting.run_status.value == "waiting_for_user_input"
    assert "B" in (waiting.clarification_question or "")
    assert waiting.python_calls_total == 0
    checkpoint = (waiting.resume_checkpoint.model_copy(deep=True)
                  if hasattr(waiting.resume_checkpoint, "model_copy")
                  else dict(waiting.resume_checkpoint))
    checkpoint["user_replies"] = [f"B={b} psi"]
    completed = asyncio.run(agent.run(waiting.run_id, req, resume_state=checkpoint,
                                      resume_result=waiting))
    assert completed.run_id == waiting.run_id
    assert completed.run_status.value == "completed", completed.final_answer
    assert [row["action_type"] for row in completed.action_history][-4:] == [
        "calculate", "verify", "synthesize", "stop"]
    assert completed.computations[0].validation_passed
    assert math.isclose(completed.computations[0].output_manifest["OUT_RESULT"]["value"], a + b)
    assert completed.python_calls_total == 1


@pytest.mark.parametrize("a,b", [(3, 9), (5, 12), (7, 18), (11, 6),
                                    (13, 2), (17, 21), (19, 23), (29, 31)])
def test_existing_exact_user_facts_reject_redundant_clarification(a, b):
    facts = UserFactRegistry.from_topic(f"A={a} psi, B={b} psi")
    bindings, missing = formula_input_readiness("Y = A + B", facts)
    assert not missing
    assert {name: row.value for name, row in bindings.items()} == {"A": a, "B": b}
    state = GoalExecutionState(run_id="NO-QUESTION", goal="Y", criteria=[],
                               required_goals=[RequiredGoal(goal_id="G1", goal_type="numeric_calculation",
                                                            semantic_target="Y", source_text_span="Y")])
    assessment = assess_actionability(state, GoalIntentKind.KB_FORMULA_CALC,
                                      kb_formula_ready=True, missing_user_inputs=missing)
    assert not assessment.clarification_allowed


@pytest.mark.parametrize("filler", [0, 1, 2, 3, 4, 5, 6, 7])
def test_verified_formula_overrides_no_progress_stop(filler):
    state = GoalExecutionState(run_id=f"LIVENESS-{filler}", goal="calculate Y", criteria=[],
                               no_progress_count=10)
    req = request("A=8 psi. Calculate Y from the internal formula.")
    intent = classify_goal_intent(req, has_user_facts=True)
    action = GoalActionPlanner.select(req, state, user_fact_ids=["USERF1"],
                                      formula_ready=True, formula_id="FORMULA1",
                                      formula_inputs_ready=True, formula_source_verified=True,
                                      simulation_spec=None, intent=intent,
                                      python_calls_used=0)
    assert action.action_type == GoalActionType.CALCULATE


@pytest.mark.parametrize("first,second", [("A", "B"), ("X", "Y"), ("P", "Q"),
                                            ("inlet", "outlet"), ("left", "right"),
                                            ("start", "end")])
def test_remaining_required_goal_is_not_silently_dropped(first, second):
    state = GoalExecutionState(run_id="MULTI", goal="two outputs", criteria=[],
                               required_goals=[
                                   RequiredGoal(goal_id="G1", goal_type="numeric_calculation",
                                                semantic_target=first, source_text_span=first, status="MET"),
                                   RequiredGoal(goal_id="G2", goal_type="numeric_calculation",
                                                semantic_target=second, source_text_span=second, status="UNMET"),
                               ], no_progress_count=5)
    assessment = assess_actionability(state, GoalIntentKind.KB_FORMULA_CALC,
                                      kb_formula_ready=True)
    assert assessment.remaining_required_goal_ids == ("G2",)
    assert assessment.executable_goal_ids == ("G2",)
    assert not assessment.safe_stop_allowed


def test_past_tense_decline_is_direct_and_binds_temporal_roles():
    text = "A line rate fell from 914 to 781 stb/d. Calculate percentage decrease."
    facts = UserFactRegistry.from_topic(text)
    assert {row.semantic_role for row in facts.records} >= {"initial", "final"}
    assert classify_goal_intent(request(text), has_user_facts=True).kind == GoalIntentKind.DIRECT_CALC
    assert direct_readiness(text, facts, ["percentage_decrease"]) == []


def test_received_amount_over_duration_needs_no_new_input():
    text = "A vessel received 540 bbl over 9 hours. Give bbl/day."
    facts = UserFactRegistry.from_topic(text)
    assert {row.name for row in facts.records} == {"amount", "duration"}
    assert operations(text) == ["amount_per_time"]
    assert direct_readiness(text, facts, ["amount_per_time"]) == []


def test_direct_multi_output_goals_match_manifest_names():
    text = "A=32 psi, B=54 psi, C=48 psi. Report the average and the highest labeled case."
    goals = parse_required_goals(request(text), "direct_calc", None)
    assert {goal.semantic_target for goal in goals} == {"mean", "maximum", "ranking"}


def test_missing_named_operand_requests_value_not_order():
    text = "A=26 psi. Calculate the difference A-B."
    orders, missing = direct_operation_operands(text, UserFactRegistry.from_topic(text), ["difference"])
    assert not orders and missing == ["B 값"]


def test_worked_example_validates_pdf_greek_exponent_without_changing_raw():
    raw = "F = 1/φ2"
    source = "Formation factor relation: F = 1/φ2. Thus, for φ = 10%, F = 100."
    normalized = normalize_extracted_equation(raw, source)
    assert normalized.raw_span == raw
    assert normalized.normalized_expression == "F = 1/(phi**2)"
    assert normalized.transformations == ("worked_example_validated_exponent",)


@pytest.mark.parametrize("source", [
    "F = 1/φ2. No worked example is given.",
    "F = 1/φ2. Thus, for φ = 10%, F = 5.",
])
def test_unsupported_pdf_exponent_interpretation_is_rejected(source):
    assert normalize_extracted_equation("F = 1/φ2", source).normalized_expression is None


def test_formula_target_parses_calculate_symbol_when_clause():
    contract = formula_target_contract("Calculate F when phi=0.18, a=1 and m=2.", ["phi", "a", "m"])
    assert contract.requested_quantity == "F"


def test_sourced_formula_uses_supplied_symbols_instead_of_shortcut():
    evidence = [
        {"evidence_id": "KB1", "source_type": "knowledge_base", "text":
         "A special case uses F = 1/phi**2."},
        {"evidence_id": "KB2", "source_type": "knowledge_base", "text":
         "The general relation is F = a/phi**m, where m is a measured exponent and a a coefficient."},
    ]
    text = "Calculate F when phi=0.19, a=1.08 and m=1.9 using the source equation."
    selected, _ = rank_formula_candidates(evidence, text, ["phi", "a", "m"],
                                          target_contract=formula_target_contract(text, ["phi", "a", "m"]))
    assert selected and selected.source_id == "KB2"


def test_quoted_equation_does_not_override_explicit_internal_source_request():
    text = "Locate the internal Y = A + B relation, then calculate Y for A=7 psi and B=9 psi."
    assert classify_goal_intent(request(text), has_user_facts=True).kind == GoalIntentKind.KB_FORMULA_CALC


def test_formula_contract_uses_only_literal_source_definition_and_unit():
    source = "Y = A + B.\nA (psi) is the inlet pressure.\nB is the outlet pressure."
    formula = next(row for row in FormulaSourceRegistry.from_evidence([
        {"evidence_id": "KB1", "source_type": "knowledge_base", "text": source}
    ]).records if row.expression_candidate == "Y = A + B")
    facts = UserFactRegistry.from_topic("A=12 psi, B=5 psi")
    contract = formula_contract(formula, {row.name: row for row in facts.records}, [],
                                source_verified=True, dimension_valid=True, source_text=source)
    assert contract and contract.executable
    assert contract.rhs_variables[0].source_unit == "psi"
    assert contract.rhs_variables[1].source_definition == "B is the outlet pressure"


def test_normalized_pdf_formula_keeps_literal_calculation_span(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    source = ("Formation factor is obtained from measured porosity.\n"
              "F = a/fm\nwhere m is the cementation factor and a is a constant.")
    req = request("phi=0.23, a=1, m=2. Find the internal formation-factor relation and compute F.")
    req.max_iterations = 8
    result = asyncio.run(GoalExecutionAgent(StaticResearch(source), object(),
                                            evaluator=PassingEvaluator()).run("V22-RAW-SPAN", req))
    assert result.run_status.value == "completed", result.final_answer
    assert result.computations[0].raw_formula_span == "F = a/fm"
    assert "phi**m" in result.computations[0].normalized_formula
