import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.research_routes import get_research_agent, router as research_router
from app.core.config import Settings
from app.models.research_schemas import ResearchRequest
from app.services.research_agent import ResearchAgent


class FakeVectorStore:
    def __init__(self, dense=None, sparse=None):
        self.dense = dense or []
        self.sparse = sparse or []
        self.write_attempted = False

    def search(self, query: str, top_k: int):
        return self.dense[:top_k]

    def keyword_search(self, query: str, top_k: int):
        return self.sparse[:top_k]

    def add_chunks(self, chunks):
        self.write_attempted = True
        raise AssertionError("research must never write to ChromaDB")


class FakeOllama:
    def __init__(self, answer: str = "종합 결과입니다. [KB1][WEB1]"):
        self.answer = answer
        self.calls = []

    async def chat(self, messages, model=None):
        self.calls.append((messages, model))
        return self.answer


def make_agent(
    tmp_path: Path,
    *,
    vector_store=None,
    ollama=None,
    web_searcher=None,
) -> ResearchAgent:
    settings = Settings(
        data_dir=tmp_path / "data",
        agent_workspace_dir=tmp_path / "workspace",
    )
    return ResearchAgent(
        settings,
        vector_store or FakeVectorStore(),
        ollama or FakeOllama(),
        web_searcher=web_searcher or (lambda query, limit: []),
    )


def test_external_search_normalizes_and_deduplicates_urls(tmp_path: Path) -> None:
    raw = [
        {
            "title": "Paper A",
            "href": "https://Example.com/paper/?utm_source=test#abstract",
            "body": "Result A",
        },
        {
            "title": "Duplicate",
            "url": "https://example.com/paper",
            "snippet": "same URL",
        },
        {
            "title": "Paper B",
            "url": "https://journal.test/b",
            "snippet": "Result B",
        },
    ]
    agent = make_agent(tmp_path, web_searcher=lambda query, limit: raw)

    results = agent.search_external_web("CO2 storage", 5)

    assert [item.evidence_id for item in results] == ["WEB1", "WEB2"]
    assert results[0].url == "https://example.com/paper"
    assert results[0].domain == "example.com"
    assert results[1].rank == 2


def test_external_search_rejects_blank_query_and_bad_limit(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)

    with pytest.raises(ValueError, match="blank"):
        agent.search_external_web("  ", 5)
    with pytest.raises(ValueError, match="between 1 and 20"):
        agent.search_external_web("CO2", 0)
    with pytest.raises(ValidationError):
        ResearchRequest(query=" ")


def test_rrf_fusion_preserves_separate_kb_web_and_figure_ids(tmp_path: Path) -> None:
    text_hit = {
        "id": "chunk-1",
        "text": "Residual trapping reduces mobile CO2.",
        "metadata": {"filename": "storage.pdf", "page": 10},
    }
    figure_hit = {
        "id": "figure-1",
        "text": "[Extracted Figure Notes]\ntitle: Saturation trend\nimage_path: fig_10.png",
        "metadata": {"filename": "storage.pdf", "page": 10, "chunk_type": "figure_note"},
    }
    store = FakeVectorStore(dense=[text_hit, figure_hit], sparse=[text_hit])
    agent = make_agent(
        tmp_path,
        vector_store=store,
        web_searcher=lambda query, limit: [
            {
                "title": "Recent study",
                "url": "https://example.org/recent",
                "snippet": "Residual trapping result",
            }
        ],
    )

    hits = agent.search_knowledge_base("residual trapping graph", 5)
    internal, figures = agent.normalize_internal_evidence(hits)
    web = agent.search_external_web(
        "recent trapping",
        2,
    )

    assert [item.evidence_id for item in internal] == ["KB1"]
    assert [item.evidence_id for item in figures] == ["FIG1"]
    assert [item.evidence_id for item in web] == ["WEB1"]
    assert {internal[0].evidence_id, web[0].evidence_id, figures[0].evidence_id} == {
        "KB1",
        "WEB1",
        "FIG1",
    }
    assert figures[0].filename == "fig_10.png"


def test_external_evidence_is_never_written_to_chroma(tmp_path: Path) -> None:
    store = FakeVectorStore()
    agent = make_agent(
        tmp_path,
        vector_store=store,
        ollama=FakeOllama("외부 근거입니다. [WEB1]"),
        web_searcher=lambda query, limit: [
            {"title": "Research", "url": "https://example.org/a", "snippet": "Recent result"}
        ],
    )
    request = ResearchRequest(query="latest CO2 research", use_internal=False)

    response = asyncio.run(agent.research(request))

    assert response.routing_mode == "external_only"
    assert response.web_sources[0].evidence_id == "WEB1"
    assert store.write_attempted is False


def test_no_evidence_refuses_without_calling_model(tmp_path: Path) -> None:
    ollama = FakeOllama()
    agent = make_agent(tmp_path, ollama=ollama)

    response = asyncio.run(
        agent.research(
            ResearchRequest(query="What is an unsupported topic?", use_external=False)
        )
    )

    assert "추측하지 않습니다" in response.answer
    assert response.inference_used is False
    assert ollama.calls == []


def test_conflicting_internal_and_web_evidence_is_flagged(tmp_path: Path) -> None:
    agent = make_agent(tmp_path)
    internal, _ = agent.normalize_internal_evidence(
        [
            {
                "id": "a",
                "text": "Residual trapping efficiency increases with brine saturation.",
                "metadata": {"filename": "book.pdf", "page": 4},
                "rrf_score": 0.1,
            }
        ]
    )
    web = agent.search_external_web(
        "trapping",
        1,
    )
    if not web:
        from app.models.research_schemas import WebEvidence

        web = [
            WebEvidence(
                evidence_id="WEB1",
                title="Study",
                url="https://example.org/study",
                domain="example.org",
                snippet="Residual trapping efficiency decreases with brine saturation.",
                rank=1,
            )
        ]

    conflicts = agent.detect_conflicts(internal, web)

    assert conflicts == [
        {
            "left": "KB1",
            "right": "WEB1",
            "reason": "opposing directional terms: increases/decreases",
        }
    ]


def test_conflict_disclosure_prevents_one_sided_conclusion() -> None:
    answer, added = ResearchAgent.ensure_conflicts_disclosed(
        "The internal source is correct. [KB1]",
        [{"left": "KB1", "right": "WEB1", "reason": "opposing terms"}],
    )

    assert "일반화할 수 없습니다" in answer
    assert "[KB1][WEB1]" in answer
    assert added == ["KB1:WEB1"]


def test_same_direction_terms_do_not_create_false_conflict(tmp_path: Path) -> None:
    from app.models.research_schemas import InternalEvidence, WebEvidence

    internal = [
        InternalEvidence(
            evidence_id="KB1",
            document="book.pdf",
            page=1,
            chunk_id="a",
            score=0.1,
            excerpt="The operation is unsafe under high pressure.",
        )
    ]
    web = [
        WebEvidence(
            evidence_id="WEB1",
            title="Study",
            url="https://example.org",
            domain="example.org",
            snippet="The operation remains unsafe under high pressure.",
            rank=1,
        )
    ]

    assert ResearchAgent.detect_conflicts(internal, web) == []


def test_invalid_model_citation_is_removed() -> None:
    answer, validation = ResearchAgent.validate_answer(
        "Supported claim. [KB1]\nInvented claim. [WEB9]",
        {"KB1"},
    )

    assert "Supported claim" in answer
    assert "Invented claim" not in answer
    assert validation["invalid_citations"] == ["WEB9"]


def test_research_api_contract(tmp_path: Path) -> None:
    hit = {
        "id": "chunk-1",
        "text": "Wellbore storage is an early-time effect.",
        "metadata": {"filename": "welltest.pdf", "page": 12},
    }
    agent = make_agent(
        tmp_path,
        vector_store=FakeVectorStore(dense=[hit]),
        ollama=FakeOllama("Wellbore storage 설명입니다. [KB1]"),
    )
    test_app = FastAPI()
    test_app.include_router(research_router, prefix="/api")
    test_app.dependency_overrides[get_research_agent] = lambda: agent
    try:
        response = TestClient(test_app).post(
            "/api/research/evidence",
            json={
                "query": "Wellbore storage가 뭐야?",
                "internal_top_k": 5,
                "external_top_k": 5,
                "use_internal": True,
                "use_external": True,
                "model": "qwen3:8b",
            },
        )
    finally:
        test_app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    for field in (
        "query",
        "answer",
        "internal_sources",
        "web_sources",
        "figures",
        "provenance",
        "model",
        "inference_used",
        "evidence_counts",
    ):
        assert field in body
    assert body["routing_mode"] == "internal_only"
    assert body["evidence_counts"] == {"internal": 1, "external": 0}
    assert body["timing"]["elapsed_seconds"] >= 0
