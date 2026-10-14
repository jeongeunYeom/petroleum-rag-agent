"""Read-only local conference preflight; never creates or reindexes a KB.

Run from the repository root with DATA_DIR pointing to the existing 18,976-chunk
data parent and RETRIEVAL_MODE set to the chosen conference mode.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


async def check() -> dict:
    data_dir = os.getenv("DATA_DIR")
    if not data_dir:
        raise RuntimeError("DATA_DIR must identify the existing production data directory")
    sqlite = Path(data_dir).resolve() / "vector_db" / "chroma.sqlite3"
    if not sqlite.is_file():
        raise RuntimeError(f"Existing ChromaDB was not found: {sqlite}")

    import chromadb
    import httpx
    from app.core.config import Settings
    from app.models.goal_research_schemas import GoalResearchRequest
    from app.models.research_schemas import ResearchRequest
    from app.services.goal_simulation import run_direct_arithmetic
    from app.services.ollama import OllamaClient
    from app.services.research_agent import ResearchAgent
    from app.services.user_fact_registry import UserFactRegistry
    from app.services.vector_store import VectorStore

    settings = Settings()
    collection = chromadb.PersistentClient(path=str(sqlite.parent)).get_collection(
        settings.collection_name)
    before = collection.count()
    if before != 18976:
        raise RuntimeError(f"KB has {before} chunks; expected the existing 18,976-chunk DB")
    metadata = collection.get(include=["metadatas"])["metadatas"]
    documents = {row.get("document") for row in metadata if row and row.get("document")}
    if len(documents) != 12:
        raise RuntimeError(f"KB has {len(documents)} documents; expected 12")

    async with httpx.AsyncClient(timeout=90) as client:
        tags = await client.get(settings.ollama_base_url.rstrip("/") + "/api/tags")
        tags.raise_for_status()
        models = {row.get("name") for row in tags.json().get("models", [])}
        if "qwen3:8b" not in models:
            raise RuntimeError("qwen3:8b is not installed in the local Ollama server")
        prompt = await client.post(settings.ollama_base_url.rstrip("/") + "/api/generate",
            json={"model": "qwen3:8b", "prompt": "Reply OK.", "stream": False,
                  "options": {"num_predict": 24, "temperature": 0}})
        prompt.raise_for_status()
        if not prompt.json().get("done"):
            raise RuntimeError("qwen3:8b did not complete the local response")

    store = VectorStore(settings)
    embedding = store.embed(["formation pressure relation"])
    if len(embedding) != 1 or not embedding[0]:
        raise RuntimeError("The configured embedding model returned no vector")
    researcher = ResearchAgent(settings, store, OllamaClient(settings))
    started = time.perf_counter()
    evidence = await researcher.research(ResearchRequest(
        query="wellbore storage pressure derivative evidence", use_internal=True,
        use_external=False, evidence_only=True, model="qwen3:8b"))
    if not evidence.internal_sources or not any(
        row.document and row.page is not None and row.excerpt for row in evidence.internal_sources):
        raise RuntimeError("The existing KB did not return a locatable source for the test question")
    if settings.retrieval_mode == "hybrid_rerank":
        researcher._get_reranker()  # Model-load check; retrieval above already used it.

    request = GoalResearchRequest(
        topic="A=17 psi, B=8 psi. Calculate the sum.",
        execution_mode="autonomous_goal_execution", allow_python_execution=True,
        python_execution_approved=True)
    facts = UserFactRegistry.from_topic(request.topic)
    calculation = await run_direct_arithmetic(
        settings, request, "GR-V23-PREFLIGHT", facts, ["sum"], "CALC1",
        original_text=request.topic)
    if not calculation.validation_passed or calculation.output_manifest["OUT_sum"]["value"] != 25:
        raise RuntimeError("Bounded direct calculation failed its validation")
    after = collection.count()
    if after != before:
        raise RuntimeError("KB chunk count changed during preflight")
    return {"ollama": "ok", "qwen3:8b": "responding", "embedding_dimensions": len(embedding[0]),
            "collection": settings.collection_name, "chunks": after, "documents": len(documents),
            "retrieval_mode": settings.retrieval_mode, "retrieval_seconds": round(time.perf_counter() - started, 3),
            "retrieval_sources": len(evidence.internal_sources),
            "first_source": {"document": evidence.internal_sources[0].document,
                             "page": evidence.internal_sources[0].page},
            "direct_calculation": "validated"}


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(check()), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"V23 preflight failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
