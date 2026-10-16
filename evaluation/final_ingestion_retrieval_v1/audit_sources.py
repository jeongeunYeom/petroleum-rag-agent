"""Read original PDFs and the existing Chroma collection without ingestion."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import chromadb
import fitz


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--rubric", type=Path, default=Path(__file__).with_name("rubric.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("source_audit.json"))
    args = parser.parse_args()
    tasks = json.loads(args.rubric.read_text(encoding="utf-8"))["tasks"]
    collection = chromadb.PersistentClient(path=str(args.data_dir / "vector_db")).get_collection(
        "petroleum_knowledge"
    )
    by_source = {}
    for task in tasks:
        if task["document"] is None:
            continue
        documents = task["document"].split("; ")
        pages = task["page"] if isinstance(task["page"], list) else [task["page"]]
        assert len(documents) == len(pages), task["question_id"]
        for name, page in zip(documents, pages):
            key = f"{name}:p{page}"
            if key in by_source:
                by_source[key]["question_ids"].append(task["question_id"])
                continue
            matching = [p for p in (args.data_dir / "raw").glob("*.pdf") if p.name.endswith("_" + name)]
            if len(matching) != 1:
                raise RuntimeError(f"Source PDF not unique: {key} ({len(matching)})")
            pdf_path = matching[0]
            pdf = fitz.open(pdf_path)
            if not 1 <= page <= len(pdf):
                raise RuntimeError(f"Source page out of bounds: {key}")
            page_text = pdf[page - 1].get_text()
            hits = collection.get(
                where={"$and": [{"document": name}, {"page": page}]},
                include=["metadatas"],
            )
            figures = [
                {"filename": path.name, "sha256": sha256(path.read_bytes())}
                for path in (args.data_dir / "figures").glob(pdf_path.name[:64] + f"_p{page}_fig*")
            ]
            by_source[key] = {
                "document": name,
                "page": page,
                "raw_pdf_filename": pdf_path.name,
                "raw_pdf_sha256_from_filename": pdf_path.name[:64],
                "pdf_text_sha256": sha256(page_text.encode("utf-8")),
                "pdf_text_character_count": len(page_text),
                "chroma_chunk_ids": hits["ids"],
                "chroma_chunk_count": len(hits["ids"]),
                "figure_images": figures,
                "question_ids": [task["question_id"]],
            }
    output = {
        "collection": collection.name,
        "collection_count": collection.count(),
        "source_audit_method": "original PDF page text and exact document/page Chroma metadata lookup; no retrieval run and no reingestion",
        "sources": list(by_source.values()),
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in output["sources"]:
        print(row["document"], row["page"], "chunks", row["chroma_chunk_count"], "figures", len(row["figure_images"]))


if __name__ == "__main__":
    main()
