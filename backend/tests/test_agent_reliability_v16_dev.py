"""Fresh synthetic development cases; not a heldout evaluation or performance estimate.

No benchmark files are loaded. Retrieval/LLM boundaries are controlled; the actual
GoalExecutionAgent, source/contract validators and Python sandbox execute end to end.
"""
import asyncio
from dataclasses import replace

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest, CriterionStatus
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_intent import classify_goal_intent, GoalIntentKind
from app.services.source_answerability import evaluate_claim_support, literal_answer
from test_goal_execution_v8 import NoResearch, StaticResearch, PassingEvaluator


KNOWLEDGE = [
    ("Define sample custody.", "Sample custody means the documented transfer of a sample between responsible people."),
    ("What is a thermowell?", "A thermowell is a protective enclosure for a temperature probe."),
    ("Explain the function of a cable gland.", "A cable gland prevents moisture entry at a cable penetration."),
    ("Describe the purpose of a bearing isolator.", "A bearing isolator separates the lubricant space from external contaminants."),
    ("Explain the relationship between acoustic transit time and path length.",
     "Acoustic transit time increases with path length at fixed wave velocity."),
    ("Explain why membrane resistance affects flux.", "Membrane resistance affects flux because it opposes transport through the membrane."),
]
MULTI = [
    ("Define sample custody; explain the function of a cable gland; define a thermowell.",
     KNOWLEDGE[0][1] + "\n" + KNOWLEDGE[2][1], False),
    ("Define a thermowell; explain the purpose of a bearing isolator.",
     KNOWLEDGE[1][1] + "\n" + KNOWLEDGE[3][1], True),
    ("Explain the function of a rupture disk; define a witness coupon.",
     "A rupture disk protects a vessel by opening a relief path.\nA witness coupon is a removable specimen exposed alongside the equipment.", True),
    ("Explain the function of a cable gland; define sample custody; explain membrane resistance and flux.",
     KNOWLEDGE[2][1] + "\n" + KNOWLEDGE[0][1] + "\n" + KNOWLEDGE[5][1], True),
]
DIRECT = [
    ("Inspection readings: 13, 21, 26, 34 mm. Find mean, median, sum, minimum, maximum and range.",
     {"mean": 23.5, "median": 23.5, "sum": 94, "minimum": 13, "maximum": 34, "range": 21}),
    ("inlet=54 psi; outlet=18 psi. Report the ratio inlet/outlet and difference inlet-outlet.",
     {"ratio": 3, "difference": 36}),
    ("검사 측정값: 17, 23, 32 kg. 합계와 최솟값을 구해줘.", {"sum": 72, "minimum": 17}),
    ("initial=45 kg; final=63 kg. Calculate percentage change from initial to final.", {"percent_change": 40}),
]
FORMULAS = [
    ("Set gain=7; shift=4; sample=9; response=gain*sample-shift. Calculate response.", 59),
    ("Use duration=6 h; speed=8 m/h; distance=speed*duration. Calculate distance.", 48),
    ("보정식 corrected=raw/divisor+zero; raw=39; divisor=3; zero=2. corrected를 계산해줘.", 15),
    ("span=14 m; fraction=0.25; allowance=2 m; reach=span*fraction+allowance. Compute reach.", 5.5),
]
KB = [
    ("lift=16 m; sag=3 m. Find the internal textbook equation for clearance and calculate clearance.",
     "Clearance calculation: clearance=lift-sag. lift and sag are lengths in m; clearance is in m.", 13),
    ("retained=28 kg; removed=12 kg. Calculate inventory using the internal source equation.",
     "Inventory equation: inventory=retained+removed. retained and removed are masses in kg; inventory is in kg.", 40),
]
UNDER = [
    ("Determine the precise sensor drift without calibration history.",
     "Sensor drift depends on calibration history and ambient temperature records.", "calibration history"),
    ("Find the optimal backwash interval; fouling records are unavailable.",
     "The backwash interval requires fouling records and measured pressure loss trends.", "fouling records"),
    ("Determine exact coating consumption with no surface survey.",
     "Coating consumption depends on measured surface area and the specified dry film thickness.", "surface area"),
    ("Determine the precise seal replacement interval; wear measurements are not provided.",
     "Seal replacement interval depends on wear measurements and operating cycle history.", "wear measurements"),
]


class RejectingEvaluator(PassingEvaluator):
    async def evaluate(self, *args, **kwargs):
        value = await super().evaluate(*args, **kwargs)
        return replace(value, achieved=False, coverage=0, gaps=["LLM reports insufficient support"],
                       criteria=[c.model_copy(update={"status": CriterionStatus.UNMET}) for c in value.criteria])


async def refuse(*args, **kwargs):
    return ""


def request(text, numeric=False):
    return GoalResearchRequest(topic=text, goal=text, model="qwen3:8b", use_external=False,
        execution_mode="autonomous_goal_execution", max_iterations=6,
        success_criteria=[GoalCriterion(criterion_id="C1", description=
            "Calculate the requested result with validated units and provenance" if numeric else text)])


def run_agent(tmp_path, monkeypatch, text, source=None, numeric=False, **kwargs):
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
                        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "sandbox"))
    agent = GoalExecutionAgent(StaticResearch(source) if source else NoResearch(), object(),
        evaluator=PassingEvaluator() if numeric else RejectingEvaluator(), synthesizer=refuse)
    return asyncio.run(agent.run("fresh-v16-development", request(text, numeric), **kwargs))


@pytest.mark.parametrize("variant", ["original", "paraphrase", "source_position", "irrelevant"])
@pytest.mark.parametrize("text,source,achieved", [(q, s, True) for q, s in KNOWLEDGE] + MULTI)
def test_full_agent_grounded_qa(tmp_path, monkeypatch, text, source, achieved, variant):
    if variant == "paraphrase":
        text = text.replace("Explain", "Describe").replace("Define", "What is").replace("function", "purpose")
    if variant == "source_position":
        source = "This appendix lists administrative headings.\n" + "\n".join(reversed(source.splitlines())) + "\nThe checklist was filed separately."
    if variant == "irrelevant":
        text += " The exercise is for our next workshop."
    result = run_agent(tmp_path, monkeypatch, text, source)
    assert (result.status.value == "achieved") == achieved, (result.final_answer, result.telemetry)
    assert result.telemetry["extractive_fallback_attempted"]
    assert result.telemetry["extractive_fallback_used"]
    assert not result.telemetry["refusal_generated"]
    assert result.telemetry["claim_support_checked"] and result.python_calls_total == 0
    assert "[KB1]" in result.final_answer
    if not achieved:
        assert result.telemetry["final_answer_kind"] == "partial_grounded"
        assert "Not established" in result.final_answer and "thermowell" in result.final_answer
        assert result.telemetry["supported_claim_count"] == 2
        assert result.telemetry["required_claim_count"] == 3


@pytest.mark.parametrize("variant", ["original", "paraphrase", "source_position", "reordered"])
@pytest.mark.parametrize("text,source,dependency", UNDER)
def test_full_agent_underdetermined(tmp_path, monkeypatch, text, source, dependency, variant):
    if variant == "paraphrase":
        text = text.replace("Determine", "Find").replace("precise", "exact")
    if variant == "source_position":
        source = "The equipment register contains supplier names.\n" + source
    if variant == "reordered" and ";" in text:
        a, b = text.split(";", 1)
        text = b.strip().rstrip(".") + ". " + a + "."
    result = run_agent(tmp_path, monkeypatch, text, source)
    assert result.status.value == "achieved", (result.final_answer, result.telemetry)
    assert result.telemetry["final_answer_kind"] == "underdetermined"
    assert dependency in result.final_answer and "cannot be determined" in result.final_answer
    assert result.python_calls_total == 0 and not result.computations
    assert not result.telemetry["refusal_generated"]


@pytest.mark.parametrize("variant", ["original", "reordered", "irrelevant"])
@pytest.mark.parametrize("text,expected", DIRECT + FORMULAS)
def test_full_agent_complete_calculation(tmp_path, monkeypatch, text, expected, variant):
    if variant == "reordered" and ";" in text:
        clauses = text.split(";")
        text = ";".join(list(reversed(clauses[:-1])) + clauses[-1:])
    if variant == "irrelevant":
        text += "\nThis exercise will be discussed at the next meeting."
    result = run_agent(tmp_path, monkeypatch, text, numeric=True)
    assert result.status.value == "achieved", (result.final_answer, result.action_history, result.telemetry)
    actions = [a["action_type"] for a in result.action_history]
    assert actions[0] == "calculate" and "retrieve" not in actions
    assert actions.count("calculate") == 1 and "verify" in actions
    assert result.python_calls_total == 1
    calc = result.computations[0]
    assert calc.validation_passed and calc.execution_hash and calc.input_fact_ids
    assert calc.formula_source_ids and calc.bound_variables and calc.normalized_formula
    assert result.telemetry["calculation_validated"] and result.telemetry["calculation_executed"]
    assert result.telemetry["operand_validation_passed"] and result.telemetry["calculation_ready"]
    if isinstance(expected, dict):
        for key, value in expected.items():
            assert calc.output["OUT_" + key] == pytest.approx(value)
    else:
        assert calc.output["OUT_RESULT"] == pytest.approx(expected)


@pytest.mark.parametrize("variant", ["original", "source_position", "irrelevant"])
@pytest.mark.parametrize("text,source,expected", KB)
def test_full_agent_kb_transition(tmp_path, monkeypatch, text, source, expected, variant):
    if variant == "source_position":
        source = "Synthetic workshop reference.\n" + source
    if variant == "irrelevant":
        text += "\nThis exercise will be discussed at the next meeting."
    result = run_agent(tmp_path, monkeypatch, text, source, numeric=True)
    assert result.status.value == "achieved", (result.final_answer, result.action_history, result.telemetry)
    assert result.telemetry["formula_ready"] and result.telemetry["calculation_ready"]
    assert [a["action_type"] for a in result.action_history][:2] == ["retrieve", "calculate"]
    calc = result.computations[0]
    assert calc.output["OUT_RESULT"] == pytest.approx(expected)
    assert calc.formula_source_ids == ["KB1"] and calc.validation_passed


@pytest.mark.parametrize("text", [
    "Find the optimal mixing setting without viscosity data. score=speed*gain.",
    "Find a precise limit; wall thickness is unknown. Vary pressure from 2 to 9.",
    "정확한 운전 한계를 구해줘. 재질 정보가 제공되지 않았다.",
])
def test_missing_data_precedes_numeric_routing(text):
    assert classify_goal_intent(request(text), has_user_facts=True).kind == GoalIntentKind.KNOWLEDGE_QA


@pytest.mark.parametrize("source", [
    "Sample custody is mentioned in the administrative catalogue.",
    "The cabinet protects the cable gland during transport.",
    "The cable gland appears here. A thermowell protects a sensor.",
])
def test_related_words_are_not_relation_support(source):
    req = request("Explain the function of a cable gland.")
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": source}]
    assert literal_answer(req, evidence) is None


def test_no_evidence_no_answer(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: Settings(data_dir=tmp_path))
    result = asyncio.run(GoalExecutionAgent(StaticResearch(""), object(), evaluator=RejectingEvaluator(),
        synthesizer=refuse).run("empty", request("Define sample custody.")))
    assert result.status.value != "achieved"
    assert not result.telemetry["extractive_fallback_used"]
    assert result.telemetry["refusal_generated"]


def test_last_iteration_gate_is_reachable(tmp_path, monkeypatch):
    text, source = KNOWLEDGE[0]
    req = request(text).model_copy(update={"max_iterations": 1})
    result = asyncio.run(GoalExecutionAgent(StaticResearch(source), object(), evaluator=RejectingEvaluator(),
        synthesizer=refuse).run("budget-end", req))
    assert result.status.value == "achieved"
    assert result.telemetry["extractive_fallback_used"]


def test_explicit_no_retrieval_is_not_missing_data():
    req = request("p=9 kg; q=16 kg. Calculate exact sum with no retrieval.", True)
    assert classify_goal_intent(req, has_user_facts=True).kind == GoalIntentKind.DIRECT_CALC


@pytest.mark.parametrize("text,source", [
    ("케이블 글랜드의 기능을 설명해줘.", "케이블 글랜드는 케이블 관통부에서 수분 침투를 방지합니다."),
    ("열전대 보호관의 역할을 알려줘.", "열전대 보호관은 온도 센서를 외부 환경으로부터 보호합니다."),
    ("정확한 센서 교정 주기를 구해줘, 사용 환경 자료가 제공되지 않았어.",
     "센서 교정 주기는 사용 환경 기록과 계측 오차 이력에 의존합니다."),
])
def test_korean_relation_subject_order(tmp_path, monkeypatch, text, source):
    result = run_agent(tmp_path, monkeypatch, text, source)
    assert result.status.value == "achieved", result.telemetry
    assert source in result.final_answer and "[KB1]" in result.final_answer


def test_opposite_source_relations_do_not_achieve(tmp_path, monkeypatch):
    text, source = KNOWLEDGE[4]
    result = run_agent(tmp_path, monkeypatch, text, source + "\n" + source.replace("increases", "decreases"))
    assert result.status.value != "achieved"
    assert result.telemetry["final_answer_kind"] == "partial_grounded"
    assert "increases" in result.final_answer and "decreases" in result.final_answer
    assert "conflicting" in result.final_answer


def test_engineering_rejection_cannot_be_overridden(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr("app.services.goal_execution_agent.EngineeringValidator.validate_claim",
                        lambda *args, **kwargs: SimpleNamespace(passed=False))
    text, source = KNOWLEDGE[0]
    result = run_agent(tmp_path, monkeypatch, text, source)
    assert result.status.value != "achieved" and not result.telemetry["extractive_fallback_used"]


def test_evidence_conflict_signal_blocks_unqualified_fallback():
    class ConflictResearch(StaticResearch):
        async def research(self, req):
            response = await super().research(req)
            response.validation["conflict_count"] = 1
            return response
    text, source = KNOWLEDGE[0]
    result = asyncio.run(GoalExecutionAgent(ConflictResearch(source), object(), evaluator=RejectingEvaluator(),
        synthesizer=refuse).run("conflict-signal", request(text)))
    assert result.status.value != "achieved"
    assert not result.telemetry["extractive_fallback_used"]
    assert result.telemetry["extractive_fallback_failure_reason"] == "retrieved_evidence_conflict"


def test_refusal_cannot_inherit_passing_evaluator():
    async def refuses(*args, **kwargs):
        return "I cannot answer this question. [KB1]"
    text, source = KNOWLEDGE[0]
    result = asyncio.run(GoalExecutionAgent(StaticResearch(source), object(), evaluator=PassingEvaluator(),
        synthesizer=refuses).run("refusal-verdict", request(text)))
    assert result.status.value == "achieved"
    assert result.telemetry["extractive_fallback_used"]
    assert source in result.final_answer


def test_wrong_citation_is_not_success():
    async def invented_id(*args, **kwargs):
        return "A fictitious valve is defined by an unrelated manual. [KB77]"
    result = asyncio.run(GoalExecutionAgent(StaticResearch("An unrelated catalogue entry."), object(),
        evaluator=PassingEvaluator(), synthesizer=invented_id).run("citation-guard", request(KNOWLEDGE[0][0])))
    assert result.status.value != "achieved"


def test_partial_normal_answer_cannot_inherit_passing_evaluator():
    text, source, _ = MULTI[0]
    async def partial(*args, **kwargs):
        return source + " [KB1]"
    result = asyncio.run(GoalExecutionAgent(StaticResearch(source), object(), evaluator=PassingEvaluator(),
        synthesizer=partial).run("partial-normal", request(text)))
    assert result.status.value != "achieved"
    assert result.telemetry["final_answer_kind"] == "partial_grounded"
    assert "thermowell" in result.final_answer


def test_inferred_criteria_do_not_add_unrequested_effects():
    class NoInventedCriteria:
        async def infer_criteria(self, req):
            raise AssertionError("No LLM expansion of mandatory factual claims")
    text, source = KNOWLEDGE[3]
    result = asyncio.run(GoalExecutionAgent(StaticResearch(source), object(), planner=NoInventedCriteria(),
        evaluator=RejectingEvaluator(), synthesizer=refuse).run("literal-goal",
            request(text).model_copy(update={"success_criteria": []})))
    assert result.status.value == "achieved"
    assert len(result.frozen_criteria) == 1
    assert result.frozen_criteria[0].description.rstrip(".") == text.rstrip(".")


@pytest.mark.parametrize("text", [
    "gain=4; gain=7; reading=3; adjusted=gain*reading. Calculate adjusted.",
    "gain=4; adjusted=gain*reading. Calculate adjusted.",
    "initial=0 kg; final=5 kg. Calculate percentage change.",
])
def test_ambiguous_missing_or_zero_inputs_never_execute(tmp_path, monkeypatch, text):
    result = run_agent(tmp_path, monkeypatch, text, numeric=True)
    assert result.python_calls_total == 0 and result.status.value != "achieved"
