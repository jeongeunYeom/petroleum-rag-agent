from __future__ import annotations

import asyncio
import ipaddress
import math
import re
import socket
import time
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import Settings
from app.models.research_schemas import WebEvidence
from app.services.web_source_quality import (
    QueryIntent,
    SourceQuality,
    WebRankScore,
    WebSourceQualityEvaluator,
    YearConstraint,
)


SUPPORTED_CONTENT_TYPES = {"text/html", "text/plain", "application/pdf"}
BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"}
SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "form"}
NOISE_RE = re.compile(
    r"(?:^|[-_\s])(?:ad|ads|advert|banner|cookie|footer|header|menu|nav|"
    r"newsletter|popup|promo|sidebar|social)(?:$|[-_\s])",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{1,}|[가-힣]{2,}")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "is", "of", "on", "or", "the", "to", "what", "with",
    "대해", "설명", "자료", "최신", "현재",
}


@dataclass(frozen=True)
class WebCandidate:
    title: str
    url: str
    domain: str
    search_snippet: str
    search_rank: int


@dataclass(frozen=True)
class Passage:
    index: int
    text: str
    heading: str | None = None
    score: float = 0.0


@dataclass
class FetchResult:
    url: str
    status: str
    content_type: str | None = None
    title: str | None = None
    blocks: list[tuple[str | None, str]] = field(default_factory=list)
    failure_reason: str | None = None
    published_date: str | None = None
    modified_date: str | None = None
    http_last_modified: str | None = None
    published_date_source: str | None = None
    modified_date_source: str | None = None
    doi: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status == "fetched" and bool(self.blocks)


@dataclass
class WebResearchResult:
    evidence: list[WebEvidence] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "WebResearchResult":
        return cls(
            stats={
                "web_candidates_discovered": 0,
                "web_fetch_attempted": 0,
                "web_fetch_succeeded": 0,
                "web_fetch_failed": 0,
                "web_fetch_cancelled": 0,
                "web_fetch_concurrency": 0,
                "web_research_timeout_seconds": 0.0,
                "web_pdf_fetched": 0,
                "web_html_fetched": 0,
                "web_snippet_fallback_count": 0,
                "web_passages_selected": 0,
                "web_passages_rejected_low_relevance": 0,
                "web_sources_with_usable_passage": 0,
                "web_evidence_count": 0,
                "web_query_intent": "general_technical",
                "web_sources_scored": 0,
                "web_sources_with_date": 0,
                "web_primary_sources": 0,
                "web_source_categories": {},
                "web_doi_count": 0,
                "web_duplicate_publications_removed": 0,
                "web_search_seconds": 0.0,
                "web_fetch_seconds": 0.0,
                "web_passage_ranking_seconds": 0.0,
                "sources": [],
            }
        )


class UnsafeUrlError(ValueError):
    pass


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.published_date: str | None = None
        self.modified_date: str | None = None
        self._skip_depth = 0
        self._preferred_depth = 0
        self._in_title = False
        self._block_tag: str | None = None
        self._block_parts: list[str] = []
        self._block_preferred = False
        self._heading: str | None = None
        self._blocks: list[tuple[bool, str | None, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): value or "" for key, value in attrs}
        if self._skip_depth:
            self._skip_depth += 1
            return
        marker = " ".join(
            (values.get("id", ""), values.get("class", ""), values.get("role", ""))
        )
        if tag in SKIP_TAGS or NOISE_RE.search(marker):
            self._skip_depth = 1
            return
        if tag in {"main", "article"}:
            self._preferred_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            self._read_meta(values)
        if tag in BLOCK_TAGS and self._block_tag is None:
            self._block_tag = tag
            self._block_parts = []
            self._block_preferred = self._preferred_depth > 0

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if self._block_tag == tag:
            text = _clean_text(" ".join(self._block_parts))
            if text:
                if tag.startswith("h"):
                    self._heading = text
                self._blocks.append((self._block_preferred, self._heading, text))
            self._block_tag = None
            self._block_parts = []
        if tag == "title":
            self._in_title = False
        if tag in {"main", "article"} and self._preferred_depth:
            self._preferred_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title = _clean_text(f"{self.title} {data}")
        if self._block_tag is not None:
            self._block_parts.append(data)

    def blocks(self) -> list[tuple[str | None, str]]:
        preferred = [(heading, text) for flag, heading, text in self._blocks if flag]
        selected = preferred if sum(len(text) for _, text in preferred) >= 100 else [
            (heading, text) for _, heading, text in self._blocks
        ]
        result: list[tuple[str | None, str]] = []
        seen: set[str] = set()
        for heading, text in selected:
            key = text.casefold()
            if len(text) < 20 or key in seen:
                continue
            seen.add(key)
            result.append((heading, text))
        return result

    def _read_meta(self, attrs: dict[str, str]) -> None:
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        value = attrs.get("content", "").strip()
        if not value:
            return
        if key in {"article:published_time", "datepublished", "publication_date"}:
            self.published_date = value
        elif key in {"article:modified_time", "datemodified", "last-modified"}:
            self.modified_date = value


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


class WebResearchService:
    """Bounded, request-scoped hydration of DDGS URL candidates."""

    def __init__(
        self,
        settings: Settings,
        *,
        embedder: Callable[[list[str]], Any] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Callable[[str, int], list[str]] | None = None,
    ) -> None:
        self.settings = settings
        self.embedder = embedder
        self.transport = transport
        self.resolver = resolver or self._resolve_host
        self.source_evaluator = WebSourceQualityEvaluator()

    async def research_async(
        self,
        query: str,
        candidates: list[WebCandidate],
        max_results: int,
    ) -> WebResearchResult:
        result = WebResearchResult.empty()
        stats = result.stats
        intent = self.source_evaluator.classify_intent(query)
        year_constraint = self.source_evaluator.parse_year_constraint(query)
        stats["web_query_intent"] = intent.value
        stats["web_candidates_discovered"] = len(candidates)
        concurrency = max(1, self.settings.web_fetch_concurrency)
        budget = max(0.01, self.settings.web_research_timeout_seconds)
        stats["web_fetch_concurrency"] = concurrency
        stats["web_research_timeout_seconds"] = budget
        if not candidates:
            return result

        unique_candidates = list({item.url: item for item in candidates}.values())
        selected_candidates = unique_candidates[: max(0, self.settings.web_max_fetch_results)]
        fetches: dict[str, FetchResult] = {}
        fetch_started = time.perf_counter()
        if self.settings.web_fetch_enabled:
            semaphore = asyncio.Semaphore(concurrency)

            async def fetch_one(candidate: WebCandidate) -> FetchResult:
                async with semaphore:
                    stats["web_fetch_attempted"] += 1
                    return await self.fetch(client, candidate.url)

            async with httpx.AsyncClient(
                timeout=self.settings.web_fetch_timeout_seconds,
                follow_redirects=False,
                transport=self.transport,
                headers={"User-Agent": "PetroleumResearchAgent/1.0 (+local research)"},
            ) as client:
                tasks = {
                    asyncio.create_task(fetch_one(candidate)): candidate
                    for candidate in selected_candidates
                }
                done, pending = await asyncio.wait(tasks, timeout=budget)
                for task in done:
                    candidate = tasks[task]
                    try:
                        fetches[candidate.url] = task.result()
                    except Exception as exc:
                        fetches[candidate.url] = FetchResult(
                            candidate.url,
                            "failed",
                            failure_reason=type(exc).__name__,
                        )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                stats["web_fetch_cancelled"] = len(pending)
                for task in pending:
                    candidate = tasks[task]
                    fetches[candidate.url] = FetchResult(
                        candidate.url,
                        "cancelled",
                        failure_reason="web_research_timeout",
                    )
        else:
            fetches = {
                item.url: FetchResult(
                    item.url,
                    "disabled",
                    failure_reason="fetch_disabled",
                )
                for item in selected_candidates
            }
        stats["web_fetch_seconds"] = round(time.perf_counter() - fetch_started, 6)

        for candidate in selected_candidates:
            fetched = fetches[candidate.url]
            if fetched.succeeded:
                stats["web_fetch_succeeded"] += 1
                if fetched.content_type == "application/pdf":
                    stats["web_pdf_fetched"] += 1
                elif fetched.content_type == "text/html":
                    stats["web_html_fetched"] += 1
            elif fetched.status not in {"cancelled", "disabled"}:
                stats["web_fetch_failed"] += 1
            stats["sources"].append(
                {
                    "url": candidate.url,
                    "domain": candidate.domain,
                    "fetch_status": fetched.status,
                    "content_type": fetched.content_type,
                    "best_passage_score": None,
                    "selected_passage_count": 0,
                    "failure_reason": fetched.failure_reason,
                }
            )

        successes = [
            (candidate, fetches[candidate.url])
            for candidate in selected_candidates
            if fetches[candidate.url].succeeded
        ]
        ranking_started = time.perf_counter()
        remaining = budget - (time.perf_counter() - fetch_started)
        if successes and remaining > 0:
            ranking_task = asyncio.to_thread(
                self._rank_fetches, query, successes, True, intent, year_constraint
            )
            try:
                ranked, rejected, best_scores, source_debug = await asyncio.wait_for(
                    ranking_task,
                    timeout=remaining,
                )
            except TimeoutError:
                ranked, rejected, best_scores, source_debug = self._rank_fetches(
                    query, successes, False, intent, year_constraint
                )
        else:
            ranked, rejected, best_scores, source_debug = self._rank_fetches(
                query, successes, False, intent, year_constraint
            )
        stats["web_passages_rejected_low_relevance"] = rejected
        for source in stats["sources"]:
            source["best_passage_score"] = best_scores.get(source["url"])
            source.update(source_debug.get(source["url"], {}))
        stats["web_passage_ranking_seconds"] = round(
            time.perf_counter() - ranking_started, 6
        )

        if ranked:
            domain_counts: dict[str, int] = {}
            publication_urls: dict[str, str] = {}
            selected: list[tuple[float, WebCandidate, FetchResult, Passage, SourceQuality, WebRankScore]] = []
            for item in ranked:
                domain = item[1].domain
                if domain_counts.get(domain, 0) >= 2:
                    continue
                doi = item[4].doi
                if doi and doi in publication_urls and publication_urls[doi] != item[1].url:
                    stats["web_duplicate_publications_removed"] += 1
                    continue
                selected.append(item)
                domain_counts[domain] = domain_counts.get(domain, 0) + 1
                if doi:
                    publication_urls[doi] = item[1].url
                if len(selected) >= max_results:
                    break
            for _, candidate, fetched, passage, source_quality, rank_score in selected:
                kind = "fetched_pdf" if fetched.content_type == "application/pdf" else "fetched_page"
                result.evidence.append(
                    WebEvidence(
                        evidence_id=f"WEB{len(result.evidence) + 1}",
                        title=fetched.title or candidate.title,
                        url=fetched.url,
                        domain=urlsplit(fetched.url).hostname or candidate.domain,
                        snippet=passage.text,
                        rank=candidate.search_rank,
                        fetched=True,
                        evidence_kind=kind,
                        content_type=fetched.content_type,
                        passage=passage.text,
                        passage_index=passage.index,
                        heading=passage.heading,
                        fetch_status="fetched",
                        search_snippet=candidate.search_snippet or None,
                        published_date=fetched.published_date,
                        modified_date=fetched.modified_date,
                        http_last_modified=fetched.http_last_modified,
                        source_category=source_quality.category,
                        authority_score=source_quality.authority_score,
                        primary_source=source_quality.primary_source,
                        published_date_source=fetched.published_date_source,
                        modified_date_source=fetched.modified_date_source,
                        doi=source_quality.doi,
                        relevance_score=rank_score.relevance_score,
                        source_quality_score=rank_score.source_quality_score,
                        recency_score=rank_score.recency_score,
                        primary_source_score=rank_score.primary_source_score,
                        final_rank_score=rank_score.final_score,
                        ranking_reason=list(rank_score.ranking_reason),
                    )
                )
                for source in stats["sources"]:
                    if source["url"] == candidate.url:
                        source["selected_passage_count"] += 1
                        break
        if len(result.evidence) < max_results:
            fallback_domains: dict[str, int] = {}
            for item in result.evidence:
                fallback_domains[item.domain] = fallback_domains.get(item.domain, 0) + 1
            publication_urls = {
                item.doi: item.url for item in result.evidence if item.doi
            }
            fallbacks: list[tuple[float, WebCandidate, FetchResult, SourceQuality, WebRankScore, Any]] = []
            for candidate in unique_candidates:
                fetched = fetches.get(candidate.url)
                if (
                    fetched is None
                    or fetched.succeeded
                    or not self.snippet_relevant(query, candidate.search_snippet)
                ):
                    continue
                if result.evidence and fetched.failure_reason not in {
                    "http_401",
                    "http_403",
                }:
                    continue
                metadata = self.source_evaluator.extract_text_metadata(
                    f"{candidate.title}\n{candidate.search_snippet}"
                )
                source_quality = self.source_evaluator.evaluate_source(
                    url=candidate.url,
                    title=candidate.title,
                    text=candidate.search_snippet,
                    doi=metadata.doi,
                )
                query_tokens = self._tokens(query)
                relevance = len(query_tokens & self._tokens(candidate.search_snippet)) / max(1, len(query_tokens))
                recency = self.source_evaluator.recency_score(
                    intent, metadata.published_date, constraint=year_constraint
                )
                rank_score = self.source_evaluator.rank(
                    intent=intent,
                    relevance_score=relevance,
                    source=source_quality,
                    recency_score=recency,
                    search_rank=candidate.search_rank,
                    published_date=metadata.published_date,
                )
                fallbacks.append((rank_score.final_score, candidate, fetched, source_quality, rank_score, metadata))
            for _, candidate, fetched, source_quality, rank_score, metadata in sorted(
                fallbacks, key=lambda item: item[0], reverse=True
            ):
                if fallback_domains.get(candidate.domain, 0) >= 2:
                    continue
                doi = source_quality.doi
                if doi and doi in publication_urls and publication_urls[doi] != candidate.url:
                    stats["web_duplicate_publications_removed"] += 1
                    continue
                result.evidence.append(
                    WebEvidence(
                        evidence_id=f"WEB{len(result.evidence) + 1}",
                        title=candidate.title,
                        url=candidate.url,
                        domain=candidate.domain,
                        snippet=candidate.search_snippet,
                        rank=candidate.search_rank,
                        fetched=False,
                        evidence_kind="search_snippet_fallback",
                        fetch_status=fetched.status if fetched else "not_attempted",
                        search_snippet=candidate.search_snippet,
                        published_date=metadata.published_date,
                        published_date_source=metadata.published_date_source,
                        source_category=source_quality.category,
                        authority_score=source_quality.authority_score,
                        primary_source=source_quality.primary_source,
                        doi=source_quality.doi,
                        relevance_score=rank_score.relevance_score,
                        source_quality_score=rank_score.source_quality_score,
                        recency_score=rank_score.recency_score,
                        primary_source_score=rank_score.primary_source_score,
                        final_rank_score=rank_score.final_score,
                        ranking_reason=list(rank_score.ranking_reason),
                    )
                )
                debug = self._source_debug(
                    candidate, fetched, source_quality, rank_score
                )
                existing = next(
                    (
                        source
                        for source in stats["sources"]
                        if source["url"] == candidate.url
                    ),
                    None,
                )
                if existing is None:
                    stats["sources"].append(debug)
                else:
                    existing.update(debug)
                fallback_domains[candidate.domain] = (
                    fallback_domains.get(candidate.domain, 0) + 1
                )
                if doi:
                    publication_urls[doi] = candidate.url
                if len(result.evidence) >= max_results:
                    break
        stats["web_passages_selected"] = sum(item.fetched for item in result.evidence)
        stats["web_sources_with_usable_passage"] = len(
            {item.url for item in result.evidence if item.fetched}
        )
        stats["web_snippet_fallback_count"] = sum(
            item.evidence_kind == "search_snippet_fallback"
            for item in result.evidence
        )
        stats["web_evidence_count"] = len(result.evidence)
        stats["web_sources_scored"] = len(
            {source["url"] for source in stats["sources"] if source.get("final_score") is not None}
        )
        stats["web_sources_with_date"] = len({item.url for item in result.evidence if item.published_date})
        stats["web_primary_sources"] = len({item.url for item in result.evidence if item.primary_source is True})
        categories: dict[str, int] = {}
        unique_sources = {item.url: item for item in result.evidence}.values()
        for item in unique_sources:
            category = item.source_category or "unknown"
            categories[category] = categories.get(category, 0) + 1
        stats["web_source_categories"] = categories
        stats["web_doi_count"] = len({item.doi for item in result.evidence if item.doi})
        return result

    def research(
        self,
        query: str,
        candidates: list[WebCandidate],
        max_results: int,
    ) -> WebResearchResult:
        """Compatibility wrapper for existing non-async callers and tests."""
        return asyncio.run(self.research_async(query, candidates, max_results))

    async def fetch(self, client: httpx.AsyncClient, url: str) -> FetchResult:
        current = url
        try:
            for redirect_count in range(self.settings.web_fetch_max_redirects + 1):
                await asyncio.to_thread(self.validate_url, current)
                async with client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            return FetchResult(current, "failed", failure_reason="redirect_without_location")
                        if redirect_count >= self.settings.web_fetch_max_redirects:
                            return FetchResult(current, "failed", failure_reason="redirect_limit")
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        return FetchResult(
                            current,
                            "failed",
                            failure_reason=f"http_{response.status_code}",
                        )
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type not in SUPPORTED_CONTENT_TYPES:
                        return FetchResult(
                            current,
                            "skipped",
                            content_type=content_type or None,
                            failure_reason="unsupported_content_type",
                        )
                    length = response.headers.get("content-length")
                    if length and int(length) > self.settings.web_fetch_max_bytes:
                        return FetchResult(
                            current,
                            "skipped",
                            content_type=content_type,
                            failure_reason="too_large",
                        )
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > self.settings.web_fetch_max_bytes:
                            return FetchResult(
                                current,
                                "skipped",
                                content_type=content_type,
                                failure_reason="too_large",
                            )
                    result = await asyncio.to_thread(
                        self.extract,
                        bytes(data),
                        content_type,
                        current,
                        response.encoding,
                    )
                    result.http_last_modified = response.headers.get("last-modified")
                    return result
        except UnsafeUrlError as exc:
            return FetchResult(current, "blocked", failure_reason=str(exc))
        except (httpx.TimeoutException, httpx.TransportError, OSError, ValueError) as exc:
            return FetchResult(current, "failed", failure_reason=type(exc).__name__)
        return FetchResult(current, "failed", failure_reason="redirect_limit")

    def validate_url(self, url: str) -> None:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError as exc:
            raise UnsafeUrlError("invalid_url") from exc
        if parts.scheme.lower() not in {"http", "https"}:
            raise UnsafeUrlError("unsupported_scheme")
        if not parts.hostname:
            raise UnsafeUrlError("missing_hostname")
        if parts.username is not None or parts.password is not None:
            raise UnsafeUrlError("credentials_not_allowed")
        if port not in {None, 80, 443}:
            raise UnsafeUrlError("port_not_allowed")
        host = parts.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith(".localhost"):
            raise UnsafeUrlError("private_network")
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None and not literal.is_global:
            raise UnsafeUrlError("private_network")
        addresses = self.resolver(host, port or (443 if parts.scheme == "https" else 80))
        if not addresses:
            raise UnsafeUrlError("dns_no_address")
        for value in addresses:
            address = ipaddress.ip_address(value)
            if not address.is_global:
                raise UnsafeUrlError("private_network")

    @staticmethod
    def _resolve_host(host: str, port: int) -> list[str]:
        return sorted(
            {
                item[4][0]
                for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            }
        )

    def extract(
        self,
        data: bytes,
        content_type: str,
        url: str,
        encoding: str | None = None,
    ) -> FetchResult:
        if content_type == "application/pdf":
            try:
                import fitz

                blocks: list[tuple[str | None, str]] = []
                with fitz.open(stream=data, filetype="pdf") as document:
                    if document.needs_pass:
                        return FetchResult(url, "failed", content_type, failure_reason="encrypted_pdf")
                    for page_number, page in enumerate(document, start=1):
                        text = _clean_text(page.get_text("text"))
                        if text:
                            blocks.append((f"Page {page_number}", text))
                        if sum(len(value) for _, value in blocks) >= 1_000_000:
                            break
                if not blocks:
                    return FetchResult(url, "failed", content_type, failure_reason="empty_pdf")
                metadata = self.source_evaluator.extract_text_metadata(
                    "\n".join(value for _, value in blocks)
                )
                return FetchResult(
                    url,
                    "fetched",
                    content_type,
                    blocks=blocks,
                    published_date=metadata.published_date,
                    published_date_source=metadata.published_date_source,
                    doi=metadata.doi,
                )
            except Exception as exc:
                return FetchResult(
                    url,
                    "failed",
                    content_type,
                    failure_reason=f"pdf_extraction_{type(exc).__name__}",
                )
        text = data.decode(encoding or "utf-8", errors="replace")
        if content_type == "text/plain":
            clean = _clean_text(text)
            blocks = [(None, clean)] if clean else []
            metadata = self.source_evaluator.extract_text_metadata(text)
            return FetchResult(
                url,
                "fetched" if blocks else "failed",
                content_type,
                blocks=blocks,
                failure_reason=None if blocks else "empty_text",
                published_date=metadata.published_date,
                published_date_source=metadata.published_date_source,
                doi=metadata.doi,
            )
        parser = _HTMLTextExtractor()
        try:
            parser.feed(text)
        except Exception:
            pass
        blocks = parser.blocks()
        metadata = self.source_evaluator.extract_html_metadata(text)
        return FetchResult(
            url,
            "fetched" if blocks else "failed",
            content_type,
            title=parser.title or None,
            blocks=blocks,
            failure_reason=None if blocks else "empty_html",
            published_date=metadata.published_date,
            modified_date=metadata.modified_date,
            published_date_source=metadata.published_date_source,
            modified_date_source=metadata.modified_date_source,
            doi=metadata.doi,
            metadata=metadata.values,
        )

    def chunk_passages(self, blocks: list[tuple[str | None, str]]) -> list[Passage]:
        limit = max(300, self.settings.web_passage_max_chars)
        overlap = min(150, limit // 5)
        passages: list[Passage] = []
        current = ""
        current_heading: str | None = None
        for heading, text in blocks:
            if current and heading and current_heading and heading != current_heading:
                passages.append(Passage(len(passages), current, current_heading))
                current = ""
                current_heading = None
            prefix = f"{heading}\n" if heading and heading != text else ""
            block = f"{prefix}{text}".strip()
            while len(block) > limit:
                split = block.rfind(". ", 0, limit)
                split = split + 1 if split >= limit // 2 else limit
                part = block[:split].strip()
                if current:
                    passages.append(Passage(len(passages), current, current_heading))
                    current = ""
                passages.append(Passage(len(passages), part, heading))
                block = block[max(0, split - overlap) :].strip()
            if current and len(current) + len(block) + 1 > limit:
                passages.append(Passage(len(passages), current, current_heading))
                tail = current[-overlap:].strip()
                current = f"{tail}\n{block}".strip() if tail else block
                current_heading = heading
            else:
                current = f"{current}\n{block}".strip()
                current_heading = current_heading or heading
        if current:
            passages.append(Passage(len(passages), current, current_heading))
        return passages

    def _rank_fetches(
        self,
        query: str,
        fetches: list[tuple[WebCandidate, FetchResult]],
        use_semantic: bool,
        intent: QueryIntent = QueryIntent.GENERAL_TECHNICAL,
        year_constraint: YearConstraint | None = None,
    ) -> tuple[
        list[tuple[float, WebCandidate, FetchResult, Passage, SourceQuality, WebRankScore]],
        int,
        dict[str, float],
        dict[str, dict[str, Any]],
    ]:
        query_tokens = self._tokens(query)
        rows: list[tuple[WebCandidate, FetchResult, Passage, float]] = []
        for candidate, fetched in fetches:
            for passage in self.chunk_passages(fetched.blocks):
                lexical = len(query_tokens & self._tokens(passage.text)) / max(
                    1, len(query_tokens)
                )
                rows.append((candidate, fetched, passage, lexical))

        semantic = [0.0] * len(rows)
        if use_semantic and self.embedder is not None and rows:
            try:
                indexes = sorted(
                    range(len(rows)),
                    key=lambda index: rows[index][3],
                    reverse=True,
                )[:8]
                vectors = self.embedder(
                    [query, *[rows[index][2].text for index in indexes]]
                )
                for index, vector in zip(indexes, vectors[1:]):
                    semantic[index] = max(0.0, self._cosine(vectors[0], vector))
            except Exception:
                pass

        by_url: dict[str, list[tuple[float, WebCandidate, FetchResult, Passage, SourceQuality, WebRankScore]]] = {}
        best_scores: dict[str, float] = {}
        source_debug: dict[str, dict[str, Any]] = {}
        rejected = 0
        threshold = self.settings.web_passage_min_relevance
        for (candidate, fetched, passage, lexical), semantic_score in zip(rows, semantic):
            score = 0.7 * semantic_score + 0.3 * lexical
            scored = Passage(
                passage.index,
                passage.text,
                passage.heading,
                score,
            )
            best_scores[candidate.url] = max(
                best_scores.get(candidate.url, float("-inf")),
                score,
            )
            source = self.source_evaluator.evaluate_source(
                url=fetched.url,
                title=fetched.title or candidate.title,
                text=passage.text,
                metadata=fetched.metadata,
                doi=fetched.doi,
            )
            recency = self.source_evaluator.recency_score(
                intent,
                fetched.published_date,
                fetched.modified_date,
                year_constraint,
            )
            rank_score = self.source_evaluator.rank(
                intent=intent,
                relevance_score=score,
                source=source,
                recency_score=recency,
                search_rank=candidate.search_rank,
                published_date=fetched.published_date,
            )
            combined = rank_score.final_score
            previous = source_debug.get(candidate.url)
            if previous is None or score > previous["relevance_score"]:
                source_debug[candidate.url] = self._source_debug(
                    candidate, fetched, source, rank_score
                )
            if score < threshold:
                rejected += 1
                continue
            by_url.setdefault(candidate.url, []).append(
                (combined, candidate, fetched, scored, source, rank_score)
            )

        ranked: list[tuple[float, WebCandidate, FetchResult, Passage, SourceQuality, WebRankScore]] = []
        for items in by_url.values():
            ranked.extend(sorted(items, key=lambda item: item[0], reverse=True)[:2])
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked, rejected, best_scores, source_debug

    @staticmethod
    def _source_debug(
        candidate: WebCandidate,
        fetched: FetchResult,
        source: SourceQuality,
        rank_score: WebRankScore,
    ) -> dict[str, Any]:
        return {
            "url": candidate.url,
            "domain": candidate.domain,
            "category": source.category,
            "published_date": fetched.published_date,
            "published_date_source": fetched.published_date_source,
            "authority_score": source.authority_score,
            "recency_score": rank_score.recency_score,
            "primary_source": source.primary_source,
            "doi": source.doi,
            "relevance_score": rank_score.relevance_score,
            "final_score": rank_score.final_score,
        }

    def rank_passages(self, query: str, passages: list[Passage]) -> list[Passage]:
        if not passages:
            return []
        query_tokens = self._tokens(query)
        lexical = [
            len(query_tokens & self._tokens(item.text)) / max(1, len(query_tokens))
            for item in passages
        ]
        semantic = [0.0] * len(passages)
        if self.embedder is not None:
            try:
                # Bound expensive BGE inference for long PDFs; lexical scoring cheaply
                # narrows hundreds of extracted passages before semantic ranking.
                semantic_indexes = sorted(
                    range(len(passages)),
                    key=lambda index: lexical[index],
                    reverse=True,
                )[:64]
                vectors = self.embedder(
                    [query, *[passages[index].text for index in semantic_indexes]]
                )
                for index, vector in zip(semantic_indexes, vectors[1:]):
                    semantic[index] = max(0.0, self._cosine(vectors[0], vector))
            except Exception:
                pass
        ranked = [
            Passage(item.index, item.text, item.heading, 0.7 * sem + 0.3 * lex)
            for item, sem, lex in zip(passages, semantic, lexical)
        ]
        return sorted(ranked, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            token.casefold()
            for token in TOKEN_RE.findall(text)
            if token.casefold() not in STOPWORDS
        }

    @classmethod
    def snippet_relevant(cls, query: str, snippet: str) -> bool:
        query_tokens = cls._tokens(query)
        return bool(query_tokens & cls._tokens(snippet))

    @staticmethod
    def _cosine(left: Any, right: Any) -> float:
        dot = sum(float(a) * float(b) for a, b in zip(left, right))
        left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
        right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
