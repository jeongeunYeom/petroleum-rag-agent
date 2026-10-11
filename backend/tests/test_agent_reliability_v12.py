"""Synthetic development cases; no frozen benchmark prompts or answer keys."""

from __future__ import annotations

import asyncio
import ast
import math
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import (CriterionEvaluation, CriterionStatus,
                                              ExpectedResultStatus, GoalCriterion,
                                              GoalResearchRequest)
from app.services.calculation_request_ir import parse_request_ir
from app.services.calculation_requirements import infer_dimensionless, rank_formula_candidates
from app.services.goal_clarification import parse_user_simulation_spec, user_simulation_missing
from app.services.goal_intent import FormulaOrigin, GoalIntentKind, classify_goal_intent
from app.services.goal_intent import SourceRequirement
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_evaluator import GoalEvaluationResult
from app.services.goal_execution_state import GoalActionType, GoalExecutionState
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_simulation import (direct_readiness, run_direct_arithmetic,
                                          run_user_formula_calculation, user_formula_bindings,
                                          _formula_output_unit)
from app.services.user_fact_registry import UserFactRegistry, normalize_unit


FACTS = [
    ("rate=125 gpm", "gpm"), ("power=55 kW", "kW"), ("energy=90 kWh", "kWh"),
    ("motor=60 hp", "hp"), ("weight=120 lbf/ft", "lbf/ft"),
    ("line=120 lb/ft", "lbf/ft"), ("kh=6000 mD·ft", "mD*ft"),
    ("kv=6000 mD*ft", "mD*ft"), ("layer=6000 md-ft", "mD*ft"),
    ("volume=800 m³/day", "m3/d"), ("volume=120 m3/hr", "m3/h"),
    ("capacity=80 ft³", "ft3"), ("diameter=4 inch", "in"),
    ("length=1000 ft", "ft"), ("mass=15 kg", "kg"),
    ("tracer=50 mg", "mg"), ("water=5 L", "L"),
    ("concentration=4 mg/L", "mg/L"), ("density=900 kg/m3", "kg/m3"),
    ("decline=2 psi/day", "psi/d"), ("production=200 stb/h", "stb/h"),
    ("speed=3 m/s", "m/s"), ("duration=2 days", "d"),
    ("elapsed=30 seconds", "s"), ("Sw=0.25 dimensionless", "dimensionless"),
]


@pytest.mark.parametrize("text,expected_unit", FACTS)
def test_fact_unit_vocabulary_preserves_raw_span(text, expected_unit):
    rows = UserFactRegistry.from_topic(text).records
    assert len(rows) == 1, (text, rows)
    assert rows[0].canonical_unit == expected_unit
    assert rows[0].raw_unit in text and rows[0].value_span and rows[0].unit_span
    assert rows[0].source_span in text


def test_value_unit_locality_and_entity_series():
    trap = "80 stb/d이고 가중시간은 3시간"
    registry = UserFactRegistry.from_topic(trap)
    added, rejected = registry.add_literal_fallback(trap, [{"name": "duration", "value": 3,
                                                            "unit": "stb/d", "source_quote": trap}])
    assert (added, rejected) == (0, 1)
    assert registry.rejection_reasons == ["value_unit_not_local"]
    segments = UserFactRegistry.from_topic("첫 구간은 100 stb/d로 3시간, 둘째는 200 stb/d로 2시간")
    assert {row.name: row.value for row in segments.records} == {
        "segment_1_rate": 100, "segment_1_duration": 3,
        "segment_2_rate": 200, "segment_2_duration": 2}
    pumps = UserFactRegistry.from_topic("펌프 전력은 각각 55, 40, 65 kW, 모두 6시간")
    assert [row.value for row in pumps.records if row.semantic_role == "power"] == [55, 40, 65]
    assert any(row.name == "shared_duration" and row.value == 6 for row in pumps.records)
    series = UserFactRegistry.from_topic("측정값은 4, 6, 8 mD")
    assert [row.value for row in series.records] == [4, 6, 8]
    rates = UserFactRegistry.from_topic("입구 500 gpm에서 출구 425 gpm")
    assert [row.value for row in rates.records if row.unit == "gpm"] == [500, 425]


ORIGINS = [
    ("내부 자료의 qo=qt-qw 관계로 계산해줘", GoalIntentKind.KB_FORMULA_CALC, FormulaOrigin.KB_REFERENCED),
    ("내가 정의한 qo=qt-qw로 계산해줘", GoalIntentKind.USER_FORMULA_CALC, FormulaOrigin.USER_DEFINED),
    ("Find the textbook equation qo=qt-qw and compute qo", GoalIntentKind.KB_FORMULA_CALC, FormulaOrigin.KB_REFERENCED),
    ("Use this equation qo=qt-qw to compute qo", GoalIntentKind.USER_FORMULA_CALC, FormulaOrigin.USER_DEFINED),
    ("교재에 나온 식 Mg=Gi-Gp를 확인하고 Mg는 얼마인가?", GoalIntentKind.KB_FORMULA_CALC, FormulaOrigin.KB_REFERENCED),
    ("자료에서 확인한 관계식 Pt=Psc+Pd+Pb+Pa로 산출해줘", GoalIntentKind.KB_FORMULA_CALC, FormulaOrigin.KB_REFERENCED),
]


@pytest.mark.parametrize("text,kind,origin", ORIGINS)
def test_formula_origin_precedes_literal_equation(text, kind, origin):
    request = GoalResearchRequest(topic=text, goal=text)
    intent = classify_goal_intent(request, has_user_facts=False)
    assert (intent.kind, intent.formula_origin) == (kind, origin)
    ir = parse_request_ir(request, [])
    assert ir.requires_domain_formula == (origin == FormulaOrigin.KB_REFERENCED)


DIRECT = [
    ("rate=240 stb/d. Convert to stb/h.", "unit_conversion", 10, "stb/h"),
    ("rate=480 stb/d. Convert to stb/h.", "unit_conversion", 20, "stb/h"),
    ("duration=2 day. Convert to h.", "unit_conversion", 48, "h"),
    ("duration=3 day. Convert to h.", "unit_conversion", 72, "h"),
    ("diameter=4 in, length=100 ft. Calculate cylinder volume.", "cylinder_volume", math.pi/36*100, "ft3"),
    ("diameter=6 in, length=120 ft. Calculate cylinder volume.", "cylinder_volume", math.pi/16*120, "ft3"),
    ("diameter=4 in, length=100 ft. Calculate cylinder volume in bbl.", "cylinder_volume", math.pi/36*100/5.615, "bbl"),
    ("diameter=4 in, length=100 ft, conversion_factor=6. Calculate cylinder volume in bbl using this conversion factor.", "cylinder_volume", math.pi/36*100/6, "bbl"),
    ("mass=30 mg, volume=5 L. Calculate mass concentration.", "concentration_mass_per_volume", 6, "mg/L"),
    ("mass=45 mg, volume=9 L. Calculate mass concentration.", "concentration_mass_per_volume", 5, "mg/L"),
    ("initial=100 psi, final=80 psi. Find percentage decrease.", "percentage_decrease", 20, "%"),
    ("initial=200 psi, final=150 psi. Find percentage decrease.", "percentage_decrease", 25, "%"),
    ("initial=100 psi, final=80 psi. Find net difference.", "net_difference", -20, "psi"),
    ("initial=70 psi, final=100 psi. Find net difference.", "net_difference", 30, "psi"),
    ("x 0: 2; x 2: 6. Calculate finite difference.", "finite_difference", 2, None),
    ("x 1: 3; x 5: 15. Calculate finite difference.", "finite_difference", 3, None),
    ("x 0: 1; x 1: 4; x 2: 9. Calculate centered difference.", "centered_difference", 4, None),
    ("x 0: 2; x 1: 6; x 2: 10. Calculate centered difference.", "centered_difference", 4, None),
    ("x 0: 1; x 1: 3; x 2: 5. Find linear regression slope.", "linear_regression_slope", 2, None),
    ("x 0: 1; x 1: 4; x 2: 7. Find linear regression slope.", "linear_regression_slope", 3, None),
    ("pump power 55, 40, 65 kW, all 6 h. Calculate energy use.", "power_times_duration", 960, "kWh"),
    ("pump power 10, 20, 30 kW, all 2 h. Calculate energy use.", "power_times_duration", 120, "kWh"),
    ("첫 구간은 100 stb/d로 3시간, 둘째는 200 stb/d로 2시간. 시간 가중 평균을 계산해줘.", "weighted_average_by_duration", 140, "stb/d"),
    ("첫 구간은 90 stb/d로 1시간, 둘째는 120 stb/d로 2시간. 시간 가중 평균을 계산해줘.", "weighted_average_by_duration", 110, "stb/d"),
    ("A=4, B=8, C=12. Find median.", "median", 8, None),
    ("A=5, B=10, C=15. Find mean.", "mean", 10, None),
    ("A=5, B=10, C=15. Find sum.", "sum", 30, None),
]


@pytest.mark.parametrize("text,operation,expected,unit", DIRECT)
def test_direct_operation_v3_bounded_python(text, operation, expected, unit, tmp_path):
    request = GoalResearchRequest(topic=text, goal=text, allow_python_execution=True,
                                  python_execution_approved=True)
    facts = UserFactRegistry.from_topic(text)
    intent = classify_goal_intent(request, has_user_facts=bool(facts.records))
    assert intent.kind == GoalIntentKind.DIRECT_CALC
    operations = parse_request_ir(request, []).requested_operation_types
    assert operations == [operation], (text, operations)
    assert direct_readiness(text, facts, operations) == []
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    result = asyncio.run(run_direct_arithmetic(settings, request, "DEV-V12", facts, operations, "CALC1"))
    row = result.output_manifest[f"OUT_{operation}"]
    assert result.validation_passed and result.execution_hash and result.input_fact_ids
    assert math.isclose(row["value"], expected, rel_tol=1e-8)
    if unit:
        assert row["unit"] == unit


FORMULAS = [
    ("Pt", "Pt = Psc + Pd + Pb + Pa", ["Psc", "Pd", "Pb", "Pa"], "four-component total pressure"),
    ("qo", "qo = qt - qw", ["qt", "qw"], "oil rate from total and water rates"),
    ("anis", "anis = kh / kv", ["kh", "kv"], "permeability anisotropy"),
    ("Mg", "Mg = Gi - Gp", ["Gi", "Gp"], "current gas mass"),
    ("F", "F = WOB * a", ["WOB", "a"], "force from weight on bit"),
]


@pytest.mark.parametrize("lhs,equation,variables,context", FORMULAS)
@pytest.mark.parametrize("variant", range(4))
def test_realistic_multi_equation_page_selects_literal_span(lhs, equation, variables, context, variant):
    noise = "\n".join(f"({index}) unrelated_{index} = x{index} + y{index}"
                       for index in range(1, 16))
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": noise + f"\n(16) {context}: {equation}\n(17) Reduced alternative: {lhs} = z + q\n"}]
    intent = [
        f"Calculate {lhs} with {context} using {', '.join(variables)}",
        f"Find the {context} relation for {lhs}; not the reduced form",
        f"{context} 식에서 {lhs}을 {', '.join(variables)}로 계산하고 축약식은 제외해줘",
        f"Use the full {context} expression for {lhs}, excluding the simplified two-term form",
    ][variant]
    selected, record = rank_formula_candidates(evidence, intent, variables)
    assert selected and selected.expression_candidate == equation, (intent, record)
    assert record.candidates_found >= 1 and record.lhs_match


def test_structural_term_count_disambiguates_same_lhs_without_guessing():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "Total pressure: Pt = Psc + Pd + Pb + Pa\n"
                         "Reduced pressure: Pt = Pb + Ps\n"}]
    selected, ranking = rank_formula_candidates(
        evidence, "Use the four-component Pt equation, not the two-term reduced form",
        ["Psc", "Pd", "Pb", "Pa", "Ps"])
    assert selected and selected.expression_candidate == "Pt = Psc + Pd + Pb + Pa"
    assert ranking.term_count_match and ranking.requested_structure_match
    ambiguous, record = rank_formula_candidates(evidence, "Pt equation", [])
    assert ambiguous is None and record.selection_reason == "ambiguous_literal_formulas"


@pytest.mark.parametrize("name,source", [
    ("Sim", "Sim is the initial movable saturation fraction."),
    ("Sw", "Sw is water saturation ratio."),
    ("x", "x is a dimensionless ratio."),
    ("phi", "Porosity fraction phi is defined here."),
    ("q", "The symbol q is explicitly dimensionless."),
])
def test_dimensionless_requires_local_definition_or_semantic_role(name, source):
    assert infer_dimensionless(name, source) is not None
    assert infer_dimensionless("unrelated", source) is None


def test_dimensionless_quotient_requires_explicit_matching_operand_units():
    assert infer_dimensionless("R", "R = P1 / P2. P1 (psi), P2 (psi).") ["source"] == "same_dimension_quotient"
    assert infer_dimensionless("R", "R = P1 / P2. P1 (psi), P2 (ft).") is None


@pytest.mark.parametrize("a,b", [(2, 3), (3, 5), (4, 7), (5, 11), (6, 13)])
@pytest.mark.parametrize("wording", ["Use my formula", "내가 정의한 식으로 계산해줘"])
def test_user_formula_has_literal_user_provenance(a, b, wording, tmp_path):
    text = f"a={a}, b={b}. result=a*b+2. {wording}."
    request = GoalResearchRequest(topic=text, goal=text, allow_python_execution=True,
                                  python_execution_approved=True)
    facts = UserFactRegistry.from_topic(text)
    intent = classify_goal_intent(request, has_user_facts=True)
    assert intent.kind == GoalIntentKind.USER_FORMULA_CALC
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    result = asyncio.run(run_user_formula_calculation(settings, request, "DEV-V12", intent.user_equation,
                                                      facts, "CALC1", f"USERF{len(facts.records)+1}"))
    assert result.validation_passed and result.formula_source_ids[0].startswith("USERF")
    assert result.output_manifest["OUT_RESULT"]["value"] == a * b + 2


def test_formula_output_unit_propagates_through_nested_sums_and_quotients():
    assert _formula_output_unit(ast.parse("Psc+Pd+Pb+Pa", mode="eval").body,
                                {name: "psi" for name in ("Psc", "Pd", "Pb", "Pa")}) == "psi"
    assert _formula_output_unit(ast.parse("mass/volume", mode="eval").body,
                                {"mass": "kg", "volume": "m3"}) == "kg/m3"
    assert _formula_output_unit(ast.parse("P1/P2", mode="eval").body,
                                {"P1": "psi", "P2": "psi"}) == ""
    with pytest.raises(ValueError, match="incompatible user formula units"):
        _formula_output_unit(ast.parse("P1 + volume", mode="eval").body,
                             {"P1": "psi", "volume": "m3"})


@pytest.mark.parametrize("c", [2, 3, 4, 5, 6])
@pytest.mark.parametrize("range_text", ["x=1부터 5까지 1 간격", "x from 1 to 5 step 1"])
def test_sweep_and_resume_fact_merge(c, range_text):
    initial = f"score=c*x. {range_text}. 최적값을 계산해줘."
    before = UserFactRegistry.from_topic(initial)
    assert parse_user_simulation_spec(initial) is None
    assert user_simulation_missing(initial, "score=c*x", before) == ["c 값"]
    after = UserFactRegistry.from_messages([initial, f"c={c}"])
    spec = parse_user_simulation_spec(initial + f" c={c}")
    assert spec and spec.fixed_fact_ids["c"] in {row.fact_id for row in after.records}
    assert spec.parameter.start == 1 and spec.parameter.stop == 5 and spec.parameter.step == 1


@pytest.mark.parametrize("value", [3, 4, 5, 6, 7])
@pytest.mark.parametrize("reply", ["b={value}", "b is {value}"])
def test_followup_fact_merges_without_losing_original(value, reply):
    initial = "a=2. out=a*b. Calculate out."
    users = UserFactRegistry.from_messages([initial, reply.format(value=value)])
    bound, missing = user_formula_bindings("out=a*b", users)
    assert not missing and {name: fact.value for name, fact in bound.items()} == {"a": 2, "b": value}


def _partial(criteria):
    return GoalEvaluationResult(
        criteria=[CriterionEvaluation(criterion_id=item.criterion_id, status=CriterionStatus.PARTIAL,
                                      reason="LLM said partial") for item in criteria],
        coverage=.5, achieved=False, expected_result_status=ExpectedResultStatus.NOT_PROVIDED,
        gaps=["stale criterion"], next_research_need=None, engineering_validation_passed=True,
        engineering_contradiction_count=0, unsupported_engineering_claim_count=0,
        goal_conflicts_with_evidence=False)


def test_validated_user_calculation_overrides_stale_operational_grade(monkeypatch):
    criteria = [GoalCriterion(criterion_id="C1", description="Use the supplied values"),
                GoalCriterion(criterion_id="C2", description="Show validated result")]
    calc = SimpleNamespace(validation_passed=True, contract_validation_passed=True,
        computation_id="CALC1", formula_source_ids=["USERF3"], input_fact_ids=["USERF1", "USERF2"],
        output_manifest={"OUT_RESULT": {"value": 30, "required": True, "unit": None}})
    monkeypatch.setattr(GoalExecutionAgent, "_provenance_complete", lambda *_args: True)
    evidence = [{"evidence_id": value} for value in ("USERF1", "USERF2", "USERF3")]
    result = GoalExecutionAgent._deterministic_calculation_criteria(
        _partial(criteria), criteria, "result: 30 [CALC1]", [calc], evidence,
        SourceRequirement.USER_FORMULA)
    assert result.achieved and all(item.status == CriterionStatus.MET for item in result.criteria)
    bad = replace(_partial(criteria), engineering_validation_passed=False)
    assert not GoalExecutionAgent._deterministic_calculation_criteria(
        bad, criteria, "result: 30 [CALC1]", [calc], evidence,
        SourceRequirement.USER_FORMULA).achieved


def test_unit_criterion_distinguishes_pa_variable_from_psi_unit(monkeypatch):
    criteria = [
        GoalCriterion(criterion_id="C1", description="Calculate Pt = Psc + Pd + Pb + Pa"),
        GoalCriterion(criterion_id="C2", description="Report the result in psi"),
    ]
    calc = SimpleNamespace(validation_passed=True, contract_validation_passed=True,
        computation_id="CALC1", formula_source_ids=["KB1"], input_fact_ids=["USERF1"],
        output_manifest={"OUT_RESULT": {"value": 1000, "required": True, "unit": "psi"}})
    monkeypatch.setattr(GoalExecutionAgent, "_provenance_complete", lambda *_args: True)
    evidence = [{"evidence_id": "KB1"}, {"evidence_id": "USERF1"}]
    answer = "Pt: 1000 psi [CALC1] [KB1]"
    result = GoalExecutionAgent._deterministic_calculation_criteria(
        _partial(criteria), criteria, answer, [calc], evidence, SourceRequirement.KB_FORMULA)
    assert result.achieved
    calc.output_manifest["OUT_RESULT"]["unit"] = None
    assert not GoalExecutionAgent._deterministic_calculation_criteria(
        _partial(criteria), criteria, answer, [calc], evidence, SourceRequirement.KB_FORMULA).achieved


@pytest.mark.parametrize("criterion", [
    "Calculate the result from supplied values", "Show a validated numeric result",
    "Report the formula output", "Use the provided input values",
    "Compute the mean", "Provide the result in psi",
    "제공된 값으로 계산", "검증된 결과 제시", "공식 계산값을 표시", "단위 psi를 명시",
])
def test_calculation_finalization_overrides_stale_operational_criteria(criterion, monkeypatch):
    criteria = [GoalCriterion(criterion_id="C1", description=criterion)]
    calc = SimpleNamespace(validation_passed=True, contract_validation_passed=True,
        computation_id="CALC1", formula_source_ids=["USERF2"], input_fact_ids=["USERF1"],
        output_manifest={"OUT_RESULT": {"value": 100, "required": True, "unit": "psi"}})
    monkeypatch.setattr(GoalExecutionAgent, "_provenance_complete", lambda *_args: True)
    result = GoalExecutionAgent._deterministic_calculation_criteria(
        _partial(criteria), criteria, "result: 100 psi [CALC1]", [calc],
        [{"evidence_id": "USERF1"}, {"evidence_id": "USERF2"}],
        SourceRequirement.USER_FORMULA)
    assert result.achieved and result.criteria[0].status == CriterionStatus.MET


def test_resume_current_fact_satisfies_initial_missing_criterion():
    criteria = [GoalCriterion(criterion_id="C1", description="c 값이 없어서 기다림")]
    calc = SimpleNamespace(validation_passed=True, computation_id="CALC1",
        source_input_ids=["USERF1", "USERF2"], bound_variables={"c": "USERF2"},
        output_manifest={"OUT_CASE_001": {}})
    result = GoalExecutionAgent._deterministic_simulation_criteria(
        _partial(criteria), criteria, "x=1, score=4 [CALC1]\nBest x=1, score=4 [CALC1]", calc)
    assert result.achieved and result.criteria[0].status == CriterionStatus.MET


def test_literal_formula_ready_forces_calculate_next_action():
    text = "Po=3000 psi, Pw=2700 psi. 내부 문서의 Pc=Po-Pw 식을 확인하고 계산해줘."
    request = GoalResearchRequest(topic=text, goal=text, allow_python_execution=True,
                                  python_execution_approved=True)
    intent = classify_goal_intent(request, has_user_facts=True)
    state = GoalExecutionState.from_criteria("DEV", text, [GoalCriterion(criterion_id="C1", description="Calculate Pc")])
    state.evidence_ids = ["KB1"]
    action = GoalActionPlanner.select(request, state, user_fact_ids=["USERF1", "USERF2"],
                                      evidence_fact_ids=[], formula_ready=True,
                                      formula_id="FORMULA1", formula_inputs_ready=True,
                                      simulation_spec=None, intent=intent)
    assert action.action_type == GoalActionType.CALCULATE
