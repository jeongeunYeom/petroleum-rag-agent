from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock, Thread
from uuid import uuid4

from app.core.config import Settings
from app.models.goal_research_schemas import (
    ExpectedResultStatus,
    GoalResearchRequest,
    GoalResearchResponse,
    GoalRunStatus,
    GoalStatus,
    GoalStopReason,
)
from app.services.goal_research_agent import GoalResearchAgent
from app.services.deliverables.service import DeliverableService


class GoalResearchRunNotFound(KeyError):
    pass


class GoalResearchRunConflict(RuntimeError):
    pass


class GoalResearchService:
    _lock = RLock()

    def __init__(self, settings: Settings, controller: GoalResearchAgent):
        self.settings = settings
        self.controller = controller
        self.deliverables = DeliverableService(settings)

    def start(self, request: GoalResearchRequest) -> GoalResearchResponse:
        run_id = self._new_run_id()
        response = GoalResearchResponse(
            run_id=run_id,
            topic=request.topic,
            goal=request.goal,
            expected_result=request.expected_result,
            run_status=GoalRunStatus.PLANNED,
            status=GoalStatus.PENDING,
            max_iterations=request.max_iterations,
            criteria_source="user" if request.success_criteria else "inferred",
            frozen_criteria=[item.model_copy(deep=True) for item in request.success_criteria],
            expected_result_status=(
                ExpectedResultStatus.INSUFFICIENT_EVIDENCE
                if request.expected_result
                else ExpectedResultStatus.NOT_PROVIDED
            ),
        )
        self._write(run_id, request, response)
        worker = Thread(
            target=self._execute,
            args=(run_id, request),
            daemon=True,
            name=f"goal-research-{run_id}",
        )
        worker.start()
        return response

    def get(self, run_id: str) -> GoalResearchResponse:
        return self._read(run_id)[1]

    def cancel(self, run_id: str) -> GoalResearchResponse:
        request, response = self._read(run_id)
        if response.run_status in {
            GoalRunStatus.COMPLETED,
            GoalRunStatus.STOPPED,
            GoalRunStatus.FAILED,
            GoalRunStatus.CANCELED,
        }:
            raise GoalResearchRunConflict(
                f"A {response.run_status.value} run cannot be canceled."
            )
        response.cancel_requested = True
        if response.run_status == GoalRunStatus.PLANNED:
            response.run_status = GoalRunStatus.CANCELED
            response.status = GoalStatus.CANCELED
            response.stop_reason = GoalStopReason.CANCELED
            response.current_stage = "finalize"
        else:
            response.current_stage = "cancel_requested"
        self._write(run_id, request, response)
        return response

    def artifact_path(self, run_id: str, artifact_id: str) -> Path:
        response = self.get(run_id)
        artifact = next(
            (item for item in response.artifacts if item.artifact_id == artifact_id and item.validation_passed and item.artifact_type in {"docx", "pptx"}),
            None,
        )
        if artifact is None:
            raise GoalResearchRunNotFound(artifact_id)
        workspace = self.settings.agent_workspace_dir.resolve()
        allowed = (workspace / "results" / "goal-research" / run_id / "deliverables").resolve()
        candidate = (workspace / artifact.path).resolve()
        try:
            candidate.relative_to(allowed)
        except ValueError as exc:
            raise GoalResearchRunNotFound(artifact_id) from exc
        if not candidate.is_file():
            raise GoalResearchRunNotFound(artifact_id)
        return candidate

    def _execute(self, run_id: str, request: GoalResearchRequest) -> None:
        try:
            result = asyncio.run(
                self.controller.run(
                    run_id,
                    request,
                    is_canceled=lambda: self._cancel_requested(run_id),
                    on_progress=lambda value: self._write(run_id, request, value),
                )
            )
            if result.run_status in {GoalRunStatus.COMPLETED, GoalRunStatus.STOPPED} and request.deliverables:
                frozen = result.model_copy(deep=True)
                result.deliverable_status = {kind: "pending" for kind in dict.fromkeys(request.deliverables)}
                result.current_stage = "deliverables"
                self._write(run_id, request, result)
                started = time.perf_counter()
                for kind in result.deliverable_status:
                    result.deliverable_status[kind] = "running"
                    self._write(run_id, request, result)
                    try:
                        result.artifacts.append(self.deliverables.create(
                            frozen.model_copy(deep=True), kind, request.include_generated_charts
                        ))
                        result.deliverable_status[kind] = "completed"
                    except Exception as exc:
                        result.deliverable_status[kind] = "failed"
                        result.deliverable_errors[kind] = str(exc)[:500]
                    self._write(run_id, request, result)
                result.timing["deliverable_generation_seconds"] = round(time.perf_counter() - started, 6)
                result.telemetry.update({
                    "artifact_generation_seconds": result.timing["deliverable_generation_seconds"],
                    "docx_success": result.deliverable_status.get("docx") == "completed",
                    "pptx_success": result.deliverable_status.get("pptx") == "completed",
                })
                result.current_stage = "finalize"
        except Exception as exc:
            _, result = self._read(run_id)
            result.run_status = GoalRunStatus.FAILED
            result.status = GoalStatus.FAILED
            result.stop_reason = GoalStopReason.ERROR
            result.current_stage = "finalize"
            result.error = str(exc)
        self._write(run_id, request, result)

    def _cancel_requested(self, run_id: str) -> bool:
        try:
            return self.get(run_id).cancel_requested
        except GoalResearchRunNotFound:
            return True

    def _path(self, run_id: str):
        if not run_id.startswith("GR-") or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
            for character in run_id
        ):
            raise GoalResearchRunNotFound(run_id)
        return self.settings.goal_research_runs_dir / f"{run_id}.json"

    def _read(self, run_id: str) -> tuple[GoalResearchRequest, GoalResearchResponse]:
        path = self._path(run_id)
        with self._lock:
            if not path.is_file():
                raise GoalResearchRunNotFound(run_id)
            data = json.loads(path.read_text(encoding="utf-8"))
        return (
            GoalResearchRequest.model_validate(data["request"]),
            GoalResearchResponse.model_validate(data["response"]),
        )

    def _write(
        self,
        run_id: str,
        request: GoalResearchRequest,
        response: GoalResearchResponse,
    ) -> None:
        path = self._path(run_id)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file():
                current = json.loads(path.read_text(encoding="utf-8"))
                if current.get("response", {}).get("cancel_requested"):
                    response.cancel_requested = True
            payload = {
                "request": request.model_dump(mode="json"),
                "response": response.model_dump(mode="json"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(path)

    @staticmethod
    def _new_run_id() -> str:
        now = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"GR-{now}-{uuid4().hex[:6].upper()}"
