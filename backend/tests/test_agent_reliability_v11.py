"""Synthetic v11 development regressions; no frozen benchmark prompts or answers."""

from __future__ import annotations

import asyncio
import math

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import GoalResearchRequest
from app.services.calculation_requirements import rank_formula_candidates
from app.services.calculation_request_ir import parse_request_ir
from app.services.goal_clarification import parse_user_simulation_spec
from app.services.goal_intent import GoalIntentKind, classify_goal_intent
from app.services.goal_simulation import direct_readiness, run_direct_arithmetic, user_formula_bindings
from app.services.user_fact_registry import UserFactRegistry, normalize_unit


FACT_CASES = [
    ("depth", "m", ("Depth is 825 m.", "Depth: 825 m.", "depth=825 m.")),
    ("temperature", "°C", ("Temperature is 62 °C.", "Temperature: 62 °C.", "temperature=62 °C.")),
    ("q", "m3/h", ("유량은 17 m³/h입니다.", "유량: 17 m³/h.", "유량은 17 m^3/h.")),
    ("length", "mm", ("길이는 18 mm입니다.", "길이: 18 mm.", "길이가 18 mm일 때")),
    ("pressure", "psi", ("압력은 2100 psi입니다.", "압력: 2100 psi.", "압력이 2100 psi이면")),
    ("segment_1", "h", ("첫 구간은 6 h.", "첫 구간에서 6 h.", "첫 구간은 6 hours.")),
    ("day_0", "", ("day 0: 8", "day 0에는 8", "day 0 = 8")),
    ("time", "h", ("시간은 4 hours.", "시간: 4 hr.", "시간이 4 h입니다.")),
    ("X_weight", "", ("X:Y=2:3", "세 패턴 X:Y=2:3", "weights X:Y=2:3")),
    ("start_time", "min", ("21:30 start, 01:10 end", "Start at 21:30 and end at 01:10", "21:30에 시작해 다음 날 01:10")),
    ("rho", "kg/m3", ("rho=1050 kg/m³", "rho: 1050 kg/m^3", "rho = 1050 kg/m3")),
    ("area", "m2", ("면적은 25 m².", "면적: 25 m^2.", "면적이 25 m2일 때")),
]


@pytest.mark.parametrize("case", FACT_CASES, ids=[row[0] for row in FACT_CASES])
def test_natural_fact_paraphrases(case):
    name, unit, variants = case
    for text in variants:
        rows = [row for row in UserFactRegistry.from_topic(text).records if row.name == name]
        assert len(rows) == 1, (text, rows)
        assert rows[0].canonical_unit == unit
        assert rows[0].source_span in text


@pytest.mark.parametrize("raw,canonical", [
    ("m³", "m3"), ("m²", "m2"), ("m³/s", "m3/s"), ("m³/d", "m3/d"),
    ("m³/h", "m3/h"), ("kg/m³", "kg/m3"), ("mm⁻¹", "1/mm"),
    ("psi⁻¹", "1/psi"), ("시간", "h"), ("hours", "h"), ("달러", "USD"),
])
def test_unit_normalization_preserves_raw_source(raw, canonical):
    assert normalize_unit(raw) == canonical
    fact = UserFactRegistry.from_topic(f"x=3 {raw}").records[0]
    assert fact.raw_unit == raw and fact.canonical_unit == canonical and raw in fact.source_span


def test_embedded_assignment_binds_symbol_not_leading_sentence():
    facts = UserFactRegistry.from_topic("A fluid specimen has SG=0.879. Calculate its conversion.")
    assert [(row.name, row.value) for row in facts.records] == [("SG", .879)]


def test_literal_fallback_rejects_nonexistent_quotes_and_values():
    text = "The supplied rate is 23 m³/h."
    registry = UserFactRegistry()
    accepted, rejected = registry.add_literal_fallback(text, [
        {"name": "q", "value": 24, "unit": "m³/h", "source_quote": "rate is 23 m³/h"},
        {"name": "q", "value": 23, "unit": "m³/h", "source_quote": "rate is 23 m³/h"},
        {"name": "x", "value": 99, "unit": "", "source_quote": "x is 99"},
    ])
    assert (accepted, rejected) == (1, 2)
    assert registry.records[0].value == 23 and registry.records[0].source_span in text


def test_direct_missing_values_asks_user_without_formula_retrieval():
    text = "X:Y=2:3. Calculate the weighted average of X and Y."
    facts = UserFactRegistry.from_topic(text)
    assert direct_readiness(text, facts, ["weighted_average"])
    assert classify_goal_intent(GoalResearchRequest(topic=text, goal=text),
                                has_user_facts=bool(facts.records)).kind == GoalIntentKind.DIRECT_CALC


def test_simulation_textbook_noun_is_not_a_sweep_action():
    text = "Explain the reservoir simulation textbook's grid discretization chapter."
    assert classify_goal_intent(GoalResearchRequest(topic=text, goal=text),
                                has_user_facts=False).kind == GoalIntentKind.KNOWLEDGE_QA


def test_interpolation_supports_generic_coordinate_points():
    text = "x 0: 0; x 2: 100. Interpolate at x 1."
    facts = UserFactRegistry.from_topic(text)
    assert {row.name for row in facts.records} >= {"point_0", "point_2", "target_x"}
    assert direct_readiness(text, facts, ["interpolation"]) == []


DIRECT_CASES = [
    ("median", 8.0, ("A=4, B=8, C=14. Compute median.", "A=4, B=8, C=14. Find the median.", "A=4, B=8, C=14. 중앙값을 구해줘.")),
    ("std_population", math.sqrt(32/3), ("A=4, B=8, C=12. Compute population standard deviation.", "A=4, B=8, C=12. Find population std.", "A=4, B=8, C=12. 모표준편차 계산.")),
    ("std_sample", 4.0, ("A=4, B=8, C=12. Compute sample standard deviation.", "A=4, B=8, C=12. Find sample std.", "A=4, B=8, C=12. 표본표준편차 계산.")),
    ("variance_population", 32/3, ("A=4, B=8, C=12. Compute population variance.", "A=4, B=8, C=12. Find population variance.", "A=4, B=8, C=12. 모분산 계산.")),
    ("geometric_mean", 4.0, ("A=2, B=4, C=8. Compute geometric mean.", "A=2, B=4, C=8. Find geometric mean.", "A=2, B=4, C=8. 기하평균을 계산.")),
    ("weighted_average", 26.0, ("X=20, Y=30, X:Y=2:3. Find weighted average.", "X=20, Y=30, X:Y=2:3. Compute weighted mean.", "X=20, Y=30, X:Y=2:3. 가중평균 계산.")),
    ("combined_rate", 20.0, ("Distance is 320 m and time is 16 h. Find combined rate.", "Distance: 320 m; time: 16 h. Compute combined rate.", "거리 320 m, 시간 16 h. 전체 평균 속도 계산.")),
    ("interpolation", 50.0, ("day 0: 0; day 2: 100. Interpolate at day 1.", "day 0=0; day 2=100. Interpolate at day 1.", "day 0에는 0, day 2에는 100. day 1에서 보간해줘.")),
    ("trapezoid", 100.0, ("day 0: 0; day 2: 100. Use trapezoid integration.", "day 0=0; day 2=100. Calculate trapezoid area.", "day 0에는 0, day 2에는 100. 사다리꼴 적분.")),
    ("repeated_percent", 80 * .9**3, ("initial=80. Apply a 10% decrease 3 times.", "initial=80. A 10% decrease 3 times.", "initial=80. 10% 감소를 3번 적용.")),
    ("elapsed_time", 220.0, ("21:30 start, 01:10 end next day. Find elapsed time.", "Start at 21:30, finish 01:10 next day. Compute elapsed time.", "21:30에 시작해 다음 날 01:10에 끝나면 경과 시간 계산.")),
    ("allocation_X", 20.0, ("total=90, X:Y:Z=2:3:4. Proportional allocation by weights.", "total=90, X:Y:Z=2:3:4. Allocate by weight proportionally.", "total=90, X:Y:Z=2:3:4. 비례 배분해줘.")),
    ("piecewise_cost", 3200.0, ("First 1000 m³ at price 2 USD, additional 400 m³ at price 3 USD. Piecewise cost?", "1000 m3 at price 2 USD; additional 400 m3 at price 3 USD. Compute piecewise cost.", "첫 1000 m³는 단가 2달러, 추가 400 m³는 단가 3달러. 구간별 비용 계산.")),
]


@pytest.mark.parametrize("case", DIRECT_CASES, ids=[row[0] for row in DIRECT_CASES])
def test_direct_operation_paraphrases_and_bounded_python(case, tmp_path):
    output, expected, variants = case
    for text in variants:
        request = GoalResearchRequest(topic=text, goal=text, execution_mode="autonomous_goal_execution",
                                      allow_python_execution=True, python_execution_approved=True)
        facts = UserFactRegistry.from_topic(text)
        intent = classify_goal_intent(request, has_user_facts=bool(facts.records))
        assert intent.kind == GoalIntentKind.DIRECT_CALC, (text, intent)
        operations = parse_request_ir(request, []).requested_operation_types
        if output.startswith("allocation_"):
            operations = ["allocation"]
        assert operations, text
    request = GoalResearchRequest(topic=variants[0], goal=variants[0], execution_mode="autonomous_goal_execution",
                                  allow_python_execution=True, python_execution_approved=True)
    facts = UserFactRegistry.from_topic(variants[0])
    operations = parse_request_ir(request, []).requested_operation_types
    for dominant, subsumed in (("weighted_average", "mean"), ("geometric_mean", "mean"),
                               ("combined_rate", "sum"), ("allocation", "sum")):
        if dominant in operations and subsumed in operations:
            operations.remove(subsumed)
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    result = asyncio.run(run_direct_arithmetic(settings, request, f"DEV-{output}", facts,
                                               operations, "CALC1"))
    assert result.validation_passed and result.execution_hash and result.input_fact_ids
    assert math.isclose(result.output_manifest[f"OUT_{output}"]["value"], expected, rel_tol=1e-9)


FORMULA_CASES = [
    ("Fluid mobility from k and mu", "mobility = k / mu", "mobility", ["k", "mu"]),
    ("Volumetric heat from rho and cp", "heat = rho * cp", "heat", ["rho", "cp"]),
    ("Porous volume using A and h", "PV = A * h * phi", "PV", ["A", "h", "phi"]),
    ("Force from pressure and area", "F = P * A", "F", ["P", "A"]),
    ("Residence time from V and q", "tau = V / q", "tau", ["V", "q"]),
    ("Thermal loss from U and dT", "loss = U * dT", "loss", ["U", "dT"]),
    ("Recovery volume from N and RF", "recoverable = N * RF", "recoverable", ["N", "RF"]),
    ("Shock loading force from m and a", "Ft = m * a", "Ft", ["m", "a"]),
]


@pytest.mark.parametrize("case", FORMULA_CASES, ids=[row[2] for row in FORMULA_CASES])
def test_formula_selection_uses_literal_span_and_context(case):
    concept, equation, lhs, variables = case
    context = concept.split(" from ")[0]
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text":
                 f"Unrelated baseline equation: x = a + b.\n{context}: {equation}.\n"
                 "Other context: y = c / d."}]
    for wording in (f"Calculate {concept}", f"Find {lhs} using {concept}",
                    f"Determine {lhs} for {context}"):
        selected, record = rank_formula_candidates(evidence, wording, variables)
        assert selected and selected.expression_candidate == equation, (wording, record)
        assert record.formula_id == selected.formula_id and record.candidates_found >= 1


PREMISE_CASES = [
    ("Always pressure increases with depth, right?", "Pressure increases with depth, correct?", "Pressure always rises with depth, doesn't it?"),
    ("A seal needs no capillary entry pressure, 맞지?", "A seal has no entry pressure requirement, 거지?", "Can I assume a seal needs no entry pressure?"),
    ("Relative permeability is unrelated to saturation, 무관하지?", "Relative permeability ignores saturation, right?", "Relative permeability always stays fixed, correct?"),
    ("More porosity always means more oil recovery, right?", "Porosity alone guarantees recovery, correct?", "Can I assume porosity determines recovery?"),
    ("A larger skin factor has no downside, 단점 없지?", "Skin factor never reduces productivity, right?", "Can I assume skin is irrelevant?"),
    ("Drilling overbalance always causes a kick, right?", "Mud overbalance causes kick, 거지?", "Overbalance guarantees kick, correct?"),
    ("Gas density has no dependence on pressure, 필요 없지?", "Pressure is irrelevant to gas density, right?", "Can I assume pressure never affects gas density?"),
    ("Capillary pressure can be ignored, 보면 되나?", "Capillary pressure is unnecessary, 맞지?", "We can ignore capillary pressure, correct?"),
]


@pytest.mark.parametrize("variants", PREMISE_CASES)
def test_premise_cues_precede_knowledge_qa(variants):
    for text in variants:
        request = GoalResearchRequest(topic=text, goal=text)
        intent = classify_goal_intent(request, has_user_facts=False)
        assert intent.kind == GoalIntentKind.PREMISE_CHECK, text


RESUME_CASES = [
    ("a=3. result=a*b. Compute result.", ("b is 5.", "b=5.", "b: 5."), "b"),
    ("V=7 m3. M=V*rho. Calculate M.", ("rho is 4 kg/m³.", "rho=4 kg/m^3.", "rho: 4 kg/m3."), "rho"),
    ("P=12 psi. delta=P-q. Compute delta.", ("q=3 psi.", "q is 3 psi.", "q: 3 psi."), "q"),
    ("x=9. y=x/z. Compute y.", ("z=3.", "z is 3.", "z: 3."), "z"),
    ("m=8 kg. force=m*a. Calculate force.", ("a=2.", "a is 2.", "a: 2."), "a"),
]


@pytest.mark.parametrize("initial,replies,missing", RESUME_CASES)
def test_resume_merges_new_literal_fact_without_duplication(initial, replies, missing):
    equation = next(row for row in ["result=a*b", "M=V*rho", "delta=P-q", "y=x/z", "force=m*a"] if row in initial)
    before = UserFactRegistry.from_messages([initial])
    assert missing in user_formula_bindings(equation, before)[1][0]
    for reply in replies:
        after = UserFactRegistry.from_messages([initial, reply])
        bound, absent = user_formula_bindings(equation, after)
        assert not absent and missing in bound
        assert len({row.fact_id for row in after.records}) == len(after.records)


USER_FORMULA_CASES = [
    ("a=2, b=5. yield=2*a*b-a*a. Calculate yield.", GoalIntentKind.USER_FORMULA_CALC),
    ("Wout=19, Wloss=3, Win=8. eta=(Wout-Wloss)/Win. Compute eta.", GoalIntentKind.USER_FORMULA_CALC),
    ("V=12 m3, rho=4 kg/m3, s=0.2. M=V*rho*(1-s). Calculate M.", GoalIntentKind.USER_FORMULA_CALC),
    ("b=5. Sweep a from 1 to 3 step 1. yield=2*a*b-a*a. Find optimum.", GoalIntentKind.USER_FORMULA_SIMULATION),
    ("c=7. Sweep t from 0 to 2 step 1. score=c*t+2. Find best.", GoalIntentKind.USER_FORMULA_SIMULATION),
]


@pytest.mark.parametrize("text,kind", USER_FORMULA_CASES)
def test_user_formula_routes_and_fixed_sweep_inputs(text, kind):
    variants = (text, text.replace("Calculate", "Compute").replace("Find optimum", "Find best"),
                text.replace("Sweep", "Vary").replace("step", "steps of"))
    for variant in variants:
        request = GoalResearchRequest(topic=variant, goal=variant)
        spec = parse_user_simulation_spec(variant)
        intent = classify_goal_intent(request, has_user_facts=bool(UserFactRegistry.from_topic(variant).records),
                                      has_simulation_spec=spec is not None)
        assert intent.kind == kind, variant
        if kind == GoalIntentKind.USER_FORMULA_SIMULATION:
            assert spec is not None and spec.fixed_fact_ids and spec.source_equation
            assert spec.parameter.step == 1 and spec.parameter.stop == 3 if "yield=" in variant else True
