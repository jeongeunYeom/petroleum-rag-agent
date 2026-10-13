"""Run-local symbol definitions; a shared unit alone never creates an alias."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.calculation_requirements import normalize_symbol, symbol_names, source_variable_unit
from app.services.compound_units import unit_factors
from app.services.formula_source_registry import FormulaSourceRecord, expression_variables
from app.services.source_verification_text import verification_view
from app.services.user_fact_registry import UserFactRecord, UserFactRegistry


@dataclass(frozen=True)
class SourceAlias:
    symbol: str
    definition: str
    source_id: str
    document: str
    page: int
    raw_span: str
    confidence: float = 1.0


_DEFINITION = re.compile(
    r"(?im)^\s*(?:where\s+)?(?P<symbol>[A-Za-z][A-Za-z0-9_]*)\s*"
    r"(?:=|:|,|\s+(?:is|denotes|means|represents)\s+)\s*"
    r"(?P<phrase>[A-Za-z][^\n.;=]{3,120})")
_NOISE = {"of", "the", "in", "at", "a", "an", "for", "given", "rate", "fluid", "point"}
_CONCEPTS = {"annulus": "annular", "frictional": "friction", "drop": "loss",
             "tvd": "depth", "vertical": "depth", "pressure": "pressure"}


def _tokens(value: str) -> set[str]:
    words = re.findall(r"[a-z]+", verification_view(value).casefold())
    return {_CONCEPTS.get(word, word) for word in words if word not in _NOISE}


def local_aliases(formula: FormulaSourceRecord, evidence: list[dict]) -> list[SourceAlias]:
    variables = expression_variables(formula.expression_candidate or "") or set()
    aliases: list[SourceAlias] = []
    for row in evidence:
        page = row.get("page")
        if (row.get("source_type") not in {"knowledge_base", "figure", "web"}
                or not formula.source_document or row.get("document") != formula.source_document
                or not isinstance(page, int) or not isinstance(formula.source_page, int)
                or abs(page - formula.source_page) > 1):
            continue
        text = str(row.get("text") or "")
        for match in _DEFINITION.finditer(text):
            symbol, phrase = match["symbol"], match["phrase"].strip()
            if symbol not in variables or not _tokens(phrase):
                continue
            aliases.append(SourceAlias(symbol, phrase, str(row.get("evidence_id") or ""),
                                       str(row["document"]), page, match.group().strip()))
    return aliases


def bind_source_aliases(formula: FormulaSourceRecord, evidence: list[dict],
                        facts: UserFactRegistry) -> tuple[dict[str, UserFactRecord], list[SourceAlias]]:
    """Only unique local definitions and compatible labelled facts can bind."""
    definitions = local_aliases(formula, evidence)
    result: dict[str, UserFactRecord] = {}
    used: list[SourceAlias] = []
    for variable in sorted(expression_variables(formula.expression_candidate or "") or ()):
        if any(normalize_symbol(fact.name) in symbol_names(variable) for fact in facts.records):
            continue  # Exact/global bindings have priority.
        entries = [entry for entry in definitions if entry.symbol == variable]
        meanings = {frozenset(_tokens(entry.definition)) for entry in entries}
        if len(meanings) != 1:
            continue
        meaning = next(iter(meanings))
        candidates = [fact for fact in facts.records if _tokens(fact.name) and
                      _tokens(fact.name) <= meaning]
        if len(candidates) != 1:
            continue
        expected = next((source_variable_unit(str(row.get("text") or ""), variable)
                         for row in evidence if row.get("evidence_id") in {entry.source_id for entry in entries}
                         and source_variable_unit(str(row.get("text") or ""), variable)), None)
        if expected and candidates[0].unit:
            try:
                if unit_factors(expected) != unit_factors(candidates[0].unit):
                    continue
            except ValueError:
                continue
        if not candidates[0].unit and expected:
            continue
        result[variable] = candidates[0]
        used.append(entries[0])
    return result, used
