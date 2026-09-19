from __future__ import annotations

import logging
import math
import os
import re
from typing import Any

import torch
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from app.core.config import Settings
from app.services.vector_store import VectorStore, expand_query_terms


logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*|[가-힣]{2,}")


class HybridVectorStore(VectorStore):
    """VectorStore v2: dense BGE-M3 + BM25 + optional cross-encoder reranking.

    The original VectorStore remains unchanged so the application can fall back
    to the previous retrieval path if needed. BM25 data and the reranker are
    loaded lazily to keep startup fast.
    """

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._bm25: BM25Okapi | None = None
        self._bm25_rows: list[dict[str, Any]] = []
        self._bm25_collection_count = -1
        self._reranker: CrossEncoder | None = None
        self._reranker_error: RuntimeError | None = None

    def add_chunks(self, chunks: list[dict[str, Any]]) -> None:
        super().add_chunks(chunks)
        self._invalidate_bm25_cache()

    def hybrid_search(
        self,
        question: str,
        top_k: int,
        score_threshold: float,
        prefer_metadata: dict[str, Any] | None = None,
        keyword_weight: float = 0.45,
    ) -> list[dict[str, Any]]:
        del keyword_weight  # v2 uses reciprocal-rank fusion instead of a fixed blend.

        candidate_multiplier = max(
            2,
            int(getattr(self.settings, "hybrid_candidate_multiplier", 4)),
        )
        candidate_k = max(top_k * candidate_multiplier, top_k)

        vector_hits = self.search(question, candidate_k)
        bm25_hits = self.bm25_search(
            question,
            candidate_k,
            prefer_metadata=prefer_metadata,
        )
        fused = self._reciprocal_rank_fusion(
            vector_hits,
            bm25_hits,
            prefer_metadata=prefer_metadata,
        )

        if self._reranker_enabled() and fused:
            rerank_k = max(
                top_k,
                int(getattr(self.settings, "reranker_candidate_k", 24)),
            )
            fused = self.rerank(question, fused[:rerank_k]) + fused[rerank_k:]

        hits = [
            hit
            for hit in fused
            if float(hit.get("score") or 0.0) >= score_threshold
        ]
        return hits[:top_k]

    def bm25_search(
        self,
        question: str,
        top_k: int,
        prefer_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_bm25_index()
        if self._bm25 is None or not self._bm25_rows:
            return []

        query_tokens = self._query_tokens(question)
        if not query_tokens:
            return []

        raw_scores = self._bm25.get_scores(query_tokens)
        if len(raw_scores) == 0:
            return []

        max_score = max(float(score) for score in raw_scores)
        if max_score <= 0:
            return []

        hits: list[dict[str, Any]] = []
        for index, raw_score in enumerate(raw_scores):
            raw_value = float(raw_score)
            if raw_value <= 0:
                continue
            row = self._bm25_rows[index]
            normalized = raw_value / max_score
            metadata_boost = self._metadata_boost(
                row["metadata"],
                prefer_metadata,
            )
            hits.append(
                {
                    "id": row["id"],
                    "text": row["text"],
                    "metadata": row["metadata"],
                    "distance": None,
                    "vector_score": 0.0,
                    "bm25_score": normalized,
                    "bm25_raw_score": raw_value,
                    "keyword_score": normalized,
                    "score": min(1.0, normalized + metadata_boost),
                }
            )

        return sorted(
            hits,
            key=lambda item: float(item.get("score") or 0.0),
            reverse=True,
        )[:top_k]

    def rerank(
        self,
        question: str,
        hits: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not hits:
            return []

        try:
            model = self._get_reranker()
        except RuntimeError as exc:
            logger.warning("Reranker unavailable; using fused retrieval order: %s", exc)
            return hits

        max_chars = max(
            256,
            int(getattr(self.settings, "reranker_max_characters", 4000)),
        )
        pairs = [
            [question, str(hit.get("text") or "")[:max_chars]]
            for hit in hits
        ]
        raw_scores = model.predict(
            pairs,
            batch_size=max(
                1,
                int(getattr(self.settings, "reranker_batch_size", 8)),
            ),
            show_progress_bar=False,
        )

        reranked: list[dict[str, Any]] = []
        for hit, raw_score in zip(hits, raw_scores):
            value = float(raw_score)
            normalized = self._sigmoid(value)
            fused_score = float(hit.get("score") or 0.0)
            updated = dict(hit)
            updated["reranker_raw_score"] = value
            updated["reranker_score"] = normalized
            # Preserve a useful floor from retrieval so existing similarity
            # thresholds keep their meaning while reranking changes ordering.
            updated["score"] = max(
                fused_score * 0.55 + normalized * 0.45,
                fused_score * 0.85,
            )
            reranked.append(updated)

        return sorted(
            reranked,
            key=lambda item: (
                float(item.get("reranker_score") or 0.0),
                float(item.get("score") or 0.0),
            ),
            reverse=True,
        )

    def _reciprocal_rank_fusion(
        self,
        vector_hits: list[dict[str, Any]],
        bm25_hits: list[dict[str, Any]],
        prefer_metadata: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        rrf_k = max(1, int(getattr(self.settings, "hybrid_rrf_k", 60)))
        merged: dict[str, dict[str, Any]] = {}

        def ensure(hit: dict[str, Any]) -> dict[str, Any]:
            chunk_id = str(hit.get("id") or "")
            current = merged.get(chunk_id)
            if current is None:
                current = dict(hit)
                current["id"] = chunk_id
                current["rrf_score"] = 0.0
                current.setdefault("vector_score", 0.0)
                current.setdefault("bm25_score", 0.0)
                current.setdefault("keyword_score", 0.0)
                merged[chunk_id] = current
            return current

        for rank, hit in enumerate(vector_hits, start=1):
            current = ensure(hit)
            distance = hit.get("distance")
            vector_score = (
                max(0.0, 1.0 - float(distance))
                if distance is not None
                else float(hit.get("score") or 0.0)
            )
            current["vector_score"] = max(
                float(current.get("vector_score") or 0.0),
                vector_score,
            )
            current["rrf_score"] += 1.0 / (rrf_k + rank)

        for rank, hit in enumerate(bm25_hits, start=1):
            current = ensure(hit)
            bm25_score = float(hit.get("bm25_score") or 0.0)
            current["bm25_score"] = max(
                float(current.get("bm25_score") or 0.0),
                bm25_score,
            )
            current["keyword_score"] = current["bm25_score"]
            current["rrf_score"] += 1.0 / (rrf_k + rank)

        if not merged:
            return []

        max_rrf = max(float(hit["rrf_score"]) for hit in merged.values()) or 1.0
        for hit in merged.values():
            rrf_normalized = float(hit["rrf_score"]) / max_rrf
            vector_score = float(hit.get("vector_score") or 0.0)
            bm25_score = float(hit.get("bm25_score") or 0.0)
            metadata_boost = self._metadata_boost(
                hit.get("metadata") or {},
                prefer_metadata,
            )
            # RRF determines consensus; dense/BM25 maxima keep strong single-
            # retriever evidence from being unfairly discarded.
            base_score = max(
                rrf_normalized,
                vector_score,
                bm25_score,
            )
            hit["score"] = min(1.0, base_score + metadata_boost)

        return sorted(
            merged.values(),
            key=lambda item: (
                float(item.get("rrf_score") or 0.0),
                float(item.get("score") or 0.0),
            ),
            reverse=True,
        )

    def _ensure_bm25_index(self) -> None:
        collection_count = self.collection.count()
        if (
            self._bm25 is not None
            and self._bm25_collection_count == collection_count
        ):
            return

        data = self.collection.get(include=["documents", "metadatas"])
        rows: list[dict[str, Any]] = []
        corpus: list[list[str]] = []
        for chunk_id, document, metadata in zip(
            data.get("ids", []),
            data.get("documents", []),
            data.get("metadatas", []),
        ):
            text = str(document or "")
            tokens = self._tokenize(text)
            if not tokens:
                tokens = ["__empty__"]
            rows.append(
                {
                    "id": str(chunk_id),
                    "text": text,
                    "metadata": metadata or {},
                }
            )
            corpus.append(tokens)

        self._bm25_rows = rows
        self._bm25 = BM25Okapi(corpus) if corpus else None
        self._bm25_collection_count = collection_count

    def _invalidate_bm25_cache(self) -> None:
        self._bm25 = None
        self._bm25_rows = []
        self._bm25_collection_count = -1

    def _query_tokens(self, question: str) -> list[str]:
        expanded = expand_query_terms(question)
        tokens = self._tokenize(question)
        for term in expanded:
            tokens.extend(self._tokenize(term))
        # Keep order while removing duplicates; BM25 query term frequency is not
        # useful enough here to justify repeated technical expansions.
        return list(dict.fromkeys(tokens))

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [
            match.group(0).lower()
            for match in _TOKEN_RE.finditer(text)
        ]

    def _reranker_enabled(self) -> bool:
        value = getattr(self.settings, "reranker_enabled", None)
        if value is not None:
            return bool(value)
        return os.getenv("RERANKER_ENABLED", "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }

    def _get_reranker(self) -> CrossEncoder:
        if self._reranker is not None:
            return self._reranker
        if self._reranker_error is not None:
            raise self._reranker_error

        model_name = str(
            getattr(
                self.settings,
                "reranker_model",
                os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base"),
            )
        )
        model_path = getattr(self.settings, "reranker_model_path", None) or os.getenv(
            "RERANKER_MODEL_PATH"
        )
        selected_model = str(model_path or model_name)
        if model_path and not os.path.exists(str(model_path)):
            self._reranker_error = RuntimeError(
                f"Reranker model path does not exist: {model_path}"
            )
            raise self._reranker_error

        device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            self._reranker = CrossEncoder(selected_model, device=device)
        except Exception as exc:
            hint = (
                " Set RERANKER_MODEL_PATH to a downloaded local model directory "
                "or set RERANKER_ENABLED=0 to use dense+BM25 without reranking."
            )
            self._reranker_error = RuntimeError(
                f"Could not load reranker `{selected_model}`.{hint}"
            )
            raise self._reranker_error from exc

        logger.info("Reranker loaded: %s / device=%s", selected_model, device)
        return self._reranker

    @staticmethod
    def _sigmoid(value: float) -> float:
        if value >= 0:
            z = math.exp(-value)
            return 1.0 / (1.0 + z)
        z = math.exp(value)
        return z / (1.0 + z)
