"""Conservative, source-bound numeric facts from retrieved evidence."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.user_fact_registry import ASSIGNMENT, NUMBER, UNIT, _name, _number


INLINE = re.compile(
    rf"(?P<label>[A-Za-z][A-Za-z0-9_ ]{{0,48}}?)\s+(?:was|is|measured at)\s+"
    rf"(?P<value>{NUMBER})\s*(?P<unit>{UNIT})(?=$|[,;.\s])",
    re.IGNORECASE,
)
ROW = re.compile(r"^\s*(?P<row>(?:Layer|Well)\s+[A-Za-z0-9_-]+)\s*:\s*", re.IGNORECASE)


class EvidenceFactRecord(BaseModel):
    fact_id: str
    source_id: str
    source_type: Literal["knowledge_base", "figure", "web"]
    name: str
    value: float
    unit: str
    raw_value_text: str
    source_span: str
    span_start: int
    span_end: int
    locator: str | None = None
    context_span: str | None = None


class EvidenceFactRegistry(BaseModel):
    records: list[EvidenceFactRecord] = Field(default_factory=list)

    @classmethod
    def from_evidence(cls, evidence: list[dict[str, Any]]) -> "EvidenceFactRegistry":
        records: list[EvidenceFactRecord] = []
        seen_names: set[str] = set()
        for source in evidence:
            source_type = source.get("source_type")
            if source_type not in {"knowledge_base", "figure", "web"}:
                continue
            text = str(source.get("text") or "")
            offset = 0
            for line in text.splitlines(keepends=True):
                row = ROW.match(line)
                base = row.end() if row else 0
                row_name = _name(row.group("row")) if row else ""
                candidates = sorted(
                    [*ASSIGNMENT.finditer(line, base), *INLINE.finditer(line, base)],
                    key=lambda match: match.start(),
                )
                occupied: list[tuple[int, int]] = []
                for match in candidates:
                    if any(start < match.end() and match.start() < end for start, end in occupied):
                        continue
                    raw = match.group("value")
                    unit = match.group("unit") or ""
                    value = _number(raw)
                    # A unitless assignment may be a formula coefficient or an unrelated number.
                    if value is None or not unit:
                        continue
                    label = re.sub(r"^(?:and|the|a|an)\s+", "", match.group("label").strip(), flags=re.I)
                    name = _name(f"{row_name}_{label}" if row_name else label)
                    if not name or not re.match(r"^[A-Za-z]", name):
                        continue
                    if name in seen_names:
                        suffix = 2
                        while f"{name}_{suffix}" in seen_names:
                            suffix += 1
                        name = f"{name}_{suffix}"
                    seen_names.add(name)
                    start, end = offset + match.start(), offset + match.end()
                    records.append(EvidenceFactRecord(
                        fact_id=f"EFACT{len(records) + 1}", source_id=str(source["evidence_id"]),
                        source_type=source_type, name=name, value=value, unit=unit,
                        raw_value_text=raw, source_span=text[start:end], span_start=start, span_end=end,
                        locator=source.get("locator"), context_span=row.group(0) if row else None,
                    ))
                    occupied.append(match.span())
                offset += len(line)
        return cls(records=records)
