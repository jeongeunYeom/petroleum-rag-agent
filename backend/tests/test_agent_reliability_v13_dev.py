"""Independent synthetic development cases for routing and literal user facts.

These are regression probes, not a final or held-out evaluation set.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import GoalResearchRequest
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_execution_state import GoalActionType, GoalExecutionState
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.formula_source_registry import FormulaSourceRegistry, source_contains_equation
from app.services.calculation_requirements import rank_formula_candidates
from app.services.goal_intent import GoalIntentKind, classify_goal_intent
from app.services.citation_semantics import ground_research_claims
from app.services.goal_simulation import (run_direct_arithmetic, run_user_formula_calculation,
                                          user_formula_bindings)
from app.services.premise_grounding import assess_premise
from app.services.user_fact_registry import UserFactRegistry


DEV_CASES = json.loads((Path(__file__).resolve().parents[2] / "evaluation" / "dev" /
                        "agent_reliability_v13_dev.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", DEV_CASES, ids=[case["id"] for case in DEV_CASES])
def test_open_development_set_routes_to_first_safe_action(case):
    text = case["message"]
    request = GoalResearchRequest(topic=text, goal=text, execution_mode="autonomous_goal_execution",
                                  allow_python_execution=True, python_execution_approved=True)
    facts = UserFactRegistry.from_topic(text)
    intent = classify_goal_intent(request, has_user_facts=bool(facts.records))
    assert intent.kind.value == case["expected_intent"]
    missing = (user_formula_bindings(intent.user_equation, facts)[1]
               if intent.kind == GoalIntentKind.USER_FORMULA_CALC else [])
    state = GoalExecutionState.from_criteria("DEV-V13", text, [])
    action = GoalActionPlanner.select(
        request, state, user_fact_ids=[row.fact_id for row in facts.records],
        formula_ready=False, formula_inputs_ready=not missing,
        simulation_spec=None, intent=intent)
    assert action.action_type.value == case["expected_first_action"]


@pytest.mark.parametrize("text,kind", [
    ("Valve readings A=18 psi and B=42 psi. What is the average?", GoalIntentKind.DIRECT_CALC),
    ("밸브 측정값 A=18 psi, B=42 psi의 평균은 얼마야?", GoalIntentKind.DIRECT_CALC),
    ("Q=36 bbl/d, t=4 d. total=Q*t. What is total?", GoalIntentKind.USER_FORMULA_CALC),
    ("q=36 bbl/d, t=4 d. total=q*t. 이 식의 결과는 얼마야?", GoalIntentKind.USER_FORMULA_CALC),
    ("Find the equation for hydrostatic pressure in the internal manual and calculate it.", GoalIntentKind.KB_FORMULA_CALC),
    ("Explain why a positive skin factor matters in a pressure transient test.", GoalIntentKind.KNOWLEDGE_QA),
    ("What is average porosity in a reservoir?", GoalIntentKind.KNOWLEDGE_QA),
    ("What does total porosity mean?", GoalIntentKind.KNOWLEDGE_QA),
])
def test_independent_intent_routes(text: str, kind: GoalIntentKind):
    request = GoalResearchRequest(topic=text, goal=text)
    facts = UserFactRegistry.from_topic(text)
    assert classify_goal_intent(request, has_user_facts=bool(facts.records)).kind == kind


@pytest.mark.parametrize("rate,duration", [(36, 4), (52, 7), (71, 3)])
@pytest.mark.parametrize("rate_unit,time_unit", [("bbl/d", "d"), ("stb/h", "h")])
@pytest.mark.parametrize("reversed_order", [False, True])
def test_user_formula_binds_literal_value_and_unit_pairs(
        rate: int, duration: int, rate_unit: str, time_unit: str, reversed_order: bool):
    inputs = [f"Q={rate} {rate_unit}", f"t={duration} {time_unit}"]
    if reversed_order:
        inputs.reverse()
    text = ", ".join(inputs) + ". total=Q*t. What is total?"
    facts = UserFactRegistry.from_topic(text)
    bound, missing = user_formula_bindings("total=Q*t", facts)
    assert missing == []
    assert {name: (item.value, item.unit) for name, item in bound.items()} == {
        "Q": (rate, rate_unit), "t": (duration, time_unit)}
    assert all(item.source_span in text for item in bound.values())


def test_formula_binds_variable_after_prose_label_without_borrowing_distractor():
    text = "Pressure p_in=155 psi, p_out=120 psi; year=2022. delta=p_in-p_out. Determine delta."
    facts = UserFactRegistry.from_topic(text)
    bound, missing = user_formula_bindings("delta=p_in-p_out", facts)
    assert missing == []
    assert {name: item.value for name, item in bound.items()} == {"p_in": 155, "p_out": 120}
    assert all(item.name != "year" for item in bound.values())


def test_english_entity_values_preserve_distinct_names():
    text = "Tank A holds 18 bbl and Tank B holds 42 bbl. Find their mean volume."
    facts = UserFactRegistry.from_topic(text)
    assert {(row.name, row.value, row.unit) for row in facts.records} == {
        ("Tank_A", 18, "bbl"), ("Tank_B", 42, "bbl")}


@pytest.mark.parametrize("rate,duration", [(36, 4), (52, 7)])
def test_user_formula_executes_with_validated_provenance_and_canceled_units(
        rate: int, duration: int, tmp_path):
    text = f"Q={rate} bbl/d, t={duration} d. total=Q*t. What is total?"
    request = GoalResearchRequest(topic=text, goal=text, allow_python_execution=True,
                                  python_execution_approved=True)
    facts = UserFactRegistry.from_topic(text)
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "work")
    calc = asyncio.run(run_user_formula_calculation(
        settings, request, "DEV-V13", "total=Q*t", facts, "CALC1", "USERF3"))
    assert calc.validation_passed and calc.contract_validation_passed
    assert calc.output_manifest["OUT_RESULT"]["value"] == rate * duration
    assert calc.output_manifest["OUT_RESULT"]["unit"] == "bbl"
    assert calc.formula_source_ids == ["USERF3"]
    assert set(calc.bound_variables) == {"Q", "t"}
    assert calc.input_fact_ids and calc.normalized_formula and calc.execution_hash


@pytest.mark.parametrize("first,second,offset", [(8, 16, 91), (15, 27, 310)])
def test_explicit_aggregate_operands_exclude_unrelated_calibration_fact(
        first: int, second: int, offset: int, tmp_path):
    text = (f"A={first} psi; B={second} psi; calibration_offset={offset} psi. "
            "Find the mean of A and B.")
    all_facts = UserFactRegistry.from_topic(text)
    selected = all_facts.named_operands(text, ["mean"])
    assert {row.name for row in selected.records} == {"A", "B"}
    request = GoalResearchRequest(topic=text, goal=text, allow_python_execution=True,
                                  python_execution_approved=True)
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "work")
    calc = asyncio.run(run_direct_arithmetic(settings, request, "DEV-V13", selected,
                                             ["mean"], "CALC1"))
    assert calc.validation_passed
    assert calc.output_manifest["OUT_mean"]["value"] == (first + second) / 2
    assert set(calc.input_fact_ids) == {row.fact_id for row in selected.records}


def test_ambiguous_operand_scope_blocks_calculation_instead_of_using_every_fact():
    text = "A=10 psi; B=20 psi; C=30 psi. Find the mean of A and unknown."
    facts = UserFactRegistry.from_topic(text)
    assert facts.named_operands(text, ["mean"]).records == []


def test_claim_grounding_keeps_supported_sentence_without_extra_assertion():
    class SourceJudge:
        async def chat_structured(self, messages, *_args, **_kwargs):
            claims = json.loads(messages[1]["content"])["claims"]
            assert len(claims) == 2
            return json.dumps({"claims": [
                {"index": 0, "supported": True, "source_ids": ["KB1"]},
                {"index": 1, "supported": False, "source_ids": []},
            ]})

    request = GoalResearchRequest(topic="Explain capillary pressure", goal="Explain capillary pressure")
    answer = ("Capillary pressure is the pressure difference across two immiscible phases. "
              "It always doubles at greater depth. [KB1]")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "Capillary pressure is the pressure difference across two immiscible phases."}]
    grounded, rejected = asyncio.run(ground_research_claims(SourceJudge(), request, answer, evidence))
    assert grounded == "Capillary pressure is the pressure difference across two immiscible phases. [KB1]"
    assert rejected == ["It always doubles at greater depth."]


def test_unsupported_citation_claim_is_not_kept_by_id_alone():
    class SourceJudge:
        async def chat_structured(self, *_args, **_kwargs):
            return json.dumps({"claims": [{"index": 0, "supported": False, "source_ids": []}]})

    request = GoalResearchRequest(topic="Explain capillary pressure", goal="Explain capillary pressure")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "Capillary pressure varies with pore geometry."}]
    grounded, rejected = asyncio.run(ground_research_claims(
        SourceJudge(), request, "Capillary pressure is always zero in sandstone. [KB1]", evidence))
    assert grounded == "" and rejected


def test_citation_judge_cannot_admit_novel_technical_term_absent_from_sources():
    class OverconfidentJudge:
        async def chat_structured(self, *_args, **_kwargs):
            return json.dumps({"claims": [{"index": 0, "supported": True,
                                            "source_ids": ["KB1"]}]})

    request = GoalResearchRequest(topic="Explain capillary pressure", goal="Explain capillary pressure")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "Capillary pressure varies with pore geometry and wettability."}]
    grounded, rejected = asyncio.run(ground_research_claims(
        OverconfidentJudge(), request,
        "Capillary pressure also depends on crystallization kinetics. [KB1]", evidence))
    assert grounded == "" and rejected


@pytest.mark.parametrize("source,expected", [
    ("Well depth is a function of cement fraction; reservoir quality is separately measured.", False),
    ("Reservoir quality is a function of cement fraction in this empirical model.", True),
])
def test_function_relation_requires_the_same_subject_and_object_in_evidence(source, expected):
    class OverconfidentJudge:
        async def chat_structured(self, *_args, **_kwargs):
            return json.dumps({"claims": [{"index": 0, "supported": True,
                                            "source_ids": ["KB1"]}]})

    request = GoalResearchRequest(topic="Explain reservoir quality", goal="Explain reservoir quality")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": source}]
    grounded, rejected = asyncio.run(ground_research_claims(
        OverconfidentJudge(), request,
        "Reservoir quality is a function of cement fraction. [KB1]", evidence))
    assert bool(grounded) is expected
    assert bool(rejected) is not expected


def test_false_premise_is_explicitly_corrected_only_from_literal_relation():
    class NoModel:
        pass

    question = "When area A increases, force W decreases, right?"
    request = GoalResearchRequest(topic=question, goal=question)
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "For this load calculation, W = p * A, where p > 0 and p is fixed."}]
    assessment = asyncio.run(assess_premise(NoModel(), request, evidence))
    assert assessment.verdict == "contradicts"
    assert "incorrect" in assessment.answer and "increases" in assessment.answer
    assert "[KB1]" in assessment.answer and assessment.supporting_source_ids == ("KB1",)


def test_false_premise_does_not_invent_correction_when_sign_is_unknown():
    class NoModel:
        pass

    question = "When area A increases, force W decreases, right?"
    request = GoalResearchRequest(topic=question, goal=question)
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "The model writes W = p * A without specifying the sign of p."}]
    assessment = asyncio.run(assess_premise(NoModel(), request, evidence))
    assert assessment.verdict == "insufficient" and not assessment.answer


@pytest.mark.parametrize("text,expected", [
    ("A=12 psi, B=22 psi. Find the average.", GoalActionType.CALCULATE),
    ("q=11 bbl/d, t=3 d. volume=q*t. What is volume?", GoalActionType.CALCULATE),
    ("내부 교재에서 정수압 공식을 찾아 계산해줘.", GoalActionType.RETRIEVE),
    ("Explain how wettability affects capillary pressure.", GoalActionType.RETRIEVE),
])
def test_first_action_routes_without_unnecessary_retrieval(text: str, expected: GoalActionType):
    request = GoalResearchRequest(topic=text, goal=text, execution_mode="autonomous_goal_execution",
                                  allow_python_execution=True, python_execution_approved=True)
    facts = UserFactRegistry.from_topic(text)
    intent = classify_goal_intent(request, has_user_facts=bool(facts.records))
    state = GoalExecutionState.from_criteria("DEV-V13", text, [])
    action = GoalActionPlanner.select(
        request, state, user_fact_ids=[row.fact_id for row in facts.records],
        formula_ready=False, simulation_spec=None, intent=intent)
    assert action.action_type == expected


def test_missing_user_formula_input_blocks_python_without_guessing():
    text = "q=11 bbl/d. volume=q*t. What is volume?"
    request = GoalResearchRequest(topic=text, goal=text, execution_mode="autonomous_goal_execution",
                                  allow_python_execution=True, python_execution_approved=True)
    facts = UserFactRegistry.from_topic(text)
    intent = classify_goal_intent(request, has_user_facts=True)
    missing = user_formula_bindings(intent.user_equation, facts)[1]
    assert missing == ["t 값"]
    state = GoalExecutionState.from_criteria("DEV-V13", text, [])
    action = GoalActionPlanner.select(
        request, state, user_fact_ids=[row.fact_id for row in facts.records],
        formula_ready=False, formula_inputs_ready=False, simulation_spec=None, intent=intent)
    assert action.action_type == GoalActionType.STOP


def test_single_goal_answer_keeps_on_topic_cited_relations_only():
    candidate = ("Wettability changes the capillary pressure curve position. [KB1]\n"
                 "Capillary pressure depends on contact angle, a measure of wettability. [KB2]\n"
                 "Capillary pressure can change the free-water level interpretation. [KB3]\n"
                 "Relative permeability varies by wettability. [KB4]")
    focused = GoalExecutionAgent._focus_research_answer(
        candidate, [], "Explain how wettability affects capillary pressure.")
    assert "[KB1]" in focused and "[KB2]" in focused
    assert "[KB3]" not in focused and "[KB4]" not in focused


def test_multifacet_research_question_is_not_narrowed_to_one_facet():
    candidate = "Fracture conductivity controls pressure loss. [KB1]\nMatrix permeability controls rock flow. [KB2]"
    focused = GoalExecutionAgent._focus_research_answer(
        candidate, [], "Compare fracture conductivity and matrix permeability.")
    assert "[KB1]" in focused and "[KB2]" in focused


def test_kb_formula_provenance_rejects_explanatory_neighbor_span():
    rows = [
        {"evidence_id": "KB1", "source_type": "knowledge_base",
         "text": "The auxiliary flow equals the main flow minus measured losses."},
        {"evidence_id": "KB2", "source_type": "knowledge_base",
         "text": "The measured relation is Qaux = Qmain - Qloss."},
    ]
    records = FormulaSourceRegistry.from_evidence(rows).records
    formula = next(row for row in records if row.expression_candidate == "Qaux = Qmain - Qloss")
    assert formula.source_id == "KB2"
    assert source_contains_equation(formula, rows[1]["text"], "Qaux = Qmain - Qloss")
    assert not source_contains_equation(formula, rows[0]["text"], "Qaux = Qmain - Qloss")


@pytest.mark.parametrize("local_context,expected", [
    ("A different operation is described here. z = x + 1", False),
    ("The named theta omega flux transform is defined by z = x + 1", True),
])
def test_named_kb_formula_requires_local_domain_context_not_just_z_and_x(
        local_context: str, expected: bool):
    rows = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": local_context}]
    selected, _ = rank_formula_candidates(
        rows, "Locate the internal theta omega flux transform formula; x=4, calculate z", ["x"])
    assert (selected is not None) is expected


def test_long_generic_output_name_does_not_bypass_named_model_context():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "A separate accounting formula is total = x + 1."}]
    selected, _ = rank_formula_candidates(
        evidence, "Find the internal theta omega flux transform formula for total when x=4", ["x"])
    assert selected is None


def test_sourced_formula_calculation_uses_exact_equation_span_and_bound_facts(tmp_path):
    text = ("Qmain=90 stb/d, Qloss=13 stb/d. Find the internal source equation for "
            "auxiliary flow and calculate Qaux.")
    request = GoalResearchRequest(topic=text, goal=text, allow_python_execution=True,
                                  python_execution_approved=True)
    facts = UserFactRegistry.from_topic(text)
    assert classify_goal_intent(request, has_user_facts=True).kind == GoalIntentKind.KB_FORMULA_CALC
    evidence = [
        {"evidence_id": "KB1", "source_type": "knowledge_base",
         "text": "Auxiliary flow is discussed here, but the relation is on another page."},
        {"evidence_id": "KB2", "source_type": "knowledge_base",
         "text": "The auxiliary flow relation is Qaux = Qmain - Qloss."},
    ]
    selected, _ = rank_formula_candidates(evidence, text, [row.name for row in facts.records])
    assert selected and selected.source_id == "KB2"
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "work")
    calc = asyncio.run(run_user_formula_calculation(
        settings, request, "DEV-V13-KB", selected.expression_candidate, facts, "CALC1", selected.source_id))
    assert calc.validation_passed and calc.formula_source_ids == ["KB2"]
    assert calc.output_manifest["OUT_RESULT"]["value"] == 77
    assert calc.output_manifest["OUT_RESULT"]["unit"] == "stb/d"
    assert set(calc.bound_variables) == {"Qmain", "Qloss"}


@pytest.mark.parametrize("text,expected", [
    ("MW=13 ppg", {"MW": (13, "ppg")}),
    ("70 stb/d for 2 h", {"rate": (70, "stb/d"), "duration": (2, "h")}),
    ("2 stb/d for 2 h", {"rate": (2, "stb/d"), "duration": (2, "h")}),
    ("640 kW at power factor 0.8", {"power": (640, "kW"), "power_factor": (.8, "")}),
    ("640 kW이고 역률은 0.8", {"power": (640, "kW"), "power_factor": (.8, "")}),
])
def test_mixed_prose_value_unit_pairs_keep_correct_local_spans(text, expected):
    facts = UserFactRegistry.from_topic(text)
    assert {row.name: (row.value, row.unit) for row in facts.records} == expected
    for row in facts.records:
        assert row.source_span in text and row.value_span
        assert text[row.value_span[0]:row.value_span[1]] == row.raw_value_text
        if row.unit_span:
            assert text[row.unit_span[0]:row.unit_span[1]] == row.raw_unit


def test_literal_power_factor_alias_binds_without_guessing():
    text = "640 kW at power factor 0.8. effective=power*pf. What is effective power?"
    facts = UserFactRegistry.from_topic(text)
    bound, missing = user_formula_bindings("effective=power*pf", facts)
    assert missing == []
    assert {name: row.value for name, row in bound.items()} == {"power": 640, "pf": .8}
