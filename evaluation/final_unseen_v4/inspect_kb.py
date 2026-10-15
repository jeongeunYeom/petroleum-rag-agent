"""Read-only source-span inspection for V4 gold construction (never ingests)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("terms", nargs="*")
    parser.add_argument("--document", default="")
    parser.add_argument("--page", type=int)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    import chromadb

    sqlite = Path(os.environ["DATA_DIR"]).resolve() / "vector_db" / "chroma.sqlite3"
    if not sqlite.is_file():
        raise RuntimeError("Existing KB absent; refusing to create one")
    collection = chromadb.PersistentClient(path=str(sqlite.parent)).get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        raise RuntimeError("Existing KB count differs from frozen precheck")
    rows = collection.get(include=["documents", "metadatas"])
    hits = []
    for chunk_id, passage, metadata in zip(rows["ids"], rows["documents"], rows["metadatas"]):
        metadata = metadata or {}
        name = str(metadata.get("document") or "")
        page = metadata.get("page")
        if args.document and args.document.casefold() not in name.casefold():
            continue
        if args.page is not None and str(page) != str(args.page):
            continue
        lowered = passage.casefold()
        score = sum(1 for term in args.terms if term.casefold() in lowered)
        if args.terms and score == 0:
            continue
        hits.append((score, {"id": chunk_id, "document": name, "page": page,
                             "text": passage[:1800]}))
    hits.sort(key=lambda item: (-item[0], item[1]["document"], str(item[1]["page"])))
    print(json.dumps({"total_hits": len(hits), "hits": [row for _, row in hits[:args.limit]]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
