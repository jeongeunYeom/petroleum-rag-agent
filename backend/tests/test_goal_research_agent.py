from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from app.models.goal_research_schemas import (
    CriterionEvaluation,
    CriterionStatus,
    ExpectedResultStatus,
    GoalCriterion,
    GoalResearchRequest,
    GoalStatus,
    GoalStopReason,
)
from app.models.research_schemas import (
    EvidenceCounts,
    InternalEvidence,
    ResearchResponse,
    ResearchTiming,
)
from app.services.goal_evaluator import GoalEvaluationResult, GoalEvaluator
from app.services.goal_planner import GoalPlanner
from app.services.goal_research_agent import EvidenceAccumulator, GoalResearchAgent


CRITERIA = [
    GoalCriterion(criterion_id="C1", description="Explain the relationship."),
    GoalCriterion(criterion_id="C2", description="Provide evidence."),
]


def research_response(chunk: str | None, validation: dict | None = None) -> ResearchResponse:
    sources = []
    if chunk:
        sources = [
            InternalEvidence(
                evidence_id="KB1",
                document="book.pdf",
                page=1,
                chunk_id=chunk,
                score=0.9,
                excerpt=f"Evidence for {chunk}",
            )
        ]
    return ResearchResponse(
        query="query",
        answer="iteration answer",
        internal_sources=sources,
        web_sources=[],
        figures=[],
        provenance=[],
        model="qwen3:8b",
        inference_used=bool(sources),
        evidence_counts=EvidenceCounts(internal=len(sources), external=0),
        routing_mode="internal_only",
        retrieval_mode="hybrid",
        timing=ResearchTiming(
            retrieval_seconds=0.01,
            reasoning_seconds=0.01,
            elapsed_seconds=0.02,
        ),
        validation=validation or {
            "engineering_contradiction_count": 0,
            "unsupported_engineering_claim_count": 0,
            "false_premise_detected": False,
        },
    )


class FakeResearchAgent:
    def __init__(self, responses: list[ResearchResponse]):
        self.responses = responses
        self.requests = []

    async def research(self, request):
        self.requests.append(request)
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]


class FakeEvaluator:
    def __init__(self, results: list[GoalEvaluationResult], mutate=False):
        self.results = results
        self.calls = 0
        self.mutate = mutate

    async def evaluate(self, request, criteria, candidate, evidence, validation):
        if self.mutate:
            criteria[0].description = "drifted"
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result


def evaluation(
    coverage: float,
    *,
    achieved: bool = False,
    expected=ExpectedResultStatus.NOT_PROVIDED,
    conflict: bool = False,
) -> GoalEvaluationResult:
    statuses = (
        [CriterionStatus.MET, CriterionStatus.MET]
        if coverage == 1
        else [CriterionStatus.MET, CriterionStatus.UNMET]
    )
    return GoalEvaluationResult(
        criteria=[
            CriterionEvaluation(
                criterion_id=f"C{index}",
                status=status,
                reason="checked",
                supporting_evidence=["KB1"] if status == CriterionStatus.MET else [],
            )
            for index, status in enumerate(statuses, start=1)
        ],
        coverage=coverage,
        achieved=achieved,
        expected_result_status=expected,
        gaps=[] if achieved else ["Need more evidence"],
        next_research_need=None if achieved else "Find a distinct source",
        engineering_validation_passed=True,
        engineering_contradiction_count=0,
        unsupported_engineering_claim_count=0,
        goal_conflicts_with_evidence=conflict,
    )


async def synthesize(*_args):
    return "Evidence-grounded candidate [KB1]."


def controller(responses, evaluations, *, planner=None, evaluator=None):
    research = FakeResearchAgent(responses)
    agent = GoalResearchAgent(
        research,
        ollama=object(),
        planner=planner or GoalPlanner(object()),
        evaluator=evaluator or FakeEvaluator(evaluations),
        synthesizer=synthesize,
    )
    return agent, research


def test_goal_research_reaches_goal_after_three_iterations():
    agent, _ = controller(
        [research_response("1"), research_response("2"), research_response("3")],
        [evaluation(0.5), evaluation(0.5), evaluation(1.0, achieved=True)],
    )
    result = asyncio.run(
        agent.run(
            "GR-TEST",
            GoalResearchRequest(topic="partial penetration", success_criteria=CRITERIA),
        )
    )
    assert result.iterations_completed == 3
    assert result.status == GoalStatus.ACHIEVED
    assert result.stop_reason == GoalStopReason.GOAL_ACHIEVED
    assert len({item.research_query for item in result.iterations}) == 3


def test_max_iterations_is_hard_limit():
    agent, research = controller(
        [research_response("1"), research_response("2"), research_response("3")],
        [evaluation(0.5)],
    )
    result = asyncio.run(agent.run(
        "GR-TEST",
        GoalResearchRequest(
            topic="topic",
            success_criteria=CRITERIA,
            max_iterations=3,
            no_progress_patience=3,
        ),
    ))
    assert len(research.requests) == 3
    assert result.stop_reason == GoalStopReason.MAX_ITERATIONS


def test_no_progress_stops_after_patience_without_new_evidence():
    same = research_response("1")
    agent, research = controller([same, same, same, same], [evaluation(0.5)])
    result = asyncio.run(agent.run(
        "GR-TEST",
        GoalResearchRequest(
            topic="topic",
            success_criteria=CRITERIA,
            max_iterations=8,
            no_progress_patience=2,
        ),
    ))
    assert len(research.requests) == 3
    assert result.stop_reason == GoalStopReason.NO_PROGRESS


def test_contradicted_hypothesis_can_still_achieve_research_goal():
    agent, _ = controller(
        [research_response("1")],
        [
            evaluation(
                1.0,
                achieved=True,
                expected=ExpectedResultStatus.CONTRADICTED,
            )
        ],
    )
    result = asyncio.run(agent.run(
        "GR-TEST",
        GoalResearchRequest(
            topic="X and recovery",
            goal="Determine the relationship",
            expected_result="X increases recovery",
            success_criteria=CRITERIA,
        ),
    ))
    assert result.status == GoalStatus.ACHIEVED
    assert result.expected_result_status == ExpectedResultStatus.CONTRADICTED


def test_goal_that_conflicts_with_evidence_is_not_supported():
    agent, _ = controller(
        [research_response("1")],
        [
            evaluation(
                0.5,
                expected=ExpectedResultStatus.CONTRADICTED,
                conflict=True,
            )
        ],
    )
    result = asyncio.run(agent.run(
        "GR-TEST",
        GoalResearchRequest(
            topic="permeability",
            goal="Prove 500 mD",
            expected_result="Permeability is 500 mD",
            success_criteria=CRITERIA,
        ),
    ))
    assert result.status == GoalStatus.NOT_SUPPORTED
    assert result.stop_reason == GoalStopReason.GOAL_CONFLICTS_WITH_EVIDENCE


def test_no_evidence_never_achieves_goal():
    agent, _ = controller(
        [research_response(None)],
        [evaluation(0.0)],
    )
    result = asyncio.run(agent.run(
        "GR-TEST",
        GoalResearchRequest(
            topic="unknown",
            success_criteria=CRITERIA,
            max_iterations=1,
        ),
    ))
    assert result.status == GoalStatus.INSUFFICIENT_EVIDENCE
    assert result.stop_reason == GoalStopReason.INSUFFICIENT_EVIDENCE


def test_web_opt_in_is_never_enabled_by_replanning():
    agent, research = controller(
        [research_response("1"), research_response("2")],
        [evaluation(0.5)],
    )
    asyncio.run(agent.run(
        "GR-TEST",
        GoalResearchRequest(
            topic="topic",
            success_criteria=CRITERIA,
            use_external=False,
            max_iterations=2,
        ),
    ))
    assert research.requests
    assert all(request.use_external is False for request in research.requests)


def test_criteria_drift_is_rejected():
    evaluator = FakeEvaluator([evaluation(0.5)], mutate=True)
    agent, _ = controller([research_response("1")], [], evaluator=evaluator)
    with pytest.raises(RuntimeError, match="criteria changed"):
        asyncio.run(agent.run(
            "GR-TEST",
            GoalResearchRequest(topic="topic", success_criteria=CRITERIA),
        ))


class DuplicatePlanner(GoalPlanner):
    def replan(self, request, criteria, evaluations, gaps, next_need, previous):
        return self.initial_plan(request, criteria)


def test_duplicate_query_is_not_researched_twice():
    agent, research = controller(
        [research_response("1"), research_response("2")],
        [evaluation(0.5)],
        planner=DuplicatePlanner(object()),
    )
    result = asyncio.run(agent.run(
        "GR-TEST",
        GoalResearchRequest(topic="topic", success_criteria=CRITERIA),
    ))
    assert len(research.requests) == 1
    assert result.stop_reason == GoalStopReason.NO_PROGRESS


def test_evidence_accumulator_deduplicates_internal_chunks():
    accumulator = EvidenceAccumulator()
    assert accumulator.add(research_response("1")) == ["KB1"]
    assert accumulator.add(research_response("1")) == []
    assert len(accumulator.internal) == 1


def test_request_limits_iterations_and_requires_source():
    with pytest.raises(ValidationError):
        GoalResearchRequest(topic="x", max_iterations=9)
    with pytest.raises(ValidationError):
        GoalResearchRequest(topic="x", use_internal=False, use_external=False)


class EvaluationOllama:
    async def chat_structured(self, *_args, **_kwargs):
        return json.dumps(
            {
                "criteria": [
                    {
                        "criterion_id": "C1",
                        "status": "met",
                        "reason": "Claimed without support",
                        "supporting_evidence": [],
                    },
                    {
                        "criterion_id": "C2",
                        "status": "met",
                        "reason": "Supported",
                        "supporting_evidence": ["KB1"],
                    },
                ],
                "expected_result_status": "not_provided",
                "gaps": [],
                "next_research_need": None,
                "goal_conflicts_with_evidence": False,
            }
        )


def test_evaluator_downgrades_met_without_supporting_evidence():
    result = asyncio.run(GoalEvaluator(EvaluationOllama()).evaluate(
        GoalResearchRequest(topic="topic", success_criteria=CRITERIA),
        CRITERIA,
        "candidate",
        [{"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "x", "text": "evidence"}],
        {},
    ))
    assert result.criteria[0].status == CriterionStatus.PARTIAL
    assert result.coverage == 0.75
    assert result.achieved is False


class MetEvaluationOllama:
    async def chat_structured(self, *_args, **_kwargs):
        return json.dumps(
            {
                "criteria": [
                    {
                        "criterion_id": item.criterion_id,
                        "status": "met",
                        "reason": "claimed met",
                        "supporting_evidence": ["KB1"],
                    }
                    for item in CRITERIA
                ],
                "expected_result_status": "contradicted",
                "gaps": [],
                "next_research_need": None,
                "goal_conflicts_with_evidence": False,
            }
        )


class PartialConflictOllama(MetEvaluationOllama):
    async def chat_structured(self, *_args, **_kwargs):
        data = json.loads(await super().chat_structured())
        data["expected_result_status"] = "partially_supported"
        data["goal_conflicts_with_evidence"] = True
        return json.dumps(data)


def test_candidate_engineering_contradiction_prevents_goal_success():
    result = asyncio.run(GoalEvaluator(MetEvaluationOllama()).evaluate(
        GoalResearchRequest(
            topic="radial flow pressure derivative",
            expected_result="radial flow derivative has unit slope",
            success_criteria=CRITERIA,
        ),
        CRITERIA,
        "Radial flow pressure derivative has a unit slope. [KB1]",
        [{
            "evidence_id": "KB1",
            "source_type": "knowledge_base",
            "locator": "book p.1",
            "text": "Radial flow has a horizontal constant pressure derivative plateau.",
        }],
        {},
    ))
    assert result.engineering_contradiction_count > 0
    assert result.achieved is False
    assert result.gaps
    assert result.next_research_need


def test_partial_hypothesis_support_cannot_trigger_goal_conflict_stop():
    result = asyncio.run(GoalEvaluator(PartialConflictOllama()).evaluate(
        GoalResearchRequest(
            topic="CO2 trapping",
            expected_result="Residual saturation increases trapping",
            success_criteria=CRITERIA,
            engineering_validation=False,
        ),
        CRITERIA,
        "Supported relationship [KB1]",
        [{"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "x", "text": "evidence"}],
        {},
    ))
    assert result.expected_result_status == ExpectedResultStatus.PARTIALLY_SUPPORTED
    assert result.goal_conflicts_with_evidence is False


class InvalidJsonOllama:
    def __init__(self):
        self.calls = 0

    async def chat_structured(self, *_args, **_kwargs):
        self.calls += 1
        return '{"criteria": ['


def test_invalid_evaluator_json_retries_then_returns_safe_unmet_result():
    ollama = InvalidJsonOllama()
    result = asyncio.run(GoalEvaluator(ollama).evaluate(
        GoalResearchRequest(
            topic="topic",
            expected_result="hypothesis",
            success_criteria=CRITERIA,
            engineering_validation=False,
        ),
        CRITERIA,
        "candidate [KB1]",
        [{"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "x", "text": "evidence"}],
        {},
    ))
    assert ollama.calls == 2
    assert result.achieved is False
    assert result.coverage == 0
    assert result.expected_result_status == ExpectedResultStatus.INSUFFICIENT_EVIDENCE
