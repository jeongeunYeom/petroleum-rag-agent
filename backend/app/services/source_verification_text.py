"""Mechanical PDF-text cleanup for matching only; callers retain the raw span."""

import re
import unicodedata


def verification_view(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw).replace("\u00ad", "")
    text = re.sub(r"(?<=[A-Za-z])-\s*\r?\n\s*(?=[a-z])", "", text)
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s*([=+*/()])\s*", r"\1", text).strip()
