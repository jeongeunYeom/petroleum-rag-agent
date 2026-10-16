from __future__ import annotations

import re

from app.services.ontology import concept_metadata


FIGURE_NOTES_RE = re.compile(r"\[\s*extracted\s+figure\s+notes\s*\]", re.IGNORECASE)
FIGURE_BLOCK_RE = re.compile(
    r"(?im)(?:^|\n)\s*figure\s+([0-9]+[A-Za-z]?)\s*:\s*"
)


def _page_sections(text: str) -> list[tuple[str, str]]:
    """Separate ordinary page text from complete Figure Note blocks."""
    marker = FIGURE_NOTES_RE.search(text)
    if marker is None:
        return [("text", text.strip())] if text.strip() else []

    sections: list[tuple[str, str]] = []
    body = text[: marker.start()].strip()
    if body:
        sections.append(("text", body))

    figure_text = text[marker.end() :].strip()
    if not figure_text:
        return sections

    matches = list(FIGURE_BLOCK_RE.finditer(figure_text))
    marker_text = "[Extracted figure notes]"
    if not matches:
        sections.append(("figure", f"{marker_text}\n{figure_text}"))
        return sections

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(figure_text)
        block = figure_text[match.start() : end].strip()
        if block:
            sections.append(("figure", f"{marker_text}\n{block}"))
    return sections


def _preferred_cut(text: str, start: int, hard_end: int) -> int:
    """Choose a readable boundary near hard_end instead of cutting mid-token."""
    if hard_end >= len(text):
        return len(text)

    window_start = start + max(1, int((hard_end - start) * 0.55))
    window = text[window_start:hard_end]

    boundaries = (
        "\n\n",
        "\n",
        ". ",
        "? ",
        "! ",
        "; ",
        ": ",
        ", ",
        " ",
    )
    for boundary in boundaries:
        position = window.rfind(boundary)
        if position >= 0:
            cut = window_start + position + len(boundary)
            if cut > start:
                return cut
    return hard_end


def _overlap_start(text: str, chunk_start: int, chunk_end: int, overlap: int) -> int:
    if overlap <= 0:
        return chunk_end
    candidate = max(chunk_start + 1, chunk_end - overlap)
    if candidate >= chunk_end:
        return chunk_end

    # Move forward to the next natural boundary so the next chunk does not
    # begin halfway through a word or equation token.
    tail = text[candidate:chunk_end]
    matches = list(re.finditer(r"(?:\n\n|\n|(?<=[.!?;:])\s+|\s+)", tail))
    if matches:
        return min(chunk_end, candidate + matches[0].end())
    return candidate


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    value = text.strip()
    if not value:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be non-negative")

    chunks: list[str] = []
    start = 0
    while start < len(value):
        hard_end = min(start + chunk_size, len(value))
        end = _preferred_cut(value, start, hard_end)
        if end <= start:
            end = hard_end

        chunk = value[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(value):
            break

        next_start = _overlap_start(value, start, end, chunk_overlap)
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def chunk_pages(
    pages: list[dict[str, object]],
    filename: str,
    digest: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    for page in pages:
        text = str(page.get("text", "")).strip()
        if not text:
            continue

        chunk_index = 0
        for chunk_type, section_text in _page_sections(text):
            # Figure Notes are structured evidence. Keep one complete note in one
            # chunk even when it is longer than the ordinary body chunk size.
            section_chunks = (
                [section_text]
                if chunk_type == "figure"
                else _chunk_text(section_text, chunk_size, chunk_overlap)
            )
            for chunk_text in section_chunks:
                chunk_id = f"{digest}:p{page['page']}:c{chunk_index}"
                metadata = {
                    "document_id": digest,
                    "document": filename,
                    "page": page["page"],
                    "chunk_index": chunk_index,
                    "chunk_type": chunk_type,
                    "is_contents": bool(page.get("is_contents", False)),
                    "is_title_page": bool(page.get("is_title_page", False)),
                    "heading": str(page.get("heading", "")),
                    "document_type": str(page.get("document_type", "")),
                }
                metadata.update(concept_metadata(chunk_text))
                chunks.append(
                    {
                        "id": chunk_id,
                        "text": chunk_text,
                        "metadata": metadata,
                    }
                )
                chunk_index += 1
    return chunks
