from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb
from chromadb.config import Settings as ChromaSettings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import PROJECT_ROOT, Settings  # noqa: E402
from app.services.research_agent import ResearchAgent  # noqa: E402
from app.services.vector_store import (  # noqa: E402
    FIGURE_DOCUMENT_MARKERS,
    VectorStore,
)


QUERIES = (
    "radial flow pressure derivative",
    "wellbore storage unit slope",
    "RFT Survey after Significant Production",
    "Appraisal Well RFT Survey",
    "supercharged points RFT",
    "type curve pressure derivative",
)


def describe(name: str, hits: list[dict[str, Any]]) -> None:
    print(f"  {name}: hit_count={len(hits)}")
    if not hits:
        return
    hit = hits[0]
    metadata = hit.get("metadata") or {}
    print(
        "    top="
        f"id={hit.get('id')} "
        f"document={metadata.get('document') or metadata.get('filename')} "
        f"page={metadata.get('page')} "
        f"chunk_type={metadata.get('chunk_type') or metadata.get('type')} "
        f"figure={ResearchAgent._is_figure_hit(str(hit.get('text') or ''), metadata)}"
    )


def main() -> int:
    settings = Settings()
    print(f"PROJECT_ROOT={PROJECT_ROOT}")
    print(f"DATA_DIR={settings.data_dir}")
    print(f"vector_db_dir={settings.vector_db_dir}")
    print(f"CHROMA_COLLECTION={settings.collection_name}")
    print(f"RETRIEVAL_MODE={settings.retrieval_mode}")

    try:
        logging.getLogger("chromadb.telemetry.product.posthog").disabled = True
        client = chromadb.PersistentClient(
            path=str(settings.vector_db_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection = client.get_collection(settings.collection_name)
    except Exception as exc:
        print(f"ERROR: existing Chroma collection is unavailable: {exc}")
        return 2

    count = collection.count()
    print(f"collection_count={count}")
    if count == 0:
        print(
            "ERROR: knowledge base collection is empty. "
            "Set DATA_DIR to the existing indexed data directory."
        )
        return 2

    data = collection.get(include=["documents", "metadatas"])
    rows = list(
        zip(
            data.get("ids", []),
            data.get("documents", []),
            data.get("metadatas", []),
        )
    )
    documents = {
        str((metadata or {}).get("document_id") or (metadata or {}).get("document") or "")
        for _, _, metadata in rows
    }
    print(f"documents={len(documents - {''})}")
    print(f"chunks={len(rows)}")

    for marker in FIGURE_DOCUMENT_MARKERS:
        marker_count = sum(marker.casefold() in str(text or "").casefold() for _, text, _ in rows)
        print(f"marker[{marker}]={marker_count}")
    figure_rows = [
        row
        for row in rows
        if ResearchAgent._is_figure_hit(str(row[1] or ""), row[2] or {})
    ]
    print(f"_is_figure_hit={len(figure_rows)}")
    for chunk_id, text, metadata in figure_rows[:10]:
        print(
            "figure_sample="
            + json.dumps(
                {
                    "id": chunk_id,
                    "document": (metadata or {}).get("document")
                    or (metadata or {}).get("filename"),
                    "page": (metadata or {}).get("page"),
                    "metadata": metadata or {},
                    "text_prefix": str(text or "")[:240].replace("\n", " "),
                },
                ensure_ascii=False,
            )
        )

    store = VectorStore(settings)
    agent = ResearchAgent(settings, store, ollama=None)
    final_nonempty = True
    figure_channel_nonempty = False
    for query in QUERIES:
        print(f"query={query}")
        dense = store.search(query, 5)
        bm25 = store.bm25_search(query, 20)
        figure_dense = store.search_figures(query, 5)
        figure_bm25 = store.bm25_search_figures(query, 20)
        final = agent.search_knowledge_base(query, 5)
        internal, figures = agent.normalize_internal_evidence(final)
        describe("vector_store.search", dense)
        describe("vector_store.bm25_search", bm25)
        describe("vector_store.search_figures", figure_dense)
        describe("vector_store.bm25_search_figures", figure_bm25)
        describe("ResearchAgent.search_knowledge_base", final)
        print(
            f"  normalized: internal={len(internal)} figures={len(figures)}"
        )
        final_nonempty = final_nonempty and bool(final)
        if "rft" in query.casefold():
            figure_channel_nonempty = figure_channel_nonempty or bool(
                figure_dense or figure_bm25
            )

    passed = bool(figure_rows and final_nonempty and figure_channel_nonempty)
    print(f"retrieval_health={'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
