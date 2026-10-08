from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.research_routes import cached_research_agent
from app.api.routes import get_ollama
from app.core.config import Settings, get_settings
from app.models.goal_research_schemas import GoalResearchRequest, GoalResearchResponse
from app.services.goal_research_agent import GoalResearchAgent
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_message_parser import GoalMessageRequest, parse_goal_message
from app.services.goal_research_service import (
    GoalResearchRunConflict,
    GoalResearchRunNotFound,
    GoalResearchService,
)


router = APIRouter(prefix="/research/goal-runs", tags=["goal-research"])


@lru_cache(maxsize=1)
def cached_goal_research_service() -> GoalResearchService:
    settings = get_settings()
    research, ollama = cached_research_agent(), get_ollama()
    return GoalResearchService(settings, GoalResearchAgent(research, ollama),
                               GoalExecutionAgent(research, ollama))


def get_goal_research_service(
    settings: Settings = Depends(get_settings),
) -> GoalResearchService:
    _ = settings
    return cached_goal_research_service()


@router.post("", response_model=GoalResearchResponse, status_code=201)
def start_goal_research(
    request: GoalResearchRequest,
    service: GoalResearchService = Depends(get_goal_research_service),
) -> GoalResearchResponse:
    return service.start(request)


@router.post("/from-message", response_model=GoalResearchResponse, status_code=201)
def start_goal_research_from_message(
    request: GoalMessageRequest,
    service: GoalResearchService = Depends(get_goal_research_service),
) -> GoalResearchResponse:
    try:
        return service.start(parse_goal_message(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{run_id}", response_model=GoalResearchResponse)
def get_goal_research(
    run_id: str,
    service: GoalResearchService = Depends(get_goal_research_service),
) -> GoalResearchResponse:
    try:
        return service.get(run_id)
    except GoalResearchRunNotFound as exc:
        raise HTTPException(status_code=404, detail="Goal research run not found") from exc


@router.post("/{run_id}/cancel", response_model=GoalResearchResponse)
def cancel_goal_research(
    run_id: str,
    service: GoalResearchService = Depends(get_goal_research_service),
) -> GoalResearchResponse:
    try:
        return service.cancel(run_id)
    except GoalResearchRunNotFound as exc:
        raise HTTPException(status_code=404, detail="Goal research run not found") from exc
    except GoalResearchRunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{run_id}/artifacts/{artifact_id}")
def download_goal_artifact(
    run_id: str,
    artifact_id: str,
    service: GoalResearchService = Depends(get_goal_research_service),
) -> FileResponse:
    try:
        path = service.artifact_path(run_id, artifact_id)
    except GoalResearchRunNotFound as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    return FileResponse(path, filename=path.name)
