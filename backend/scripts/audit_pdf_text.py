#!/usr/bin/env python3
"""Compare PDF text extractors on selected pages without modifying the knowledge base."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz

from app.services.document_processor import DocumentProcessor


def parse_pages(value: str, total_pages: int) -> list[int]:
    if not value.strip():
        return list(range(1, total_pages + 1))
    pages: list[int] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        page = int(token)
        if page < 1 or page > total_pages:
            raise ValueError(f"Page {page} is outside 1..{total_pages}")
        pages.append(page)
    return list(dict.fromkeys(pages))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--pages",
        default="",
        help="Comma-separated PDF page numbers. Empty means all pages.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON report path.",
    )
    parser.add_argument(
        "--compare-pdfplumber",
        action="store_true",
        help=(
            "Opt in to pdfplumber comparison. Some malformed-xref PDFs can make "
            "pdfminer fallback scanning very slow, so this is disabled by default."
        ),
    )
    args = parser.parse_args()

    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")

    report: dict[str, object] = {
        "pdf": str(pdf_path),
        "pages": [],
    }

    plumber_doc = None
    if args.compare_pdfplumber:
        import pdfplumber

        plumber_doc = pdfplumber.open(pdf_path)

    try:
        with fitz.open(pdf_path) as pymupdf_doc:
            wanted = parse_pages(args.pages, len(pymupdf_doc))
            for page_number in wanted:
                index = page_number - 1
                page = pymupdf_doc[index]
                pymupdf_text = (page.get_text("text", sort=True) or "").strip()
                plumber_text = ""
                if plumber_doc is not None:
                    plumber_text = (
                        plumber_doc.pages[index].extract_text(layout=True) or ""
                    ).strip()
                selected, extractor, diagnostics = DocumentProcessor.select_page_text(
                    pymupdf_text,
                    plumber_text,
                )

                entry = {
                    "page": page_number,
                    "selected_extractor": extractor,
                    "diagnostics": diagnostics,
                    "selected_text": selected,
                    "pymupdf_sorted_text": pymupdf_text,
                    "pdfplumber_layout_text": plumber_text,
                }
                report["pages"].append(entry)
                print(
                    f"p{page_number}: {extractor} "
                    f"(PyMuPDF={diagnostics['pymupdf_sorted']['score']:.0f}, "
                    f"pdfplumber={diagnostics['pdfplumber_layout']['score']:.0f})"
                )
    finally:
        if plumber_doc is not None:
            plumber_doc.close()

    output = args.output or pdf_path.with_name(f"{pdf_path.stem}_text_audit.json")
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
