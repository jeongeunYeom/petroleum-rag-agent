"""Pre-freeze source, schema, and prior-question overlap checks; never runs the Agent."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

import chromadb
import numpy as np
from sentence_transformers import SentenceTransformer


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATASET = HERE / "benchmark.json"


def prior_questions() -> list[tuple[str, str]]:
    prior: list[tuple[str, str]] = []
    refs = [
        (f"evaluation/final-benchmark-v{n}", f"evaluation/final_benchmark_v{n}.json")
        for n in range(1, 5)
    ] + [("eval/v12-unseen", "evaluation/unseen_v12/unseen_eval_v12.json")]
    for ref, path in refs:
        data = json.loads(subprocess.check_output(["git", "show", f"{ref}:{path}"], cwd=ROOT))
        for idx, row in enumerate(data.get("tasks", [])):
            if row.get("question"):
                prior.append((f"{ref}:{row.get('id') or row.get('task_id') or idx}", row["question"]))
    for path in [ROOT / "evaluation" / "dev" / "agent_reliability_v13_dev.json",
                 *[ROOT / "evaluation" / name for name in (
                     "agentic_heldout_v1.json", "petroleum_agent_heldout_v1.json",
                     "petroleum_agent_heldout_v1_questions.json", "well_test_agent_benchmark.json")]]:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("tasks", data.get("questions", data.get("cases", [])))
        for idx, row in enumerate(rows):
            if isinstance(row, dict):
                question = row.get("question") or row.get("prompt") or row.get("message")
                if question:
                    prior.append((f"{path.name}:{row.get('id') or row.get('task_id') or idx}", question))
    for path in (ROOT / "backend" / "tests").rglob("*.py"):
        for idx, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if len(line) < 45 or not re.search(r"(?:question|query|message|prompt)\s*[:=]", line, re.I):
                continue
            match = re.search(r"[\"']([^\"']{35,})[\"']", line)
            if match:
                prior.append((f"{path.name}:{idx}", match.group(1)))
    return prior


def main() -> None:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    tasks = data["tasks"]
    assert len(tasks) >= 50 and len({row["id"] for row in tasks}) == len(tasks)
    assert data["product_sha"] == "32de96cac75f6a96463e5ccebc24eab2eb061fe0"
    assert all(row.get("question") and row.get("reference_answer") and row.get("expected_claims")
               and "answerable" in row and row.get("difficulty") and row.get("category")
               and "source_ids" in row for row in tasks)
    assert all("expected_numeric" in row and "expected_unit" in row and "tolerance" in row
               for row in tasks if row["category"] in {
                   "direct_calculation", "user_formula_calculation", "kb_formula_calculation"})
    assert all(sid in data["source_catalog"] for row in tasks for sid in row["source_ids"])
    db = ROOT / "data" / "vector_db"
    assert (db / "chroma.sqlite3").exists(), "Existing DB missing; do not create one"
    collection = chromadb.PersistentClient(path=str(db)).get_collection("petroleum_knowledge")
    assert collection.count() == 18976
    rows = collection.get(include=["documents", "metadatas"])
    normalize = lambda value: " ".join(str(value).casefold().split())
    missing = []
    for sid, spec in data["source_catalog"].items():
        texts = [text for text, meta in zip(rows["documents"], rows["metadatas"])
                 if meta.get("document") == spec["document"] and meta.get("page") == spec["page"]]
        if not texts or not any(normalize(spec["anchor"]) in normalize(text) for text in texts):
            missing.append(sid)
    if missing:
        raise ValueError("Missing Chroma source spans: " + ", ".join(missing))

    prior = prior_questions()
    import os
    os.environ["HF_HUB_OFFLINE"] = "1"
    model = SentenceTransformer("BAAI/bge-m3", device="cpu")
    new_q = [row["question"] for row in tasks]
    prior_q = [row[1] for row in prior]
    vectors = model.encode(new_q + prior_q, normalize_embeddings=True, batch_size=8,
                           show_progress_bar=False)
    similarity = np.asarray(vectors[:len(tasks)]) @ np.asarray(vectors[len(tasks):]).T
    tokens = lambda value: set(re.findall(r"[\w가-힣]+", value.casefold()))
    comparisons = []
    for idx, row in enumerate(tasks):
        nearest = int(np.argmax(similarity[idx]))
        old_id, old_q = prior[nearest]
        a, b = tokens(row["question"]), tokens(old_q)
        jaccard = len(a & b) / max(1, len(a | b))
        cosine = float(similarity[idx, nearest])
        comparisons.append({"id": row["id"], "nearest_prior_id": old_id,
                            "cosine": round(cosine, 4), "token_jaccard": round(jaccard, 4),
                            "near_duplicate": cosine >= .92 or (cosine >= .86 and jaccard >= .45)})
    output = {"dataset_sha256": hashlib.sha256(DATASET.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
              "task_count": len(tasks), "categories": dict(Counter(t["category"] for t in tasks)),
              "difficulty": dict(Counter(t["difficulty"] for t in tasks)),
              "prior_question_count": len(prior), "source_anchors_verified": len(data["source_catalog"]),
              "near_duplicate_count": sum(item["near_duplicate"] for item in comparisons),
              "nearest_matches": comparisons}
    (HERE / "dedup_preflight.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("task_count", "categories", "difficulty",
                                                 "prior_question_count", "source_anchors_verified",
                                                 "near_duplicate_count")}, ensure_ascii=False))
    print("FLAGGED:", [item for item in comparisons if item["near_duplicate"]])
    if output["near_duplicate_count"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
