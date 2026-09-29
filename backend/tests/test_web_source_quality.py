from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.services.web_research import WebCandidate, WebResearchService
from app.services.web_source_quality import QueryIntent, WebSourceQualityEvaluator


EVALUATOR = WebSourceQualityEvaluator()
TODAY = date(2026, 9, 29)


@pytest.mark.parametrize(
    "query,expected",
    [
        ("latest CO2 storage monitoring", QueryIntent.LATEST),
        ("recent CCS developments", QueryIntent.LATEST),
        ("history of well testing", QueryIntent.HISTORICAL),
        ("pressure derivative 설명", QueryIntent.GENERAL_TECHNICAL),
        ("내부 교재와 최근 웹 연구를 비교", QueryIntent.COMPARISON),
    ],
)
def test_query_intent(query: str, expected: QueryIntent) -> None:
    assert EVALUATOR.classify_intent(query) is expected


@pytest.mark.parametrize(
    "query,year,since",
    [("2023 SPE 논문", 2023, False), ("since 2020 CCS", 2020, True), ("2020 이후 연구", 2020, True)],
)
def test_year_constraint(query: str, year: int, since: bool) -> None:
    constraint = EVALUATOR.parse_year_constraint(query)
    assert constraint and (constraint.year, constraint.since) == (year, since)


@pytest.mark.parametrize(
    "url,title,metadata,expected",
    [
        ("https://netl.doe.gov/report", "Technical report", {}, "government"),
        ("https://research.example.edu/paper", "Research", {}, "academic"),
        ("https://example.ac.uk/paper", "Research", {}, "academic"),
        ("https://example.com/a", "Paper", {"citation_journal_title": "Journal"}, "journal"),
        ("https://onepetro.org/paper", "Conference paper", {}, "professional_society"),
        ("https://unknown.example/a", "Page", {}, "unknown"),
        ("https://slb.com/resource", "Technical report", {}, "company_official"),
        ("https://reuters.com/a", "News", {}, "news"),
        ("https://example.com/blog", "Engineering blog summary", {}, "technical_blog"),
        ("https://researchgate.net/a", "Paper mirror", {}, "aggregator"),
    ],
)
def test_source_categories(
    url: str, title: str, metadata: dict[str, str], expected: str
) -> None:
    assert EVALUATOR.evaluate_source(url=url, title=title, metadata=metadata).category == expected


def test_html_metadata_sources_and_doi() -> None:
    html = """
    <meta property="article:published_time" content="2025-08-12">
    <meta name="citation_publication_date" content="2024-01-01">
    <meta itemprop="dateModified" content="2026-02-03">
    <meta name="citation_doi" content="10.1234/ABC.9">
    """
    value = EVALUATOR.extract_html_metadata(html, today=TODAY)
    assert value.published_date == "2025-08-12"
    assert value.published_date_source == "article_meta"
    assert value.modified_date == "2026-02-03"
    assert value.modified_date_source == "article_meta"
    assert value.doi == "10.1234/abc.9"


def test_citation_and_json_ld_dates() -> None:
    citation = EVALUATOR.extract_html_metadata(
        '<meta name="citation_publication_date" content="2024-11">', today=TODAY
    )
    json_ld = EVALUATOR.extract_html_metadata(
        '<script type="application/ld+json">'
        '{"@type":"Article","datePublished":"2023-05-02","dateModified":"2024-01-01"}'
        "</script>",
        today=TODAY,
    )
    assert (citation.published_date, citation.published_date_source) == ("2024-11-01", "citation_meta")
    assert (json_ld.published_date, json_ld.published_date_source) == ("2023-05-02", "json_ld")
    assert json_ld.modified_date == "2024-01-01"


def test_malformed_and_far_future_dates_are_ignored() -> None:
    assert EVALUATOR.normalize_date("not-a-date", today=TODAY) is None
    assert EVALUATOR.normalize_date("2099-01-01", today=TODAY) is None
    assert EVALUATOR.extract_text_metadata("SEPTEMBER 2025 PERSPECTIVE", today=TODAY).published_date == "2025-09-01"


def test_http_last_modified_is_not_publication_date(tmp_path: Path) -> None:
    service = WebResearchService(
        Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html", "last-modified": "Wed, 01 Jan 2025 00:00:00 GMT"},
                text="<main><p>Pressure derivative supports well test interpretation with diagnostic trends.</p></main>",
            )
        ),
        resolver=lambda host, port: ["93.184.216.34"],
    )
    candidate = WebCandidate("Test", "https://example.com/a", "example.com", "pressure derivative", 1)
    result = service.research("pressure derivative", [candidate], 1)
    assert result.evidence[0].published_date is None
    assert result.evidence[0].http_last_modified is not None


def test_recency_policy_and_explicit_year() -> None:
    latest = EVALUATOR.recency_score(QueryIntent.LATEST, "2026-01-01", today=TODAY)
    old = EVALUATOR.recency_score(QueryIntent.LATEST, "2010-01-01", today=TODAY)
    unknown = EVALUATOR.recency_score(QueryIntent.LATEST, None, today=TODAY)
    historical = EVALUATOR.recency_score(QueryIntent.HISTORICAL, "2026-01-01", today=TODAY)
    constraint = EVALUATOR.parse_year_constraint("since 2020")
    assert latest > unknown > old
    assert historical == 0
    assert EVALUATOR.recency_score(QueryIntent.GENERAL_TECHNICAL, "2021-01-01", constraint=constraint, today=TODAY) == 1
    assert EVALUATOR.recency_score(QueryIntent.GENERAL_TECHNICAL, "2019-01-01", constraint=constraint, today=TODAY) == 0


def _rank(url: str, title: str, relevance: float, published: str | None, search_rank: int = 1):
    source = EVALUATOR.evaluate_source(url=url, title=title, text=title)
    recency = EVALUATOR.recency_score(QueryIntent.LATEST, published, today=TODAY)
    return EVALUATOR.rank(
        intent=QueryIntent.LATEST,
        relevance_score=relevance,
        source=source,
        recency_score=recency,
        search_rank=search_rank,
        published_date=published,
    ).final_score


def test_ranking_is_relevance_first_and_quality_breaks_close_ties() -> None:
    relevant_academic = _rank("https://x.edu/a", "Research paper", 0.9, "2020-01-01")
    irrelevant_government = _rank("https://energy.gov/a", "Technical report", 0.1, "2026-01-01")
    government = _rank("https://energy.gov/a", "Technical report", 0.70, "2025-01-01")
    blog = _rank("https://x.example/blog", "Blog summary", 0.70, "2025-01-01")
    assert relevant_academic > irrelevant_government
    assert government > blog


def test_recent_primary_beats_old_aggregator_and_discovery_is_small() -> None:
    primary = _rank("https://onepetro.org/a", "Paper 10.1234/test", 0.70, "2026-01-01", 8)
    aggregator = _rank("https://researchgate.net/a", "Paper mirror", 0.70, "2010-01-01", 1)
    rank_one = _rank("https://x.example/a", "Page", 0.7, None, 1)
    rank_ten = _rank("https://x.example/a", "Page", 0.7, None, 10)
    assert primary > aggregator
    assert 0 < rank_one - rank_ten < 0.02


@pytest.mark.parametrize(
    "url,title,text,expected",
    [
        ("https://nature.com/a", "Article", "doi 10.1234/test", True),
        ("https://energy.gov/a", "Technical report", "official assessment", True),
        ("https://x.example/blog", "Blog summary", "blog", False),
        ("https://reuters.com/a", "News", "rewrite", False),
        ("https://x.example/a", "Page", "misc", None),
    ],
)
def test_primary_source_detection(url: str, title: str, text: str, expected: bool | None) -> None:
    assert EVALUATOR.evaluate_source(url=url, title=title, text=text).primary_source is expected


@pytest.mark.parametrize("same_doi,with_doi,expected_urls", [(True, True, 1), (False, True, 2), (False, False, 2)])
def test_publication_dedupe(
    tmp_path: Path, same_doi: bool, with_doi: bool, expected_urls: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        suffix = "shared" if same_doi else request.url.path.strip("/")
        doi = f'<meta name="citation_doi" content="10.1234/{suffix}">' if with_doi else ""
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=f"{doi}<main><p>CO2 storage monitoring uses pressure data and seismic monitoring for reservoir assessment.</p></main>",
        )

    service = WebResearchService(
        Settings(
            data_dir=tmp_path / "data",
            agent_workspace_dir=tmp_path / "workspace",
            web_passage_min_relevance=0.01,
        ),
        transport=httpx.MockTransport(handler),
        resolver=lambda host, port: ["93.184.216.34"],
    )
    candidates = [
        WebCandidate("Paper A", "https://a.example/a", "a.example", "CO2 storage monitoring", 1),
        WebCandidate("Paper B", "https://b.example/b", "b.example", "CO2 storage monitoring", 2),
    ]
    result = service.research("CO2 storage monitoring", candidates, 4)
    assert len({item.url for item in result.evidence}) == expected_urls
    assert result.stats["web_duplicate_publications_removed"] == (1 if same_doi and with_doi else 0)


def test_paywalled_relevant_snippet_can_fill_remaining_results(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "onepetro.org":
            return httpx.Response(403)
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            text="Pressure derivative evidence identifies flow regimes in well testing.",
        )

    service = WebResearchService(
        Settings(
            data_dir=tmp_path / "data",
            agent_workspace_dir=tmp_path / "workspace",
            web_passage_min_relevance=0.01,
        ),
        transport=httpx.MockTransport(handler),
        resolver=lambda host, port: ["93.184.216.34"],
    )
    result = service.research(
        "pressure derivative well testing",
        [
            WebCandidate("Accessible", "https://open.example/a", "open.example", "pressure derivative", 1),
            WebCandidate("SPE paper", "https://onepetro.org/a", "onepetro.org", "pressure derivative well testing paper", 2),
        ],
        3,
    )
    assert {item.evidence_kind for item in result.evidence} == {
        "fetched_page",
        "search_snippet_fallback",
    }
    fallback = next(item for item in result.evidence if not item.fetched)
    assert fallback.source_category == "professional_society"
