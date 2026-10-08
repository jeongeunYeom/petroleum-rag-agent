"""Deterministic, topic-only calculation inputs (not scientific evidence)."""

from __future__ import annotations

import math
import re

from pydantic import BaseModel, Field


NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?|[-+]?\d+\s*/\s*\d+"
UNIT = r"(?:kg/m\^?3|m\^?3/d|m\^?3|stb/d|bbl/d|acres?|feet|ft|mD|md|psi|psia|psig|kPa|Pa|bbl|stb|days?|hours?|hr|kg|m|%|cP)"
ASSIGNMENT = re.compile(
    rf"(?P<label>[A-Za-z][A-Za-z0-9 _/\-]{{0,48}}?)\s*[:=]\s*(?P<value>{NUMBER})\s*(?P<unit>{UNIT})?(?=$|[,;\s]|\.(?!\d)|[가-힣])",
    re.IGNORECASE,
)
TUPLE_HEADER = re.compile(r"\((?P<header>[^()]+)\)\s*:")
TUPLE_ROW = re.compile(r"(?P<label>[A-Za-z][A-Za-z0-9_]*)\s*=\s*\((?P<values>[^()]+)\)")
WELL_HEADER = re.compile(r"\bWell\s+(?P<well>[A-Za-z][A-Za-z0-9_-]*)\s*:", re.IGNORECASE)
KOREAN_SG = re.compile(rf"비중\s*(?:은|는|이|가|[:=])?\s*(?P<value>{NUMBER})")
KOREAN_NAMED_SG = re.compile(rf"\bSG\s*(?:은|는|이|가)\s*(?P<value>{NUMBER})(?=$|[가-힣,;\s]|\.(?!\d))", re.I)
KOREAN_SIMULATION_INPUT = re.compile(
    rf"(?P<label>저류층\s*부피|벌크\s*부피|부피|CO₂?\s*밀도|이산화탄소\s*밀도|밀도)"
    rf"\s*(?:은|는|이|가|[:=])?\s*(?P<value>{NUMBER})\s*(?P<unit>{UNIT})?",
    re.I,
)
BARE_SERIES = re.compile(
    rf"(?P<body>(?:\b[A-Z]\s+(?:{NUMBER})\s*[,;]\s*)+\b[A-Z]\s+(?:{NUMBER}))"
    rf"\s*(?P<unit>stb/d|bbl/d|m\^?3/d)(?=$|[가-힣,;.\s])"
)
BARE_ITEM = re.compile(rf"\b(?P<label>[A-Z])\s+(?P<value>{NUMBER})")
KOREAN_RATE = re.compile(
    rf"\b(?P<label>[A-Z][A-Za-z0-9_]*)\s*(?:의\s*(?:생산량|유량)\s*)?"
    rf"(?:은|는|이|가)\s*(?P<value>{NUMBER})\s*(?P<unit>stb/d|bbl/d|m\^?3/d)", re.I,
)


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
            for found in KOREAN_NAMED_SG.finditer(text):
                add("SG", found.group("value"), "", found.group(0), None, offset + found.start())
            for found in KOREAN_SIMULATION_INPUT.finditer(text):
                label = found.group("label")
                name = "bulk_volume" if "부피" in label else "CO2_density"
                add(name, found.group("value"), found.group("unit") or "", found.group(0), None,
                    offset + found.start())
            for series in BARE_SERIES.finditer(text):
                for item in BARE_ITEM.finditer(series.group("body")):
                    add(f"{item.group('label')}_rate", item.group("value"), series.group("unit"),
                        series.group(0), series.group(0), offset + series.start())
            for found in KOREAN_RATE.finditer(text):
                add(f"{found.group('label')}_rate", found.group("value"), found.group("unit"),
                    found.group(0), None, offset + found.start())
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
