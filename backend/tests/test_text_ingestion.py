from app.models.schemas import DocumentRecord
from app.services.document_processor import DocumentProcessor, INGESTION_VERSION


def _record(version: str | None) -> DocumentRecord:
    return DocumentRecord(
        document_id="a" * 64,
        filename="book.pdf",
        sha256="a" * 64,
        status="processed",
        ingestion_version=version,
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
