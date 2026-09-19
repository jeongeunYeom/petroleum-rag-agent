from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.evidence_research import EvidenceResearchService


router = APIRouter(tags=["research"])


class EvidenceResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    internal_top_k: int = Field(default=5, ge=1, le=20)
    external_top_k: int = Field(default=5, ge=1, le=10)
    use_internal: bool = True
    use_external: bool = True
    model: str | None = Field(default=None, max_length=200)


@lru_cache(maxsize=1)
def get_research_service() -> EvidenceResearchService:
    return EvidenceResearchService(get_settings())


@router.post("/research/evidence")
def research_with_evidence(request: EvidenceResearchRequest):
    try:
        return get_research_service().research(
            request.query,
            internal_top_k=request.internal_top_k,
            external_top_k=request.external_top_k,
            use_internal=request.use_internal,
            use_external=request.use_external,
            model=request.model,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/research/capabilities")
def research_capabilities():
    settings = get_settings()
    return {
        "agent": "evidence-research-v1",
        "knowledge_base": "BGE-M3 + BM25 + optional reranker over ChromaDB",
        "external_search": "DDGS metasearch",
        "synthesis_model": settings.text_model,
        "provenance_labels": ["KB#", "WEB#"],
        "web_content_persisted_to_knowledge_base": False,
    }
