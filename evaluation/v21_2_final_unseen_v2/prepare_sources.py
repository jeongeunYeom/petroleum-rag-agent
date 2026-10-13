"""Read-only, deterministic source selection for the V21.2 final evaluation."""

from __future__ import annotations

import hashlib
import json
import random
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import chromadb


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DB = Path(r"D:\petroleum-rag-agent\data\vector_db")
SEED = 20261013
REPORT_SHA = "f04e56503564da9e9ac7c3bbbf5403dcf8cdea52"
LOCAL_BROWSER = Path(r"D:\petroleum-rag-agent\evaluation\v20_1_browser_e2e")
DIRS = (
    "evaluation/v20_1_browser_e2e/",
    "evaluation/v21_dev/",
    "evaluation/v21_1_dev/",
    "evaluation/v21_2_dev/",
    "evaluation/v21_2_regression_old24/",
)
FORMULA = re.compile(r"(?<!\w)[A-Za-z][A-Za-z0-9_]{0,8}\s*=\s*[^\n]{4,90}")


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def walk_for_sources(value: object, found: set[tuple[str, int]]) -> None:
    if isinstance(value, dict):
        document = value.get("document") or value.get("document_name")
        page = value.get("page") or value.get("page_number")
        if isinstance(document, str) and document.lower().endswith(".pdf"):
            try:
                found.add((document, int(page)))
            except (TypeError, ValueError):
                pass
        for child in value.values():
            walk_for_sources(child, found)
    elif isinstance(value, list):
        for child in value:
            walk_for_sources(child, found)


def excluded_sources() -> tuple[set[tuple[str, int]], dict[str, int]]:
    found: set[tuple[str, int]] = set()
    counts: dict[str, int] = {}
    tracked = git("ls-tree", "-r", "--name-only", REPORT_SHA, "evaluation").decode().splitlines()
    for directory in DIRS:
        paths = [p for p in tracked if p.startswith(directory) and p.endswith(".json")]
        before = len(found)
        for path in paths:
            try:
                data = json.loads(git("show", f"{REPORT_SHA}:{path}"))
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                continue
            walk_for_sources(data, found)
        counts[directory] = len(found) - before
    before = len(found)
    if LOCAL_BROWSER.is_dir():
        for path in sorted(LOCAL_BROWSER.rglob("*.json")):
            try:
                walk_for_sources(json.loads(path.read_text(encoding="utf-8")), found)
            except (OSError, json.JSONDecodeError):
                continue
    counts["local D:/petroleum-rag-agent/evaluation/v20_1_browser_e2e/"] = len(found) - before
    return found, counts


def db_snapshot() -> dict[str, str]:
    result = {}
    for path in sorted(DB.rglob("*")):
        if path.is_file():
            h = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
            result[str(path.relative_to(DB)).replace("\\", "/")] = h.hexdigest()
    return result


def main() -> None:
    excluded, counts = excluded_sources()
    (OUT / "excluded_sources.json").write_text(
        json.dumps({"from_directories": counts, "document_pages": [
            {"document": doc, "page": page} for doc, page in sorted(excluded)
        ]}, ensure_ascii=False, indent=2), encoding="utf-8")

    collection = chromadb.PersistentClient(path=str(DB)).get_collection("petroleum_knowledge")
    assert collection.count() == 18976, collection.count()
    rows = collection.get(include=["metadatas", "documents"])
    pages: dict[tuple[str, int], list[tuple[str, str]]] = defaultdict(list)
    for chunk_id, metadata, document_text in zip(rows["ids"], rows["metadatas"], rows["documents"]):
        if not metadata:
            continue
        doc = metadata.get("document")
        page = metadata.get("page")
        if not doc or not isinstance(page, int) or (doc, page) in excluded:
            continue
        pages[(doc, page)].append((chunk_id, document_text or ""))

    grouped: dict[str, list[dict]] = defaultdict(list)
    for (doc, page), chunks in sorted(pages.items()):
        text = "\n".join(chunk[1] for chunk in chunks)
        if len(text.strip()) < 350:
            continue
        grouped[doc].append({
            "document": doc, "page": page,
            "chunk_ids": [chunk[0] for chunk in chunks],
            "text": text[:12000],
            "formula_candidate_count": len(FORMULA.findall(text)),
        })

    rng = random.Random(SEED)
    selected = []
    for doc, choices in sorted(grouped.items()):
        formula_pages = [row for row in choices if row["formula_candidate_count"]]
        plain_pages = [row for row in choices if not row["formula_candidate_count"]]
        selected.extend(rng.sample(formula_pages, min(14, len(formula_pages))))
        selected.extend(rng.sample(plain_pages, min(8, len(plain_pages))))
    selected.sort(key=lambda row: (row["document"], row["page"]))
    existing_pool = OUT / "source_pool.json"
    if existing_pool.exists():
        # Preserve the pre-authoring draw: later-discovered exclusions can only
        # remove candidates, never cause a question-dependent replacement draw.
        original = json.loads(existing_pool.read_text(encoding="utf-8"))["sources"]
        selected = [row for row in original if (row["document"], row["page"]) not in excluded]
    (OUT / "source_pool.json").write_text(
        json.dumps({"seed": SEED, "selection": "14 formula-like and 8 other eligible pages per document, uniform without replacement", "sources": selected}, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "kb_snapshot_before.json").write_text(json.dumps(db_snapshot(), indent=2), encoding="utf-8")
    print(json.dumps({"collection_count": collection.count(), "documents": len(grouped), "eligible_pages": len(pages), "excluded_pages": len(excluded), "selected_pages": len(selected), "excluded_by_directory": counts}, indent=2))


if __name__ == "__main__":
    main()
