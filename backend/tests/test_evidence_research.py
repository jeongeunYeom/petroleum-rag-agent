from __future__ import annotations

from app.core.config import Settings
from app.services.evidence_research import EvidenceResearchService
from app.tools.external_search_tools import ExternalSearchTools


class FakeDDGS:
    def text(self, query, **kwargs):
        assert query == "well control latest guidance"
        return [
            {
                "title": "Example guidance",
                "href": "https://example.org/well-control",
                "body": "Updated well control guidance snippet.",
            },
            {
                "title": "Duplicate",
                "href": "https://example.org/well-control",
                "body": "Duplicate result.",
            },
        ]


def test_external_search_normalizes_and_dedupes(monkeypatch):
    monkeypatch.setattr(
        "app.tools.external_search_tools.DDGS",
        lambda: FakeDDGS(),
    )
    result = ExternalSearchTools().search_external_web(
        "well control latest guidance",
        max_results=5,
    )

    assert result["source_count"] == 1
    assert result["sources"][0]["source_id"] == "WEB1"
    assert result["sources"][0]["domain"] == "example.org"


class FakeKnowledgeTools:
    def search_knowledge_base(self, query, top_k=5):
        return {
            "query": query,
            "sources": [
                {
                    "document": "Drilling Engineering.pdf",
                    "page": 75,
                    "score": 0.91,
                    "excerpt": "Kick is an influx of formation fluid into the wellbore.",
                }
            ],
            "figures": [],
            "source_count": 1,
            "figure_count": 0,
        }


class FakeExternalTools:
    def search_external_web(self, query, max_results=5):
        return {
            "query": query,
            "provider": "ddgs",
            "source_count": 1,
            "sources": [
                {
                    "source_id": "WEB1",
                    "source_type": "external_web",
                    "provider": "ddgs",
                    "title": "Current guidance",
                    "url": "https://example.org/current",
                    "domain": "example.org",
                    "snippet": "A current external reference.",
                    "rank": 1,
                }
            ],
        }


def test_research_keeps_internal_and_external_provenance(monkeypatch, tmp_path):
    service = EvidenceResearchService(
        Settings(data_dir=tmp_path),
        knowledge_tools=FakeKnowledgeTools(),
        external_tools=FakeExternalTools(),
    )
    monkeypatch.setattr(
        service,
        "_synthesize",
        lambda prompt, model=None: "내부 근거 [KB1], 외부 근거 [WEB1], 종합 추론.",
    )

    result = service.research("Kick과 최신 well control 정보를 비교해줘")

    assert result["evidence_counts"] == {"internal": 1, "external": 1}
    assert result["internal_sources"][0]["source_id"] == "KB1"
    assert result["web_sources"][0]["source_id"] == "WEB1"
    assert result["policy"]["web_persisted_to_knowledge_base"] is False
    assert {item["source_type"] for item in result["provenance"]} == {
        "knowledge_base",
        "external_web",
    }
