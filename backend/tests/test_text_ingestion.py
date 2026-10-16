import asyncio
from pathlib import Path

import fitz

from app.core.config import Settings
from app.models.schemas import DocumentRecord
from app.services.document_processor import DocumentProcessor, INGESTION_VERSION


def _record(
    version: str | None,
    *,
    figure_analysis_enabled: bool | None = True,
) -> DocumentRecord:
    return DocumentRecord(
        document_id="a" * 64,
        filename="book.pdf",
        sha256="a" * 64,
        status="processed",
        ingestion_version=version,
        figure_analysis_enabled=figure_analysis_enabled,
    )


def test_text_extraction_quality_penalizes_replacement_characters():
    clean = DocumentProcessor.text_extraction_quality(
        "Archie equation relates porosity, resistivity, and water saturation."
    )
    damaged = DocumentProcessor.text_extraction_quality(
        "Archie equa��� porosity � resistivity."
    )

    assert clean["score"] > damaged["score"]
    assert damaged["replacement_chars"] == 4


def test_select_page_text_prefers_cleaner_candidate():
    selected, extractor, diagnostics = DocumentProcessor.select_page_text(
        "R�� = ��",
        "Rw = water resistivity\nRt = true formation resistivity",
    )

    assert extractor == "pdfplumber_layout"
    assert "water resistivity" in selected
    assert (
        diagnostics["pdfplumber_layout"]["score"]
        > diagnostics["pymupdf_sorted"]["score"]
    )


def test_select_page_text_prefers_pymupdf_on_equal_quality():
    selected, extractor, _ = DocumentProcessor.select_page_text(
        "same text",
        "same text",
    )

    assert selected == "same text"
    assert extractor == "pymupdf_sorted"


def test_ingestion_version_marks_old_records_stale():
    assert DocumentProcessor.is_current_record(_record(INGESTION_VERSION))
    assert not DocumentProcessor.is_current_record(_record(None))
    assert not DocumentProcessor.is_current_record(_record("legacy"))


def test_text_only_record_is_reprocessed_when_figure_analysis_is_requested():
    text_only = _record(
        INGESTION_VERSION,
        figure_analysis_enabled=False,
    )

    assert DocumentProcessor.is_current_record(
        text_only,
        analyze_figures=False,
    )
    assert not DocumentProcessor.is_current_record(
        text_only,
        analyze_figures=True,
    )



def _settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    settings = Settings(
        data_dir=data_dir,
        agent_workspace_dir=tmp_path / "workspace",
    )
    for directory in [
        settings.raw_dir,
        settings.extracted_dir,
        settings.figures_dir,
        settings.figure_notes_dir,
        settings.figure_candidates_dir,
        settings.figure_analysis_inputs_dir,
        settings.metadata_dir,
        settings.ontology_dir,
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    return settings


def test_extract_pdf_preserves_visual_reading_order_and_diagnostics(tmp_path: Path):
    pdf_path = tmp_path / "reading-order.pdf"
    document = fitz.open()
    page = document.new_page()

    # Deliberately insert the lower line first. Plain extraction can preserve
    # insertion order, while sort=True should recover visual top-to-bottom order.
    page.insert_text((72, 220), "BOTTOM: Rt is true formation resistivity.", fontsize=11)
    page.insert_text((72, 72), "TOP: Rw is water resistivity.", fontsize=11)
    document.save(pdf_path)
    document.close()

    processor = DocumentProcessor(_settings(tmp_path), object())
    pages, figure_count = asyncio.run(
        processor._extract_pdf(
            pdf_path,
            "b" * 64,
            analyze_figures=False,
        )
    )

    assert figure_count == 0
    assert len(pages) == 1
    text = str(pages[0]["text"])
    assert text.index("TOP:") < text.index("BOTTOM:")
    assert pages[0]["text_extractor"] in {"pymupdf_sorted", "pdfplumber_layout"}
    diagnostics = pages[0]["text_extraction_diagnostics"]
    assert "pymupdf_sorted" in diagnostics
    assert "pdfplumber_layout" in diagnostics
    assert diagnostics["pymupdf_sorted"]["characters"] > 0
