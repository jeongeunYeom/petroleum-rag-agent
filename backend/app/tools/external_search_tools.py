from __future__ import annotations

from urllib.parse import urlparse
from typing import Any

from ddgs import DDGS


class ExternalSearchTools:
    """Read-only external web search backed by DDGS.

    This tool returns search-result evidence only. It never treats web snippets as
    trusted internal knowledge and it never writes external content into ChromaDB.
    """

    def search_external_web(
        self,
        query: str,
        max_results: int = 5,
        region: str = "wt-wt",
        timelimit: str | None = None,
    ) -> dict[str, Any]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ValueError("External web search requires a query.")

        try:
            limit = int(max_results)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_results must be an integer.") from exc
        if not 1 <= limit <= 10:
            raise ValueError("max_results must be between 1 and 10.")

        search_kwargs: dict[str, Any] = {
            "region": str(region or "wt-wt"),
            "safesearch": "moderate",
            "max_results": limit,
        }
        if timelimit:
            search_kwargs["timelimit"] = str(timelimit)

        try:
            rows = DDGS().text(normalized_query, **search_kwargs) or []
        except Exception as exc:
            raise RuntimeError(f"External web search failed: {exc}") from exc

        sources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            url = str(row.get("href") or row.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                continue
            seen_urls.add(url)
            sources.append(
                {
                    "source_id": f"WEB{len(sources) + 1}",
                    "source_type": "external_web",
                    "provider": "ddgs",
                    "title": str(row.get("title") or "").strip(),
                    "url": url,
                    "domain": parsed.netloc.lower(),
                    "snippet": str(
                        row.get("body") or row.get("snippet") or ""
                    ).strip(),
                    "rank": index,
                }
            )
            if len(sources) >= limit:
                break

        return {
            "query": normalized_query,
            "provider": "ddgs",
            "source_count": len(sources),
            "sources": sources,
        }
