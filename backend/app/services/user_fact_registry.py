"""Deterministic, topic-only calculation inputs (not scientific evidence)."""

from __future__ import annotations

import math
import re

from pydantic import BaseModel, Field


NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?|[-+]?\d+\s*/\s*\d+"
UNIT = r"(?:stb/d|bbl/d|m\^?3/d|acres?|feet|ft|mD|md|psi|psia|psig|kPa|Pa|bbl|stb|days?|hours?|hr|m|%|cP)"
ASSIGNMENT = re.compile(
    rf"(?P<label>[A-Za-z][A-Za-z0-9 _/-]{{0,48}}?)\s*[:=]\s*(?P<value>{NUMBER})\s*(?P<unit>{UNIT})?(?=$|[,;\s]|\.(?!\d)|[가-힣])",
    re.IGNORECASE,
)
TUPLE_HEADER = re.compile(r"\((?P<header>[^()]+)\)\s*:")
TUPLE_ROW = re.compile(r"(?P<label>[A-Za-z][A-Za-z0-9_]*)\s*=\s*\((?P<values>[^()]+)\)")
WELL_HEADER = re.compile(r"\bWell\s+(?P<well>[A-Za-z][A-Za-z0-9_-]*)\s*:", re.IGNORECASE)
KOREAN_SG = re.compile(rf"비중\s*(?:은|는|이|가|[:=])?\s*(?P<value>{NUMBER})")


def _number(raw: str) -> float | None:
    try:
        value = (
            float(raw.split("/", 1)[0]) / float(raw.split("/", 1)[1])
            if "/" in raw else float(raw.replace(",", ""))
        )
    except (ValueError, ZeroDivisionError):
        return None
    return value if math.isfinite(value) else None


def _name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")


class UserFactRecord(BaseModel):
    fact_id: str
    name: str
    value: float
    unit: str = ""
    raw_value_text: str
    source_span: str
    context_span: str | None = None
    topic_start: int
    topic_end: int


class UserFactRegistry(BaseModel):
    records: list[UserFactRecord] = Field(default_factory=list)

    @classmethod
    def from_topic(cls, topic: str) -> "UserFactRegistry":
        records: list[UserFactRecord] = []
        header: list[tuple[str, str]] | None = None
        header_text: str | None = None
        well: str | None = None
        offset = 0

        def add(name: str, raw: str, unit: str, span: str, context: str | None, start: int) -> None:
            value = _number(raw)
            if value is None or not _name(name):
                return
            records.append(UserFactRecord(
                fact_id=f"USERF{len(records) + 1}", name=_name(name), value=value,
                unit=unit, raw_value_text=raw, source_span=span,
                context_span=context, topic_start=start, topic_end=start + len(span),
            ))

        for line in topic.splitlines(keepends=True):
            text = line.rstrip("\r\n")
            match = TUPLE_HEADER.search(text)
            if match:
                columns = []
                for column in match.group("header").split(","):
                    parts = column.strip().rsplit(" ", 1)
                    if len(parts) != 2 or not re.fullmatch(UNIT, parts[1], re.IGNORECASE):
                        columns = []
                        break
                    columns.append((_name(parts[0]), parts[1]))
                header = columns or None
                header_text = match.group(0).rstrip(":").strip() if header else None
            well_match = WELL_HEADER.search(text)
            if well_match:
                well = well_match.group("well")
            tuple_spans = []
            for row in TUPLE_ROW.finditer(text):
                tuple_spans.append(row.span())
                values = [part.strip() for part in row.group("values").split(",")]
                if not header or len(values) != len(header) or not all(re.fullmatch(NUMBER, item) for item in values):
                    continue
                for (column, unit), raw in zip(header, values):
                    add(f"{row.group('label')}_{column}", raw, unit, row.group(0), header_text, offset + row.start())
            for found in ASSIGNMENT.finditer(text):
                if any(start <= found.start() < end for start, end in tuple_spans):
                    continue
                label = found.group("label").strip()
                if label.casefold().startswith("well "):
                    continue
                if label.casefold() in {"measurements", "values", "data", "inputs"} and not found.group("unit"):
                    continue
                if not found.group("unit") and re.match(r"\s+[A-Za-z]", text[found.end():]):
                    # A following word may be an unsupported unit; do not erase it.
                    continue
                prefix = f"Well_{well}_" if well and label.casefold() not in {"well", "layer"} else ""
                add(prefix + label, found.group("value"), found.group("unit") or "", found.group(0), f"Well {well}" if well else None, offset + found.start())
            for found in KOREAN_SG.finditer(text):
                add("SG", found.group("value"), "", found.group(0), None, offset + found.start())
            offset += len(line)
        return cls(records=records)

    def evidence(self) -> list[dict[str, object]]:
        return [
            {
                "evidence_id": item.fact_id, "source_type": "user_fact",
                "locator": "request.topic", "text": item.source_span,
                **item.model_dump(exclude={"fact_id"}),
            }
            for item in self.records
        ]
