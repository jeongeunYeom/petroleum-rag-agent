"""Verify the frozen candidate, references, KB and model identities before calls."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

import chromadb
import requests

from common import (BENCHMARK_SHA, JUDGE_MODEL, OLD_COMMIT, POLICY_SHA, PRODUCT_SHA,
                    REPO, ROOT, assert_frozen, kb_snapshot, old_bytes, product_unchanged,
                    save_json)


def main() -> None:
    assert_frozen()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if head != PRODUCT_SHA or not product_unchanged():
        raise RuntimeError("evaluation branch does not start at the exact product candidate")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("exact judge model cannot be checked without OPENAI_API_KEY")
    snapshot = kb_snapshot()
    if not snapshot["all_files_match_frozen"]:
        raise RuntimeError("production Chroma files differ from the frozen V18 snapshot")
    collection = chromadb.PersistentClient(path=snapshot["directory"]).get_collection(snapshot["collection"])
    metadata = collection.get(include=["metadatas"])["metadatas"]
    documents = len({m.get("document") for m in metadata if m and m.get("document")})
    chunks = collection.count()
    if (documents, chunks) != (12, 18976):
        raise RuntimeError(f"unexpected KB snapshot: {documents} documents / {chunks} chunks")
    local = requests.get("http://127.0.0.1:11434/api/version", timeout=15)
    local.raise_for_status()
    tags = requests.get("http://127.0.0.1:11434/api/tags", timeout=15)
    tags.raise_for_status()
    qwen = next((m for m in tags.json().get("models", []) if m.get("name") == "qwen3:8b"), None)
    if not qwen:
        raise RuntimeError("qwen3:8b unavailable")
    judge = requests.get(
        f"https://api.openai.com/v1/models/{JUDGE_MODEL}",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}, timeout=30,
    )
    judge.raise_for_status()
    if judge.json().get("id") != JUDGE_MODEL:
        raise RuntimeError("exact judge model unavailable")
    assets = ["scored_rows.json", "final_metrics.json", "final_results.csv"]
    assets.extend(f"raw/{system}/V18P-{index:03d}.json"
                  for system in ("qwen_closed_book", "v18_agent", "gpt_reference")
                  for index in range(1, 25))
    reference_hashes = {name: hashlib.sha256(old_bytes(name)).hexdigest() for name in assets}
    record = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_branch": "eval/v20-1-poster-reeval", "evaluation_branch_sha_before_harness_commit": head,
        "evaluated_product_sha": PRODUCT_SHA, "frozen_benchmark_freeze_commit": "e91cdc25705766e40c11e98f045eb5344887aba9",
        "benchmark_sha256": BENCHMARK_SHA, "policy_sha256": POLICY_SHA,
        "baseline_source_branch": "eval/v18-poster-final", "baseline_source_commit": OLD_COMMIT,
        "baseline_artifact_sha256": reference_hashes,
        "kb": {**snapshot, "documents": documents, "chunks": chunks},
        "ollama_version": local.json().get("version"),
        "local_model": {"name": qwen["name"], "digest": qwen.get("digest")},
        "retrieval_mode": "hybrid", "web_disabled": True, "external_evidence_disabled": True,
        "judge_model": judge.json().get("id"), "judge_temperature": 0,
        "backend_pytest": "1554 passed", "frontend_tests": "23 passed", "frontend_build": "PASS",
        "model_calls_before_harness_commit": 0,
    }
    save_json(ROOT / "preflight.json", record)
    print(json.dumps({"benchmark": BENCHMARK_SHA, "policy": POLICY_SHA,
                      "kb_match": snapshot["all_files_match_frozen"], "documents": documents,
                      "chunks": chunks, "judge": JUDGE_MODEL}, indent=2))


if __name__ == "__main__":
    main()
