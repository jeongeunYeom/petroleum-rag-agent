"""Read-only checks for a staged full-PDF knowledge-base rebuild."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

import fitz

from app.core.config import Settings
from app.services.research_agent import ResearchAgent
from app.services.vector_store import VectorStore
from scripts.reingest_kb_baseline import db_rows, write_json


FORMATION_ID = "d3d33e53ea2478fe3729bba7019d8604095c5b6c2c2d3dc0bd7e9608a9931ebb"
SANITY = (
    ("Heriot-Watt_University_-_Well_Test_Analysis.pdf", "radial flow layered reservoir total flow rate permeability", 75),
    ("Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf", "membrane efficiency water activity mud chemistry delta P wellbore failure", 80),
    ("Heriot-Watt_University_-_Production_Technology_I.pdf", "flowing wells laminar turbulent flow transition", 75),
    ("Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_III.pdf", "crude oil emulsions viscosity temperature treating equipment", 75),
    ("Heriot-Watt_University_-_Reservoir_Simulation.pdf", "permeability tensor diagonal velocity components", 75),
    ("Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_VII.pdf", "SPE Symbols Standard quantity symbols dimensions", 110),
    ("Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf", "CSP technology time lapse seismic fluid movement spatial resolution", 75),
    ("Heriot-Watt_University_-_Production_Technology_II.pdf", "artificial lift selection Vogel curve well drawdown production increase", 75),
    ("Heriot-Watt_University_-_Drilling_Engineering.pdf", "hydrostatic pressure P 0.052 MW TVD mud weight", 75),
    ("Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_I.pdf", "coordinate transformation eigenvectors matrix reservoir", 75),
    ("Heriot_Watt_University_-_Formation_Evaluation.pdf", "water saturation Rw Rwa square root relationship", 171),
    ("Heriot-Watt University - Reservoir Engineering.pdf", "API gravity specific gravity 141.5 131.5", 90),
)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    source, stage, backup, out = (
        args.source.resolve(), args.stage.resolve(), args.backup.resolve(), args.report_dir.resolve()
    )
    inventory = json.loads((out / "document_inventory.json").read_text(encoding="utf-8"))
    progress = json.loads((out / "ingestion_progress.json").read_text(encoding="utf-8"))
    old_by_name = {item["filename"]: item for item in inventory["documents"]}
    old_ids, old_meta, old_texts = db_rows(source)
    ids, metadatas, texts = db_rows(stage)
    by_doc: dict[str, Counter] = defaultdict(Counter)
    by_page: dict[tuple[str, int], list[tuple[str, dict, str]]] = defaultdict(list)
    for chunk_id, metadata, text in zip(ids, metadatas, texts):
        metadata = metadata or {}
        document = str(metadata.get("document") or "")
        by_doc[document]["total"] += 1
        by_doc[document][str(metadata.get("chunk_type") or "text")] += 1
        if metadata.get("chunk_type") == "equation":
            by_doc[document]["verified_equation" if "equation_verified: true" in text.lower()
                             else "unverified_equation"] += 1
        by_page[(str(metadata.get("document_id") or ""), int(metadata.get("page") or 0))].append(
            (chunk_id, metadata, text)
        )

    comparison = []
    for name, old in old_by_name.items():
        new = by_doc[name]
        record_path = stage / "metadata" / f"{old['sha256']}.json"
        record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
        candidates = []
        candidate_dir = stage / "figure_candidates" / old["sha256"]
        for path in candidate_dir.glob("*.json") if candidate_dir.exists() else ():
            try:
                candidates.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        candidate_statuses = Counter(str(item.get("candidate_status") or "unknown") for item in candidates)
        vision_inputs = Counter(str(item.get("analysis_input_sha256")) for item in candidates
                                if item.get("analysis_input_sha256") and item.get("vision_call_count"))
        warning_reasons = Counter(
            str(reason)
            for item in candidates
            for reason in (
                (item.get("manual_review_reasons") if isinstance(item.get("manual_review_reasons"), list) else [])
                + (item.get("validation_errors") if isinstance(item.get("validation_errors"), list) else [])
            )
        )
        comparison.append({
            "document": name,
            "old_chunks": old["current_chunk_count"],
            "old_text": old["text_chunks"],
            "old_equation": old["equation_chunks"],
            "old_figure": old["figure_chunks"],
            "new_chunks": new["total"],
            "new_text": new["text"],
            "new_equation": new["equation"],
            "verified_equation_chunks": new["verified_equation"],
            "unverified_equation_chunks": new["unverified_equation"],
            "new_figure": new["figure"],
            "record_chunks_match": record.get("chunks") == new["total"],
            "ingestion_version": record.get("ingestion_version"),
            "figure_analysis_enabled": record.get("figure_analysis_enabled"),
            "figure_valid": record.get("figures_valid"),
            "figure_review_required": record.get("figures_review_required"),
            "equation_valid": record.get("equations_valid"),
            "equation_review_required": record.get("equations_review_required"),
            "candidate_statuses": dict(candidate_statuses),
            "repeated_vision_input_hashes": sum(count > 1 for count in vision_inputs.values()),
            "warning_reasons": dict(warning_reasons.most_common(15)),
        })
    write_json(out / "before_after.json", {"documents": comparison,
                                          "old_total": len(old_ids), "new_total": len(ids)})

    checks = (
        (FORMATION_ID, 28, ("q", "k", "mu"), "Darcy equation"),
        (FORMATION_ID, 171, ("s_w", "r_w", "r_wa", "sqrt"), "water saturation relationship"),
        (FORMATION_ID, 172, ("0.08", "0.6", "ohm"), "Rwa numerical example"),
        (old_by_name["Heriot-Watt University - Reservoir Engineering.pdf"]["sha256"], 90,
         ("api", "141.5", "131.5", "sg"), "API gravity"),
        (old_by_name["Heriot-Watt_University_-_Drilling_Engineering.pdf"]["sha256"], 75,
         ("0.052", "mw", "tvd"), "hydrostatic pressure"),
        (old_by_name["Heriot-Watt_University_-_Well_Test_Analysis.pdf"]["sha256"], 75,
         ("q", "k", "mu"), "radial flow"),
        (old_by_name["Heriot-Watt_University_-_Reservoir_Simulation.pdf"]["sha256"], 75,
         ("k", "p", "mu"), "tensor Darcy velocity"),
        (old_by_name["Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_I.pdf"]["sha256"], 75,
         ("a", "k"), "coordinate transformation"),
        (old_by_name["Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf"]["sha256"], 80,
         ("p", "em", "ln"), "mud chemistry membrane efficiency"),
    )
    equations = []
    for digest, page, terms, label in checks:
        chunks = by_page[(digest, page)]
        combined = "\n".join(text for _, _, text in chunks)
        normalized = re.sub(r"\s+", "", combined.lower()).replace("μ", "mu").replace("µ", "mu")
        terms_present = {term: term in normalized for term in terms}
        equation_chunks = [
            {"id": chunk_id, "text_prefix": text[:700], "verified": "equation_verified: true" in text.lower()}
            for chunk_id, metadata, text in chunks if metadata.get("chunk_type") == "equation"
        ]
        equations.append({"label": label, "document_id": digest, "page": page,
                          "terms_present": terms_present, "equation_chunks": equation_chunks,
                          "text_chunk_count": sum(metadata.get("chunk_type") == "text" for _, metadata, _ in chunks),
                          "text_prefix": combined[:1000]})
    write_json(out / "equation_audit.json", {"checks": equations})

    figures = []
    for document, counter in by_doc.items():
        rows = [(chunk_id, metadata, text) for chunk_id, metadata, text in zip(ids, metadatas, texts)
                if metadata and metadata.get("document") == document and metadata.get("chunk_type") == "figure"]
        captioned = [row for row in rows if "source_caption_verified: true" in row[2].lower()]
        selected = (captioned or rows)[:3]
        if document == "Heriot_Watt_University_-_Formation_Evaluation.pdf":
            figure_four = [row for row in rows if row[1].get("page") == 172]
            selected = (figure_four + [row for row in selected if row not in figure_four])[:3]
        for chunk_id, metadata, text in selected:
            image_match = re.search(r"(?im)^image_path:\s*(.+)$", text)
            image_path = Path(image_match.group(1).strip()) if image_match else None
            note_page = re.search(r"(?im)^page_number:\s*(\d+)", text)
            caption = re.search(r"(?im)^source_caption:\s*(.*)$", text)
            figures.append({
                "id": chunk_id, "document": document, "page": metadata.get("page"),
                "note_page": int(note_page.group(1)) if note_page else None,
                "page_match": bool(note_page and int(note_page.group(1)) == metadata.get("page")),
                "source_caption": caption.group(1) if caption else None,
                "image_path": str(image_path) if image_path else None,
                "image_exists": bool(image_path and image_path.is_file()),
                "page_context_prefix": " ".join(
                    part[:200] for _, item_meta, part in by_page[
                        (str(metadata.get("document_id") or ""), int(metadata.get("page") or 0))
                    ] if item_meta.get("chunk_type") == "text"
                )[:400],
                "note_prefix": text[:800],
            })
        if not selected:
            figures.append({"document": document, "figure_chunks": 0,
                            "review_required": next((r["figure_review_required"] for r in comparison
                                                     if r["document"] == document), 0)})
    write_json(out / "figure_audit.json", {"samples": figures})

    settings = replace(Settings(), data_dir=stage, retrieval_mode="hybrid")
    store = VectorStore(settings)
    agent = ResearchAgent(settings, store, ollama=None)
    retrieval = []
    for document, query, page in SANITY:
        hits = agent.search_knowledge_base(query, 5)
        with fitz.open(old_by_name[document]["raw_path"]) as pdf:
            source_text = pdf[page - 1].get_text("text", sort=True)
        page_rows = by_page[(old_by_name[document]["sha256"], page)]
        indexed_body = "\n".join(text for _, metadata, text in page_rows
                                 if metadata.get("chunk_type") == "text")
        top = [{"rank": rank, "document": (hit.get("metadata") or {}).get("document"),
                "page": (hit.get("metadata") or {}).get("page"), "id": hit.get("id"),
                "chunk_type": (hit.get("metadata") or {}).get("chunk_type")}
               for rank, hit in enumerate(hits, start=1)]
        retrieval.append({"query": query, "expected_document": document,
                          "expected_page": page, "top5": top,
                          "source_text_prefix": source_text[:500],
                          "indexed_text_prefix": indexed_body[:500],
                          "source_characters": len(source_text),
                          "indexed_body_characters": len(indexed_body),
                          "document_top5": any(hit["document"] == document for hit in top),
                          "page_top5": any(hit["document"] == document and hit["page"] == page for hit in top)})
        print(f"[RETRIEVAL] {document}: doc={retrieval[-1]['document_top5']} page={retrieval[-1]['page_top5']}", flush=True)
    write_json(out / "retrieval_sanity.json", {"checks": retrieval})

    ready = (
        len(comparison) == 12
        and len(ids) > 0
        and all(row["record_chunks_match"] and row["ingestion_version"] == "kb-ingestion-v9"
                and row["figure_analysis_enabled"] is True for row in comparison)
        and all(all(item["terms_present"].values()) for item in equations[:3])
        and all(item.get("page_match") and item.get("image_exists") for item in figures if item.get("id"))
        and all(item["document_top5"] for item in retrieval)
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    manifest = {
        "baseline": "full-reingestion-v1",
        "status": "STAGED_AUTOMATED_PASS_MANUAL_QA_PENDING" if ready else "STAGED_BLOCKED",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "product_git_sha": sha, "ingestion_version": "kb-ingestion-v9",
        "analyze_figures": True, "embedding_model": settings.embedding_model,
        "collection_name": settings.collection_name,
        "source_data_dir": str(source), "staged_data_dir": str(stage), "backup_db_dir": str(backup),
        "document_count": len(by_doc), "chunk_count": len(ids),
        "document_hashes": {name: row["sha256"] for name, row in old_by_name.items()},
        "per_document": comparison,
        "retrieval_document_top5_count": sum(item["document_top5"] for item in retrieval),
        "retrieval_page_top5_count": sum(item["page_top5"] for item in retrieval),
        "production_switched": False,
    }
    write_json(out / "manifest.json", manifest)
    print(f"[VERIFY] {manifest['status']}: {len(by_doc)} documents, {len(ids)} chunks", flush=True)


if __name__ == "__main__":
    main()
