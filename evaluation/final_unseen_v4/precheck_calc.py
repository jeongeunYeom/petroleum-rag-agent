"""Read-only V4 precheck of the known, non-V4 production API-gravity path."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    data_dir = Path(os.environ["DATA_DIR"]).resolve()
    sqlite = data_dir / "vector_db" / "chroma.sqlite3"
    if not sqlite.is_file() or os.environ.get("RETRIEVAL_MODE") != "hybrid":
        raise RuntimeError("Expected existing ChromaDB and RETRIEVAL_MODE=hybrid")

    import chromadb
    from fastapi.testclient import TestClient
    from app.main import app

    collection = chromadb.PersistentClient(path=str(sqlite.parent)).get_collection("petroleum_knowledge")
    before = collection.count()
    if before != 18976:
        raise RuntimeError(f"Unexpected KB count: {before}")

    with TestClient(app) as client:
        response = client.post("/api/research/goal-runs/from-message", json={
            "message": "비중이 0.918인 원유의 API도를 내부 교재의 식을 찾아 계산해줘.",
            "model": "qwen3:8b",
        })
        response.raise_for_status()
        run_id = response.json()["run_id"]
        deadline = time.monotonic() + 180
        while True:
            state = client.get(f"/api/research/goal-runs/{run_id}")
            state.raise_for_status()
            run = state.json()
            if run["run_status"] in {"completed", "stopped", "failed", "waiting_for_user_input"}:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Known API-gravity precheck did not finish within 180 seconds")
            time.sleep(0.5)

    validated = [calc for calc in run.get("computations", []) if calc.get("validation_passed")]
    sources = {source.get("evidence_id"): source for source in run.get("internal_sources", [])}
    formula_sources = [sources[source_id] for calc in validated
                       for source_id in calc.get("formula_source_ids", []) if source_id in sources]
    if (run["run_status"] != "completed" or not validated or not formula_sources
            or not any(source.get("page") == 90 and "141.5" in str(source.get("excerpt"))
                       for source in formula_sources)):
        raise RuntimeError("Known KB formula did not complete with validated p.90 provenance")
    if collection.count() != before:
        raise RuntimeError("KB count changed during precheck")
    print(json.dumps({
        "run_status": run["run_status"],
        "actions": [item.get("action_type") for item in run.get("action_history", [])],
        "validated_calculations": len(validated),
        "formula_sources": [{"document": item.get("document"), "page": item.get("page")}
                            for item in formula_sources],
        "answer": run.get("final_answer"),
        "kb_chunks_after": collection.count(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
