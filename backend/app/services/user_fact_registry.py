"""Deterministic, topic-only calculation inputs (not scientific evidence)."""

from __future__ import annotations

import math
import re

from pydantic import BaseModel, Field


NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?(?:[eE][-+]?\d+)?|[-+]?\.\d+(?:[eE][-+]?\d+)?|[-+]?\d+\s*/\s*\d+"
UNIT = (r"(?:kg/m(?:\^?3|³)|m(?:\^?3|³)/(?:s|d|h)|\$/m(?:\^?3|³)|"
        r"m(?:\^?3|³)|mm(?:\^?2|²|⁻¹)|m(?:\^?2|²)|psi(?:⁻¹|\^-?1)?|stb/d|bbl/d|"
        r"acres?|feet|ft|mD|md|psia|psig|kPa|Pa|bbl|stb|days?|hours?|hr|h|"
        r"kg|kJ|lbf|cP|°C|USD|달러|시간|분|min|m/s|mm|m|%)")
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
NATURAL_FACT = re.compile(
    rf"(?P<label>[A-Za-z_][A-Za-z0-9_]*|[가-힣]{{2,12}}(?:\s+[A-Za-z_][A-Za-z0-9_]*)?)"
    rf"\s*(?:은|는|이|가|을|를|에서|에는|:|\s+of|\s+is)?\s*"
    rf"(?P<value>{NUMBER})\s*(?P<unit>{UNIT})(?![A-Za-z0-9/])", re.I,
)
ENGLISH_IS_VALUE = re.compile(rf"\b(?P<label>[A-Za-z][A-Za-z0-9_]*)\s+(?:is|was)\s+"
                              rf"(?P<value>[-+]?\d+(?:\.\d+)?)(?:\s*(?P<unit>{UNIT}))?(?=$|[.,;\s])", re.I)
DAY_POINT = re.compile(rf"\bday\s*(?P<day>\d+)(?![\d.])\s*(?:에는|에서|:|=|is|was)\s*"
                       rf"(?P<value>{NUMBER})(?!\s*(?:{UNIT}))", re.I)
COORD_POINT = re.compile(rf"\b(?P<axis>x|t|time)\s*(?P<coordinate>[-+]?\d+(?:\.\d+)?)\s*"
                         rf"(?:에는|에서|:|=|->)\s*(?P<value>[-+]?\d+(?:\.\d+)?)", re.I)
CLOCK = re.compile(r"(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)")
RATIO_SERIES = re.compile(r"(?P<names>[A-Za-z](?::[A-Za-z]){1,8})\s*=\s*(?P<values>\d+(?::\d+){1,8})")
TARGET_DAY = re.compile(rf"(?:\bday\s*|\bday=)(?P<day>{NUMBER})\s*(?:에서|의|at)?\s*(?:보간|interpolat)", re.I)
TARGET_DAY_AFTER = re.compile(rf"(?:보간|interpolat\w*)\s*(?:at\s+|for\s+|day\s*)*day\s*(?P<day>{NUMBER})", re.I)
TARGET_COORD = re.compile(r"(?:보간|interpolat\w*)\s*(?:at\s+|for\s+)?(?:x|t|time)\s*(?P<coordinate>[-+]?\d+(?:\.\d+)?)", re.I)
PERCENT_LITERAL = re.compile(rf"(?P<value>{NUMBER})\s*%")
REPEAT_COUNT = re.compile(r"(?P<count>\d+)\s*(?:번|회|times?)\s*(?:반복|적용)?", re.I)
TIER = re.compile(rf"(?P<volume>{NUMBER})\s*(?P<unit>m(?:\^?3|³)|stb|bbl)"
                  rf".{{0,40}}?(?:단가|price|rate|cost)\s*(?P<price>{NUMBER})\s*(?:달러|USD|\$)?", re.I)
KOREAN_ORDINAL = re.compile(rf"(?P<ordinal>첫|둘째|셋째|넷째|다섯째|여섯째|일곱째|여덟째|아홉째|열째)\s*"
                             rf"(?P<label>구간|run|단계)?\s*(?:은|는|에서)?\s*(?P<value>{NUMBER})\s*(?P<unit>{UNIT})", re.I)


def normalize_unit(raw: str) -> str:
    """Canonical spelling only; no unverified dimensional conversion."""
    value = raw.strip().replace("³", "3").replace("²", "2").replace("^", "")
    value = value.replace("⁻¹", "-1")
    if value.endswith("-1"):
        return "1/" + value[:-2]
    aliases = {"시간": "h", "hours": "h", "hour": "h", "hr": "h",
               "분": "min", "달러": "USD", "md": "mD"}
    return aliases.get(value.casefold(), value)


def _natural_name(label: str) -> str:
    original = label.strip().casefold()
    value = re.sub(r"(?:은|는|이|가|을|를|에서|에는)$", "", original).strip()
    aliases = {"유량": "q", "유량 q": "q", "속도": "speed", "허용 속도": "allowed_speed",
               "깊이": "depth", "온도": "temperature", "밀도": "density",
               "부피": "volume", "저류층 부피": "bulk_volume", "벌크 부피": "bulk_volume",
               "압력": "pressure", "거리": "distance", "시간": "time", "비중": "SG",
               "길이": "length", "면적": "area", "에너지": "energy", "힘": "force",
               "초기 값": "initial", "초기값": "initial", "전체": "total", "총량": "total"}
    return aliases.get(original, aliases.get(value, _name(label if len(label) <= 2 and label.isupper() else label.casefold())))


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
    raw_unit: str = ""
    canonical_unit: str = ""
    raw_value_text: str
    source_span: str
    context_span: str | None = None
    topic_start: int
    topic_end: int


class UserFactRegistry(BaseModel):
    records: list[UserFactRecord] = Field(default_factory=list)

    def add_literal_fallback(self, topic: str, candidates: list[dict[str, object]]) -> tuple[int, int]:
        """Admit model-extracted facts only when their exact numeric/unit quote exists."""
        accepted = rejected = 0
        for candidate in candidates[:20]:
            quote = str(candidate.get("source_quote") or "")
            name = _name(str(candidate.get("name") or ""))
            raw_unit = str(candidate.get("unit") or "")
            raw_value = candidate.get("value")
            if (not name or not quote or quote not in topic or
                    raw_value is None or isinstance(raw_value, bool) or
                    raw_unit and raw_unit not in quote):
                rejected += 1
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                rejected += 1
                continue
            numeric_spans = [(match.group(), _number(match.group())) for match in re.finditer(NUMBER, quote)]
            matching = [(raw, parsed) for raw, parsed in numeric_spans if parsed is not None and
                        math.isclose(parsed, value, rel_tol=0, abs_tol=1e-12)]
            if not math.isfinite(value) or len(matching) != 1 or any(row.name == name for row in self.records):
                rejected += 1
                continue
            start = topic.index(quote)
            canonical = normalize_unit(raw_unit)
            self.records.append(UserFactRecord(
                fact_id=f"USERF{len(self.records) + 1}", name=name, value=value,
                unit=canonical, raw_unit=raw_unit, canonical_unit=canonical,
                raw_value_text=matching[0][0], source_span=quote,
                topic_start=start, topic_end=start + len(quote)))
            accepted += 1
        return accepted, rejected

    @classmethod
    def from_messages(cls, messages: list[str]) -> "UserFactRegistry":
        """Merge follow-up facts without reassigning the original USERF IDs."""
        merged: list[UserFactRecord] = []
        for message in messages:
            previous = len(merged)
            for item in cls.from_topic(message).records:
                existing = [index for index, row in enumerate(merged[:previous]) if row.name == item.name]
                old = existing[0] if len(existing) == 1 else None
                if old is not None:
                    if merged[old].value == item.value and merged[old].canonical_unit == item.canonical_unit:
                        continue
                    # A later explicit correction replaces the value but keeps its stable ID.
                    item = item.model_copy(update={"fact_id": merged[old].fact_id})
                    merged[old] = item
                else:
                    merged.append(item.model_copy(update={"fact_id": f"USERF{len(merged) + 1}"}))
        return cls(records=merged)

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
            canonical = normalize_unit(unit)
            normalized_name = _name(name)
            if any(item.value == value and item.canonical_unit == canonical and
                   item.topic_start < start + len(span) and start < item.topic_end and
                   (item.name == normalized_name or item.source_span in span or span in item.source_span)
                   for item in records):
                return
            records.append(UserFactRecord(
                fact_id=f"USERF{len(records) + 1}", name=normalized_name, value=value,
                unit=canonical, raw_unit=unit, canonical_unit=canonical,
                raw_value_text=raw, source_span=span,
                context_span=context, topic_start=start, topic_end=start + len(span),
            ))

        for line in topic.splitlines(keepends=True):
            text = line.rstrip("\r\n")
            protected_spans: list[tuple[int, int]] = []
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
            coordinate_matches = [item for item in COORD_POINT.finditer(text)
                                  if not ((assigned := ASSIGNMENT.match(text, item.start()))
                                          and assigned.group("unit"))]
            coordinate_spans = [item.span() for item in coordinate_matches]
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
                if any(start < found.end() and found.start() < end for start, end in coordinate_spans):
                    continue
                label = found.group("label").strip()
                label = re.split(r"\b(?:has|have|with|where|given|and|at)\b", label, flags=re.I)[-1].strip()
                if label.casefold().startswith("well "):
                    continue
                if label.casefold() in {"measurements", "values", "data", "inputs"} and not found.group("unit"):
                    continue
                if (not found.group("unit") and not found.group("value").endswith(".")
                        and re.match(r"\s+[A-Za-z]", text[found.end():])):
                    # A following word may be an unsupported unit; do not erase it.
                    continue
                prefix = f"Well_{well}_" if well and label.casefold() not in {"well", "layer"} else ""
                normalized_label = label.casefold() if len(label) > 2 and label.istitle() else label
                add(prefix + normalized_label, found.group("value"), found.group("unit") or "", found.group(0), f"Well {well}" if well else None, offset + found.start())
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
                protected_spans.append(series.span())
                for item in BARE_ITEM.finditer(series.group("body")):
                    add(f"{item.group('label')}_rate", item.group("value"), series.group("unit"),
                        series.group(0), series.group(0), offset + series.start())
            for found in KOREAN_RATE.finditer(text):
                protected_spans.append(found.span())
                add(f"{found.group('label')}_rate", found.group("value"), found.group("unit"),
                    found.group(0), None, offset + found.start())
            piecewise = bool(re.search(r"구간별|추가.{0,20}단가|piecewise", text, re.I))
            if piecewise:
                protected_spans.extend(found.span() for found in TIER.finditer(text))
            for found in KOREAN_ORDINAL.finditer(text):
                ordinal = ("첫", "둘째", "셋째", "넷째", "다섯째", "여섯째", "일곱째", "여덟째", "아홉째", "열째").index(found["ordinal"]) + 1
                add(f"segment_{ordinal}", found["value"], found["unit"],
                    found.group(0), None, offset + found.start())
            for found in NATURAL_FACT.finditer(text):
                if any(start < found.end() and found.start() < end for start, end in protected_spans):
                    continue
                name = _natural_name(found["label"])
                if name.casefold() in {"a", "the", "of"} and found["unit"] == "%":
                    continue
                if re.fullmatch(r"[A-Z]", name) and normalize_unit(found["unit"]) in {"stb/d", "bbl/d", "m3/d"}:
                    name += "_rate"
                if name and name not in {"첫", "둘째", "셋째", "넷째", "다섯째"}:
                    add(name, found["value"], found["unit"], found.group(0), None, offset + found.start())
            for found in ENGLISH_IS_VALUE.finditer(text):
                if found["unit"]:
                    continue  # The unit-bearing natural fact above owns this span.
                add(found["label"], found["value"], "", found.group(0), None,
                    offset + found.start())
            for found in DAY_POINT.finditer(text):
                add(f"day_{found['day']}", found["value"], "", found.group(0), None, offset + found.start())
            for found in coordinate_matches:
                coordinate = found["coordinate"].replace(".", "p").replace("-", "n")
                add(f"point_{coordinate}", found["value"], "", found.group(0), None,
                    offset + found.start())
            for found in RATIO_SERIES.finditer(text):
                labels, values = found["names"].split(":"), found["values"].split(":")
                if len(labels) == len(values):
                    for label, value in zip(labels, values):
                        add(f"{label}_weight", value, "", found.group(0), found.group(0), offset + found.start())
            target_day = TARGET_DAY.search(text) or TARGET_DAY_AFTER.search(text)
            if target_day:
                add("target_day", target_day["day"], "d", target_day.group(0), None,
                    offset + target_day.start())
            target_coord = TARGET_COORD.search(text)
            if target_coord:
                add("target_x", target_coord["coordinate"], "", target_coord.group(0), None,
                    offset + target_coord.start())
            if re.search(r"증가|감소|increase|decrease|percent\s+to\s+fraction|퍼센트.{0,12}소수", text, re.I):
                for found in PERCENT_LITERAL.finditer(text):
                    add("change_percent" if re.search(r"증가|감소|increase|decrease", text, re.I)
                        else "percent_value", found["value"], "%", found.group(0), None,
                        offset + found.start())
                repeated = REPEAT_COUNT.search(text)
                if repeated and re.search(r"반복|적용|repeated|successive|times", text, re.I):
                    add("repeat_count", repeated["count"], "", repeated.group(0), None,
                        offset + repeated.start())
            if piecewise:
                for index, found in enumerate(TIER.finditer(text), 1):
                    add(f"tier_{index}_volume", found["volume"], found["unit"], found.group(0),
                        None, offset + found.start())
                    add(f"tier_{index}_price", found["price"], "USD/" + normalize_unit(found["unit"]),
                        found.group(0), None, offset + found.start())
            for index, found in enumerate(CLOCK.finditer(text)):
                minutes = int(found["hour"]) * 60 + int(found["minute"])
                add("start_time" if index == 0 else "end_time", str(minutes), "min", found.group(0),
                    None, offset + found.start())
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
