from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit


LATEST_RE = re.compile(
    r"\b(?:latest|recent|current|today|new(?:est)?|state[- ]of[- ]the[- ]art|202[5-9])\b"
    r"|최신|최근|현재|동향|올해|최근\s*연구",
    re.IGNORECASE,
)
HISTORICAL_RE = re.compile(
    r"\b(?:history|historical|origin|first|development\s+history|evolution)\b"
    r"|역사|과거|처음|기원|발전\s*과정",
    re.IGNORECASE,
)
COMPARISON_RE = re.compile(
    r"\b(?:compare|comparison|versus|vs\.?)\b|비교",
    re.IGNORECASE,
)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
TECHNICAL_REPORT_RE = re.compile(
    r"\b(?:technical\s+report|research\s+(?:paper|report)|conference\s+paper|"
    r"standard|guidance|assessment|white\s*paper|publication|journal|abstract)\b"
    r"|기술\s*보고서|연구\s*(?:논문|보고서)|학술|표준|가이드",
    re.IGNORECASE,
)


class QueryIntent(str, Enum):
    LATEST = "latest"
    HISTORICAL = "historical"
    GENERAL_TECHNICAL = "general_technical"
    COMPARISON = "comparison"


class YearConstraintType(str, Enum):
    EXACT = "exact"
    SINCE = "since"
    AS_OF = "as_of"


@dataclass(frozen=True)
class YearConstraint:
    year: int
    constraint_type: YearConstraintType = YearConstraintType.EXACT

    @property
    def since(self) -> bool:
        return self.constraint_type is YearConstraintType.SINCE


@dataclass(frozen=True)
class ExtractedWebMetadata:
    published_date: str | None = None
    published_date_source: str | None = None
    modified_date: str | None = None
    modified_date_source: str | None = None
    doi: str | None = None
    values: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceQuality:
    category: str
    authority_score: float
    primary_source: bool | None
    primary_source_score: float
    doi: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WebRankScore:
    relevance_score: float
    source_quality_score: float
    recency_score: float
    primary_source_score: float
    discovery_rank_score: float
    final_score: float
    ranking_reason: tuple[str, ...]


class _MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.json_ld: list[str] = []
        self._in_json_ld = False
        self._json_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            key = (
                values.get("property")
                or values.get("name")
                or values.get("itemprop")
            ).strip().lower()
            content = values.get("content", "").strip()
            if key and content:
                self.meta.setdefault(key, content)
        if (
            tag.lower() == "script"
            and values.get("type", "").lower() == "application/ld+json"
        ):
            self._in_json_ld = True
            self._json_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_json_ld:
            self.json_ld.append("".join(self._json_parts))
            self._in_json_ld = False
            self._json_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_parts.append(data)


class WebSourceQualityEvaluator:
    CATEGORY_SCORES = {
        "government": 0.92,
        "standards_body": 0.90,
        "professional_society": 0.88,
        "journal": 0.86,
        "academic": 0.82,
        "publisher": 0.80,
        "company_official": 0.74,
        "news": 0.50,
        "unknown": 0.45,
        "technical_blog": 0.40,
        "aggregator": 0.35,
    }
    PROFESSIONAL_DOMAINS = (
        "spe.org", "onepetro.org", "seg.org", "aapg.org", "agu.org",
    )
    PUBLISHER_DOMAINS = (
        "nature.com", "sciencedirect.com", "springer.com", "springerlink.com",
        "wiley.com", "tandfonline.com", "mdpi.com", "frontiersin.org",
    )
    GOVERNMENT_DOMAINS = (
        "energy.gov", "netl.doe.gov", "usgs.gov", "epa.gov", "iea.org", "ipcc.ch",
    )
    STANDARDS_DOMAINS = ("iso.org", "astm.org", "api.org")
    COMPANY_DOMAINS = (
        "slb.com", "halliburton.com", "bakerhughes.com", "shell.com", "bp.com",
        "exxonmobil.com", "chevron.com", "equinor.com",
    )
    NEWS_DOMAINS = ("reuters.com", "bloomberg.com", "bbc.com", "cnn.com")
    AGGREGATOR_DOMAINS = (
        "researchgate.net", "academia.edu", "semanticscholar.org", "scribd.com",
    )

    def classify_intent(self, query: str) -> QueryIntent:
        if HISTORICAL_RE.search(query):
            return QueryIntent.HISTORICAL
        if COMPARISON_RE.search(query):
            return QueryIntent.COMPARISON
        if LATEST_RE.search(query):
            return QueryIntent.LATEST
        return QueryIntent.GENERAL_TECHNICAL

    @staticmethod
    def parse_year_constraint(query: str) -> YearConstraint | None:
        as_of = re.search(
            r"(?:as\s+of\s*)(20\d{2})|"
            r"(20\d{2})(?:년)?\s*(?:기준|현재)",
            query,
            re.IGNORECASE,
        )
        if as_of:
            return YearConstraint(
                int(as_of.group(1) or as_of.group(2)),
                YearConstraintType.AS_OF,
            )
        since = re.search(
            r"(?:since|after|from)\s*(20\d{2})|"
            r"(20\d{2})(?:년)?\s*(?:이후|부터)",
            query,
            re.IGNORECASE,
        )
        if since:
            return YearConstraint(
                int(since.group(1) or since.group(2)),
                YearConstraintType.SINCE,
            )
        exact = re.search(
            r"(?:published\s+in|from\s+the\s+year)\s*(20\d{2})|"
            r"(20\d{2})(?:년(?:에)?)?\s*(?:발표|출판|게재)(?:된|한)?|"
            r"(20\d{2})(?:년)?\s*(?:SPE\s*)?"
            r"(?:논문|연구|paper|papers|study|studies|publication)",
            query,
            re.IGNORECASE,
        )
        if exact:
            return YearConstraint(
                int(next(value for value in exact.groups() if value)),
                YearConstraintType.EXACT,
            )
        return None

    def extract_html_metadata(
        self,
        html: str,
        *,
        today: date | None = None,
    ) -> ExtractedWebMetadata:
        parser = _MetadataParser()
        try:
            parser.feed(html)
        except Exception:
            pass

        published_keys = (
            ("article:published_time", "article_meta"),
            ("datepublished", "article_meta"),
            ("citation_publication_date", "citation_meta"),
            ("citation_date", "citation_meta"),
            ("dc.date", "dc_meta"),
            ("dcterms.date", "dc_meta"),
            ("parsely-pub-date", "parsely_meta"),
            ("pubdate", "article_meta"),
        )
        modified_keys = (
            ("article:modified_time", "article_meta"),
            ("datemodified", "article_meta"),
            ("date.modified", "dc_meta"),
        )
        published, published_source = self._first_date(
            parser.meta,
            published_keys,
            today,
        )
        modified, modified_source = self._first_date(
            parser.meta,
            modified_keys,
            today,
        )
        json_doi: str | None = None
        for raw in parser.json_ld:
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            for item in self._json_objects(payload):
                if published is None:
                    value = self.normalize_date(item.get("datePublished"), today=today)
                    if value:
                        published, published_source = value, "json_ld"
                if modified is None:
                    value = self.normalize_date(item.get("dateModified"), today=today)
                    if value:
                        modified, modified_source = value, "json_ld"
                json_doi = json_doi or self.extract_doi(
                    " ".join(str(item.get(key) or "") for key in ("doi", "identifier", "sameAs"))
                )

        visible_date = self.extract_visible_date(html[:5000], today=today)
        if published is None and visible_date:
            published, published_source = visible_date, "visible_text"
        doi = self.extract_doi(
            " ".join([*parser.meta.values(), html[:20_000]])
        ) or json_doi
        return ExtractedWebMetadata(
            published_date=published,
            published_date_source=published_source,
            modified_date=modified,
            modified_date_source=modified_source,
            doi=doi,
            values=parser.meta,
        )

    def extract_text_metadata(
        self,
        text: str,
        *,
        today: date | None = None,
    ) -> ExtractedWebMetadata:
        published = self.extract_visible_date(text[:5000], today=today)
        return ExtractedWebMetadata(
            published_date=published,
            published_date_source="visible_text" if published else None,
            doi=self.extract_doi(text[:30_000]),
        )

    @classmethod
    def evaluate_source(
        cls,
        *,
        url: str,
        title: str,
        text: str = "",
        metadata: dict[str, str] | None = None,
        doi: str | None = None,
    ) -> SourceQuality:
        domain = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        searchable = f"{title} {text}".casefold()
        values = metadata or {}
        doi = doi or cls.extract_doi(
            " ".join((url, title, text, *values.values()))
        )
        has_journal_metadata = any(
            key.startswith("citation_")
            or key in {"prism.publicationname", "dc.type", "dcterms.type"}
            for key in values
        ) and bool(
            re.search(r"journal|article|paper|conference|proceedings", " ".join(values.values()), re.I)
            or values.get("citation_journal_title")
            or values.get("citation_title")
        )

        if cls._domain_matches(domain, cls.GOVERNMENT_DOMAINS) or domain.endswith(".gov"):
            category = "government"
        elif cls._domain_matches(domain, cls.STANDARDS_DOMAINS):
            category = "standards_body"
        elif cls._domain_matches(domain, cls.PROFESSIONAL_DOMAINS):
            category = "professional_society"
        elif has_journal_metadata:
            category = "journal"
        elif domain.endswith(".edu") or re.search(r"\.ac\.[a-z]{2,}$", domain):
            category = "academic"
        elif cls._domain_matches(domain, cls.PUBLISHER_DOMAINS):
            category = "publisher"
        elif cls._domain_matches(domain, cls.AGGREGATOR_DOMAINS):
            category = "aggregator"
        elif cls._domain_matches(domain, cls.NEWS_DOMAINS):
            category = "news"
        elif cls._domain_matches(domain, cls.COMPANY_DOMAINS) and TECHNICAL_REPORT_RE.search(searchable):
            category = "company_official"
        elif re.search(r"\bblog\b", searchable):
            category = "technical_blog"
        elif doi:
            category = "journal"
        else:
            category = "unknown"

        primary: bool | None = None
        if category in {"news", "technical_blog", "aggregator"}:
            primary = False
        elif doi and category in {
            "journal", "publisher", "professional_society", "academic"
        }:
            primary = True
        elif category in {"government", "standards_body", "company_official"} and (
            TECHNICAL_REPORT_RE.search(searchable) or has_journal_metadata
        ):
            primary = True
        elif category in {
            "government", "standards_body", "professional_society", "academic",
            "publisher", "company_official",
        }:
            primary = None

        reasons = [f"{category}_source"]
        if doi:
            reasons.append("doi_present")
        if primary is True:
            reasons.append("primary_source")
        elif primary is False:
            reasons.append("secondary_source")
        return SourceQuality(
            category=category,
            authority_score=cls.CATEGORY_SCORES[category],
            primary_source=primary,
            primary_source_score=1.0 if primary is True else 0.0 if primary is False else 0.25,
            doi=doi,
            reasons=tuple(reasons),
        )

    def recency_score(
        self,
        intent: QueryIntent,
        published_date: str | None,
        modified_date: str | None = None,
        constraint: YearConstraint | None = None,
        *,
        today: date | None = None,
    ) -> float:
        if intent is QueryIntent.HISTORICAL:
            return 0.0
        current = today or date.today()
        raw_date = published_date or modified_date
        reference = current
        if constraint and constraint.constraint_type is YearConstraintType.AS_OF:
            as_of_year = min(constraint.year, current.year)
            source_year = re.search(r"(?<!\d)(?:18|19|20)\d{2}(?!\d)", raw_date or "")
            if source_year and int(source_year.group()) > as_of_year:
                return 0.0
            if as_of_year < current.year:
                reference = date(as_of_year, 12, 31)
        value = self.normalize_date(raw_date, today=current)
        if value is None:
            return 0.25
        published = date.fromisoformat(value)
        if constraint:
            if constraint.constraint_type is YearConstraintType.SINCE:
                return 1.0 if published.year >= constraint.year else 0.0
            if constraint.constraint_type is YearConstraintType.EXACT:
                distance = abs(published.year - constraint.year)
                return 1.0 if distance == 0 else 0.5 if distance == 1 else 0.0
        age = max(0.0, (reference - published).days / 365.25)
        if age <= 1:
            return 1.0
        if age <= 2:
            return 0.8
        if age <= 5:
            return 0.5
        if age <= 10:
            return 0.2
        return 0.0

    def rank(
        self,
        *,
        intent: QueryIntent,
        relevance_score: float,
        source: SourceQuality,
        recency_score: float,
        search_rank: int,
        published_date: str | None,
    ) -> WebRankScore:
        weights = {
            QueryIntent.LATEST: (0.65, 0.15, 0.10, 0.08, 0.02),
            QueryIntent.COMPARISON: (0.67, 0.15, 0.08, 0.08, 0.02),
            QueryIntent.HISTORICAL: (0.75, 0.15, 0.0, 0.08, 0.02),
            QueryIntent.GENERAL_TECHNICAL: (0.75, 0.15, 0.02, 0.06, 0.02),
        }[intent]
        discovery = 1 / max(1, search_rank)
        final = (
            weights[0] * relevance_score
            + weights[1] * source.authority_score
            + weights[2] * recency_score
            + weights[3] * source.primary_source_score
            + weights[4] * discovery
        )
        reasons = list(source.reasons)
        reasons.append(
            "high_query_relevance" if relevance_score >= 0.6 else "query_relevant"
        )
        if published_date:
            reasons.append(f"published_{published_date[:4]}")
        if intent is QueryIntent.HISTORICAL:
            reasons.append("historical_recency_disabled")
        elif recency_score >= 0.8:
            reasons.append("recent_publication")
        return WebRankScore(
            relevance_score=relevance_score,
            source_quality_score=source.authority_score,
            recency_score=recency_score,
            primary_source_score=source.primary_source_score,
            discovery_rank_score=discovery,
            final_score=final,
            ranking_reason=tuple(dict.fromkeys(reasons)),
        )

    @staticmethod
    def normalize_date(value: Any, *, today: date | None = None) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        parsed: date | None = None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            for date_format in ("%B %Y", "%b %Y", "%B %d, %Y", "%b %d, %Y"):
                try:
                    parsed = datetime.strptime(text.strip(), date_format).date()
                    break
                except ValueError:
                    continue
        if parsed is None:
            try:
                parsed = parsedate_to_datetime(text).date()
            except (TypeError, ValueError, OverflowError):
                match = re.search(r"(?<!\d)(18\d{2}|19\d{2}|20\d{2})(?:[-/.](\d{1,2}))?(?:[-/.](\d{1,2}))?", text)
                if match:
                    try:
                        parsed = date(
                            int(match.group(1)),
                            int(match.group(2) or 1),
                            int(match.group(3) or 1),
                        )
                    except ValueError:
                        parsed = None
        if parsed is None:
            return None
        current = today or datetime.now(timezone.utc).date()
        if parsed > current + timedelta(days=31):
            return None
        return parsed.isoformat()

    @classmethod
    def extract_visible_date(cls, text: str, *, today: date | None = None) -> str | None:
        match = re.search(
            r"(?:published|publication\s+date|date\s+published|pubdate)\s*[:|-]\s*"
            r"([^<\n]{4,40})",
            text,
            re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r"\s*(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
                r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
                r"Nov(?:ember)?|Dec(?:ember)?)\s+(?:\d{1,2},\s+)?\d{4}",
                text,
                re.IGNORECASE,
            )
        return cls.normalize_date(match.group(0 if match and match.lastindex is None else 1), today=today) if match else None

    @staticmethod
    def extract_doi(text: str) -> str | None:
        match = DOI_RE.search(text or "")
        return match.group(0).rstrip(".,;)]}").lower() if match else None

    @classmethod
    def _first_date(
        cls,
        values: dict[str, str],
        keys: tuple[tuple[str, str], ...],
        today: date | None,
    ) -> tuple[str | None, str | None]:
        for key, source in keys:
            value = cls.normalize_date(values.get(key), today=today)
            if value:
                return value, source
        return None, None

    @staticmethod
    def _json_objects(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            items = [value]
            graph = value.get("@graph")
            if isinstance(graph, list):
                items.extend(item for item in graph if isinstance(item, dict))
            return items
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _domain_matches(domain: str, patterns: tuple[str, ...]) -> bool:
        return any(domain == item or domain.endswith(f".{item}") for item in patterns)
