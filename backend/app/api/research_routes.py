from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import Settings, get_settings
from app.core.error_mapping import ExternalServiceError
from app.core.errors import to_http_exception
from app.models.research_schemas import ResearchRequest, ResearchResponse
from app.services.research_agent import ResearchAgent


router = APIRouter(prefix="/research", tags=["research"])


@lru_cache(maxsize=1)
def cached_research_agent() -> ResearchAgent:
    # Delay heavy Chroma/embedding imports until the production dependency is used.
    from app.api.routes import get_ollama, get_vector_store

    return ResearchAgent(get_settings(), get_vector_store(), get_ollama())


def get_research_agent(
    settings: Settings = Depends(get_settings),
) -> ResearchAgent:
    # The dependency argument keeps Settings overrideable in API tests.
    _ = settings
    return cached_research_agent()


@router.post("/evidence", response_model=ResearchResponse)
async def research_with_evidence(
    request: ResearchRequest,
    agent: ResearchAgent = Depends(get_research_agent),
) -> ResearchResponse:
    try:
        return await agent.research(request)
    except ExternalServiceError as exc:
        raise to_http_exception(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
