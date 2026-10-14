"""Fresh development-only paraphrase and safety checks for the V23 live demo.

These cases exercise general parsing/binding rules. They are not a final benchmark.
"""

import asyncio
import re
import time

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import (GoalResearchRequest, GoalResearchResponse,
                                             GoalRunStatus, GoalStatus, GoalStopReason)
from app.services.calculation_request_ir import OPERATIONS
from app.services.calculation_request_ir import parse_request_ir
from app.services.formula_source_registry import FormulaSourceRegistry, source_contains_equation
from app.services.calculation_requirements import rank_formula_candidates, formula_target_contract
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_execution_state import GoalExecutionState
from app.services.goal_intent import (GoalIntentKind, classify_goal_intent,
                                      clearly_out_of_domain, user_equation)
from app.services.goal_knowledge_retrieval import bilingual_recovery_query, plan_query
from app.services.goal_research_service import GoalResearchService
from app.services.source_answerability import _terms
from app.services.premise_grounding import (derive_safe_relation_from_equation,
                                             _sourced_engineering_rule_correction)
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
