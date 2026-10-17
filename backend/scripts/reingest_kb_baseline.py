"""Audit and rebuild the production PDFs in an isolated data directory.

The source data directory is read-only here. The replacement is never activated
by this script; activation requires a separate validation decision.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

import chromadb
import fitz

from app.core.config import Settings
from app.services.document_processor import DocumentProcessor, delete_document_derived_files
from app.services.ollama import OllamaClient
from app.services.vector_store import VectorStore


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def pdf_files(data_dir: Path) -> list[Path]:
    return sorted((data_dir / "raw").glob("*.pdf"))


def db_rows(data_dir: Path) -> tuple[list[str], list[dict], list[str]]:
    client = chromadb.PersistentClient(path=str(data_dir / "vector_db"))
    collection = client.get_collection("petroleum_knowledge")
    result = collection.get(include=["metadatas", "documents"])
    return result["ids"], result["metadatas"], result["documents"]


def inventory(source: Path, report_dir: Path) -> list[dict]:
    ids, metadatas, documents = db_rows(source)
    counts: dict[str, Counter] = defaultdict(Counter)
    names: dict[str, set[str]] = defaultdict(set)
    for metadata, text in zip(metadatas, documents):
        metadata = metadata or {}
        digest = str(metadata.get("document_id") or "")
        counts[digest]["total"] += 1
        kind = str(metadata.get("chunk_type") or "text")
        counts[digest][kind] += 1
        if "[Equation Note Metadata]" in text:
            counts[digest]["equation_marker"] += 1
        if "[Figure Note Metadata]" in text:
            counts[digest]["figure_marker"] += 1
        names[digest].add(str(metadata.get("document") or ""))

    rows = []
    for pdf in pdf_files(source):
        with pdf.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        record_path = source / "metadata" / f"{digest}.json"
        record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
        with fitz.open(pdf) as document:
            pages = len(document)
        rows.append({
            "filename": pdf.name[65:] if pdf.name.startswith(f"{digest}_") else pdf.name,
            "raw_path": str(pdf),
            "sha256": digest,
            "file_bytes": pdf.stat().st_size,
            "pages": pages,
            "current_document_id": digest,
            "db_document_names": sorted(names[digest]),
            "current_chunk_count": counts[digest]["total"],
            "text_chunks": counts[digest]["text"],
            "equation_chunks": counts[digest]["equation"],
            "figure_chunks": counts[digest]["figure"],
            "inline_equation_markers": counts[digest]["equation_marker"],
            "inline_figure_markers": counts[digest]["figure_marker"],
            "ingestion_version": record.get("ingestion_version"),
            "figure_analysis_enabled": record.get("figure_analysis_enabled"),
            "record_chunks": record.get("chunks"),
            "digest_matches_filename": pdf.name.startswith(f"{digest}_"),
        })
    raw_ids = {row["sha256"] for row in rows}
    anomalies = {
        "raw_without_db": sorted(raw_ids - set(counts)),
        "db_without_raw": sorted(set(counts) - raw_ids),
        "duplicate_hashes": sorted(k for k, n in Counter(row["sha256"] for row in rows).items() if n > 1),
        "same_name_different_digest": sorted(
            name for name, n in Counter(row["filename"] for row in rows).items() if n > 1
        ),
        "filename_digest_mismatch": [row["filename"] for row in rows if not row["digest_matches_filename"]],
        "legacy_records": [row["filename"] for row in rows if row["ingestion_version"] != "kb-ingestion-v9"],
    }
    output = {
        "source_data_dir": str(source),
        "collection": "petroleum_knowledge",
        "total_chunks": len(ids),
        "document_count": len(counts),
        "pdf_count": len(rows),
        "documents": rows,
        "anomalies": anomalies,
    }
    write_json(report_dir / "document_inventory.json", output)
    return rows


def legacy_audit(source: Path, report_dir: Path, rows: list[dict]) -> None:
    ids, metadatas, documents = db_rows(source)
    by_page: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for chunk_id, metadata, text in zip(ids, metadatas, documents):
        metadata = metadata or {}
        by_page[(str(metadata.get("document_id") or ""), int(metadata.get("page") or 0))].append({
            "id": chunk_id, "metadata": metadata, "text": text,
        })
    targets = ("Well_Test_Analysis", "Drilling_Engineering", "Reservoir Engineering",
               "Reservoir_Simulation", "Volume_I.", "Volume_II.", "Volume_V",
               "Volume V (1)")
    samples = []
    for row in rows:
        if not any(target in row["filename"] for target in targets):
            continue
        extracted_path = source / "extracted" / f"{row['sha256']}.json"
        old_pages = {
            int(page["page"]): str(page.get("text") or "")
            for page in json.loads(extracted_path.read_text(encoding="utf-8"))["pages"]
        }
        with fitz.open(row["raw_path"]) as pdf:
            eligible = list(range(min(75, len(pdf)), len(pdf) + 1))
            body = next((p for p in eligible if len(old_pages.get(p, "")) > 500
                         and "=" not in old_pages.get(p, "")), eligible[0])
            equation = next((p for p in eligible if p != body and
                             re.search(r"[A-Za-z0-9)]\s*=\s*[A-Za-z0-9(]", old_pages.get(p, ""))),
                            next((p for p in eligible if p != body and "=" in old_pages.get(p, "")), body))
            figure = next((p for p in eligible if p not in {body, equation} and
                           re.search(r"(?i)\bfig(?:ure)?[. ]+\d", old_pages.get(p, ""))
                           and pdf[p - 1].get_images(full=True)),
                          next((p for p in eligible if p not in {body, equation} and
                                pdf[p - 1].get_images(full=True)), body))
            for kind, page_number in (("body", body), ("equation", equation), ("figure", figure)):
                page = pdf[page_number - 1]
                raw = page.get_text("text", sort=True)
                extracted = old_pages.get(page_number, "")
                chunks = by_page[(row["sha256"], page_number)]
                stored = "\n".join(chunk["text"] for chunk in chunks)
                sample = {
                    "document": row["filename"], "document_id": row["sha256"],
                    "type": kind, "page": page_number,
                    "pdf_image_count": len(page.get_images(full=True)),
                    "pymupdf_text_prefix": raw[:1200],
                    "extracted_text_prefix": extracted[:1200],
                    "chroma_text_prefix": stored[:1200],
                    "pymupdf_characters": len(raw), "extracted_characters": len(extracted),
                    "chroma_characters": len(stored), "chroma_chunk_count": len(chunks),
                    "page_metadata_correct": all(c["metadata"].get("page") == page_number for c in chunks),
                    "equation_chunks": sum(c["metadata"].get("chunk_type") == "equation" for c in chunks),
                    "figure_chunks": sum(c["metadata"].get("chunk_type") == "figure" for c in chunks),
                    "extracted_equation_lines": re.findall(r"(?m)^.{0,60}=.{1,90}$", extracted)[:5],
                }
                samples.append(sample)
    write_json(report_dir / "legacy_audit.json", {"samples": samples})


async def ingest(source: Path, stage: Path, report_dir: Path, rows: list[dict], force_ids: set[str]) -> None:
    if stage.resolve() == source.resolve():
        raise ValueError("Staging data directory must differ from production data directory")
    unknown_ids = force_ids - {row["sha256"] for row in rows}
    if unknown_ids:
        raise ValueError(f"Unknown document IDs selected for staged reprocessing: {sorted(unknown_ids)}")
    for name in ("raw", "extracted", "figures", "figure_notes", "figure_candidates",
                 "figure_analysis_inputs", "vector_db", "metadata", "ontology"):
        (stage / name).mkdir(parents=True, exist_ok=True)
    settings = replace(Settings(), data_dir=stage)
    ollama = OllamaClient(settings)
    store = VectorStore(settings)
    progress_path = report_dir / "ingestion_progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {"documents": []}
    completed = {entry["sha256"] for entry in progress["documents"] if entry.get("status") == "completed"}
    for index, row in enumerate(sorted(rows, key=lambda item: item["pages"]), start=1):
            digest = row["sha256"]
            if digest in force_ids:
                store.delete_document(digest)
                delete_document_derived_files(settings, digest)
                completed.discard(digest)
            if digest in completed:
                count = len(store.collection.get(where={"document_id": digest})["ids"])
                if count == next(entry["chunks"] for entry in progress["documents"] if entry["sha256"] == digest):
                    print(f"[SKIP verified] {index}/{len(rows)} {row['filename']}", flush=True)
                    continue
                raise RuntimeError(f"Incomplete staged record for {row['filename']}: {count} chunks")
            target = stage / "raw" / Path(row["raw_path"]).name
            if not target.exists():
                shutil.copy2(row["raw_path"], target)
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise RuntimeError(f"Staging raw PDF hash mismatch: {target}")
            print(f"[INGEST] {index}/{len(rows)} {row['filename']}", flush=True)
            started = time.monotonic()
            processor = DocumentProcessor(settings, ollama)
            try:
                record, chunks = await processor.extract(target, digest, analyze_figures=True)
                store.add_chunks(chunks)
                actual = len(store.collection.get(where={"document_id": digest})["ids"])
                if actual != len(chunks):
                    raise RuntimeError(f"Chroma count mismatch: {actual} != {len(chunks)}")
                entry = {
                    "sha256": digest, "filename": row["filename"], "status": "completed",
                    "seconds": round(time.monotonic() - started, 2), "pages": record.pages,
                    "chunks": actual, "figures": record.figures,
                    "figures_analyzed": record.figures_analyzed,
                    "figures_valid": record.figures_valid,
                    "figures_review_required": record.figures_review_required,
                    "figures_failed": record.figures_failed,
                    "figures_ignored": record.figures_ignored,
                    "figure_vision_calls": record.figure_vision_calls,
                    "equations_detected": record.equations_detected,
                    "equations_valid": record.equations_valid,
                    "equations_review_required": record.equations_review_required,
                    "equations_failed": record.equations_failed,
                    "equation_vision_calls": record.equation_vision_calls,
                    "text_chunks": sum(c["metadata"].get("chunk_type") == "text" for c in chunks),
                    "equation_chunks": sum(c["metadata"].get("chunk_type") == "equation" for c in chunks),
                    "figure_chunks": sum(c["metadata"].get("chunk_type") == "figure" for c in chunks),
                }
            except Exception as exc:
                entry = {"sha256": digest, "filename": row["filename"], "status": "failed",
                         "seconds": round(time.monotonic() - started, 2), "error": f"{type(exc).__name__}: {exc}"}
                progress["documents"] = [e for e in progress["documents"] if e["sha256"] != digest] + [entry]
                write_json(progress_path, progress)
                raise
            progress["documents"] = [e for e in progress["documents"] if e["sha256"] != digest] + [entry]
            write_json(progress_path, progress)
            print(f"[DONE] {row['filename']}: {actual} chunks in {entry['seconds']}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("inventory", "audit", "ingest"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--stage", type=Path)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--force-id", action="append", default=[], help="Reprocess this staged PDF even if complete")
    args = parser.parse_args()
    source = args.source.resolve()
    report_dir = args.report_dir.resolve()
    rows = inventory(source, report_dir)
    if args.phase == "audit":
        legacy_audit(source, report_dir, rows)
    if args.phase == "ingest":
        if not args.stage:
            parser.error("--stage is required for ingestion")
        asyncio.run(ingest(source, args.stage.resolve(), report_dir, rows, set(args.force_id)))


if __name__ == "__main__":
    main()
