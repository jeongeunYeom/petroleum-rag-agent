from __future__ import annotations

import re

from app.services.ontology import concept_metadata


STRUCTURED_MARKER_RE = re.compile(
    r"\[\s*extracted\s+(figure|equation)\s+notes\s*\]",
    re.IGNORECASE,
)
FIGURE_BLOCK_RE = re.compile(
    r"(?im)(?:^|\n)\s*figure\s+([0-9]+[A-Za-z]?)\s*:\s*"
    r"(?=\[figure note metadata\])"
)
EQUATION_BLOCK_RE = re.compile(
    r"(?im)(?:^|\n)\s*equation\s+([0-9]+[A-Za-z]?)\s*:\s*"
    r"(?=\[equation note metadata\])"
)


def _structured_blocks(
    chunk_type: str,
    value: str,
) -> list[tuple[str, str]]:
    value = value.strip()
    if not value:
        return []

    if chunk_type == "figure":
        block_re = FIGURE_BLOCK_RE
        marker_text = "[Extracted figure notes]"
    elif chunk_type == "equation":
        block_re = EQUATION_BLOCK_RE
        marker_text = "[Extracted equation notes]"
    else:
        return [(chunk_type, value)]

    matches = list(block_re.finditer(value))
    if not matches:
        return [(chunk_type, f"{marker_text}\n{value}")]

    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        block = value[match.start() : end].strip()
        if block:
            blocks.append((chunk_type, f"{marker_text}\n{block}"))
    return blocks


def _page_sections(text: str) -> list[tuple[str, str]]:
    """Separate body text, Figure Notes, and verified Equation Notes."""
    markers = list(STRUCTURED_MARKER_RE.finditer(text))
    if not markers:
        return [("text", text.strip())] if text.strip() else []

    sections: list[tuple[str, str]] = []
    cursor = 0
    for index, marker in enumerate(markers):
        body = text[cursor:marker.start()].strip()
        if body:
            sections.append(("text", body))

        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        value = text[marker.end():end].strip()
        chunk_type = marker.group(1).casefold()
        sections.extend(_structured_blocks(chunk_type, value))
        cursor = end

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

    boundary_patterns = (
        r"\n\n",
        r"\n",
        r"(?<=[.!?;:])\s+",
        r"\s+",
    )

    # Prefer structural boundaries even when they create slightly more overlap.
    # In particular, a newline is safer than beginning halfway through an
    # equation or variable definition.
    before = text[chunk_start:candidate]
    for boundary_re in boundary_patterns:
        matches = list(re.finditer(boundary_re, before))
        if matches:
            return chunk_start + matches[-1].end()

    # For a very long token/equation with no earlier boundary, move forward
    # rather than starting in the middle of that token.
    after = text[candidate:chunk_end]
    for boundary_re in boundary_patterns:
        match = re.search(boundary_re, after)
        if match:
            return min(chunk_end, candidate + match.end())
    return chunk_end


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
            # Structured visual evidence must remain whole so a verified equation
            # or Figure Note cannot be separated from its metadata.
            section_chunks = (
                [section_text]
                if chunk_type in {"figure", "equation"}
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
