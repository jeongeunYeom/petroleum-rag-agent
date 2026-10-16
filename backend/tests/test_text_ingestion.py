import asyncio
from pathlib import Path

import fitz
from PIL import Image

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


def test_select_page_text_rejects_layout_fragmentation_for_subscripts():
    pymupdf = (
        "Rwa Comparison\n"
        "Rwa = Rt / F ≈ RID / F\n"
        "Rw is water resistivity. Rwa reaches 0.6 ohm-m."
    )
    pdfplumber = (
        "R\n"
        "  wa Comparison\n"
        "R     R\n"
        " wa =  t / F ≈ R\n"
        "              ID / F\n"
        "R\n"
        " w is water resistivity. R\n"
        "                         wa reaches 0.6 ohm-m."
    )

    selected, extractor, diagnostics = DocumentProcessor.select_page_text(
        pymupdf,
        pdfplumber,
    )

    assert extractor == "pymupdf_sorted"
    assert selected == pymupdf
    assert diagnostics["pdfplumber_layout"]["lines"] > diagnostics["pymupdf_sorted"]["lines"]


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



def test_equation_regions_detect_vector_math_but_skip_plain_equations(tmp_path: Path):
    processor = DocumentProcessor(_settings(tmp_path), object())

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 120), "S_w = R_w / R_wa (8)", fontsize=12)
    page.draw_line((105, 106), (210, 106))
    page.draw_line((90, 112), (96, 118))
    page.draw_line((96, 118), (102, 102))

    risky = processor._equation_regions(page)
    assert risky
    assert "S_w" in str(risky[0]["raw_text"])
    assert int(risky[0]["vector_element_count"]) >= 1
    assert risky[0]["has_radical"] is False

    plain_document = fitz.open()
    plain_page = plain_document.new_page()
    plain_page.insert_text((72, 120), "Z = X + Y", fontsize=12)

    assert processor._equation_regions(plain_page) == []

    document.close()
    plain_document.close()


def test_equation_crop_includes_adjacent_rhs_text_block(tmp_path: Path):
    processor = DocumentProcessor(_settings(tmp_path), object())
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 120), "Rwa = Rt", fontsize=12)
    page.insert_text((140, 120), "F approx RID", fontsize=12)
    page.draw_line((120, 108), (138, 108))

    regions = processor._equation_regions(page)

    assert len(regions) == 1
    assert "RID" in regions[0]["raw_text"]
    assert regions[0]["rect"][2] > 190
    document.close()


def test_unverified_vector_equation_is_removed_from_body_chunks(tmp_path: Path):
    pdf_path = tmp_path / "radical.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 80), "Water saturation requires visual verification.")
    page.insert_text((72, 120), "Sw = Rw / Rwa (8)")
    page.draw_line((104, 108), (165, 108))
    document.save(pdf_path)
    document.close()

    processor = DocumentProcessor(_settings(tmp_path), object())
    pages, _ = asyncio.run(processor._extract_pdf(pdf_path, "c" * 64, False))

    assert "Water saturation requires visual verification" in pages[0]["text"]
    assert "Sw = Rw / Rwa" not in pages[0]["text"]
    assert "[Visual equation awaiting verification]" in pages[0]["text"]



def test_source_figure_caption_uses_image_geometry_and_preserves_source_text(tmp_path: Path):
    image_path = tmp_path / "figure.png"
    Image.new("RGB", (600, 400), "white").save(image_path)

    document = fitz.open()
    page = document.new_page()
    xref = page.insert_image(
        fitz.Rect(120, 100, 480, 340),
        filename=str(image_path),
    )
    page.insert_textbox(
        fitz.Rect(90, 355, 520, 395),
        "Figure 19 (Upper) - Inasion and Resistivity Profile in water bearing zone.",
        fontsize=9,
    )

    matched = DocumentProcessor._source_figure_caption(page, xref)

    assert matched is not None
    assert matched["figure_number"] == "19"
    assert matched["caption_position"] == "below"
    assert "Inasion" in str(matched["source_caption"])
    document.close()


def test_source_figure_caption_ignores_distant_unrelated_caption(tmp_path: Path):
    image_path = tmp_path / "logo.png"
    Image.new("RGB", (300, 160), "white").save(image_path)

    document = fitz.open()
    page = document.new_page()
    xref = page.insert_image(
        fitz.Rect(20, 20, 120, 75),
        filename=str(image_path),
    )
    page.insert_textbox(
        fitz.Rect(80, 500, 520, 540),
        "Figure 7 Deep reservoir response.",
        fontsize=9,
    )

    assert DocumentProcessor._source_figure_caption(page, xref) is None
    document.close()
