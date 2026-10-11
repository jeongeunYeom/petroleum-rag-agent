"""Validate new source anchors and audit question overlap without reading old answers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATASET = HERE / "unseen_eval_v12.json"


def prior_questions() -> list[tuple[str, str]]:
    prior: list[tuple[str, str]] = []
    for version in (1, 2, 3, 4):
        raw = subprocess.check_output([
            "git", "show", f"evaluation/final-benchmark-v{version}:evaluation/final_benchmark_v{version}.json"
        ], cwd=ROOT)
        for task in json.loads(raw)["tasks"]:
            prior.append((f"v{version}:{task['task_id']}", task["question"]))
    for name in ("agentic_heldout_v1.json", "petroleum_agent_heldout_v1.json",
                 "petroleum_agent_heldout_v1_questions.json", "well_test_agent_benchmark.json"):
        path = ROOT / "evaluation" / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        tasks = data if isinstance(data, list) else data.get("tasks", data.get("questions", []))
        for index, task in enumerate(tasks):
            if isinstance(task, dict) and task.get("question"):
                prior.append((f"{name}:{task.get('task_id') or task.get('id') or index}", task["question"]))
    return prior


def main() -> None:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    tasks = data["tasks"]
    if len(tasks) < 50 or len({item["id"] for item in tasks}) != len(tasks):
        raise ValueError("Need >=50 unique task IDs")
    if any(not item["source_ids"] and item["answerable"] and item["category"] not in {"calculation"}
           for item in tasks):
        raise ValueError("Source-free positive task")
    import chromadb
    collection = chromadb.PersistentClient(path=str(ROOT / "data" / "vector_db")).get_collection(
        "petroleum_knowledge")
    if collection.count() != 18976:
        raise RuntimeError("Existing Chroma count changed; do not ingest or rebuild")
    rows = collection.get(include=["documents", "metadatas"])
    normalize = lambda value: " ".join(str(value).casefold().split())
    source_errors = []
    for source_id, spec in data["source_catalog"].items():
        texts = [text for text, meta in zip(rows["documents"], rows["metadatas"])
                 if meta.get("document") == spec["document"] and meta.get("page") == spec["page"]]
        if not texts or normalize(spec["anchor"]) not in normalize(" ".join(texts)):
            source_errors.append(source_id)
    if source_errors:
        raise ValueError("Missing literal source anchors: " + ", ".join(source_errors))

    # This is an overlap audit only: old answers and rubrics are never loaded.
    os.environ["HF_HUB_OFFLINE"] = "1"
    from sentence_transformers import SentenceTransformer
    import numpy as np
    prior = prior_questions()
    model = SentenceTransformer("BAAI/bge-m3", device="cpu")
    new_vectors = model.encode([item["question"] for item in tasks], normalize_embeddings=True,
                               batch_size=8, show_progress_bar=False)
    old_vectors = model.encode([question for _, question in prior], normalize_embeddings=True,
                               batch_size=8, show_progress_bar=False)
    similarity = np.asarray(new_vectors) @ np.asarray(old_vectors).T
    def tokens(value: str) -> set[str]:
        return set(re.findall(r"[\w가-힣]+", value.casefold()))
    overlap = []
    for index, task in enumerate(tasks):
        old_index = int(np.argmax(similarity[index]))
        old_id, old_question = prior[old_index]
        a, b = tokens(task["question"]), tokens(old_question)
        jaccard = len(a & b) / max(1, len(a | b))
        score = float(similarity[index, old_index])
        overlap.append({"task_id": task["id"], "nearest_prior_id": old_id,
                        "cosine_similarity": round(score, 4), "token_jaccard": round(jaccard, 4),
                        "near_duplicate": score >= .92 or (score >= .86 and jaccard >= .45)})
    result = {"dataset_sha256": hashlib.sha256(DATASET.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
              "new_tasks": len(tasks), "prior_questions": len(prior),
              "source_anchors_valid": len(data["source_catalog"]),
              "near_duplicate_count": sum(item["near_duplicate"] for item in overlap),
              "nearest_matches": overlap}
    (HERE / "dedup_preflight.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"new_tasks": result["new_tasks"], "prior_questions": result["prior_questions"],
                      "source_anchors_valid": result["source_anchors_valid"],
                      "near_duplicate_count": result["near_duplicate_count"],
                      "flagged_ids": [item["task_id"] for item in overlap if item["near_duplicate"]]}))
    if result["near_duplicate_count"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
