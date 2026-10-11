"""Read-only inspection of the existing Chroma source spans for benchmark authoring."""

import argparse
import re
from pathlib import Path

import chromadb


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("patterns", nargs="+")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    collection = chromadb.PersistentClient(path=str(root / "data" / "vector_db")).get_collection(
        "petroleum_knowledge"
    )
    assert collection.count() == 18976
    rows = collection.get(include=["documents", "metadatas"])
    for expression in args.patterns:
        pattern = re.compile(expression, re.I)
        print(f"\n### {expression}")
        seen = set()
        count = 0
        for text, meta in zip(rows["documents"], rows["metadatas"]):
            hit = pattern.search(text)
            key = (meta.get("document"), meta.get("page"))
            if hit is None or key in seen:
                continue
            seen.add(key)
            print(f"{meta.get('document')} p.{meta.get('page')}: "
                  + " ".join(text[max(0, hit.start()-180):hit.end()+480].split()))
            count += 1
            if count >= args.limit:
                break


if __name__ == "__main__":
    main()
