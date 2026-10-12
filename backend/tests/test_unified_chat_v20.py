"""Unified-chat service contract using fresh synthetic runs, not sealed evaluation."""

import time

from app.core.config import Settings
from app.models.goal_research_schemas import (GoalResearchResponse, GoalRunStatus,
    GoalStatus, GoalStopReason)
from app.services.goal_message_parser import GoalMessageRequest, parse_goal_message
from app.services.goal_research_service import GoalResearchService


class AchievedController:
    async def run(self, run_id, request, **_kwargs):
        return GoalResearchResponse(run_id=run_id, topic=request.topic,
            max_iterations=request.max_iterations, run_status=GoalRunStatus.COMPLETED,
            status=GoalStatus.ACHIEVED, stop_reason=GoalStopReason.GOAL_ACHIEVED,
            final_answer="Grounded answer [KB1]")


def test_artifact_failure_is_reported_without_false_target_completion(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    controller = AchievedController()
    service = GoalResearchService(settings, controller, controller)

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic file failure")

    service.deliverables.create = fail
    request = parse_goal_message(GoalMessageRequest(message="Create a report about pressure testing."))
    started = service.start(request)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = service.get(started.run_id)
        busy = any(value in {"pending", "running"} for value in result.deliverable_status.values())
        if result.run_status in {GoalRunStatus.COMPLETED, GoalRunStatus.STOPPED, GoalRunStatus.FAILED} and not busy:
            break
        time.sleep(.01)
    assert result.run_status == GoalRunStatus.STOPPED
    assert result.stop_reason == GoalStopReason.DELIVERABLE_FAILED
    assert result.telemetry["target_completed"] is False
    assert result.telemetry["entrypoint"] == "unified_chat"
    assert result.deliverable_status == {"docx": "failed"}
    assert "could not be generated" in result.final_answer
