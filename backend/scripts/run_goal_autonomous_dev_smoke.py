"""Development-only two-source smoke; not part of frozen evaluations."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest
from app.models.research_schemas import EvidenceCounts, InternalEvidence, ResearchResponse, ResearchTiming
from app.services.goal_research_agent import GoalResearchAgent
from app.services.goal_research_service import GoalResearchService
from app.services.ollama import OllamaClient


class StagedEvidence:
    def __init__(self):
        self.calls = 0

    async def research(self, request):
        self.calls += 1
        text = (
            "Measured permeability for case A is 10 mD."
            if self.calls == 1 else
            "Measured permeability for case B is 20 mD."
        )
        return ResearchResponse(
            query=request.query, answer=text,
            internal_sources=[InternalEvidence(
                evidence_id="KB1", document="dev_fixture.txt", page=self.calls,
                chunk_id=str(self.calls), score=1.0, excerpt=text,
            )],
            web_sources=[], figures=[], provenance=[],
            model=request.model, inference_used=True,
            evidence_counts=EvidenceCounts(internal=1, external=0),
            routing_mode="internal_only", retrieval_mode="hybrid",
            timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0),
            validation={},
        )


def main():
    settings = get_settings()
    request = GoalResearchRequest(
        topic="Compare two measured permeability cases",
        goal="Use measured case A and B values to calculate their difference and percentage change, then chart both values.",
        success_criteria=[
            GoalCriterion(criterion_id="C1", description="Identify both source-supported permeability inputs"),
            GoalCriterion(criterion_id="C2", description="Calculate the difference and percentage change using cited input values"),
            GoalCriterion(criterion_id="C3", description="Generate a chart of both measured values"),
        ],
        engineering_validation=False,
        use_external=False,
        max_iterations=3,
        no_progress_patience=3,
        allow_python_execution=True,
        python_execution_approved=True,
        deliverables=["docx", "pptx"],
        model="qwen3:8b",
    )
    service = GoalResearchService(settings, GoalResearchAgent(StagedEvidence(), OllamaClient(settings)))
    started = service.start(request)
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        result = service.get(started.run_id)
        if result.run_status.value in {"failed", "canceled"}:
            break
        if set(request.deliverables).issubset(result.deliverable_status) and all(
            status in {"completed", "failed"} for status in result.deliverable_status.values()
        ):
            break
        time.sleep(0.5)
    else:
        raise TimeoutError("Development smoke did not reach final deliverable state")
    output = settings.goal_research_runs_dir / f"{started.run_id}.json"
    print(json.dumps({
        "run_id": started.run_id,
        "status": result.status.value,
        "coverage": [item.goal_coverage for item in result.iterations],
        "python_decisions": [
            {"requested": item.python_requested, "reason": item.python_decision_reason}
            for item in result.iterations
        ],
        "python_calls": result.python_calls_total,
        "python_attempts": result.python_attempts_total,
        "computations": [
            {"id": item.computation_id, "valid": item.validation_passed,
             "attempts": item.attempts, "sources": item.source_evidence_ids,
             "outputs": item.output_files}
            for item in result.computations
        ],
        "stop_reason": result.stop_reason.value if result.stop_reason else None,
        "deliverable_status": result.deliverable_status,
        "artifacts": [
            {"type": item.artifact_type, "path": item.path, "bytes": item.size_bytes}
            for item in result.artifacts
        ],
        "run_log": str(output),
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
