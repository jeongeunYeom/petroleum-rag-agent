"""Recognize an explicitly named local document without domain-specific aliases."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class DocumentConstraint:
    document_id: str
    title: str


def _words(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9가-힣]+", value.replace("_", " ").casefold()))


def explicit_document_constraints(query: str, catalog: Iterable[dict]) -> list[DocumentConstraint]:
    """Return every explicitly named document, preserving longer unique aliases."""
    text = _words(query)
    matches: list[tuple[int, DocumentConstraint]] = []
    raw_matches: list[tuple[int, DocumentConstraint]] = []
    for item in catalog:
        document_id = str(item.get("document_id") or "")
        title = str(item.get("filename") or item.get("title") or "").removesuffix(".pdf")
        if not document_id or not title:
            continue
        aliases = {title}
        if " - " in title.replace("_", " "):
            aliases.add(title.replace("_", " ").split(" - ", 1)[1])
        for alias in aliases:
            phrase = _words(alias)
            if len(phrase.split()) < 2:
                continue
            found = re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text)
            if not found:
                continue
            before, after = text[max(0, found.start() - 25):found.start()], text[found.end():found.end() + 22]
            raw_matches.append((len(phrase), DocumentConstraint(document_id, title)))
            if not (re.search(r"\b(?:from|in|within|according to|document|source|pdf)\s*$", before)
                    or re.match(r"\s*(?:에서|의|pdf|교재|문서|자료|source|document)", after)
                    or found.start() == 0):
                continue
            matches.append((len(phrase), DocumentConstraint(document_id, title)))
    if len({item.document_id for _, item in raw_matches}) >= 2 and re.search(
            r"\b(?:compare|contrast|both|across)\b|비교|두\s*문서|종합", text):
        matches = raw_matches
    matches.sort(key=lambda item: item[0], reverse=True)
    selected: dict[str, DocumentConstraint] = {}
    for _, constraint in matches:
        selected.setdefault(constraint.document_id, constraint)
    return list(selected.values())


def explicit_document_constraint(query: str, catalog: Iterable[dict]) -> DocumentConstraint | None:
    """Recognize one unambiguous title for a scoped retrieval call."""
    matches = explicit_document_constraints(query, catalog)
    return matches[0] if len(matches) == 1 else None
