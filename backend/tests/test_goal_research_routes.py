from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.goal_research_routes import get_goal_research_service
from app.core.config import Settings
from app.main import app
from app.models.goal_research_schemas import (
    GoalResearchRequest,
    GoalResearchResponse,
    GoalRunStatus,
    GoalStatus,
    GoalStopReason,
)
from app.services.goal_research_service import GoalResearchService


def response(run_id="GR-TEST", run_status=GoalRunStatus.PLANNED):
    return GoalResearchResponse(
        run_id=run_id,
        topic="topic",
        run_status=run_status,
        status=GoalStatus.PENDING,
        max_iterations=4,
    )


class FakeService:
    def __init__(self):
        self.value = response()
        self.request = None

    def start(self, request):
        self.request = request
        self.value.topic = request.topic
        return self.value

    def get(self, run_id):
        assert run_id == self.value.run_id
        return self.value

    def cancel(self, run_id):
        assert run_id == self.value.run_id
        self.value.run_status = GoalRunStatus.CANCELED
        self.value.status = GoalStatus.CANCELED
        self.value.stop_reason = GoalStopReason.CANCELED
        return self.value


def test_goal_research_routes_start_poll_and_cancel():
    service = FakeService()
    app.dependency_overrides[get_goal_research_service] = lambda: service
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/research/goal-runs",
                json={"topic": "Residual CO2 trapping"},
            )
            assert created.status_code == 201
            assert created.json()["run_id"] == "GR-TEST"
            assert client.get("/api/research/goal-runs/GR-TEST").status_code == 200
            canceled = client.post("/api/research/goal-runs/GR-TEST/cancel")
            assert canceled.json()["run_status"] == "canceled"
    finally:
        app.dependency_overrides.clear()


def test_goal_research_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/api/research/goal-runs" in paths
    assert "/api/research/goal-runs/from-message" in paths
    assert "/api/research/goal-runs/{run_id}" in paths
    assert "/api/research/goal-runs/{run_id}/cancel" in paths


def test_single_message_route_uses_existing_goal_service_without_web_by_default():
    service = FakeService()
    app.dependency_overrides[get_goal_research_service] = lambda: service
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/research/goal-runs/from-message",
                json={"message": "SG가 0.918인 원유의 API gravity를 내부 교재의 식을 찾아 계산해줘."},
            )
            assert created.status_code == 201
            assert service.request.execution_mode == "autonomous_goal_execution"
            assert service.request.use_internal and not service.request.use_external
            assert service.request.expected_result is None
            assert service.request.goal.startswith("SG가 0.918")
            assert client.post("/api/research/goal-runs/from-message", json={"message": "이 주제로 조사해줘."}).status_code == 422
    finally:
        app.dependency_overrides.clear()


class CompletingController:
    async def run(self, run_id, request, *, is_canceled, on_progress):
        value = response(run_id, GoalRunStatus.RUNNING)
        value.topic = request.topic
        on_progress(value)
        value.run_status = GoalRunStatus.COMPLETED
        value.status = GoalStatus.ACHIEVED
        value.stop_reason = GoalStopReason.GOAL_ACHIEVED
        value.final_answer = "done"
        return value


def test_background_service_persists_complete_run(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        agent_workspace_dir=tmp_path / "workspace",
    )
    service = GoalResearchService(settings, CompletingController())
    created = service.start(GoalResearchRequest(topic="topic"))
    deadline = time.monotonic() + 2
    current = created
    while time.monotonic() < deadline:
        current = service.get(created.run_id)
        if current.run_status == GoalRunStatus.COMPLETED:
            break
        time.sleep(0.01)
    assert current.status == GoalStatus.ACHIEVED
    assert current.final_answer == "done"
    assert (settings.goal_research_runs_dir / f"{created.run_id}.json").is_file()


def test_deliverables_remain_pending_during_terminal_agent_progress(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    service = GoalResearchService(settings, CompletingController())
    request = GoalResearchRequest(topic="topic", deliverables=["docx", "pptx"])
    interim = response("GR-TEST", GoalRunStatus.COMPLETED)
    service._write("GR-TEST", request, interim)
    assert service.get("GR-TEST").deliverable_status == {"docx": "pending", "pptx": "pending"}
