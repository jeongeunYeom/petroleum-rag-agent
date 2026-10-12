"""New synthetic v19 development scenarios; no sealed evaluation data is read."""

import asyncio
import json
from dataclasses import replace

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import (CriterionEvaluation, CriterionStatus,
    ExpectedResultStatus, GoalCriterion, GoalResearchRequest, GoalRunStatus, GoalStatus)
from app.models.research_schemas import EvidenceCounts, InternalEvidence, ResearchResponse, ResearchTiming
from app.services.calculation_requirements import rank_formula_candidates
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_evaluator import GoalEvaluationResult
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_execution_state import ActionRecord, GoalActionType, GoalExecutionState
from app.services.goal_intent import classify_goal_intent
from app.services.vector_store import VectorStore


class SyntheticResearch:
    def __init__(self, pages=(), neighbors=()):
        self.pages = pages
        self.calls = 0
        self.queries = []
        self.vector_store = self if neighbors else None
        self.neighbors = neighbors

    async def research(self, request):
        self.calls += 1
        self.queries.append(request.query)
        page = self.pages[min(self.calls - 1, len(self.pages) - 1)] if self.pages else []
        sources = [InternalEvidence(evidence_id=f"KB{i}", document="synthetic-v19-guide.txt",
                    page=number, chunk_id=f"s{number}", score=1.0, excerpt=body)
                   for i, (number, body) in enumerate(page, 1)]
        return ResearchResponse(query=request.query, answer="", internal_sources=sources,
            web_sources=[], figures=[], provenance=[], model=request.model, inference_used=False,
            evidence_counts=EvidenceCounts(internal=len(sources), external=0),
            routing_mode="internal_only", retrieval_mode="hybrid",
            timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0))

    def get_local_chunks(self, document, page, chunk_id, limit=6):
        assert document == "synthetic-v19-guide.txt"
        return [{"id": f"s{number}", "text": body,
                 "metadata": {"document": document, "page": number, "chunk_index": 2}}
                for number, body in self.neighbors if abs(number - page) <= 1][:limit]


class PassingEvaluator:
    async def evaluate(self, request, criteria, answer, evidence, validation, **kwargs):
        ids = [str(row["evidence_id"]) for row in evidence]
        return GoalEvaluationResult(criteria=[CriterionEvaluation(criterion_id=c.criterion_id,
            status=CriterionStatus.MET, reason="Synthetic support", supporting_evidence=ids)
            for c in criteria], coverage=1, achieved=True,
            expected_result_status=ExpectedResultStatus.NOT_PROVIDED, gaps=[], next_research_need=None,
            engineering_validation_passed=True, engineering_contradiction_count=0,
            unsupported_engineering_claim_count=0, goal_conflicts_with_evidence=False)


class RejectingEvaluator(PassingEvaluator):
    async def evaluate(self, *args, **kwargs):
        result = await super().evaluate(*args, **kwargs)
        return replace(result, achieved=False, coverage=0,
            criteria=[c.model_copy(update={"status": CriterionStatus.UNMET}) for c in result.criteria])


class SyntheticSemanticSupport:
    """Deterministic stand-in for semantic judgments over literal synthetic spans."""
    def __init__(self, unsupported_terms=()):
        self.unsupported_terms = tuple(unsupported_terms)

    async def chat_structured(self, messages, schema, **kwargs):
        payload = json.loads(messages[-1]["content"])
        spans = payload["source_spans"]
        decisions = []
        for claim in payload["claims"]:
            description = claim["description"].casefold()
            missing = any(term in description for term in self.unsupported_terms)
            partial = missing and (" and " in description or "," in description)
            matched = [span["span_id"] for span in spans]
            decisions.append({"claim_id": claim["claim_id"],
                "status": "PARTIALLY_SUPPORTED" if partial else "UNSUPPORTED" if missing else "SUPPORTED",
                "span_ids": matched[:2] if not missing or partial else [],
                "evidence_conflict": False})
        return json.dumps({"claims": decisions})


async def no_synthesis(*args, **kwargs):
    return ""


def request(text, *, criterion=None, max_iterations=8):
    return GoalResearchRequest(topic=text, goal=text, model="qwen3:8b", use_internal=True,
        use_external=False, execution_mode="autonomous_goal_execution", max_iterations=max_iterations,
        max_retrieval_actions=3, success_criteria=[GoalCriterion(criterion_id="C1",
            description=criterion or text)])


def execute(tmp_path, monkeypatch, text, pages=(), *, neighbors=(), qa=False, criterion=None,
            unsupported_terms=()):
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    research = SyntheticResearch(pages, neighbors)
    agent = GoalExecutionAgent(research, SyntheticSemanticSupport(unsupported_terms) if qa else object(),
        evaluator=RejectingEvaluator() if qa else PassingEvaluator(), synthesizer=no_synthesis)
    result = asyncio.run(agent.run("v19-synthetic", request(text, criterion=criterion)))
    return result, research, agent


def actions(result):
    return [row["action_type"] for row in result.action_history]


def result_value(result):
    output = result.computations[0].output_manifest
    return next(row["value"] for key, row in output.items() if key.startswith("OUT_"))


def test_formula_recovery_second_retrieval_executes(tmp_path, monkeypatch):
    text = "Force=7 lbf; Arm=3 ft. Find the internal equation for Torque and calculate Torque."
    pages = [[(4, "Torque is defined by force and lever arm.")],
             [(5, "Torque equation: Torque=Force*Arm. Force (lbf); Arm (ft).")]]
    result, research, _ = execute(tmp_path, monkeypatch, text, pages)
    assert actions(result)[:3] == ["retrieve", "retrieve", "calculate"]
    assert result.computations[0].validation_passed and result_value(result) == 21
    assert result.telemetry["formula_recovery_attempt_count"] == 1
    assert result.telemetry["formula_recovery_success"]
    assert "Force" in research.queries[1] and "lbf" in research.queries[1]


def test_formula_local_indexed_neighbor_executes(tmp_path, monkeypatch):
    text = "Mass=18 kg; Area=6 m2. Find the internal Flux equation and calculate Flux."
    pages = [[(11, "Flux depends on mass and area. See the adjacent definition.")]]
    neighbors = [(12, "Flux equation: Flux=Mass/Area. Mass (kg); Area (m2).")]
    result, research, _ = execute(tmp_path, monkeypatch, text, pages, neighbors=neighbors)
    assert research.calls == 1
    assert actions(result)[:2] == ["retrieve", "calculate"]
    assert result_value(result) == 3
    assert result.telemetry["formula_local_expansion_used"]
    assert result.telemetry["formula_local_expansion_success"]
    assert result.computations[0].formula_source_ids == ["KB2"]


def test_local_chunk_reader_stays_on_original_indexed_pages():
    class Collection:
        def get(self, *, ids=None, where=None, include=None):
            if ids:
                return {"metadatas": [{"chunk_index": 5}]}
            page = where["$and"][1]["page"]
            rows = {
                6: [("s6", "Adjacent earlier passage", 4)],
                7: [("s7", "Original passage", 5), ("s7b", "Neighboring literal equation", 6)],
                8: [("s8", "Adjacent later passage", 7)],
            }.get(page, [])
            return {"ids": [row[0] for row in rows], "documents": [row[1] for row in rows],
                "metadatas": [{"document": "synthetic-v19-guide.txt", "page": page,
                               "chunk_index": row[2]} for row in rows]}

    store = object.__new__(VectorStore)
    store.collection = Collection()
    rows = store.get_local_chunks("synthetic-v19-guide.txt", 7, "s7", limit=2)
    assert [row["id"] for row in rows] == ["s7b", "s6"]
    assert all(abs(row["metadata"]["page"] - 7) <= 1 for row in rows)


def test_formula_unit_compatibility_disambiguates_literal_candidates():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "document": "synthetic.txt",
        "text": "Index equation: Index=Load/Area. Load (kg); Area (m2)."},
        {"evidence_id": "KB2", "source_type": "knowledge_base", "document": "synthetic.txt",
         "text": "Index equation: Index=Load/Area. Load (psi); Area (ft2)."}]
    selected, ranking = rank_formula_candidates(evidence, "Calculate Index from Load and Area",
        ["Load", "Area"], {"Load": "psi", "Area": "ft2"})
    assert selected and selected.source_id == "KB2"
    assert ranking.unit_score > 0


def test_formula_recovery_bounded_and_no_invention(tmp_path, monkeypatch):
    text = "Sample=9 kg. Find the internal source equation for Yield and calculate Yield."
    pages = [[(3, "Yield is discussed in the process overview.")],
             [(4, "This section lists operating conditions only.")],
             [(5, "No mathematical definition is supplied here.")]]
    result, research, _ = execute(tmp_path, monkeypatch, text, pages)
    assert research.calls == 3
    assert result.telemetry["formula_recovery_attempt_count"] == 2
    assert not result.telemetry["formula_recovery_success"]
    assert not result.computations and result.status != GoalStatus.ACHIEVED


def test_unverified_source_cannot_force_calculation():
    text = "Load=8 kg. Find the internal Yield equation and calculate Yield."
    req = request(text)
    state = GoalExecutionState.from_criteria("v19", text, req.success_criteria)
    state.evidence_ids = ["KB1"]
    state.completed_actions.append(ActionRecord(
        iteration=1, action_id="ACT-1", action_type=GoalActionType.RETRIEVE,
        target_criteria=["C1"], status="completed", reason_code="formula_source_missing",
        evidence_added=["KB1"]))
    state.iteration = 1
    action = GoalActionPlanner.select(req.model_copy(update={"allow_python_execution": True,
        "python_execution_approved": True}), state, user_fact_ids=["USERF1"],
        formula_ready=True, formula_source_verified=False, formula_inputs_ready=True,
        simulation_spec=None, intent=classify_goal_intent(req, has_user_facts=True))
    assert action.action_type == GoalActionType.RETRIEVE
    assert action.reason_code == "formula_recovery"


def test_source_unit_conflict_never_reaches_python(tmp_path, monkeypatch):
    text = "Load=8 psi; Area=2 m2. Find the internal Index equation and calculate Index."
    source = "Index relation: Index=Load/Area. Load (kg); Area (m2)."
    result, _, _ = execute(tmp_path, monkeypatch, text, [[(6, source)]])
    assert result.python_calls_total == 0
    assert not result.computations
    assert result.status != GoalStatus.ACHIEVED
    assert not result.telemetry["calculation_validated"]


@pytest.mark.parametrize("text,source,expected", [
    ("Load=40 psi; Area=8 ft2. Find the internal equation for Index and calculate Index.",
     "Index relation: Index=Load/Area. Load (psi); Area (ft2).", 5),
    ("질량 Mass=18 kg, 면적 Area=6 m2. 내부 자료의 Flux 관계식으로 Flux를 계산해줘.",
     "Flux relation: Flux=Mass/Area. Mass (kg); Area (m2).", 3),
    ("Weight=24 g/mol; AirWeight=30 g/mol. Find the internal equation for Ratio and calculate Ratio.",
     "Ratio relation: Ratio=Weight/AirWeight. Weight (g/mol); AirWeight (g/mol).", 0.8),
])
def test_ready_source_forces_deterministic_calculate(tmp_path, monkeypatch, text, source, expected):
    result, research, _ = execute(tmp_path, monkeypatch, text, [[(8, source)]])
    assert actions(result)[:2] == ["retrieve", "calculate"]
    assert result.telemetry["forced_calculate_transition"]
    assert result.telemetry["formula_source_verified"]
    assert result.computations[0].validation_passed
    assert result_value(result) == pytest.approx(expected)


def test_all_grounded_claims_override_refusal(tmp_path, monkeypatch):
    text = "Define a pressure snubber and explain its purpose."
    source = "A pressure snubber dampens rapid pressure pulses before they reach a gauge."
    result, _, _ = execute(tmp_path, monkeypatch, text, [[(2, source)]], qa=True,
        criterion="A pressure snubber dampens rapid pressure pulses before they reach a gauge")
    assert result.status == GoalStatus.ACHIEVED
    assert result.telemetry["pre_stop_guard_checked"]
    assert result.telemetry["pre_stop_guard_prevented_refusal"]
    assert "[KB1]" in result.final_answer


def test_literal_relation_overrides_generic_model_refusal(tmp_path, monkeypatch):
    source = "A relief valve prevents pressure from exceeding a set limit."
    result, _, _ = execute(tmp_path, monkeypatch,
        "Explain the function of a relief valve.",
        [[(2, source)]], qa=True,
        criterion="Function of a relief valve: a relief valve prevents pressure from exceeding a set limit",
        unsupported_terms=("relief",))
    assert result.telemetry["deterministic_literal_support_recovered"] >= 1
    assert result.telemetry["pre_stop_guard_prevented_refusal"]
    assert "[KB1]" in result.final_answer


def test_partial_grounding_keeps_supported_claims(tmp_path, monkeypatch):
    text = "Define a pressure snubber, identify a relief valve, and state an undocumented calibration interval."
    source = ("A pressure snubber dampens rapid pressure pulses before they reach a gauge.\n"
              "A relief valve opens to limit excess pressure.")
    criteria = [GoalCriterion(criterion_id="C1", description="A pressure snubber dampens rapid pressure pulses"),
                GoalCriterion(criterion_id="C2", description="A relief valve opens to limit excess pressure"),
                GoalCriterion(criterion_id="C3", description="State the exact calibration interval")]
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    req = request(text).model_copy(update={"success_criteria": criteria})
    result = asyncio.run(GoalExecutionAgent(SyntheticResearch([[(2, source)]]),
        SyntheticSemanticSupport(("calibration",)),
        evaluator=RejectingEvaluator(), synthesizer=no_synthesis).run("partial-v19", req))
    assert result.status != GoalStatus.ACHIEVED
    assert result.telemetry["partial_grounded_answer_used"]
    assert "[KB1]" in result.final_answer
    assert "calibration" in result.final_answer.casefold()


def test_related_but_unsupported_claim_stays_unanswered(tmp_path, monkeypatch):
    result, _, _ = execute(tmp_path, monkeypatch,
        "State the exact burst pressure of a rupture disk in this guide.",
        [[(2, "A rupture disk is a one-time overpressure protection device.")]], qa=True,
        unsupported_terms=("burst pressure",))
    assert result.status != GoalStatus.ACHIEVED
    assert not result.telemetry["pre_stop_guard_prevented_refusal"]
    assert not result.computations


@pytest.mark.parametrize("text,source,reply,expected", [
    ("Feed=14 kg. Find the internal equation for Product and calculate Product.",
     "Product equation: Product=Feed*Factor. Feed (kg); Factor is dimensionless.",
     "Factor=3 dimensionless", 42),
    ("Output=9 kg. Use Gain=Output*Multiplier to calculate Gain.", "", "Multiplier=4 dimensionless", 36),
    ("Length=12 m. Use Reach=Length+Offset to calculate Reach.", "", "Offset=5 m", 17),
])
def test_resume_recomputes_readiness_and_keeps_run(tmp_path, monkeypatch, text, source, reply, expected):
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    research = SyntheticResearch([[(7, source)]] if source else [])
    agent = GoalExecutionAgent(research, object(), evaluator=PassingEvaluator(), synthesizer=no_synthesis)
    req = request(text)
    first = asyncio.run(agent.run("resume-v19", req))
    assert first.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT
    checkpoint = dict(first.resume_checkpoint)
    checkpoint["user_replies"] = [reply]
    resumed = asyncio.run(agent.run(first.run_id, req, resume_state=checkpoint, resume_result=first))
    assert resumed.run_id == first.run_id
    assert resumed.telemetry["resume_readiness_recomputed"]
    assert resumed.telemetry["resume_block_cleared"]
    assert resumed.telemetry["clarification_suppressed_existing_input"]
    assert resumed.clarification_question is None
    assert resumed.computations[0].validation_passed
    assert result_value(resumed) == expected


def test_korean_request_english_formula_source(tmp_path, monkeypatch):
    result, _, _ = execute(tmp_path, monkeypatch,
        "힘 Force=9 lbf, 팔길이 Arm=4 ft야. 내부 자료의 Torque 식을 찾아 계산해줘.",
        [[(9, "Torque equation: Torque=Force*Arm. Force (lbf); Arm (ft).")]])
    assert result.status == GoalStatus.ACHIEVED
    assert result_value(result) == 36
    assert "[KB1]" in result.final_answer


def test_korean_request_english_claim_source(tmp_path, monkeypatch):
    result, _, _ = execute(tmp_path, monkeypatch,
        "압력 스너버의 기능을 내부 근거로 설명해줘.",
        [[(9, "A pressure snubber dampens rapid pressure pulses before they reach a gauge.")]],
        qa=True, criterion="A pressure snubber dampens rapid pressure pulses before they reach a gauge")
    assert result.status == GoalStatus.ACHIEVED
    assert result.telemetry["pre_stop_guard_prevented_refusal"]
    assert "[KB1]" in result.final_answer
