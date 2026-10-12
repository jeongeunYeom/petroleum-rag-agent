"""Fresh synthetic v18 development cases; no sealed benchmark material."""

import asyncio
import json

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import (CriterionEvaluation, CriterionStatus,
    ExpectedResultStatus, GoalCriterion, GoalStatus, GoalRunStatus)
from app.models.research_schemas import InternalEvidence, ResearchResponse, EvidenceCounts, ResearchTiming
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_evaluator import GoalEvaluationResult
from app.services.goal_message_parser import GoalMessageRequest, parse_goal_message
from app.services.goal_simulation import direct_operation_operands, formula_input_readiness
from app.services.user_fact_registry import UserFactRegistry
from app.services.formula_source_registry import FormulaSourceRegistry, source_contains_equation
from app.services.compound_units import unit_factors


class SyntheticSources:
    def __init__(self, *passages):
        self.passages = passages
        self.calls = 0

    async def research(self, request):
        self.calls += 1
        rows = [InternalEvidence(evidence_id=f"KB{i}", document="synthetic-v18-manual.txt",
            page=10 + i, chunk_id=f"synthetic-{i}", score=1, excerpt=text)
            for i, text in enumerate(self.passages, 1)]
        return ResearchResponse(query=request.query, answer="", internal_sources=rows,
            web_sources=[], figures=[], provenance=[], model=request.model, inference_used=False,
            evidence_counts=EvidenceCounts(internal=len(rows), external=0),
            routing_mode="internal_only", retrieval_mode="hybrid",
            timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0))


class SyntheticSupport:
    def __init__(self, statuses=()):
        self.statuses = statuses

    async def chat_structured(self, messages, schema, **kwargs):
        if "source_spans" not in messages[-1]["content"]:
            return "{}"
        payload = json.loads(messages[-1]["content"])
        return json.dumps({"claims": [{"claim_id": claim["claim_id"],
            "status": self.statuses[i] if i < len(self.statuses) else "SUPPORTED",
            "span_ids": [payload["source_spans"][min(i, len(payload["source_spans"]) - 1)]["span_id"]],
            "evidence_conflict": False} for i, claim in enumerate(payload["claims"])]})


class RejectingEvaluator:
    async def evaluate(self, request, criteria, answer, evidence, validation, **kwargs):
        return GoalEvaluationResult(criteria=[CriterionEvaluation(criterion_id=c.criterion_id,
            status=CriterionStatus.UNMET, reason="Synthetic rejection", supporting_evidence=[])
            for c in criteria], coverage=0, achieved=False,
            expected_result_status=ExpectedResultStatus.NOT_PROVIDED, gaps=[], next_research_need=None,
            engineering_validation_passed=True, engineering_contradiction_count=0,
            unsupported_engineering_claim_count=0, goal_conflicts_with_evidence=False)


async def unavailable(*args, **kwargs):
    return "Insufficient evidence."


def execute(tmp_path, monkeypatch, message, *, passages=(), statuses=(), claims=()):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    sources = SyntheticSources(*passages)
    request = parse_goal_message(GoalMessageRequest(message=message))
    if claims:
        request = request.model_copy(update={"success_criteria": [GoalCriterion(
            criterion_id=f"C{i}", description=text) for i, text in enumerate(claims, 1)]})
    agent = GoalExecutionAgent(sources, SyntheticSupport(statuses),
                               evaluator=RejectingEvaluator(), synthesizer=unavailable)
    return asyncio.run(agent.run("GR-V18-SYNTHETIC", request)), sources


@pytest.mark.parametrize("message,expected", [
    ("R1=13 psi; R2=21 psi. Calculate the mean of R1 and R2.", "17"),
    ("Tank_A=8 kg; Tank_B=11 kg. Calculate the sum of Tank_A and Tank_B.", "19"),
    ("before_pressure=46 psi; after_pressure=29 psi. Calculate before minus after difference.", "17"),
    ("recovered=18 kg; introduced=30 kg. Calculate recovered/introduced ratio.", "0.6"),
    ("A=6 psi; B=17 psi; C=10 psi. Rank A, B and C.", "B"),
    ("X=23 m; Y=31 m. Calculate the maximum of X and Y.", "31"),
])
def test_direct_full_agent_without_retrieval(tmp_path, monkeypatch, message, expected):
    result, sources = execute(tmp_path, monkeypatch, message)
    assert sources.calls == 0
    assert result.telemetry["intent_route"] == "direct_calc"
    assert result.telemetry["route_forced_by_deterministic_readiness"]
    assert result.python_calls_total == 1
    assert result.computations[0].validation_passed
    assert result.telemetry["deterministic_calc_finalizer_used"]
    assert result.clarification_question is None
    assert expected in result.final_answer


@pytest.mark.parametrize("message,value,unit", [
    ("density = mass / volume. mass=27 kg; volume=9 m3. Calculate density.", 3, "kg/m3"),
    ("pressure_area = pressure * area. pressure=12 Pa; area=4 m2. Calculate pressure_area.", 48, "Pa*m2"),
    ("drop = initial - final. before_pressure=52 psi; after_pressure=19 psi. Calculate drop.", 33, "psi"),
    ("expense = rate * duration. rate=7 USD/h; duration=3 h. Calculate expense.", 21, "USD"),
    ("Index = load / speed. load=20 psi; speed=4 m/s. Calculate Index.", 5, "psi*s/m"),
])
def test_user_formula_full_agent(tmp_path, monkeypatch, message, value, unit):
    result, sources = execute(tmp_path, monkeypatch, message)
    assert sources.calls == 0
    assert result.status == GoalStatus.ACHIEVED
    assert result.telemetry["intent_route"] == "user_formula_calc"
    assert result.python_calls_total == 1
    calc = result.computations[0]
    assert calc.validation_passed and calc.contract_validation_passed
    assert calc.output_manifest["OUT_RESULT"]["value"] == value
    assert unit_factors(calc.output_manifest["OUT_RESULT"]["unit"]) == unit_factors(unit)
    assert result.telemetry["deterministic_calc_finalizer_used"]
    assert "[CALC1]" in result.final_answer


@pytest.mark.parametrize("message,passage,value,unit", [
    ("mass=36 kg; volume=9 m3. Calculate density using the internal source equation.",
     "The laboratory density relation is density = mass / volume.", 4, "kg/m3"),
    ("recovered=21 kg; introduced=70 kg. Calculate yield using the internal source relation.",
     "yield is the ratio of recovered to introduced.", .3, "dimensionless"),
    ("entry=45 psi; exit=12 psi. Calculate loss using the internal source equation.",
     "For this synthetic line, loss = entry - exit.", 33, "psi"),
    ("energy=72 kWh; duration=8 h. Calculate average_power using the internal source formula.",
     "The monitored relation is average_power = energy / duration.", 9, "kWh/h"),
    ("charge=25 USD; count=5 dimensionless. Calculate unit_charge using the internal source equation.",
     "For the invoice example, unit_charge = charge / count.", 5, "USD"),
])
def test_kb_formula_retrieve_then_calculate(tmp_path, monkeypatch, message, passage, value, unit):
    result, sources = execute(tmp_path, monkeypatch, message, passages=[passage])
    assert sources.calls >= 1
    assert result.status == GoalStatus.ACHIEVED
    actions = [a["action_type"] for a in result.action_history]
    assert actions.index("retrieve") < actions.index("calculate") < actions.index("verify")
    assert result.telemetry["formula_source_verified"]
    calc = result.computations[0]
    assert calc.validation_passed and calc.contract_validation_passed
    assert calc.formula_source_ids == ["KB1"]
    assert calc.output_manifest[next(iter(calc.output_manifest))]["value"] == pytest.approx(value)
    output_unit = calc.output_manifest[next(iter(calc.output_manifest))]["unit"] or "dimensionless"
    assert unit_factors(output_unit) == unit_factors(unit)
    assert "[KB1]" in result.final_answer and "[CALC1]" in result.final_answer


@pytest.mark.parametrize("message,passage", [
    ("Explain how the copper mesh captures droplets.",
     "The copper mesh captures droplets by coalescing them into larger drops."),
    ("Explain why the ceramic valve limits reverse flow.",
     "The ceramic valve limits reverse flow because its spring closes the return port."),
    ("Describe the function of the amber seal.",
     "The amber seal prevents vapor leakage by closing the outer annulus."),
    ("Explain how the glass baffle separates bubbles.",
     "The glass baffle separates bubbles by slowing the liquid stream."),
])
def test_grounded_qa_fast_path(tmp_path, monkeypatch, message, passage):
    result, sources = execute(tmp_path, monkeypatch, message, passages=[passage], claims=[message])
    assert sources.calls >= 1
    assert result.status == GoalStatus.ACHIEVED
    assert result.telemetry["grounded_fast_path_used"]
    assert not result.telemetry["refusal_generated"]
    assert passage in result.final_answer and "[KB1]" in result.final_answer


def test_partial_support_is_not_generic_refusal(tmp_path, monkeypatch):
    passage = "The bronze rotor distributes coolant through the upper channel."
    result, _ = execute(tmp_path, monkeypatch,
        "Explain the bronze rotor and the unknown lower actuator.", passages=[passage],
        statuses=["SUPPORTED", "UNSUPPORTED"],
        claims=["Explain the bronze rotor function", "Explain the lower actuator function"])
    assert result.status != GoalStatus.ACHIEVED
    assert passage in result.final_answer
    assert result.telemetry["final_answer_kind"] == "partial_grounded"
    assert not result.telemetry["refusal_generated"]


def test_conflicting_evidence_cannot_fast_path(tmp_path, monkeypatch):
    result, _ = execute(tmp_path, monkeypatch,
        "Explain whether the violet gasket increases leakage.",
        passages=["The violet gasket increases leakage under load.",
                  "The violet gasket decreases leakage under load."],
        claims=["Effect of the violet gasket on leakage"])
    assert result.status != GoalStatus.ACHIEVED
    assert not result.telemetry["grounded_fast_path_used"]


def test_missing_formula_variable_requires_specific_input():
    facts = UserFactRegistry.from_topic("mass=35 kg")
    _, missing = formula_input_readiness("density = mass / volume", facts)
    assert missing == ["volume 값"]


def test_ambiguous_same_unit_order_is_not_guessed():
    text = "inlet_pressure=43 psi; outlet_pressure=28 psi. Calculate their ratio."
    facts = UserFactRegistry.from_topic(text)
    order, missing = direct_operation_operands(text, facts, ["ratio"])
    assert not order and missing == ["비율의 분자/분모 순서"]


def test_definition_provenance_is_exact_span():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "yield is the ratio of recovered to introduced.", "document": "synthetic", "page": 11}]
    record = FormulaSourceRegistry.from_evidence(evidence).records[0]
    assert source_contains_equation(record, evidence[0]["text"])
    assert not source_contains_equation(record, "unrelated neighboring page")


def test_compound_unit_parser_rejects_malformed():
    assert unit_factors("USD/(kg*m3)") == {"USD": 1, "kg": -1, "m3": -1}
    with pytest.raises(ValueError):
        unit_factors("psi//m")


def test_missing_kb_operand_waits_then_resumes_same_run(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    sources = SyntheticSources("The measured relation is density = mass / volume.")
    request = parse_goal_message(GoalMessageRequest(
        message="mass=30 kg. Calculate density using the internal source equation."))
    agent = GoalExecutionAgent(sources, SyntheticSupport(),
                               evaluator=RejectingEvaluator(), synthesizer=unavailable)
    paused = asyncio.run(agent.run("GR-V18-RESUME", request))
    assert paused.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT
    assert "volume" in paused.clarification_question
    assert "value and unit" in paused.clarification_question
    assert paused.python_calls_total == 0
    checkpoint = {**paused.resume_checkpoint, "user_replies": ["volume=6 m3"]}
    resumed = asyncio.run(agent.run(paused.run_id, request, resume_state=checkpoint,
                                    resume_result=paused))
    assert resumed.run_id == paused.run_id
    assert resumed.status == GoalStatus.ACHIEVED
    assert resumed.computations[0].validation_passed
    assert resumed.computations[0].output_manifest["OUT_RESULT"]["value"] == 5
    assert [row["action_type"] for row in resumed.action_history].index("retrieve") < [
        row["action_type"] for row in resumed.action_history].index("calculate")


@pytest.mark.parametrize("message,expected", [
    ("In 2021, Q1=12 psi; Q2=18 psi. Calculate the mean of Q1 and Q2.", 15),
    ("recovered=21 kg; introduced=35 kg; calibration=99 kg. Calculate recovered/introduced ratio.", .6),
])
def test_irrelevant_numbers_do_not_become_operands(tmp_path, monkeypatch, message, expected):
    result, sources = execute(tmp_path, monkeypatch, message)
    assert sources.calls == 0 and result.python_calls_total == 1
    assert result.status == GoalStatus.ACHIEVED
    assert any(row["value"] == pytest.approx(expected) for row in
               result.computations[0].output_manifest.values())


@pytest.mark.parametrize("unit,expected", [
    ("g/mol", {"g": 1, "mol": -1}),
    ("kg/kmol", {"kg": 1, "kmol": -1}),
    ("lb/lbmol", {"lb": 1, "lbmol": -1}),
])
def test_molecular_weight_units_are_bounded(unit, expected):
    assert unit_factors(unit) == expected
    with pytest.raises(ValueError):
        unit_factors(unit + "/")


def test_molecular_weight_assignments_keep_both_source_spans():
    facts = UserFactRegistry.from_topic("M=24.6 g/mol, M_air=29.0 g/mol")
    assert [(row.name, row.value, row.unit, row.extraction_method) for row in facts.records] == [
        ("M", 24.6, "g/mol", "explicit_assignment"),
        ("M_air", 29.0, "g/mol", "explicit_assignment"),
    ]
    assert all("g/mol" in row.source_span for row in facts.records)


def test_molecular_weight_resume_uses_same_run_and_finishes(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    sources = SyntheticSources("The synthetic molecular weight ratio relation is R = M / M_air.")
    request = parse_goal_message(GoalMessageRequest(
        message="Find the internal molecular weight ratio relation and calculate R for my sample."))
    agent = GoalExecutionAgent(sources, SyntheticSupport(),
                               evaluator=RejectingEvaluator(), synthesizer=unavailable)
    paused = asyncio.run(agent.run("GR-V18-MOLAR-RESUME", request))
    assert paused.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT
    assert paused.python_calls_total == 0
    assert "M" in paused.clarification_question and "M_air" in paused.clarification_question
    checkpoint = {**paused.resume_checkpoint,
                  "user_replies": ["M=21.6 g/mol, M_air=30.0 g/mol"]}
    resumed = asyncio.run(agent.run(paused.run_id, request, resume_state=checkpoint,
                                    resume_result=paused))
    assert resumed.run_id == paused.run_id
    assert resumed.status == GoalStatus.ACHIEVED
    assert resumed.run_status != GoalRunStatus.WAITING_FOR_USER_INPUT
    assert resumed.clarification_question is None
    actions = [row["action_type"] for row in resumed.action_history]
    assert actions.index("retrieve") < actions.index("calculate") < actions.index("verify")
    assert sources.calls == 1
    calc = resumed.computations[0]
    assert calc.validation_passed and calc.formula_source_ids == ["KB1"]
    assert calc.output_manifest["OUT_RESULT"]["value"] == pytest.approx(.72)
    assert calc.output_manifest["OUT_RESULT"]["unit"] == "dimensionless"
    assert "dimensionless" in resumed.final_answer and "[CALC1]" in resumed.final_answer
