"""Fresh synthetic development fixtures; no frozen evaluation inputs or answers."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import (CriterionEvaluation, CriterionStatus,
    ExpectedResultStatus, GoalResearchRequest, GoalStatus)
from app.models.research_schemas import InternalEvidence, ResearchResponse, EvidenceCounts, ResearchTiming
from app.services.goal_evaluator import GoalEvaluationResult
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_intent import classify_goal_intent, explicitly_underdetermined
from app.services.source_answerability import evaluate_claim_support, semantic_claim_support, SupportStatus
from app.services.compound_units import unit_factors
from app.services.user_fact_registry import UserFactRegistry


PASSAGES = [
    "The amber cartridge removes dissolved dye by adsorption onto its porous coating.",
    "The violet latch closes the sampling port when the spring expands.",
    "The silver sleeve reduces sensor vibration through elastic damping.",
]


class Sources:
    def __init__(self, texts=PASSAGES):
        self.texts = texts
        self.calls = 0

    async def research(self, request):
        self.calls += 1
        sources = [InternalEvidence(evidence_id=f"KB{i}", document="synthetic-device-manual.txt",
            page=i, chunk_id=f"fixture-{i}", score=1, excerpt=text) for i, text in enumerate(self.texts, 1)]
        return ResearchResponse(query=request.query, answer="", internal_sources=sources,
            web_sources=[], figures=[], provenance=[], model=request.model, inference_used=False,
            evidence_counts=EvidenceCounts(internal=len(sources), external=0), routing_mode="internal_only",
            retrieval_mode="hybrid", timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0))


class Verdicts:
    """Controlled semantic boundary, not a measurement of model accuracy."""
    def __init__(self, statuses=None, bad_span=False, conflict=False):
        self.statuses = statuses
        self.bad_span = bad_span
        self.conflict = conflict
        self.support_calls = 0

    async def chat_structured(self, messages, schema, **kwargs):
        if "source_spans" in messages[-1]["content"] and "claims" in schema["properties"]:
            self.support_calls += 1
            payload = json.loads(messages[-1]["content"])
            return json.dumps({"claims": [{"claim_id": c["claim_id"],
                "status": (self.statuses or ["SUPPORTED"] * len(payload["claims"]))[i],
                "span_ids": ["INVENTED" if self.bad_span else payload["source_spans"][min(i, len(payload["source_spans"])-1)]["span_id"]],
                "evidence_conflict": self.conflict} for i, c in enumerate(payload["claims"])]})
        return "{}"


class Evaluator:
    def __init__(self, accepted=False):
        self.accepted = accepted

    async def evaluate(self, request, criteria, answer, evidence, validation, **kwargs):
        return GoalEvaluationResult(criteria=[CriterionEvaluation(criterion_id=c.criterion_id,
            status=CriterionStatus.MET if self.accepted else CriterionStatus.UNMET,
            reason="Synthetic evaluator verdict", supporting_evidence=[]) for c in criteria],
            coverage=float(self.accepted), achieved=self.accepted,
            expected_result_status=ExpectedResultStatus.NOT_PROVIDED, gaps=[], next_research_need=None,
            engineering_validation_passed=True, engineering_contradiction_count=0,
            unsupported_engineering_claim_count=0, goal_conflicts_with_evidence=False)


async def refusal(*args, **kwargs):
    return "Insufficient evidence."


def req(text):
    return GoalResearchRequest(topic=text, goal=text, model="qwen3:8b", use_external=False,
                               execution_mode="autonomous_goal_execution", max_iterations=6)


def run_agent(tmp_path, monkeypatch, text, *, sources=None, judge=None, accepted=False):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings", lambda: settings)
    research = sources or Sources()
    agent = GoalExecutionAgent(research, judge or Verdicts(), evaluator=Evaluator(accepted), synthesizer=refusal)
    return asyncio.run(agent.run("GR-SYNTHETIC-V17", req(text))), research


@pytest.mark.parametrize("text", [
    "호박색 카트리지가 용해된 염료를 제거하는 원리를 설명해줘.",
    "용해 염료 제거에 쓰이는 호박색 카트리지는 어떻게 작동하는지 설명해줘.",
    "Explain how the amber cartridge removes dissolved dye.",
])
def test_grounded_fallback_overrides_rejecting_evaluator(tmp_path, monkeypatch, text):
    result, _ = run_agent(tmp_path, monkeypatch, text)
    assert result.status == GoalStatus.ACHIEVED
    assert result.telemetry["fallback_used"]
    assert not result.telemetry["refusal_generated"]
    assert PASSAGES[0] in result.final_answer and "[KB1]" in result.final_answer


MULTI = "호박색 카트리지의 제거 원리를 설명해줘. 그리고 보라색 걸쇠의 닫힘 조건을 설명해줘. 그리고 은색 슬리브의 역할을 설명해줘."


@pytest.mark.parametrize("statuses,achieved", [(["SUPPORTED"]*3, True),
    (["SUPPORTED", "UNSUPPORTED", "SUPPORTED"], False), (["PARTIALLY_SUPPORTED"]*3, False)])
def test_atomic_partial_and_consistency(tmp_path, monkeypatch, statuses, achieved):
    assert len(evaluate_claim_support(req(MULTI), []).claims) == 3
    result, _ = run_agent(tmp_path, monkeypatch, MULTI, judge=Verdicts(statuses), accepted=True)
    assert (result.status == GoalStatus.ACHIEVED) == achieved
    assert result.telemetry["claim_count"] == 3
    assert not result.telemetry["refusal_generated"]
    assert "[KB1]" in result.final_answer


@pytest.mark.parametrize("judge", [Verdicts(bad_span=True), Verdicts(conflict=True), Verdicts(["UNSUPPORTED"])])
def test_invalid_support_cannot_inherit_achieved(tmp_path, monkeypatch, judge):
    result, _ = run_agent(tmp_path, monkeypatch, "호박색 카트리지의 염료 제거 원리를 설명해줘.", judge=judge, accepted=True)
    assert result.status != GoalStatus.ACHIEVED


@pytest.mark.parametrize("text", ["호박색 카트리지는 염료를 첨가하므로 그 과정을 설명해줘.",
    "Describe the dye addition process of the amber cartridge, which adds dissolved dye."])
def test_embedded_false_premise_corrected(tmp_path, monkeypatch, text):
    result, _ = run_agent(tmp_path, monkeypatch, text, judge=Verdicts(["CONTRADICTED"]))
    assert result.telemetry["contradicted_claim_count"] == 1
    assert "반대" in result.final_answer or "contradicted" in result.final_answer
    assert PASSAGES[0] in result.final_answer
    assert result.status != GoalStatus.ACHIEVED


@pytest.mark.parametrize("text", [
    "초기 측정값은 62 mm, 최종 측정값은 28 mm. 초기 측정값/최종 측정값 비율을 계산해줘.",
    "최종 측정값은 28 mm, 초기 측정값은 62 mm. 초기 측정값을 최종 측정값으로 나눈 비율을 계산해줘.",
    "입구 62 mm, 출구 28 mm. 입구/출구 비율을 계산해줘.",
])
def test_korean_prose_real_calculation(tmp_path, monkeypatch, text):
    result, research = run_agent(tmp_path, monkeypatch, text, accepted=True)
    assert result.status == GoalStatus.ACHIEVED, result.model_dump()
    assert research.calls == 0
    assert result.python_calls_total == 1 and result.computations[0].validation_passed
    assert any(abs(float(v["value"]) - 62/28) < 1e-8 for v in result.computations[0].output_manifest.values())


@pytest.mark.parametrize("unit", ["EUR/kg", "Pa/(m/s)^2", "kg/m3", "L/h", "kPa/cm", "kg*(m/s)^2"])
def test_compound_unit_grammar(unit):
    assert unit_factors(unit)
    facts = UserFactRegistry.from_topic(f"r=12 {unit};")
    assert len(facts.records) == 1 and facts.records[0].unit == unit


@pytest.mark.parametrize("unit", ["Pa//m", "Pa/(m/s", "kg^99", "kg/__import__", "((((kg))))", "Pa/(m/s)^-99"])
def test_malformed_units_rejected(unit):
    with pytest.raises(ValueError):
        unit_factors(unit)


@pytest.mark.parametrize("text,value,unit", [
    ("r=12 EUR/kg; w=4 kg. Use R = r*w to calculate R.", 48, "EUR"),
    ("R = r*w. w=4 kg, r=12 EUR/kg. R을 계산해줘.", 48, "EUR"),
    ("c=3 Pa/(m/s)^2; v=4 m/s. Use P = c*v**2 to calculate P.", 48, "Pa"),
    ("a=9 kg, b=3 kg. Z = a/b. Z는 무차원. Z를 계산해줘.", 3, "dimensionless"),
])
def test_user_formula_real_sandbox(tmp_path, monkeypatch, text, value, unit):
    result, research = run_agent(tmp_path, monkeypatch, text, accepted=True)
    assert result.status == GoalStatus.ACHIEVED, result.model_dump()
    assert research.calls == 0
    record = result.computations[0]
    assert record.validation_passed and record.output_manifest["OUT_RESULT"]["value"] == value
    assert record.output_manifest["OUT_RESULT"]["unit"] == unit


@pytest.mark.parametrize("text", [
    "p=17 Pa, q=8 Pa. 내부 교재의 보정량 정의를 적용하여 결과를 계산해줘.",
    "Given p=17 Pa and q=8 Pa, calculate the correction using the internal handbook definition.",
])
def test_source_required_route_without_formula_keyword(text):
    intent = classify_goal_intent(req(text), has_user_facts=True)
    assert intent.kind.value == "kb_formula_calc"


@pytest.mark.parametrize("text", [
    "p=17 Pa, q=8 Pa. 내부 교재의 R 보정량 정의를 적용하여 R을 계산해줘.",
    "Given p=17 Pa and q=8 Pa, calculate R using the internal handbook definition of correction R.",
])
def test_kb_transition_full_agent(tmp_path, monkeypatch, text):
    result, research = run_agent(tmp_path, monkeypatch, text, accepted=True,
        sources=Sources(["Correction R is the combined offset. R = p + q. p (Pa) and q (Pa) are supplied offsets; R is in Pa."]))
    assert result.status == GoalStatus.ACHIEVED, result.model_dump()
    assert research.calls >= 1
    actions = [a["action_type"] for a in result.action_history]
    assert actions[0] == "retrieve" and "calculate" in actions
    assert result.computations[0].validation_passed
    assert result.computations[0].formula_source_ids == ["KB1"]
    assert not result.clarification_question


@pytest.mark.parametrize("text", [
    "이 정보만으로 잔여 수명을 정확한 값으로 알려줘.",
    "Determine the exact remaining lifetime from this fact alone.",
    "주어진 정보만으로 정확한 잔여 수명을 설명해줘.",
])
def test_underdetermined_grounded_dependency(tmp_path, monkeypatch, text):
    assert explicitly_underdetermined(text)
    result, _ = run_agent(tmp_path, monkeypatch, text, sources=Sources([
        "Remaining lifetime requires the measured wear depth and a calibrated wear rate."]))
    assert "wear depth" in result.final_answer and "wear rate" in result.final_answer
    assert result.telemetry["final_answer_kind"] == "underdetermined"
    assert result.python_calls_total == 0


@pytest.mark.parametrize("text", [
    "호박색 카트리지의 역할은 무엇이고 보라색 걸쇠는 언제 닫히며 은색 슬리브는 왜 쓰이는지 설명해줘.",
    "Explain the silver sleeve's role and describe the violet latch's closing condition and explain the amber cartridge's removal mechanism.",
    "은색 슬리브의 역할을 설명하고 호박색 카트리지의 제거 원리를 설명하며 보라색 걸쇠의 닫힘 조건을 알려줘.",
])
def test_three_clauses_and_reordered_agent(tmp_path, monkeypatch, text):
    result, _ = run_agent(tmp_path, monkeypatch, text)
    assert result.telemetry["claim_count"] == 3
    assert result.status == GoalStatus.ACHIEVED


def test_noun_phrase_not_split():
    assert len(evaluate_claim_support(req("Explain the relationship between the latch and spring."), []).claims) == 1


def test_conflict_not_hidden_by_selected_span(tmp_path, monkeypatch):
    result, _ = run_agent(tmp_path, monkeypatch, "은색 슬리브와 센서 진동의 관계를 설명해줘.",
        sources=Sources(["The silver sleeve increases sensor vibration.", "The silver sleeve reduces sensor vibration."]),
        accepted=True)
    assert result.status != GoalStatus.ACHIEVED
    assert "[KB1]" in result.final_answer and "[KB2]" in result.final_answer


def test_literal_whitespace_preserved(tmp_path, monkeypatch):
    text = "The amber cartridge removes dissolved dye\nby adsorption onto its porous coating."
    result, _ = run_agent(tmp_path, monkeypatch, "호박색 카트리지의 염료 제거 원리를 설명해줘.", sources=Sources([text]))
    assert text in result.final_answer
    assert result.telemetry["exact_span_validation_passed"]


@pytest.mark.parametrize("unit", ["EUR/kg^99", "Pa/(m/s", "kg//s", "Pa/(m/s)^-99"])
def test_malformed_unit_never_drops_into_unitless_fact(unit):
    assert not UserFactRegistry.from_topic(f"r=12 {unit};").records


def test_engineering_rejection_cannot_inherit_achieved(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.engineering_validator.EngineeringValidator.validate_claim",
                        lambda *args, **kwargs: SimpleNamespace(passed=False))
    result, _ = run_agent(tmp_path, monkeypatch, "호박색 카트리지의 염료 제거 원리를 설명해줘.", accepted=True)
    assert result.status != GoalStatus.ACHIEVED
    assert not result.telemetry["exact_span_validation_passed"]
