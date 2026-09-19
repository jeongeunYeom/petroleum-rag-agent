from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.services.evidence_research import EvidenceResearchService
from app.tools.external_search_tools import ExternalSearchTools


class ResearchTools:
    """Agent-facing read-only tools for external search and evidence synthesis."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.external = ExternalSearchTools()
        self._research_service: EvidenceResearchService | None = None

    def search_external_web(
        self,
        query: str,
        max_results: int = 5,
    ) -> dict[str, Any]:
        return self.external.search_external_web(
            query,
            max_results=max_results,
        )

    def research_with_evidence(
        self,
        query: str,
        internal_top_k: int = 5,
        external_top_k: int = 5,
        model: str | None = None,
    ) -> dict[str, Any]:
        return self._get_research_service().research(
            query,
            internal_top_k=internal_top_k,
            external_top_k=external_top_k,
            use_internal=True,
            use_external=True,
            model=model,
        )

    def _get_research_service(self) -> EvidenceResearchService:
        if self._research_service is None:
            self._research_service = EvidenceResearchService(
                self.settings,
                external_tools=self.external,
            )
        return self._research_service
