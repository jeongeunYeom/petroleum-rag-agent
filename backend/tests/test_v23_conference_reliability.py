"""Fresh development-only paraphrase and safety checks for the V23 live demo.

These cases exercise general parsing/binding rules. They are not a final benchmark.
"""

import asyncio
import json
import re
import time
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import (GoalResearchRequest, GoalResearchResponse,
                                             GoalRunStatus, GoalStatus, GoalStopReason)
from app.services.calculation_request_ir import OPERATIONS
from app.services.calculation_request_ir import parse_request_ir
from app.services.formula_source_registry import (FormulaSourceRegistry, isolated_source_formula,
                                                  source_contains_equation, expression_variables)
from app.services.calculation_requirements import (rank_formula_candidates, formula_target_contract,
                                                   infer_dimensionless)
from app.services.goal_clarification import clarification_question, public_missing_inputs
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_execution_state import GoalExecutionState
from app.services.goal_intent import (GoalIntentKind, classify_goal_intent,
                                      clearly_out_of_domain, user_equation)
from app.services.goal_knowledge_retrieval import bilingual_recovery_query, plan_query, substantive_question
from app.services.goal_research_service import GoalResearchService
from app.services.source_answerability import (_terms, _instructional_span, atomic_claims,
                                               semantic_claim_support, SupportStatus,
                                               ClaimSupport, RequiredClaim, grounded_answer)
from app.services.premise_grounding import (derive_safe_relation_from_equation,
                                             _sourced_engineering_rule_correction,
                                             _sourced_ratio_correction)
from app.services.goal_simulation import direct_operation_operands, direct_readiness, user_formula_bindings
from app.services.required_goals import parse_required_goals
from app.services.user_fact_registry import UserFactRegistry
from app.services.engineering_validator import EngineeringValidator
from test_goal_execution_v8 import NoResearch, PassingEvaluator, StaticResearch


def req(text: str) -> GoalResearchRequest:
    return GoalResearchRequest(topic=text, goal=text, execution_mode="autonomous_goal_execution")


def route(text: str) -> GoalIntentKind:
    return classify_goal_intent(req(text), has_user_facts=bool(UserFactRegistry.from_topic(text).records)).kind


def operations(text: str) -> list[str]:
    return [name for name, pattern in OPERATIONS.items() if re.search(pattern, text, re.I)]


_TRIPLES = [(71, 32, 18), (119, 46, 27), (203, 88, 41),
            (37, 24, 15), (164, 91, 53)]


@pytest.mark.parametrize("a,b,c", _TRIPLES)
@pytest.mark.parametrize("phrase,operation", [
    ("What is the total production?", "sum"),
    ("전체 유량 얼마야?", "sum"),
    ("이 유량들 합쳐줘", "sum"),
    ("Give the arithmetic mean.", "mean"),
    ("평균 계산해줘", "mean"),
    ("Which is the highest?", "maximum"),
])
def test_direct_paraphrase_families_route_without_missing_values(a, b, c, phrase, operation):
    text = f"A={a} stb/d, B={b} stb/d, C={c} stb/d. {phrase}"
    facts = UserFactRegistry.from_topic(text)
    assert len(facts.records) == 3
    assert route(text) == GoalIntentKind.DIRECT_CALC
    assert operation in operations(text)
    assert direct_readiness(text, facts, [operation]) == []


@pytest.mark.parametrize("text,expected,values", [
    ("생산정 A=143 stb/d, B=96 stb/d, C=61 stb/d다. 총 생산 유량은?", "sum", [143, 96, 61]),
    ("Oil rate was 765 stb/d and is now 612 stb/d. What percentage decline is that?",
     "percentage_decrease", [765, 612]),
    ("Gas=4500 scf, oil=150 stb. Compute the gas divided by oil ratio.", "ratio", [4500, 150]),
    ("A=31 psi, B=19 psi. Find A-B.", "difference", [31, 19]),
    ("Start=1800 psi and end=1980 psi. Find the percent increase.", "percentage_increase", [1800, 1980]),
    ("가스 960 scf와 원유 32 stb에서 가스/오일 비를 계산해줘.", "ratio", [960, 32]),
])
def test_fresh_direct_dev_failures_are_classified_and_bound_without_retrieval(text, expected, values):
    facts = UserFactRegistry.from_topic(text)
    ir = parse_request_ir(req(text), [])
    assert [row.value for row in facts.records] == values
    assert route(text) == GoalIntentKind.DIRECT_CALC
    assert expected in ir.requested_operation_types
    assert direct_readiness(text, facts, ir.requested_operation_types) == []
    _, missing = direct_operation_operands(text, facts, ir.requested_operation_types)
    assert not missing


def test_percent_decline_output_goal_uses_percent_not_input_rate_unit():
    text = "Oil rate was 765 stb/d and is now 612 stb/d. What percentage decline is that?"
    request = req(text)
    criteria = GoalExecutionAgent._explicit_numeric_criteria(request, UserFactRegistry.from_topic(text), None)
    goals = parse_required_goals(request, "direct_calc", None)
    assert len(criteria) == 1 and "percentage_decrease" in criteria[0].description
    assert len(goals) == 1 and goals[0].requested_unit == "%"


@pytest.mark.parametrize("phrase,expected", [
    ("총합과 가장 높은 항목은?", {"sum", "maximum"}),
    ("합계와 제일 낮은 값은 뭐야?", {"sum", "minimum"}),
])
def test_korean_extreme_phrasings_keep_both_requested_numeric_goals(phrase, expected):
    text = f"A=34 stb/d, B=61 stb/d, C=29 stb/d. {phrase}"
    assert expected <= set(parse_request_ir(req(text), []).requested_operation_types)


def test_gor_acronym_uses_explicit_gas_over_oil_volumes_and_preserves_units():
    text = "Gas=1540 scf, oil=77 stb. Calculate GOR."
    facts = UserFactRegistry.from_topic(text)
    operations = parse_request_ir(req(text), []).requested_operation_types
    assert "ratio" in operations
    assert direct_readiness(text, facts, operations) == []
    order, missing = direct_operation_operands(text, facts, operations)
    assert not missing and order["ratio"] == ("Gas", "oil")


def test_absolute_and_percent_decline_request_retains_both_outputs():
    text = "Oil production changed from 620 to 496 stb/d. Give absolute decrease and percentage decrease."
    facts = UserFactRegistry.from_topic(text)
    operations = parse_request_ir(req(text), []).requested_operation_types
    assert {"difference", "percentage_decrease"} <= set(operations)
    order, missing = direct_operation_operands(text, facts, operations)
    assert not missing
    initial, final = order["difference"]
    values = {row.name: row.value for row in facts.records}
    assert values[initial] - values[final] == 124


@pytest.mark.parametrize("text", [
    "비자성 collar가 방향 측정에 왜 쓰여?",
    "How can a non-magnetic drill collar protect a survey?",
])
def test_drill_collar_retrieval_expands_domain_synonyms_without_asserting_an_answer(text):
    plan = plan_query(text)
    assert any("Monel drill collar" in query or "monel" in query.casefold() for query in plan.queries)


@pytest.mark.parametrize("text", [
    "Compare carbonate and sand formation factor empirical relations.",
    "지층 인자 formation factor가 공극률과 어떻게 관계되나?",
])
def test_formation_factor_retrieval_is_disambiguated_as_petrophysics(text):
    plan = plan_query(text)
    assert plan.domain == "petrophysics"
    assert any("porosity" in query for query in plan.queries)


def test_lithology_singular_terms_keep_textbook_plural_search_forms():
    plan = plan_query("Compare carbonate and sand formation factor relations.")
    assert "carbonates" in plan.search_text and "sands" in plan.search_text


def test_concept_support_terms_drop_request_filler_but_keep_empirical_formula_meaning():
    terms = _terms("교재 근거로 carbonate와 sand의 formation factor 경험식이 어떻게 다른지 비교해줘.")
    assert {"carbonate", "sand", "formation", "factor", "formula"} <= terms
    assert not terms.intersection({"교재", "어떻게", "다른지", "비교해줘"})


@pytest.mark.parametrize("text", [
    "Find the textbook sand relation and compute formation factor for phi=0.20.",
    "내부 교재의 공극률-지층 저항 인자 식으로 phi=0.25일 때 값을 계산해줘.",
])
def test_requested_formation_factor_target_is_not_confused_with_source_exponent(text):
    assert GoalExecutionAgent._requested_target(req(text)) == "F"


def test_hyphenated_type_curve_query_keeps_both_searchable_concepts():
    plan = plan_query("Why add pressure derivative to a well-test type-curve match?")
    assert "type" in plan.concepts and "curve" in plan.concepts
    assert any("type curve" in query for query in plan.queries)


@pytest.mark.parametrize("text", [
    "Find the API conversion in the reservoir textbook and apply it to SG=0.928.",
    "Locate a sourced specific-gravity to API relation and apply this to SG=0.88.",
])
def test_sourced_relation_application_is_not_misrouted_as_direct_unit_conversion(text):
    assert route(text) == GoalIntentKind.KB_FORMULA_CALC


def test_source_context_reconstructs_flattened_greek_porosity_exponents_without_changing_raw_span():
    source = ("In carbonates, F = 1/φ2 is usually used. "
              "In sands, F = 0.62/φ2.15 (Humble formula) is used. "
              "The proper porosity-to-formation factor relationship must be selected.")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "document": "synthetic source", "page": 4, "text": source}]
    records = FormulaSourceRegistry.from_evidence(evidence).records
    by_raw = {row.raw_span: row for row in records}
    carbonate = by_raw["F = 1/φ2"]
    sand = next(row for row in records if row.raw_span.startswith("F = 0.62/φ2.15"))
    assert carbonate.expression_candidate == "F = 1/(phi**2)"
    assert sand.expression_candidate == "F = 0.62/(phi**2.15)"
    assert source_contains_equation(carbonate, source)
    assert source_contains_equation(sand, source)
    assert carbonate.raw_span in source and sand.raw_span in source


def test_greek_numeric_suffix_is_not_rewritten_when_defined_as_separate_variable():
    source = ("φ2 is a variable measured separately. "
              "F = 1/φ2. The porosity-to-formation factor relationship needs investigation.")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "document": "synthetic source", "page": 4, "text": source}]
    record = next(row for row in FormulaSourceRegistry.from_evidence(evidence).records
                  if row.raw_span == "F = 1/φ2")
    assert record.expression_candidate == "F = 1/phi2"


def test_user_quoted_equation_disambiguates_verified_source_equations():
    source = ("In carbonates, F = 1/φ2 is usually used. "
              "In sands, F = 0.62/φ2.15 (Humble formula) is used. "
              "The proper porosity-to-formation factor relationship must be selected.")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "document": "synthetic manual", "page": 7, "text": source}]
    query = "Verify the textbook equation F=1/phi^2 for carbonate and compute it at phi=0.24."
    candidate, _ = rank_formula_candidates(evidence, query, ["phi"],
        target_contract=formula_target_contract(query, ["phi"], "F"))
    assert candidate and candidate.expression_candidate == "F = 1/(phi**2)"
    assert source_contains_equation(candidate, source)


def test_named_formula_prefers_literal_label_over_equivalent_alternative():
    source = ("For sands, F = 0.62/φ2.15 (Humble formula), or F = 0.81/φ2 "
              "(a simpler form practically equivalent to the Humble formula). "
              "The proper porosity-to-formation factor relationship must be selected.")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "document": "synthetic manual", "page": 8, "text": source}]
    query = "Find the Humble formula and compute formation factor for phi=0.23."
    candidate, _ = rank_formula_candidates(evidence, query, ["phi"],
        target_contract=formula_target_contract(query, ["phi"], "F"))
    assert candidate and "0.62" in candidate.expression_candidate
    assert source_contains_equation(candidate, source)


@pytest.mark.parametrize("spacer", ["", "  "])
def test_source_worked_example_proves_trailing_denominator_exponent(spacer):
    source = (f"For other saturation values, Rt and Ro are related by Rt = Ro/Sw{spacer}\n"
              "2 . For Sw = 50%, 1/Sw\n2 = 4, and Rt = 4 Ro.")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "document": "synthetic manual", "page": 9, "text": source}]
    records = FormulaSourceRegistry.from_evidence(evidence).records
    equation = next(row for row in records if row.raw_span.startswith("Rt = Ro/Sw"))
    assert equation.raw_span == f"Rt = Ro/Sw{spacer}\n2"
    assert equation.expression_candidate == "Rt = Ro/(Sw**2)"
    assert source_contains_equation(equation, source)


def test_unverified_trailing_exponent_does_not_become_clipped_quotient():
    source = "The extracted page reads Rt = Ro/Sw\n2 . There is no worked example."
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "document": "synthetic manual", "page": 9, "text": source}]
    assert not any(row.expression_candidate and row.lhs == "Rt"
                   for row in FormulaSourceRegistry.from_evidence(evidence).records)


@pytest.mark.parametrize("text", [
    "Does influx happen because borehole pressure is above the formation pressure?",
    "Does produced gas increase because reservoir pressure falls?",
])
def test_causal_question_is_checked_as_premise_before_answering(text):
    assert route(text) == GoalIntentKind.PREMISE_CHECK


@pytest.mark.parametrize("source", [
    "Formation factor F is obtained from measured porosity. For φ = 10%, F = 1/φ2 is used. Thus F = 100.",
    "The porosity-to-formation factor relation for carbonates is F = 1/φ2.",
])
def test_positive_inverse_power_source_corrects_monotonic_false_premise(source):
    assessment = derive_safe_relation_from_equation(
        "Formation factor F increases as porosity increases, right?", {"KB1": source}, False)
    assert assessment.verdict == "contradicts"
    assert "decreases" in assessment.answer and "[KB1]" in assessment.answer
    assert assessment.supporting_spans == ("F = 1/φ2",)


def test_inverse_power_correction_recognizes_named_formation_factor_target():
    source = "The porosity-to-formation factor relation for carbonates is F = 1/φ2."
    assessment = derive_safe_relation_from_equation(
        "Does formation factor increase as porosity increases?", {"KB1": source}, False)
    assert assessment.verdict == "contradicts"
    assert "formation factor" in assessment.answer.casefold()


def test_inverse_power_without_positive_domain_does_not_assert_direction():
    source = "A textbook prints Y = 2/x2 with no variable range or worked example."
    assessment = derive_safe_relation_from_equation(
        "Y increases as x increases, right?", {"KB1": source}, False)
    assert assessment.verdict == "insufficient"


_PAIRS = [(13, 5), (27, 9), (42, 7), (61, 11), (84, 12)]


@pytest.mark.parametrize("a,b", _PAIRS)
@pytest.mark.parametrize("formula,target", [
    ("Y = A + B", "Y"), ("D = A - B", "D"),
    ("P = A * B", "P"), ("Q = A / B", "Q"),
])
def test_literal_user_formula_families_bind_only_supplied_facts(a, b, formula, target):
    text = f"A={a} psi, B={b} psi. Use my equation {formula}; calculate {target}."
    equation = user_equation(text)
    assert equation == formula
    assert route(text) == GoalIntentKind.USER_FORMULA_CALC
    bound, missing = user_formula_bindings(equation, UserFactRegistry.from_topic(text))
    assert not missing
    assert {key: fact.value for key, fact in bound.items()} == {"A": a, "B": b}


@pytest.mark.parametrize("a,b", _PAIRS)
@pytest.mark.parametrize("equation", [
    "Y = A + B", "D = A - B", "Q = A / B", "P = A * B", "W = (A + B) / B",
])
def test_literal_kb_formula_source_and_bindings_are_exact(a, b, equation):
    source = f"The measured relation is {equation}. A and B are supplied measurements."
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "document": "synthetic manual", "page": 7, "text": source}]
    formulas = FormulaSourceRegistry.from_evidence(evidence).records
    selected = next(row for row in formulas if row.expression_candidate == equation)
    assert source_contains_equation(selected, source, equation)
    facts = UserFactRegistry.from_topic(f"A={a} psi, B={b} psi")
    bound, missing = user_formula_bindings(equation, facts)
    assert not missing
    assert {key: fact.value for key, fact in bound.items()} == {"A": a, "B": b}


@pytest.mark.parametrize("a,b", _PAIRS)
@pytest.mark.parametrize("phrase,operation", [
    ("총 rate 얼마야?", "sum"),
    ("전체 유량을 계산해줘", "sum"),
    ("두 유량 합쳐줘", "sum"),
    ("평균을 구해줘", "mean"),
])
def test_korean_operation_variants(a, b, phrase, operation):
    text = f"A={a} stb/d, B={b} stb/d. {phrase}"
    assert route(text) == GoalIntentKind.DIRECT_CALC
    assert operation in operations(text)
    assert len(UserFactRegistry.from_topic(text).records) == 2


@pytest.mark.parametrize("a,b", _PAIRS)
@pytest.mark.parametrize("phrase,operation", [
    ("Find the combined production.", "sum"),
    ("Add these rates.", "sum"),
    ("Calculate the mean value.", "mean"),
])
def test_english_operation_variants(a, b, phrase, operation):
    text = f"A={a} stb/d, B={b} stb/d. {phrase}"
    assert route(text) == GoalIntentKind.DIRECT_CALC
    assert operation in operations(text)


@pytest.mark.parametrize("a,b", _PAIRS)
@pytest.mark.parametrize("phrase", ["총 rate 얼마야?", "Calculate 전체 유량."])
def test_mixed_language_rate_variants(a, b, phrase):
    text = f"A={a} stb/d, B={b} stb/d. {phrase}"
    assert route(text) == GoalIntentKind.DIRECT_CALC
    assert "sum" in operations(text)


@pytest.mark.parametrize("a,b,c", _TRIPLES)
@pytest.mark.parametrize("phrase,expected", [
    ("Calculate the sum and mean.", {"sum", "mean"}),
    ("Calculate the sum and ranking.", {"sum", "ranking"}),
    ("Calculate the mean and maximum.", {"mean", "maximum"}),
])
def test_multiple_explicit_outputs_are_frozen_separately(a, b, c, phrase, expected):
    text = f"A={a} stb/d, B={b} stb/d, C={c} stb/d. {phrase}"
    goals = parse_required_goals(req(text), "direct_calc", None)
    assert {goal.semantic_target for goal in goals} == expected
    assert all(goal.required and goal.status != "MET" for goal in goals)


@pytest.mark.parametrize("text", [
    "오늘 날씨 예보 알려줘", "축구 결과가 뭐야?", "영화 추천해줘",
    "Give me a cooking recipe", "Tell me a joke",
])
def test_clearly_out_of_domain_gets_short_safe_guidance(text):
    assert clearly_out_of_domain(text)
    result = asyncio.run(GoalExecutionAgent(NoResearch(), object()).run("GR-V23-OOD", req(text)))
    assert result.run_status == GoalRunStatus.STOPPED
    assert result.final_answer and "Traceback" not in result.final_answer
    assert result.telemetry["intent_route"] == "out_of_domain"


@pytest.mark.parametrize("text", [
    "How does weather affect drilling?", "석유 시추 현장의 날씨 예보 영향은?",
    "Oil production forecast versus weather", "Tell me a joke about well testing",
])
def test_domain_context_is_not_rejected_as_unrelated(text):
    assert not clearly_out_of_domain(text)


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
def test_empty_final_answer_is_recovered_safely(value):
    result = GoalResearchResponse(run_id=f"GR-V23-{value}", topic="석유공학 질문", goal="설명",
                                  max_iterations=4)
    finished = GoalExecutionAgent._finish(result, GoalRunStatus.COMPLETED, GoalStatus.ACHIEVED,
                                           GoalStopReason.GOAL_ACHIEVED, "", time.perf_counter())
    assert finished.final_answer.strip()
    assert finished.status == GoalStatus.STOPPED
    assert "Traceback" not in finished.final_answer


@pytest.mark.parametrize("a,b", [(12, 7), (19, 6), (24, 9), (32, 5), (47, 13)])
@pytest.mark.parametrize("question", [
    "Find the internal equation for Y from A and B, then calculate Y.",
    "내부 교재의 Y 관계식을 찾아 A와 B로 Y를 계산해줘.",
    "Use the textbook relation and compute Y from A and B.",
])
def test_one_missing_operand_resumes_same_run(a, b, question, tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    request = req(f"A={a} psi. {question}")
    request.max_iterations = 8
    agent = GoalExecutionAgent(StaticResearch("Y = A + B. A and B are pressures in psi."),
                               object(), evaluator=PassingEvaluator())
    waiting = asyncio.run(agent.run("GR-V23-RESUME", request))
    assert waiting.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT
    assert waiting.python_calls_total == 0
    assert "B" in (waiting.clarification_question or "")
    checkpoint = dict(waiting.resume_checkpoint)
    checkpoint["user_replies"] = [f"B={b} psi"]
    finished = asyncio.run(agent.run(waiting.run_id, request, resume_state=checkpoint,
                                     resume_result=waiting))
    assert finished.run_id == waiting.run_id
    assert finished.status == GoalStatus.ACHIEVED, finished.final_answer
    assert finished.python_calls_total == 1
    assert finished.computations[0].validation_passed
    assert sum(row["action_type"] == "calculate" for row in finished.action_history) == 1
    assert "B" not in (finished.clarification_question or "")


@pytest.mark.parametrize("a,b", _PAIRS)
@pytest.mark.parametrize("kind", ["ratio", "mean", "formula"])
def test_ambiguous_or_missing_inputs_are_not_invented(a, b, kind):
    if kind == "ratio":
        text = f"A={a} psi, B={b} bbl. Calculate ratio A/B."
        selected, missing = direct_operation_operands(text, UserFactRegistry.from_topic(text), ["ratio"])
        assert not selected and missing
    elif kind == "mean":
        text = f"A={a} psi, B={b} bbl. Calculate the mean."
        assert direct_readiness(text, UserFactRegistry.from_topic(text), ["mean"])
    else:
        text = f"A={a} psi. Use my equation Y = A / B to calculate Y."
        bound, missing = user_formula_bindings("Y = A / B", UserFactRegistry.from_topic(text))
        assert "A" in bound and "B 값" in missing


@pytest.mark.parametrize("a,b", _PAIRS)
@pytest.mark.parametrize("shape", ["power", "compact", "unicode"])
def test_casual_formula_and_unit_spellings_are_parseable_without_rewriting_source(a, b, shape):
    if shape == "power":
        text = f"s={a}, B={b}. My formula R(s)=B+s^2; calculate R."
        assert user_equation(text) == "R = B+s**2"
    elif shape == "compact":
        text = f"A={a} stb/d,B={b} stb/d.합쳐줘"
        assert "sum" in operations(text)
        assert len(UserFactRegistry.from_topic(text).records) == 2
    else:
        text = f"φ={a/100}, ρ={b} kg/m³. Calculate using my relation X = φ * ρ."
        assert len(UserFactRegistry.from_topic(text).records) == 2
        assert user_equation(text) == "X = φ * ρ"


@pytest.mark.parametrize("question,answer", [
    ("Radial-flow derivative rises with unit slope, correct?",
     "No. A radial-flow derivative is a horizontal constant plateau, not a unit slope. "
     "Wellbore storage has pressure and derivative overlap on a unit-slope line."),
    ("In radial flow the pressure and derivative overlap on a unit-slope line, right?",
     "No. That overlap and unit slope indicate wellbore storage; radial flow has a horizontal derivative plateau."),
    ("Does spherical flow have a +1/2 derivative slope?",
     "No. Spherical flow has derivative slope -1/2, whereas linear flow is +1/2."),
    ("Linear flow gives a -1/2 derivative slope, correct?",
     "No. Linear flow has +1/2 derivative slope; spherical flow has -1/2."),
    ("Kick happens when mud hydrostatic pressure is above formation pressure, right?",
     "No. A kick may occur when formation pressure exceeds mud hydrostatic pressure."),
    ("Kick은 mud pressure가 formation pressure보다 클 때 생기는 거지?",
     "아니요. 지층 압력이 이수압보다 높을 때 kick이 발생할 수 있습니다."),
    ("Wellbore storage shows a flat derivative plateau, correct?",
     "No. Wellbore storage shows overlapping pressure and derivative on a unit-slope line."),
    ("Spherical flow has the same +1/2 slope as linear flow, right?",
     "No. Spherical flow has -1/2 slope; linear flow has +1/2 slope."),
])
def test_false_premise_paraphrases_require_correction(question, answer):
    assert route(question) == GoalIntentKind.PREMISE_CHECK
    detected, corrected, _ = EngineeringValidator().false_premise_correction(question, answer)
    assert detected
    assert corrected


def test_source_feature_before_regime_is_attributed_to_following_during_clause():
    source = ("A unit-slope line appears during wellbore storage; a horizontal derivative "
              "during early radial flow.")
    claim = "During radial flow, the pressure derivative is a horizontal plateau."
    assert EngineeringValidator().validate_claim(claim, source, query="radial flow derivative").passed


def test_hyphenated_regime_subject_is_not_stolen_by_later_comparison():
    question = "Radial-flow derivative must be unit slope like early wellbore storage, correct?"
    premises = EngineeringValidator().detect_false_premises(question)
    assert any(item.get("regime") == "radial" and item.get("incorrect_feature") == "unit_slope"
               for item in premises)
    answer = ("That is incorrect. Radial flow has a horizontal derivative plateau; "
              "wellbore storage has overlapping pressure and derivative on a unit-slope line.")
    assert EngineeringValidator().false_premise_correction(question, answer)[1]


def test_bilingual_recovery_preserves_explicit_comparison_terms():
    plan = plan_query("교재 근거로 carbonate와 sand의 formation factor 경험식을 비교해줘.", refined=True)
    retry = bilingual_recovery_query(plan)
    assert "carbonate" in retry and "sand" in retry and "factor" in retry


def test_false_premise_correction_requires_literal_regime_and_storage_support():
    question = "Radial flow에서 derivative가 unit-slope로 pressure와 겹치나요?"
    sources = {
        "KB1": "A unit-slope line appears during wellbore storage; a horizontal derivative during early radial flow.",
        "KB2": ("At early time in the period of wellbore storage dominated flow, the pressure\n"
                "and its logarithmic derivative overlay on the unit slope diagonal."),
    }
    assessment = _sourced_engineering_rule_correction(question, sources, True)
    assert assessment.verdict == "contradicts"
    assert assessment.supporting_source_ids == ("KB1", "KB2")
    assert "수평" in assessment.answer and "겹칩니다" in assessment.answer
    assert "\n" not in assessment.answer and "\n" in assessment.supporting_spans[1]
    assert _sourced_engineering_rule_correction(question, {"KB1": sources["KB1"]}, True).verdict == "insufficient"


def test_drilling_pressure_correction_requires_explicit_source_relation():
    question = "Does a kick occur because mud pressure exceeds formation pressure?"
    source = ("Because formation pressure exceeds mud hydrostatic pressure, fluids flow "
              "from formation into the wellbore and a kick occurs.")
    assessment = _sourced_engineering_rule_correction(question, {"KB9": source}, False)
    assert assessment.verdict == "contradicts" and assessment.supporting_source_ids == ("KB9",)
    assert _sourced_engineering_rule_correction(question, {"KB9": "Kicks are discussed here."}, False).verdict == "insufficient"


@pytest.mark.parametrize("source", [
    "Porosity, by definition, is the volume of the non-solid part of the rock (filled with fluids) divided by the bulk volume.",
    "Porosity is the ratio of void volume to bulk volume.",
    "Porosity = pore volume / bulk volume.",
])
def test_fixed_denominator_premise_uses_literal_ratio_definition(source):
    question = "At constant bulk volume, does greater porosity mean less pore volume?"
    result = _sourced_ratio_correction(question, {"KB7": source}, False)
    assert result.verdict == "contradicts"
    assert "pore volume" in result.answer and "same direction" in result.answer
    assert result.supporting_spans == (source,)
    assert "[KB7]" in result.answer


@pytest.mark.parametrize("source", [
    "Porosity and pore volume are mentioned in a discussion of bulk volume.",
    "Porosity = bulk volume / pore volume.",
    "Porosity is not pore volume divided by bulk volume.",
])
def test_fixed_denominator_premise_rejects_missing_or_reversed_ratio(source):
    result = _sourced_ratio_correction(
        "At fixed bulk volume, greater porosity means smaller pore volume, yes?",
        {"KB7": source}, False)
    assert result.verdict == "insufficient"


def test_full_agent_completes_sourced_fixed_denominator_correction(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    request = req("At fixed bulk volume, greater porosity means smaller pore volume, yes?")
    request.max_iterations = 6
    source = ("Porosity, by definition, is the volume of the non-solid part of the rock "
              "(that filled with fluids) divided by the bulk volume.")
    result = asyncio.run(GoalExecutionAgent(StaticResearch(source), object(),
                                             evaluator=PassingEvaluator()).run("GR-V23-RATIO", request))
    assert result.status == GoalStatus.ACHIEVED, result.final_answer
    assert "same direction" in result.final_answer
    assert "[KB1]" in result.final_answer
    assert result.python_calls_total == 0


@pytest.mark.parametrize("name", ["Kappa", "Zeta", "Lambda", "Xi", "Omega", "Sigma", "Theta", "Upsilon"])
def test_absent_source_equation_never_executes_a_calculation(name, tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    text = f"A=23 psi. Find the internal {name} relation for Y and calculate Y."
    request = req(text)
    request.max_iterations = 6
    result = asyncio.run(GoalExecutionAgent(StaticResearch("The manual discusses measurements but states no equation."),
                                             object(), evaluator=PassingEvaluator()).run("GR-V23-NOFORMULA", request))
    assert result.status != GoalStatus.ACHIEVED
    assert result.python_calls_total == 0
    assert result.final_answer.strip()
    assert not any(row["action_type"] == "calculate" for row in result.action_history)


@pytest.mark.parametrize("error", [
    ValueError("secret JSON parse failure"), RuntimeError("secret model transport stack"),
    OSError("secret Chroma path"), KeyError("secret key"),
    TypeError("secret malformed response"), LookupError("secret lookup"),
    ConnectionError("secret provider"), TimeoutError("secret timeout"),
    AssertionError("secret assertion"), ZeroDivisionError("secret division"),
])
def test_background_run_exception_is_logged_but_not_exposed(error, tmp_path, monkeypatch):
    class FailingAgent:
        async def run(self, *_args, **_kwargs):
            raise error

    request = GoalResearchRequest(topic="저류층에 관해 설명해줘", goal="설명")
    response = GoalResearchResponse(run_id="GR-V23-FAIL", topic=request.topic,
                                    goal=request.goal, max_iterations=request.max_iterations)
    service = GoalResearchService(Settings(data_dir=tmp_path / "data",
                                           agent_workspace_dir=tmp_path / "workspace"),
                                  FailingAgent())
    monkeypatch.setattr(service, "_read", lambda _run_id: (request, response))
    saved = []
    monkeypatch.setattr(service, "_write", lambda _run_id, _request, result, **_kw: saved.append(result))
    service._execute(response.run_id, request)
    final = saved[-1]
    assert final.run_status == GoalRunStatus.FAILED
    assert final.final_answer and "secret" not in final.final_answer
    assert final.error and "secret" not in final.error


def test_goal_run_persistence_uses_distinct_atomic_temp_paths(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    service_a = GoalResearchService(settings, object())
    service_b = GoalResearchService(settings, object())
    request = GoalResearchRequest(topic="verify persistence")
    response = GoalResearchResponse(run_id="GR-V23-PERSIST", topic=request.topic,
                                    goal=request.goal, max_iterations=request.max_iterations)
    moved = []
    original_replace = Path.replace

    def record_replace(source, target):
        moved.append(source.name)
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", record_replace)
    service_a._write(response.run_id, request, response)
    service_b._write(response.run_id, request, response)
    assert len(moved) == len(set(moved)) == 2
    assert all(name.startswith("GR-V23-PERSIST.json.") and name.endswith(".tmp") for name in moved)
    assert service_a.get(response.run_id).run_id == response.run_id
    assert not list(settings.goal_research_runs_dir.glob("*.tmp"))


@pytest.mark.parametrize("text,expected", [
    ("A=120 stb/d, B=80 stb/d. 총 rate 얼마야?", 200),
    ("A=41 stb/d, B=29 stb/d. 합쳐줘", 70),
    ("A=16 stb/d, B=34 stb/d. Find combined production.", 50),
])
def test_full_agent_direct_fast_path_uses_no_retrieval(text, expected, tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    result = asyncio.run(GoalExecutionAgent(NoResearch(), object(), evaluator=PassingEvaluator())
                         .run("GR-V23-DIRECT", req(text)))
    assert result.status == GoalStatus.ACHIEVED, result.final_answer
    assert [row["action_type"] for row in result.action_history] == [
        "calculate", "verify", "synthesize", "stop"]
    assert result.computations[0].validation_passed
    assert result.computations[0].output_manifest["OUT_sum"]["value"] == expected


def test_full_agent_function_style_user_equation_uses_validated_result(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    text = "s=2, B=7. Use my formula R(s)=B+s^2; calculate R."
    result = asyncio.run(GoalExecutionAgent(NoResearch(), object(), evaluator=PassingEvaluator())
                         .run("GR-V23-FUNCTION", req(text)))
    assert result.status == GoalStatus.ACHIEVED, result.final_answer
    assert result.computations[0].validation_passed
    assert result.computations[0].output_manifest["OUT_RESULT"]["value"] == 11
    assert not any(row["action_type"] == "retrieve" for row in result.action_history)


def test_full_agent_reports_absolute_and_relative_decline_without_asking_again(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    text = "Production changed from 620 to 496 stb/d. Give absolute decrease and percentage decrease."
    result = asyncio.run(GoalExecutionAgent(NoResearch(), object(), evaluator=PassingEvaluator())
                         .run("GR-V23-DECLINE", req(text)))
    assert result.status == GoalStatus.ACHIEVED, result.final_answer
    assert [row["action_type"] for row in result.action_history] == [
        "calculate", "verify", "synthesize", "stop"]
    manifest = result.computations[0].output_manifest
    assert manifest["OUT_difference"]["value"] == 124
    assert manifest["OUT_percentage_decrease"]["value"] == 20
    assert "124" in result.final_answer and "20" in result.final_answer


def test_full_agent_uses_verified_stacked_exponent_not_clipped_division(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    source = ("In the sourced saturation relation, Rt = Ro/Sw\n2 . "
              "For Sw = 50%, 1/Sw\n2 = 4 and Rt = 4 Ro. Sw is water saturation.")
    text = "Find the internal Rt equation from Ro and Sw. Ro=4 ohm-m, Sw=0.5. Calculate Rt."
    result = asyncio.run(GoalExecutionAgent(StaticResearch(source), object(),
                                            evaluator=PassingEvaluator()).run("GR-V23-POWER", req(text)))
    assert result.status == GoalStatus.ACHIEVED, result.final_answer
    calc = result.computations[0]
    assert calc.validation_passed and calc.output_manifest["OUT_RESULT"]["value"] == 16
    assert calc.formula_source_ids == ["KB1"]
    assert "16" in result.final_answer


@pytest.mark.parametrize("a,b,c", [(23, 47, 31), (91, 62, 84), (12, 35, 29), (118, 73, 66)])
@pytest.mark.parametrize("phrase,expected", [
    ("Report the total and highest item.", {"sum", "maximum"}),
    ("Which item is highest? Also give the total.", {"sum", "maximum"}),
    ("총합과 가장 높은 항목을 알려줘.", {"sum", "maximum"}),
    ("평균도 구하고 최댓값도 알려줘.", {"mean", "maximum"}),
    ("Give the average and the minimum.", {"mean", "minimum"}),
    ("합계 그리고 순위를 알려줘.", {"sum", "ranking"}),
    ("Find the maximum and minimum readings.", {"maximum", "minimum"}),
    ("Calculate the mean and rank them high to low.", {"mean", "ranking"}),
])
def test_new_conjoined_direct_requests_have_independent_required_outputs(a, b, c, phrase, expected):
    text = f"A={a} stb/d, B={b} stb/d, C={c} stb/d. {phrase}"
    assert route(text) == GoalIntentKind.DIRECT_CALC
    assert expected <= {goal.semantic_target for goal in parse_required_goals(req(text), "direct_calc", None)}
    assert direct_readiness(text, UserFactRegistry.from_topic(text), list(expected)) == []


@pytest.mark.parametrize("phi", [.17, .19, .22, .26, .31, .35])
@pytest.mark.parametrize("wording", [
    "Calculate carbonate formation factor F from phi={phi}.",
    "Find the internal equation for carbonate formation factor F; phi={phi}. Calculate with citation.",
    "For carbonate material with phi={phi}, determine F using the sourced relation.",
    "Use the carbonate formation factor formula for phi={phi} and report F.",
])
def test_named_context_and_bound_inputs_beat_generic_free_parameter_formula(phi, wording):
    text = ("Formation factor is obtained from measured porosity. "
            "F = a/phi**m where a is a constant and m is the cementation factor. "
            "For carbonates, F = 1/phi**2; for sands, F = 0.62/phi**2.15.")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": text,
                 "document": "formation.pdf", "page": 1}]
    question = wording.format(phi=phi)
    formula, _ = rank_formula_candidates(evidence, question, ["phi"],
                                         target_contract=formula_target_contract(question, ["phi"], "F"))
    assert formula is not None
    assert formula.expression_candidate == "F = 1/phi**2"
    assert source_contains_equation(formula, text)
    assert expression_variables(formula.expression_candidate) == {"phi"}


@pytest.mark.parametrize("source,target,remaining", [
    ("Pc = Po - Pf", "Po", {"Pc", "Pf"}),
    ("R = P - D", "P", {"R", "D"}),
    ("C = A + B", "A", {"C", "B"}),
    ("Q = X / Y", "X", {"Q", "Y"}),
])
@pytest.mark.parametrize("suffix", [" Both are pressures.", " These variables are measured values.",
                                    " Use the literal source relation."])
def test_algebraic_isolation_retains_literal_source_and_only_rhs_inputs(source, target, remaining, suffix):
    text = source + "." + suffix
    evidence = [{"evidence_id": "KB7", "source_type": "knowledge_base", "text": text,
                 "document": "pressure.pdf", "page": 8}]
    original = FormulaSourceRegistry.from_evidence(evidence).records[0]
    derived = isolated_source_formula(original, target, text)
    assert derived is not None
    assert derived.raw_span == original.raw_span == source
    assert derived.source_equation == original.expression_candidate
    assert derived.formula_derivation == "algebraic_isolation"
    assert derived.source_id == "KB7"
    assert derived.lhs == target
    assert expression_variables(derived.expression_candidate or "") == remaining
    assert source_contains_equation(derived, text)


def test_algebraic_isolation_rejects_a_source_with_a_clipped_additive_term():
    text = "Pc = Po - Pf. Both pressures are measured in psi."
    evidence = [{"evidence_id": "KB7", "source_type": "knowledge_base", "text": text}]
    original = FormulaSourceRegistry.from_evidence(evidence).records[0]
    derived = isolated_source_formula(original, "Po", text)
    assert derived is not None
    assert not source_contains_equation(derived, text.replace("Pf.", "Pf + Q."))


@pytest.mark.parametrize("name,source", [
    ("phi", "Porosity is a pore-volume fraction."),
    ("porosity", "Porosity is a pore-volume fraction."),
    ("Sw", "Water saturation is a fraction of pore volume."),
    ("SG", "Specific gravity is a density ratio."),
])
@pytest.mark.parametrize("value", [0.11, 0.27, 0.43])
def test_semantically_dimensionless_input_needs_no_unit(name, source, value):
    assert infer_dimensionless(name, source)
    facts = UserFactRegistry.from_topic(f"{name}={value}")
    assert len(facts.records) == 1 and not facts.records[0].unit


@pytest.mark.parametrize("code", [
    "calculation_contract_unit_missing", "fact_id_unknown", "formula_source_missing",
    "materialization_failed", "variable_binding_missing", "simulation_input_missing",
    "formula_source_missing:internal", "calculation_readiness_failed",
])
@pytest.mark.parametrize("korean", [True, False])
def test_internal_blockers_never_escape_public_clarification(code, korean):
    assert code not in public_missing_inputs([code])
    message = clarification_question([code], korean)
    assert code not in message
    assert "필요" in message if korean else "provide" in message.lower()


def test_rearranged_formula_executes_with_original_formula_provenance(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    source = ("In a pressure balance, Pc = Po - Pf. Pc is compacting pressure (psi), "
              "Po is overburden pressure (psi), and Pf is fluid pressure (psi).")
    text = "Find the internal equation for Po from Pf=1800 psi and Pc=20 psi. Calculate with citation."
    result = asyncio.run(GoalExecutionAgent(StaticResearch(source), object(),
                                            evaluator=PassingEvaluator()).run("GR-V23-ISOLATE", req(text)))
    assert result.status == GoalStatus.ACHIEVED, result.final_answer
    assert [row["action_type"] for row in result.action_history] == [
        "retrieve", "calculate", "verify", "synthesize", "stop"]
    calc = result.computations[0]
    assert calc.validation_passed and calc.formula_source_ids == ["KB1"]
    assert calc.output_manifest["OUT_RESULT"]["value"] == 1820
    assert "1820" in result.final_answer


@pytest.mark.parametrize("question", [
    "Compare carbonate and sand formation factor relations.",
    "교재 근거로 carbonate와 sand의 formation factor 경험식을 비교해줘.",
    "Find sand versus carbonate formation factor differences.",
    "Formation Evaluation에서 carbonate와 sand의 F 식을 각각 찾아 비교해줘.",
])
def test_comparative_retrieval_keeps_both_named_contexts_in_one_query(question):
    plan = plan_query(question)
    assert plan.queries
    assert "in " in plan.queries[0]
    assert "carbonate" in plan.queries[0] and "sand" in plan.queries[0]
    assert "formation" in plan.queries[0] and "factor" in plan.queries[0]


@pytest.mark.parametrize("prefix", ["I know", "we know", "I have", "Given", "Using"])
@pytest.mark.parametrize("connector", ["and", ","])
def test_prose_assignment_intro_and_trailing_clause_keep_literal_symbols(prefix, connector):
    sentence = f"{prefix} a=1 {connector} m=2 but porosity is not yet available."
    facts = UserFactRegistry.from_topic(sentence)
    assert {(item.name, item.value) for item in facts.records} == {("a", 1.0), ("m", 2.0)}


def test_semantic_judge_receives_literal_relation_even_when_embedding_prefers_distractors():
    class SpanJudge:
        async def chat_structured(self, messages, _schema, **_kwargs):
            import json
            payload = json.loads(messages[-1]["content"])
            matched = [p for p in payload["source_spans"] if
                       "lack of definiteness" in p["text"] and "derivative response" in p["text"]]
            return json.dumps({"claims": [{"claim_id": "CLAIM1", "status": "SUPPORTED" if matched else "UNSUPPORTED",
                                 "span_ids": [matched[0]["span_id"]] if matched else
                                 [payload["source_spans"][0]["span_id"]], "evidence_conflict": False}]})

    question = "What is the purpose of adding a pressure derivative to a type-curve match?"
    relation = ("The main difficulty with the basic type curve procedure is the lack of definiteness "
                "in the pressure match. Bourdet modified the type curve to include the derivative response.")
    evidence = [{"evidence_id": f"KB{i+1}", "source_type": "knowledge_base", "document": "welltest.pdf",
                 "page": i+1, "text": "\n".join(
                     f"Pressure derivative type curve vocabulary list {i}-{j}." for j in range(9))}
                for i in range(4)]
    evidence.append({"evidence_id": "KB5", "source_type": "knowledge_base",
                     "document": "welltest.pdf", "page": 7, "text": relation})
    def wrong_embedding(texts):
        return [[1.0, 0.0] for _ in texts]
    support = asyncio.run(semantic_claim_support(req(question), evidence, [], SpanJudge(), wrong_embedding))
    assert support.claims[0].support_status == SupportStatus.SUPPORTED
    assert support.claims[0].supporting_evidence_ids == ["KB5"]
    assert relation in support.claims[0].supporting_spans[0]
    assert support.diagnostics["exact_span_validation_passed"]


@pytest.mark.parametrize("singular,plural", [
    ("carbonate", "carbonates"), ("sand", "sands"), ("formation", "formations"),
    ("model", "models"), ("curve", "curves"),
])
def test_source_claim_lexicon_matches_bounded_singular_plural(singular, plural):
    assert singular in _terms(plural)


def test_dimensionless_formula_resume_preserves_source_and_bound_facts(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    source = ("Formation factor F is obtained from the measured porosity of the formation. "
              "F = a/fm where m is the cementation factor and a is a constant.")
    text = ("Use the internal formation factor equation to get F. "
            "I know a=1 and m=2 but porosity is not yet available.")
    request = req(text)
    agent = GoalExecutionAgent(StaticResearch(source), object(), evaluator=PassingEvaluator())
    waiting = asyncio.run(agent.run("GR-V23-DIM-RESUME", request))
    assert waiting.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT
    assert "phi" in (waiting.clarification_question or "").casefold()
    assert "unit" not in (waiting.clarification_question or "").casefold()
    checkpoint = dict(waiting.resume_checkpoint)
    checkpoint["user_replies"] = ["phi=0.2"]
    finished = asyncio.run(agent.run(waiting.run_id, request, resume_state=checkpoint,
                                     resume_result=waiting))
    assert finished.run_id == waiting.run_id and finished.status == GoalStatus.ACHIEVED
    assert sum(row["action_type"] == "calculate" for row in finished.action_history) == 1
    assert finished.computations[0].formula_source_ids == ["KB1"]
    assert finished.computations[0].validation_passed
    assert finished.computations[0].output_manifest["OUT_RESULT"]["value"] == pytest.approx(25)
    assert "dimensionless" in finished.final_answer


@pytest.mark.parametrize("formula,signs", [
    ("Y = k * X**n", "k > 0. n < 0."),
    ("Y = 2 * X**-1", ""),
    ("Z = a * t**p", "a = 3. p = -2."),
    ("Z = -2 * t**3", ""),
])
def test_verified_signed_power_can_reject_only_opposite_monotonic_premise(formula, signs):
    from app.services.premise_grounding import derive_safe_relation_from_equation
    output = formula.split("=", 1)[0].strip()
    variable = "X" if "X" in formula else "t"
    source = f"{formula}. {signs} {variable} > 0."
    question = f"For {variable} > 0, {output} increases as {variable} increases, correct?"
    result = derive_safe_relation_from_equation(question, {"KB9": source}, False)
    assert result.verdict == "contradicts"
    assert result.method == "sourced_signed_power"
    assert formula in result.answer and "[KB9]" in result.answer
    assert "decreases" in result.answer


@pytest.mark.parametrize("source", [
    "Y = k * X**n. X > 0.",
    "Y = k * X**n. k > 0. X > 0.",
    "Y = k * X**n. n < 0. X > 0.",
    "Y = k * X**n. k > 0. n < 0.",
    "Y = k * X**n. k > 0. k < 0. n < 0. X > 0.",
])
def test_signed_power_correction_refuses_unknown_or_conflicting_signs(source):
    from app.services.premise_grounding import derive_safe_relation_from_equation
    outcome = derive_safe_relation_from_equation("Y increases as X increases, correct?", {"KB1": source}, False)
    assert outcome.verdict == "insufficient"


def test_partial_knowledge_keeps_supported_criterion_met_without_full_goal_success():
    from app.models.goal_research_schemas import GoalCriterion, CriterionStatus
    criteria = [GoalCriterion(criterion_id="C1", description="Explain the sourced water-saturation definition"),
                GoalCriterion(criterion_id="C2", description="Explain an unverified field-scale consequence")]
    support = ClaimSupport([
        RequiredClaim("CLAIM1", criteria[0].description, True, SupportStatus.SUPPORTED,
                      ["KB1"], ["Water saturation is a fraction of pore volume."]),
        RequiredClaim("CLAIM2", criteria[1].description, True, SupportStatus.UNSUPPORTED),
    ])
    graded = GoalExecutionAgent._support_evaluation(criteria, support, False)
    assert [item.status for item in graded] == [CriterionStatus.MET, CriterionStatus.UNMET]
    assert graded[0].supporting_evidence == ["KB1"]
    assert not support.all_required_supported
    answer = grounded_answer(req(criteria[0].description + " and " + criteria[1].description), support)
    assert "Water saturation" in answer and "Not established" in answer


@pytest.mark.parametrize("question", [
    "Explain fractional flow in waterflood analysis from the internal text.",
    "For a waterflood, describe fractional flow using local engineering material.",
])
def test_waterflood_fractional_flow_retrieval_uses_domain_synonyms_not_an_answer(question):
    plan = plan_query(question)
    joined = plan.search_text.casefold()
    assert "fractional flow" in joined and "relative permeability" in joined
    assert "water" in joined and "injection" in joined
    assert "breakthrough saturation" not in joined


@pytest.mark.parametrize("question", [
    "Find a cited pressure equation for Po given Pf=1800 psi and Pc=25 psi.",
    "Po를 Pf=1700 psi, Pc=40 psi에서 내부 압력 관계식으로 계산해줘.",
])
def test_pressure_symbol_query_expands_source_terms_without_injecting_equation(question):
    joined = plan_query(question).search_text.casefold()
    assert "overburden pressure" in joined
    assert "fluid pressure" in joined
    assert "compacting stress" in joined
    assert "po = pf + pc" not in joined


class ClauseSplitter:
    def __init__(self, clauses):
        self.clauses = clauses

    async def chat_structured(self, *_args, **_kwargs):
        return json.dumps({"clauses": self.clauses})


@pytest.mark.parametrize("question,clauses", [
    ("Compare the carbonate and sand formation-factor expressions in the formation-evaluation material.",
     ["Compare", "the carbonate", "sand", "formation-factor", "expressions", "in the",
      "formation-evaluation", "material"]),
    ("Explain porosity and saturation from the source.",
     ["Explain", "porosity", "saturation from the source"]),
])
def test_atomic_claims_reject_wordwise_noun_phrase_splitting(question, clauses):
    claims = asyncio.run(atomic_claims(req(question), ClauseSplitter(clauses)))
    assert len(claims) == 1
    assert claims[0].description == question.rstrip(".")


def test_atomic_claims_keep_two_genuine_requested_relations():
    question = "Explain water saturation and describe capillary pressure."
    clauses = ["Explain water saturation", "describe capillary pressure"]
    claims = asyncio.run(atomic_claims(req(question), ClauseSplitter(clauses)))
    assert [claim.description for claim in claims] == clauses


@pytest.mark.parametrize("question", [
    "압력만 맞추는 type-curve 방법에 도함수를 더한 이유를 찾아줘.",
    "교재에서 type-curve를 맞추는 방법의 한계를 설명해줘.",
])
def test_pressure_matching_verb_is_not_a_false_premise_cue(question):
    assert route(question) == GoalIntentKind.KNOWLEDGE_QA


@pytest.mark.parametrize("question", [
    "압력 도함수가 항상 증가하는 게 맞지?",
    "유동이 radial일 때 unit slope가 맞나요?",
])
def test_explicit_korean_agreement_question_still_routes_to_premise_check(question):
    assert route(question) == GoalIntentKind.PREMISE_CHECK


@pytest.mark.parametrize("question", [
    "A documented relation says F climbs as porosity grows; is this true?",
    "When mud pressure exceeds formation pressure it causes a kick, doesn't it?",
    "Formation factor rises with porosity, is that correct?",
])
def test_english_assertion_verification_routes_to_premise_check(question):
    assert route(question) == GoalIntentKind.PREMISE_CHECK


@pytest.mark.parametrize("question", [
    "In a carbonate rock use the sourced formation-factor equation at phi=0.21 to obtain F.",
    "Use a cited Humble sand relation for formation factor with phi=0.31.",
    "For the internal formation-factor relation I know a=1 and m=2, but porosity is missing.",
])
def test_sourced_relation_with_named_inputs_is_formula_calculation(question):
    assert route(question) == GoalIntentKind.KB_FORMULA_CALC
    assert GoalExecutionAgent._requested_target(req(question)) == "F"


@pytest.mark.parametrize("text,names", [
    ("Use phi=0.18 to calculate F.", {"phi"}),
    ("Take phi=0.26 to find F.", {"phi"}),
    ("The values a=1 and m=2 are known.", {"a", "m"}),
    ("The values a=1 and m=2 are provided.", {"a", "m"}),
])
def test_explicit_assignment_survives_grammatical_following_words(text, names):
    assert names <= {row.name for row in UserFactRegistry.from_topic(text).records}


@pytest.mark.parametrize("question", [
    "P_in=53 psi, P_out=17 psi. Determine P_in-P_out.",
    "A=97 psi, B=41 psi. Find A-B.",
])
def test_named_subtraction_uses_supplied_order_without_retrieval(question):
    facts = UserFactRegistry.from_topic(question)
    selected = parse_request_ir(req(question), []).requested_operation_types
    assert route(question) == GoalIntentKind.DIRECT_CALC
    assert "difference" in selected
    assert direct_readiness(question, facts, selected) == []
    order, missing = direct_operation_operands(question, facts, selected)
    assert not missing and "difference" in order


@pytest.mark.parametrize("question,expected", [
    ("Measurements A=8 psi, B=2 psi, C=6 psi. Give both extrema.", {"maximum", "minimum"}),
    ("Rate changes from 310 to 248 stb/d. State absolute and percentage declines.",
     {"difference", "percentage_decrease"}),
])
def test_compound_direct_requests_keep_both_outputs(question, expected):
    assert route(question) == GoalIntentKind.DIRECT_CALC
    assert expected <= set(parse_request_ir(req(question), []).requested_operation_types)


@pytest.mark.parametrize("phrase,operation", [
    ("Which reading is largest?", "maximum"),
    ("Tell me the smallest value.", "minimum"),
    ("Identify the highest pressure.", "maximum"),
    ("Report the lowest reading.", "minimum"),
])
def test_comparative_extrema_use_direct_arithmetic_without_kb(phrase, operation):
    text = f"A=44 psi, B=62 psi, C=37 psi. {phrase}"
    facts = UserFactRegistry.from_topic(text)
    assert route(text) == GoalIntentKind.DIRECT_CALC
    assert operation in parse_request_ir(req(text), []).requested_operation_types
    assert direct_readiness(text, facts, [operation]) == []


def test_gor_role_binding_accepts_descriptive_fact_names_without_guessing_generic_ratio():
    question = "Produced gas=1850 scf and oil=50 stb. Calculate gas/oil ratio."
    facts = UserFactRegistry.from_topic(question)
    selected, missing = direct_operation_operands(question, facts, ["ratio"])
    assert selected["ratio"] == ("Produced_gas", "oil") and not missing
    ambiguous = "Gas volume=1850 scf and oil volume=50 stb. Calculate their ratio."
    selected, missing = direct_operation_operands(ambiguous, UserFactRegistry.from_topic(ambiguous), ["ratio"])
    assert not selected and missing  # numerator order cannot be invented


def test_missing_symbol_in_explicit_arithmetic_is_a_clarification_blocker():
    question = "A=73 stb/d. I will send B next; then give A+B."
    facts = UserFactRegistry.from_topic(question)
    assert "B 값" in direct_readiness(question, facts, ["sum"])


def test_formula_query_keeps_hyphenated_relation_and_supplied_symbols():
    plan = plan_query("Find the formation-factor relation at phi=0.2, a=1 and m=2.")
    assert "formation factor porosity cementation factor" in plan.search_text
    assert "in relations in" not in plan.search_text


def test_lithology_and_named_model_disambiguate_literal_parallel_equations():
    source = ("Formation factor F is obtained from measured porosity φ. For φ = 10%, F = 100.\n"
              "in carbonates, F = 1/φ2 is usually used;\n"
              "in sands, F = 0.62/φ2.15 (Humble formula), or\n"
              "F = 0.81/φ2 (a simpler form practically equivalent to the Humble formula).\n"
              "Within their normal range these two ways of expressing the Humble formula yield similar results.")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": source,
                 "document": "formation-evaluation.pdf", "locator": "165"}]
    for query, expected in [
        ("For a carbonate rock, use its sourced formation-factor equation at phi=0.2 to get F.",
         "F = 1/φ2"),
        ("Apply the cited Humble sand relation for formation factor at phi=0.2.",
         "F = 0.62/φ2.15"),
    ]:
        contract = formula_target_contract(query, ["phi"], requested_target="F")
        selected, _ = rank_formula_candidates(evidence, query, ["phi"], target_contract=contract)
        assert selected is not None and expected in selected.raw_span
        assert source_contains_equation(selected, source)


def test_extracted_inverse_power_corrects_growth_wording_only_from_literal_source():
    source = "For porosity φ = 10%, the formation factor relation is F = 1/φ2."
    question = "Formation factor F grows as porosity increases, is this true?"
    correction = derive_safe_relation_from_equation(question, {"KB1": source}, False)
    assert correction.verdict == "contradicts"
    assert "decreases" in correction.answer and "[KB1]" in correction.answer
    assert correction.quote in source


def test_generic_porosity_context_does_not_choose_a_specific_model_and_ignore_supplied_exponent():
    evidence = [
        {"evidence_id": "KB1", "source_type": "knowledge_base",
         "text": "Formation factor F is obtained from measured porosity. "
                 "F = a/fm where m is the cementation factor and a is a constant.",
         "document": "guide.pdf", "locator": "164"},
        {"evidence_id": "KB2", "source_type": "knowledge_base",
         "text": "For porosity φ = 10%, F=100. In sands F = 0.62/φ2.15 (Humble formula).",
         "document": "guide.pdf", "locator": "165"},
    ]
    query = "Get F from the internal porosity relation; phi=0.27 and m=2 are known, but a is not."
    contract = formula_target_contract(query, ["phi", "m"], requested_target="F")
    selected, _ = rank_formula_candidates(evidence, query, ["phi", "m"], target_contract=contract)
    assert selected is not None and selected.source_id == "KB1"
    assert expression_variables(selected.expression_candidate) == {"a", "phi", "m"}


@pytest.mark.parametrize("presentation", [
    "Use only the local textbook",
    "Please give a short cited explanation",
    "Focus on the exact source relation",
    "한 문단으로 근거를 포함해 설명해줘",
])
def test_presentation_preface_does_not_change_retrieval_or_claim_terms(presentation):
    question = "교재에서 물 포화도가 공극 체적 중 무엇을 나타내는지 밝혀줘."
    wrapped = f"{presentation}: {question}"
    assert substantive_question(wrapped) == question
    assert plan_query(wrapped).queries == plan_query(question).queries
    assert _terms(wrapped) == _terms(question)


def test_factual_colon_clause_is_not_discarded_as_presentation():
    question = "Water saturation: compare irreducible and initial values."
    assert substantive_question(question) == question


@pytest.mark.parametrize("presentation", [
    "Check this against internal sources", "Explicitly correct my premise",
    "Cite the literal source relation", "근거와 대조해서 답해줘",
])
def test_premise_presentation_preface_does_not_change_claim_or_retrieval(presentation):
    question = "Radial flow derivative rises with unit slope, correct?"
    wrapped = f"{presentation}: {question}"
    assert substantive_question(wrapped) == question
    assert plan_query(wrapped, premise=True).queries == plan_query(question, premise=True).queries
    assert _terms(wrapped) == _terms(question)


def test_named_lithology_span_beats_same_equation_in_generic_example():
    evidence = [
        {"evidence_id": "KB1", "source_type": "knowledge_base", "document": "guide.pdf",
         "locator": "10", "text": "In carbonates, F = 1/phi^2 is usually used; "
         "in sands, F = 0.62/phi^2.15 may be used."},
        {"evidence_id": "KB2", "source_type": "knowledge_base", "document": "guide.pdf",
         "locator": "12", "text": "For this formation, the most appropriate F relation is F = 1/phi^2. "
         "Thus, at phi = 0.1, F is 100."},
    ]
    question = "Apply the sourced carbonate formation-factor relation at phi=0.185 to find F."
    contract = formula_target_contract(question, ["phi"], requested_target="F")
    selected, _ = rank_formula_candidates(evidence, question, ["phi"], target_contract=contract)
    assert selected is not None and selected.source_id == "KB1"
    assert source_contains_equation(selected, evidence[0]["text"])


def test_learning_objectives_are_not_sent_as_factual_evidence_to_semantic_judge():
    objective = ("LEARNING OBJECTIVES\n• Present a simple equation for fractional flow of water.\n"
                 "• Comment on the impact of viscosity on fractional flow.")
    factual = ("Relative permeability affects waterflood performance through the fractional "
               "flow equation, as does the viscosity ratio.")
    assert _instructional_span(objective)
    assert not _instructional_span(factual)

    class SpanJudge:
        async def chat_structured(self, messages, _schema, **_kwargs):
            payload = json.loads(messages[-1]["content"])
            assert payload["source_spans"]
            assert all(not _instructional_span(item["text"]) for item in payload["source_spans"])
            chosen = next(item for item in payload["source_spans"] if factual in item["text"])
            return json.dumps({"claims": [{"claim_id": "CLAIM1", "status": "SUPPORTED",
                "span_ids": [chosen["span_id"]], "evidence_conflict": False}]})

    evidence = [
        {"evidence_id": "KB1", "source_type": "knowledge_base", "text": objective,
         "document": "lecture.pdf", "page": 1},
        {"evidence_id": "KB2", "source_type": "knowledge_base", "text": factual,
         "document": "lecture.pdf", "page": 2},
    ]
    support = asyncio.run(semantic_claim_support(
        req("Explain how fractional flow informs waterflood performance."),
        evidence, [], SpanJudge()))
    assert support.claims[0].support_status == SupportStatus.SUPPORTED
    assert support.claims[0].supporting_evidence_ids == ["KB2"]


def test_relation_query_rephrases_informs_without_supplying_an_answer():
    plan = plan_query("Explain how fractional flow informs waterflood interpretation from a textbook.")
    assert plan.queries[0] == "fractional flow determines waterflood interpretation"
    assert "breakthrough" not in plan.search_text and "production" not in plan.search_text
