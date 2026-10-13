"""Mechanically exclude prior pages and sample unused production-KB passages.

Run before authoring V3 tasks. This script never prints or exports prior questions.
"""

from __future__ import annotations

import json
import hashlib
import random
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import chromadb


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
KB_DIR = Path(r"D:\petroleum-rag-agent\data\vector_db")
V2_REV = "b8334b58bcebe36aaa79c50399e8a8110b782216"
SEED = 20261013
PRIOR_DIRS = (
    "evaluation/v20_1_browser_e2e",
    "evaluation/v21_dev",
    "evaluation/v21_1_dev",
    "evaluation/v21_2_dev",
    "evaluation/v21_2_regression_old24",
)


def key(document: str, page: int) -> tuple[str, int]:
    return (re.sub(r"[^a-z0-9]", "", document.casefold()), int(page))


def collect_pairs(value: object, found: set[tuple[str, int]]) -> None:
    if isinstance(value, dict):
        doc = value.get("document") or value.get("source_document")
        page = value.get("page") or value.get("source_page")
        if isinstance(doc, str) and isinstance(page, (int, str)):
            match = re.fullmatch(r"(?:p(?:age)?\.?\s*)?(\d+)", str(page), re.I)
            if match:
                found.add(key(doc, int(match.group(1))))
        for nested in value.values():
            collect_pairs(nested, found)
    elif isinstance(value, list):
        for nested in value:
            collect_pairs(nested, found)


def git_json(rev_path: str) -> object:
    return json.loads(subprocess.check_output(["git", "show", rev_path], cwd=REPO))


def prior_pairs() -> set[tuple[str, int]]:
    found: set[tuple[str, int]] = set()
    for directory in PRIOR_DIRS:
        root = REPO / directory
        if root.exists():
            for file in root.rglob("*.json"):
                try:
                    collect_pairs(json.loads(file.read_text(encoding="utf-8")), found)
                except (OSError, ValueError):
                    continue
    # V2 files are consumed only to derive prior-use pages. Never display its text.
    for name in ("excluded_sources.json", "benchmark.json"):
        value = git_json(f"{V2_REV}:evaluation/v21_2_final_unseen_v2/{name}")
        collect_pairs(value, found)
    return found


def main() -> None:
    excluded = prior_pairs()
    client = chromadb.PersistentClient(path=str(KB_DIR))
    collection = client.get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        raise RuntimeError(f"unexpected KB count: {collection.count()}")
    kb = collection.get(include=["metadatas", "documents"])
    pages: dict[tuple[str, int], list[tuple[int, str]]] = defaultdict(list)
    for meta, text in zip(kb["metadatas"], kb["documents"]):
        if not meta or not text or not meta.get("document") or not meta.get("page"):
            continue
        pages[(meta["document"], int(meta["page"]))].append(
            (int(meta.get("chunk_index") or 0), text)
        )
    docs = {doc for doc, _ in pages}
    if len(docs) != 12:
        raise RuntimeError(f"unexpected document count: {len(docs)}")
    eligible: dict[str, list[dict]] = defaultdict(list)
    for (doc, page), chunks in pages.items():
        if key(doc, page) in excluded:
            continue
        chunks.sort()
        text = "\n".join(part for _, part in chunks)
        if len(text) < 450:
            continue
        formula_lines = [
            line.strip()[:220]
            for line in text.splitlines()
            if re.search(r"\b[A-Za-zα-ωΑ-Ω][A-Za-z0-9_]{0,12}\s*=\s*[^=]", line)
            and 6 <= len(line.strip()) <= 240
        ][:12]
        eligible[doc].append(
            {
                "document": doc,
                "page": page,
                "chunk_count": len(chunks),
                "formula_line_count": len(formula_lines),
                "formula_preview": formula_lines[:2],
                "passage_preview": text[:350],
                "passage_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    rng = random.Random(SEED)
    sampled: list[dict] = []
    for doc in sorted(eligible):
        general = sorted(eligible[doc], key=lambda item: item["page"])
        rng.shuffle(general)
        selected = general[: min(24, len(general))]
        formula = [item for item in general if item["formula_line_count"]]
        for item in formula[: min(18, len(formula))]:
            if item not in selected:
                selected.append(item)
        for order, item in enumerate(selected, 1):
            sampled.append({"candidate_order": order, **item})
    excluded_payload = {
        "seed": SEED,
        "from_directories": list(PRIOR_DIRS) + ["evaluation/v21_2_final_unseen_v2"],
        "document_pages": [
            {"document_key": doc, "page": page} for doc, page in sorted(excluded)
        ],
    }
    pool_payload = {
        "seed": SEED,
        "collection": "petroleum_knowledge",
        "collection_count": collection.count(),
        "document_count": len(docs),
        "eligible_page_count": sum(map(len, eligible.values())),
        "sampled_page_count": len(sampled),
        "candidates": sampled,
    }
    (HERE / "excluded_sources.json").write_text(
        json.dumps(excluded_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (HERE / "source_pool.json").write_text(
        json.dumps(pool_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "excluded_pages": len(excluded),
                "eligible_pages": pool_payload["eligible_page_count"],
                "sampled_pages": len(sampled),
                "sampled_by_document": {doc: sum(item["document"] == doc for item in sampled) for doc in sorted(docs)},
                "sampled_formula_pages": sum(bool(item["formula_line_count"]) for item in sampled),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
