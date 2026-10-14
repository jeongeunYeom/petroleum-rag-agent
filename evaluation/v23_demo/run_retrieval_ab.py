"""Read-only 40-case development comparison for existing KB retrieval modes."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["hybrid", "hybrid_rerank"], required=True)
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args()
    data_dir = os.getenv("DATA_DIR")
    if not data_dir:
        raise SystemExit("DATA_DIR must point to the existing production KB parent")
    sqlite = Path(data_dir) / "vector_db" / "chroma.sqlite3"
    if not sqlite.is_file():
        raise SystemExit(f"Existing KB is absent: {sqlite}")

    import chromadb
    from app.core.config import Settings
    from app.models.research_schemas import ResearchRequest
    from app.services.ollama import OllamaClient
    from app.services.research_agent import ResearchAgent
    from app.services.vector_store import VectorStore

    catalog = json.loads((HERE / "retrieval_dev.json").read_text(encoding="utf-8"))["cases"]
    if len(catalog) != 40:
        raise SystemExit("Retrieval development catalog must contain 40 cases")
    collection = chromadb.PersistentClient(path=str(sqlite.parent)).get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        raise SystemExit("Refusing A/B test against an unexpected KB count")
    settings = replace(Settings(), retrieval_mode=args.mode)
    agent = ResearchAgent(settings, VectorStore(settings), OllamaClient(settings))
    output = HERE / f"retrieval_ab_{args.mode}.json"
    rows = json.loads(output.read_text(encoding="utf-8"))["rows"] if output.exists() else []
    done = {row["id"] for row in rows}
    for case in catalog[:args.limit]:
        if case["id"] in done:
            continue
        start = time.perf_counter()
        try:
            response = await agent.research(ResearchRequest(
                query=case["query"], internal_top_k=5, use_internal=True,
                use_external=False, evidence_only=True, model="qwen3:8b"))
            sources = response.internal_sources
            hits = [{"id": row.evidence_id, "document": row.document, "page": row.page,
                     "excerpt": row.excerpt[:800]} for row in sources]
            target_page = any(row.document == case["document"] and row.page == case["page"]
                              for row in sources)
            target_formula = any(row.document == case["document"] and row.page == case["page"]
                                 and case.get("formula", "").replace(" ", "") in row.excerpt.replace(" ", "")
                                 for row in sources) if case.get("formula") else None
            row = {"id": case["id"], "mode": args.mode, "seconds": round(time.perf_counter() - start, 3),
                   "target_document_hit": any(s.document == case["document"] for s in sources),
                   "target_page_hit": target_page, "target_formula_span_hit": target_formula,
                   "target_page_rank": next((i + 1 for i, s in enumerate(sources)
                                             if s.document == case["document"] and s.page == case["page"]), None),
                   "sources": hits, "error": None}
        except Exception as exc:
            row = {"id": case["id"], "mode": args.mode, "seconds": round(time.perf_counter() - start, 3),
                   "target_document_hit": False, "target_page_hit": False,
                   "target_formula_span_hit": False if case.get("formula") else None,
                   "target_page_rank": None, "sources": [], "error": f"{type(exc).__name__}: {exc}"}
        rows.append(row)
        output.write_text(json.dumps({"mode": args.mode, "rows": rows}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"{args.mode} {case['id']} page={row['target_page_hit']} "
              f"formula={row['target_formula_span_hit']} {row['seconds']}s", flush=True)
    if collection.count() != 18976:
        raise SystemExit("KB count changed during read-only retrieval comparison")
    valid = [row for row in rows if not row["error"]]
    latency = sorted(row["seconds"] for row in valid)
    formula = [row for row in valid if row["target_formula_span_hit"] is not None]
    print(json.dumps({"mode": args.mode, "cases": len(rows), "errors": len(rows) - len(valid),
                      "target_page_hit_rate": sum(row["target_page_hit"] for row in valid) / len(valid) if valid else None,
                      "target_formula_span_hit_rate": sum(row["target_formula_span_hit"] for row in formula) / len(formula) if formula else None,
                      "median_seconds": statistics.median(latency) if latency else None,
                      "p95_seconds": latency[max(0, int(0.95 * len(latency)) - 1)] if latency else None},
                     indent=2))


if __name__ == "__main__":
    asyncio.run(main())
