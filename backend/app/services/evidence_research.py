from __future__ import annotations

import re
from typing import Any

import httpx

from app.core.config import Settings
from app.tools.external_search_tools import ExternalSearchTools
from app.tools.knowledge_tools import KnowledgeTools


_RESEARCH_SYSTEM_PROMPT = """당신은 석유공학 Evidence Research Agent이다.
다음 규칙을 반드시 지킨다.
1. 답변의 사실 주장은 제공된 내부 지식베이스 근거 [KB#] 또는 외부 검색 근거 [WEB#]에만 기반한다.
2. 모델의 사전지식을 사실 근거처럼 사용하지 않는다.
3. 내부 지식베이스와 외부 검색 결과를 명확히 구분한다.
4. 외부 웹 검색 snippet은 검색 결과 요약일 뿐이며, 내부 교재/논문 근거와 동일한 신뢰도로 취급하지 않는다.
5. 두 출처가 충돌하면 충돌 내용을 숨기지 말고 각각의 근거를 제시한다.
6. 여러 근거를 연결해 새로운 결론을 도출할 때는 반드시 '종합 추론'이라고 표시하고, 어떤 근거들을 연결했는지 인용한다.
7. 근거가 부족한 부분은 추측하지 말고 확인할 수 없다고 말한다.
8. 한국어로 답하되 원문 기술 용어는 영어를 병기할 수 있다.
9. 가능한 경우 각 핵심 문장 끝에 [KB#], [WEB#] 형식의 근거 ID를 붙인다.
10. 최종 답변은 '내부 지식베이스 근거', '외부 검색 근거', '종합 추론', '한계/불확실성' 순서로 구성한다.
"""


class EvidenceResearchService:
    """Combine local RAG evidence and external web evidence, then synthesize.

    Web evidence is never inserted into the persistent knowledge base. This keeps
    provenance explicit and prevents transient web content from contaminating the
    curated petroleum-engineering corpus.
    """

    def __init__(
        self,
        settings: Settings,
        knowledge_tools: KnowledgeTools | None = None,
        external_tools: ExternalSearchTools | None = None,
    ):
        self.settings = settings
        self.knowledge_tools = knowledge_tools or KnowledgeTools(settings)
        self.external_tools = external_tools or ExternalSearchTools()

    def research(
        self,
        query: str,
        *,
        internal_top_k: int = 5,
        external_top_k: int = 5,
        use_internal: bool = True,
        use_external: bool = True,
        model: str | None = None,
    ) -> dict[str, Any]:
        question = str(query or "").strip()
        if not question:
            raise ValueError("Research requires a query.")
        if not use_internal and not use_external:
            raise ValueError("At least one evidence source must be enabled.")

        internal_result: dict[str, Any] = {
            "query": question,
            "sources": [],
            "source_count": 0,
            "figures": [],
            "figure_count": 0,
        }
        external_result: dict[str, Any] = {
            "query": question,
            "sources": [],
            "source_count": 0,
            "provider": "ddgs",
        }

        if use_internal:
            internal_result = self.knowledge_tools.search_knowledge_base(
                question,
                top_k=internal_top_k,
            )
        if use_external:
            external_result = self.external_tools.search_external_web(
                question,
                max_results=external_top_k,
            )

        internal_sources = self._normalize_internal_sources(
            internal_result.get("sources") or []
        )
        web_sources = list(external_result.get("sources") or [])

        if not internal_sources and not web_sources:
            return {
                "query": question,
                "answer": "내부 지식베이스와 외부 검색에서 답변에 사용할 근거를 찾지 못했습니다.",
                "internal_sources": [],
                "web_sources": [],
                "figures": internal_result.get("figures") or [],
                "provenance": [],
                "model": model or self.settings.text_model,
                "inference_used": False,
            }

        prompt = self._build_prompt(question, internal_sources, web_sources)
        answer = self._synthesize(prompt, model=model)

        provenance = [
            {
                "source_id": source["source_id"],
                "source_type": "knowledge_base",
                "document": source.get("document"),
                "page": source.get("page"),
            }
            for source in internal_sources
        ] + [
            {
                "source_id": source.get("source_id"),
                "source_type": "external_web",
                "title": source.get("title"),
                "url": source.get("url"),
                "domain": source.get("domain"),
            }
            for source in web_sources
        ]

        return {
            "query": question,
            "answer": answer,
            "internal_sources": internal_sources,
            "web_sources": web_sources,
            "figures": internal_result.get("figures") or [],
            "provenance": provenance,
            "model": model or self.settings.text_model,
            "inference_used": True,
            "evidence_counts": {
                "internal": len(internal_sources),
                "external": len(web_sources),
            },
            "policy": {
                "web_persisted_to_knowledge_base": False,
                "requires_source_labels": True,
                "conflicts_must_be_disclosed": True,
            },
        }

    @staticmethod
    def _normalize_internal_sources(sources: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for source in sources:
            if hasattr(source, "model_dump"):
                payload = source.model_dump()
            elif isinstance(source, dict):
                payload = dict(source)
            else:
                continue
            payload["source_id"] = f"KB{len(normalized) + 1}"
            payload["source_type"] = "knowledge_base"
            normalized.append(payload)
        return normalized

    @staticmethod
    def _clean_excerpt(value: Any, limit: int = 1400) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text[:limit]

    def _build_prompt(
        self,
        question: str,
        internal_sources: list[dict[str, Any]],
        web_sources: list[dict[str, Any]],
    ) -> str:
        blocks: list[str] = [f"질문:\n{question}"]

        if internal_sources:
            blocks.append("\n[내부 지식베이스 근거]")
            for source in internal_sources:
                blocks.append(
                    "\n".join(
                        [
                            f"[{source['source_id']}]",
                            f"document: {source.get('document')}",
                            f"page: {source.get('page')}",
                            f"score: {source.get('score')}",
                            f"excerpt: {self._clean_excerpt(source.get('excerpt'))}",
                        ]
                    )
                )

        if web_sources:
            blocks.append("\n[외부 검색 근거]")
            for source in web_sources:
                blocks.append(
                    "\n".join(
                        [
                            f"[{source.get('source_id')}]",
                            f"title: {source.get('title')}",
                            f"domain: {source.get('domain')}",
                            f"url: {source.get('url')}",
                            f"snippet: {self._clean_excerpt(source.get('snippet'))}",
                        ]
                    )
                )

        blocks.append(
            "\n위 근거만 사용해 답변하세요. 내부 근거와 외부 근거를 섞어 하나의 사실처럼 "
            "표현하지 말고, 결합해서 도출한 내용은 '종합 추론'으로 명시하세요."
        )
        return "\n\n".join(blocks)

    def _synthesize(self, prompt: str, *, model: str | None) -> str:
        selected_model = model or self.settings.text_model
        payload = {
            "model": selected_model,
            "messages": [
                {"role": "system", "content": _RESEARCH_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {
                "temperature": 0,
                "num_ctx": 12288,
                "num_predict": 1400,
            },
        }
        try:
            with httpx.Client(timeout=self.settings.ollama_timeout_seconds) as client:
                response = client.post(
                    f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Evidence synthesis failed with Ollama model {selected_model}: {exc}"
            ) from exc

        content = str(response.json().get("message", {}).get("content") or "").strip()
        if not content:
            raise RuntimeError("Evidence synthesis returned an empty answer.")
        return content
