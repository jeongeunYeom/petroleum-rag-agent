"""Narrow, literal support for source-equation and independent numeric-fact requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.calculation_requirements import normalize_symbol
from app.services.formula_source_registry import FormulaSourceRegistry, normalize_formula
from app.services.user_fact_registry import UNIT


SYMBOL = re.compile(r"(?<![A-Za-z0-9_])(?:[A-Z][a-z]{1,3}(?:_[A-Za-z0-9]+)?|[A-Z]_[A-Za-z0-9]+)(?![A-Za-z0-9_])")
EQUATION_QUESTION = re.compile(r"\b(?:relationship|relation|equation|formula|law)\b|관계식|수식|공식|관계|(?<![가-힣])식(?:을|를|이|의)?|(?:무슨|어떤)\s*식", re.I)
VALUE_QUESTION = re.compile(r"\b(?:values?|units?)\b|값|단위", re.I)
QUANTITY = re.compile(rf"(?<![A-Za-z0-9])(?P<value>[-+]?\d+(?:\.\d+)?)\s*(?P<unit>{UNIT})(?=$|[\s.,;])", re.I)
NON_SYMBOLS = {"what", "when", "where", "which", "the", "this", "that", "from", "with", "well", "case", "level"}
VISUAL_READ = re.compile(
    r"(?:figure|fig\.?|그림)\s*\w*.*(?:curve|axis|trend|trace|plot|곡선|축|추세|직접\s*읽|눈금|단면도|그림으로\s*확인)"
    r"|그림으로\s*확인|단면도", re.I)
NAMED_RELATION = re.compile(
    r"\b([A-Za-z][A-Za-z0-9_-]{2,})\s*(?:'s\s*)?(?:equation|formula|law|relation(?:ship)?|식(?:을|를|이|의)?|법칙)", re.I)


@dataclass(frozen=True)
class LiteralClaimSupport:
    answer: str
    supporting_ids: tuple[str, ...]
    required_symbols: tuple[str, ...]
    satisfied_symbols: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return bool(self.required_symbols) and self.required_symbols == self.satisfied_symbols


def requested_symbols(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group() for match in SYMBOL.finditer(query)
                               if match.group().casefold() not in NON_SYMBOLS))


def literal_source_answer(query: str, evidence: list[dict[str, Any]], *, korean: bool) -> LiteralClaimSupport | None:
    """Answer only exact source relations or independently stated value/unit pairs.

    Ambiguous or conflicting literals fall back to the normal grounded synthesis.
    No retrieved number becomes a calculation output here.
    """
    symbols = requested_symbols(query)
    if VISUAL_READ.search(query):
        return None
    source_rows = [row for row in evidence if row.get("source_type") in {"knowledge_base", "web"}]
    relation = NAMED_RELATION.search(query) if EQUATION_QUESTION.search(query) and not VALUE_QUESTION.search(query) else None
    if relation:
        relation_name = relation.group(1)
        verified = []
        rows_by_id = {str(row.get("evidence_id")): row for row in source_rows}
        for record in FormulaSourceRegistry.from_evidence(source_rows).records:
            row = rows_by_id.get(record.source_id, {})
            source_text = str(row.get("text") or "")
            if (not record.expression_candidate or
                    "equation_verified: true" not in source_text.casefold() or
                    not re.search(rf"(?im)^equation_text:\s*{re.escape(record.raw_span)}\s*$", source_text)):
                continue
            page = str(row.get("locator") or "").split(" chunk ", 1)[0]
            contextual = [item for item in source_rows if page and
                          str(item.get("locator") or "").startswith(page + " chunk ") and
                          re.search(rf"(?<![A-Za-z0-9]){re.escape(relation_name)}(?![A-Za-z0-9])",
                                    str(item.get("text") or ""), re.I)]
            if contextual:
                verified.append((record, contextual[0]))
        if len({normalize_formula(item.raw_span) for item, _ in verified}) == 1 and verified:
            record, context = verified[0]
            lead = f"근거 자료의 {relation_name} 식" if korean else f"The sourced {relation_name} relation"
            ids = tuple(dict.fromkeys((record.source_id, str(context["evidence_id"]))))
            citations = " ".join(f"[{source_id}]" for source_id in ids)
            return LiteralClaimSupport(f"{lead}: {record.raw_span} {citations}", ids,
                                       (relation_name,), (relation_name,))
    if not symbols:
        return None
    if EQUATION_QUESTION.search(query) and not VALUE_QUESTION.search(query) and len(symbols) >= 2:
        matches = []
        for record in FormulaSourceRegistry.from_evidence(source_rows).records:
            if not record.expression_candidate:
                continue
            formula_symbols = {normalize_symbol(value) for value in re.findall(
                r"[A-Za-z][A-Za-z0-9_]*", record.expression_candidate)}
            if all(normalize_symbol(symbol) in formula_symbols for symbol in symbols):
                matches.append(record)
        distinct = {normalize_formula(item.expression_candidate or "") for item in matches}
        if len(distinct) != 1:
            return None
        record = matches[0]
        lead = "근거 자료의 관계식" if korean else "The sourced relationship"
        return LiteralClaimSupport(f"{lead}: {record.raw_span} [{record.source_id}]",
                                   (record.source_id,), symbols, symbols)

    if not VALUE_QUESTION.search(query):
        return None
    lines = []
    ids = []
    satisfied = []
    for symbol in symbols:
        qualifier_match = re.search(
            rf"\b((?:Interval|Level|Case|Layer|Well)\s+[A-Za-z0-9]+)(?:\s*의)?\s+{re.escape(symbol)}(?![A-Za-z0-9_])",
            query, re.I)
        qualifier = qualifier_match.group(1) if qualifier_match else None
        values: dict[tuple[str, str], str] = {}
        for row in source_rows:
            text = str(row.get("text") or "")
            for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
                if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", sentence):
                    continue
                if qualifier and qualifier.casefold() not in sentence.casefold():
                    continue
                for occurrence in re.finditer(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", sentence):
                    nearby = sentence[occurrence.end():occurrence.end() + 90]
                    quantity = QUANTITY.search(nearby)
                    if quantity and not re.search(r"\b(?:Figure|Table|Page)\s*$", nearby[:quantity.start()], re.I):
                        values[(quantity.group("value"), quantity.group("unit"))] = str(row["evidence_id"])
        if len(values) != 1:
            continue
        (value, unit), source_id = next(iter(values.items()))
        label = f"{qualifier} {symbol}" if qualifier else symbol
        lines.append(f"{label} = {value} {unit} [{source_id}]")
        ids.append(source_id)
        satisfied.append(symbol)
    if not lines:
        return None
    if len(satisfied) < len(symbols):
        missing = ", ".join(symbol for symbol in symbols if symbol not in satisfied)
        lines.append((f"{missing} 값과 단위는 현재 근거에서 확인할 수 없습니다."
                      if korean else f"The available evidence does not establish the value and unit of {missing}."))
    return LiteralClaimSupport("\n".join(lines), tuple(dict.fromkeys(ids)), symbols, tuple(satisfied))
