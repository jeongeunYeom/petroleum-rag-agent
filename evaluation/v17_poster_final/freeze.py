"""Read-only freeze checks and immutable fingerprints; no model inference."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRODUCT = "3c5f0fd1da77ac46cb8447ed13f9b8ad9b30d7c3"
BASE_V16 = "57af58c44816c3734ea3d5a7aa4e1f08407798ba"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def db_snapshot() -> dict:
    import chromadb

    directory = ROOT / "data" / "vector_db"
    client = chromadb.PersistentClient(path=str(directory))
    collections = {entry.name: client.get_collection(entry.name).count() for entry in client.list_collections()}
    collection = client.get_collection("petroleum_knowledge")
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    documents = sorted({m.get("document") for m in metadatas if m and m.get("document")})
    return {
        "directory": str(directory),
        "collections": collections,
        "documents": documents,
        "document_count": len(documents),
        "file_sha256": {str(path.relative_to(directory)): sha(path) for path in sorted(directory.rglob("*")) if path.is_file()},
        "sqlite_size_bytes": (directory / "chroma.sqlite3").stat().st_size,
    }


def validate_sources(tasks: list[dict]) -> None:
    import chromadb

    collection = chromadb.PersistentClient(path=str(ROOT / "data" / "vector_db")).get_collection("petroleum_knowledge")
    clean = lambda value: re.sub(r"\s+", " ", value).strip().casefold()
    for task in tasks:
        for span in task["supporting_spans"]:
            result = collection.get(ids=[span["chunk_id"]], include=["documents", "metadatas"])
            assert result["ids"], (task["id"], "missing chunk")
            metadata = result["metadatas"][0]
            assert metadata.get("document") == task["source_document"], task["id"]
            assert str(metadata.get("page")) == str(task["source_page"]), task["id"]
            assert clean(span["text"]) in clean(result["documents"][0]), task["id"]


def prefreeze() -> dict:
    assert git("branch", "--show-current") == "eval/v17-poster-final"
    assert git("rev-parse", "HEAD") == PRODUCT
    assert not (HERE / "freeze_receipt.json").exists()
    tasks = json.loads((HERE / "benchmark.json").read_text(encoding="utf-8"))["tasks"]
    assert len(tasks) == len({task["id"] for task in tasks}) == 24
    assert [task["id"] for task in tasks] == [f"V17-{i:02d}" for i in range(1, 25)]
    assert Counter(task["category"] for task in tasks) == {
        "knowledge": 6, "reasoning": 4, "direct_calculation": 4,
        "user_formula": 3, "kb_formula": 3, "false_premise": 2, "unanswerable": 2,
    }
    assert sum(task["numeric_gold"] is not None for task in tasks) == 10
    assert all(len(task["required_claims"]) >= 2 for task in tasks if task["category"] == "reasoning")
    assert sum(len(task["required_claims"]) >= 3 for task in tasks if task["category"] == "reasoning") >= 2
    assert sum(bool(re.search(r"[가-힣]", task["question"])) and bool(task["supporting_spans"]) for task in tasks) >= 6
    assert json.loads((HERE / "duplicate_check.json").read_text(encoding="utf-8"))["passed"] is True
    validate_sources(tasks)
    db = db_snapshot()
    assert db["collections"]["petroleum_knowledge"] == 18976 and db["document_count"] == 12
    manifest = {
        "product_sha": PRODUCT, "base_v16_sha": BASE_V16,
        "main_sha": git("rev-parse", "main"),
        "benchmark_sha256": sha(HERE / "benchmark.json"),
        "policy_sha256": sha(HERE / "POLICY.md"),
        "duplicate_check_sha256": sha(HERE / "duplicate_check.json"),
        "freeze_commit": "See freeze_receipt.json (commit ID unknowable within its own tree)",
        "task_count": 24, "numeric_count": 10,
        "category_distribution": dict(Counter(task["category"] for task in tasks)),
        "source_page_distribution": dict(Counter(f"{task['source_document']} p{task['source_page']}" for task in tasks if task["source_document"])),
        "duplicate_screen": {"historical_question_count": json.loads((HERE / "duplicate_check.json").read_text(encoding="utf-8"))["historical_question_count"], "passed": True},
        "chroma_snapshot": db,
        "models": {"qwen": "qwen3:8b", "gpt_reference": "gpt-5.4-mini-2026-03-17", "judge": "gpt-5.4-2026-03-05"},
        "evaluation_policy": "POLICY.md frozen with benchmark; 24 common tasks, 10 numeric tasks; no retries or substitutions",
        "agent_settings": {"execution_mode": "autonomous_goal_execution", "retrieval_mode": "hybrid", "web": False, "data_dir": str(ROOT / "data")},
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    item = prefreeze()
    print("ready-to-freeze", item["benchmark_sha256"], item["chroma_snapshot"]["collections"], item["chroma_snapshot"]["document_count"])
