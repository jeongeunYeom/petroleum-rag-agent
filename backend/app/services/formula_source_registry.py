"""Literal equation anchors; neither semantic rewriting nor executable code."""

from __future__ import annotations

import ast
import re
from typing import Any

from pydantic import BaseModel, Field
from app.services.compound_units import UNIT, unit_factors
from app.services.formula_units import formula_output_unit

from app.services.formula_layout_normalizer import (
    STACKED_FRACTION, STACKED_POWER, STACKED_POWER_FRACTION, WRAPPED_ADD_FRACTION,
    WRAPPED_OPERATOR_FRACTION, WRAPPED_OPERATOR,
    isolate_equation, normalize_extracted_equation,
)


EQUATION = re.compile(
    r"(?P<equation>\b[A-Za-zφρΔμλ][A-Za-z0-9_φρΔμλ₀-₉ₓₒₐ]*\s*=\s*"
    r"(?:(?!\.\s+[A-Za-z]|,\s*[A-Za-z][A-Za-z0-9_₀-₉ₓₒₐ]*\s*=)[A-Za-z0-9_φρΔμλ₀-₉ₓₒₐ+\-*/().×÷−· \t])+)"
)
EXPLICIT_DEFINITION = re.compile(
    r"\b(?P<lhs>[A-Za-z][A-Za-z0-9_]*)\s+"
    r"(?:is|equals|is\s+defined\s+as)\s+(?:the\s+)?"
    r"(?:(?:ratio\s+of\s+(?P<ratio_a>[A-Za-z][A-Za-z0-9_]*)\s+to\s+"
    r"(?P<ratio_b>[A-Za-z][A-Za-z0-9_]*))|"
    r"(?:(?P<difference_a>[A-Za-z][A-Za-z0-9_]*)\s+minus\s+"
    r"(?P<difference_b>[A-Za-z][A-Za-z0-9_]*)))\b", re.I)
TRANSLATION = str.maketrans({"×": "*", "÷": "/", "−": "-", "–": "-", "·": "*",
                            "φ": "phi", "ρ": "rho", "Δ": "Delta", "μ": "mu", "λ": "lambda",
                            "ₓ": "x", "ₒ": "o", "ₐ": "a",
                            "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
                            "₆": "6", "₇": "7", "₈": "8", "₉": "9"})
ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Constant,
           ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Load)


def normalize_formula(value: str) -> str:
    return re.sub(r"\s+", "", value.translate(TRANSLATION)).casefold()


def expression_variables(formula: str) -> set[str] | None:
    try:
        lhs, rhs = (part.strip() for part in formula.translate(TRANSLATION).split("=", 1))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", lhs):
            return None
        tree = ast.parse(rhs, mode="eval")
        if not all(isinstance(node, ALLOWED) and (
            not isinstance(node, ast.Constant) or isinstance(node.value, (int, float))
        ) for node in ast.walk(tree)):
            return None
        return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    except (ValueError, SyntaxError):
        return None


def equation_ast(formula: str) -> str | None:
    """Canonical equation structure, including every variable and numeric constant."""
    if expression_variables(formula) is None:
        return None
    lhs, rhs = formula.translate(TRANSLATION).split("=", 1)
    return f"{lhs.strip().casefold()}={ast.dump(ast.parse(rhs.strip(), mode='eval'), include_attributes=False)}"


def _clipped_addition(text: str, equation: str) -> bool:
    """Reject an additive fragment when the source itself declares incompatible units."""
    try:
        lhs, rhs = (part.strip() for part in equation.split("=", 1))
        tree = ast.parse(rhs, mode="eval").body
        if not isinstance(tree, ast.BinOp) or not isinstance(tree.op, (ast.Add, ast.Sub)):
            return False
        names = {lhs, *(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))}
        units = {}
        for name in names:
            found = re.search(rf"(?im)^\s*{re.escape(name)}\s*(?:=|:)\s*[A-Za-z][^\n]{{0,100}}?"
                              rf"\((?P<unit>{UNIT})\)", text)
            if not found:
                return False
            units[name] = found["unit"]
        return unit_factors(formula_output_unit(tree, units)) != unit_factors(units[lhs])
    except (SyntaxError, ValueError, KeyError):
        return True


def source_contains_equation(record: "FormulaSourceRecord", text: str,
                             formula: str | None = None) -> bool:
    """A locator or neighboring chunk never substitutes for this exact source span."""
    if text[record.span_start:record.span_end] != record.raw_span:
        return False
    if _unconsumed_continuation(text, record.span_end):
        return False
    if record.layout_transformations:
        local = text[max(0, record.span_start - 350):min(len(text), record.span_end + 350)]
        layout = normalize_extracted_equation(record.raw_span, local)
        source_equation = layout.normalized_expression
        expected = (isolate_equation(source_equation, record.target_variable)
                    if source_equation and record.formula_derivation == "algebraic_isolation"
                    and record.target_variable else source_equation)
        return bool(source_equation and source_equation == record.source_equation
                    and list(layout.transformations) == record.layout_transformations
                    and expected == record.normalized_expression
                    and expected and record.equation_ast == equation_ast(expected)
                    and record.equation_ast == equation_ast(record.expression_candidate or "")
                    and record.equation_ast == equation_ast(formula or record.expression_candidate or ""))
    # Recreate the candidate from the literal span and its local source context.
    # A record whose executable formula was changed after extraction is not evidence.
    expected = _source_expression(record.raw_span, text, record.span_start, record.span_end)
    return bool(record.expression_candidate and record.equation_ast
                and not _clipped_addition(text, expected)
                and equation_ast(expected) == record.equation_ast
                and record.equation_ast == equation_ast(record.expression_candidate)
                and record.equation_ast == equation_ast(formula or record.expression_candidate))


def _unconsumed_continuation(text: str, end: int) -> bool:
    """A short operator row immediately after a span belongs to that formula.

    A prose sentence or a separately labeled equation is not attached. This
    rejects a clipped prefix; the full layout block must be reconstructed first.
    """
    return bool(re.match(r"[ \t]*\r?\n[ \t]*[+\-*/×÷−][ \t]*"
                         r"(?:[A-Za-zφρμλ][A-Za-z0-9_φρμλ]*|\d+(?:\.\d+)?)"
                         r"(?=[ \t]*(?:\r?\n|$|[+\-*/×÷−]))", text[end:]))


def porosity_exponent_layout_context(local: str) -> bool:
    """Require an explicit porosity relation and cementation exponent beside the span."""
    porosity_relation = (
        re.search(r"\bformation(?:\s+resistivity)?\s+factor\b.{0,180}\b(?:measured\s+)?porosity\b",
                  local, re.I | re.S)
        or re.search(r"\bF\s+is\s+(?:usually\s+)?obtained\s+from\s+(?:the\s+)?"
                     r"measured\s+porosity\b", local, re.I))
    cementation = re.search(
        r"\bm\s+(?:is\s+(?:the\s+)?)?cementation\s+(?:factor|exponent)\b|"
        r"\bcementation\s+(?:factor|exponent)\s*(?:\(\s*)?(?:is\s+)?m\b", local, re.I)
    fm_defined = re.search(
        r"\bfm\s*(?:is|denotes|means|=)\b|\b(?:variable|parameter)\s+fm\b", local, re.I)
    return bool(porosity_relation and cementation and not fm_defined)


def _source_expression(raw: str, text: str, start: int, end: int) -> str:
    """Interpret only source-verifiable layout artifacts, never arbitrary `fm`."""
    if definition := EXPLICIT_DEFINITION.fullmatch(raw):
        numerator = definition.group("ratio_a") or definition.group("difference_a")
        denominator = definition.group("ratio_b") or definition.group("difference_b")
        operator = "/" if definition.group("ratio_a") else "-"
        return f"{definition['lhs']} = {numerator} {operator} {denominator}"
    candidate = raw.translate(TRANSLATION)
    local = text[max(0, start - 350):min(len(text), end + 350)]
    layout = normalize_extracted_equation(raw, local)
    if layout.normalized_expression:
        return layout.normalized_expression
    if not re.search(r"(?<![A-Za-z0-9_])fm(?![A-Za-z0-9_])", candidate, re.I):
        return candidate
    if not (porosity_exponent_layout_context(local)
            and re.fullmatch(r"\s*F\s*=\s*a\s*/\s*fm\s*", candidate, re.I)):
        return candidate
    return re.sub(r"(?<![A-Za-z0-9_])fm(?![A-Za-z0-9_])", "phi**m", candidate, count=1, flags=re.I)


class FormulaSourceRecord(BaseModel):
    formula_id: str
    source_id: str
    source_type: str
    raw_span: str
    normalized_span: str
    locator: str | None = None
    span_start: int
    span_end: int
    expression_candidate: str | None = None
    normalized_expression: str | None = None
    source_equation: str | None = None
    formula_derivation: str | None = None
    target_variable: str | None = None
    layout_transformations: list[str] = Field(default_factory=list)
    equation_ast: str | None = None
    lhs: str | None = None
    rhs: str | None = None
    required_variables: list[str] = Field(default_factory=list)
    source_document: str | None = None
    source_page: int | str | None = None
    context: str = ""


class FormulaSourceRegistry(BaseModel):
    records: list[FormulaSourceRecord] = Field(default_factory=list)
    layout_events: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_evidence(cls, evidence: list[dict[str, Any]]) -> "FormulaSourceRegistry":
        records: list[FormulaSourceRecord] = []
        layout_events: list[dict[str, Any]] = []
        for source in evidence:
            if source.get("source_type") not in {"knowledge_base", "figure", "web"}:
                continue
            text = str(source.get("text") or "")
            stacked_spans: list[tuple[int, int]] = []
            for pattern in (STACKED_POWER_FRACTION, STACKED_FRACTION, STACKED_POWER,
                            WRAPPED_ADD_FRACTION, WRAPPED_OPERATOR_FRACTION, WRAPPED_OPERATOR):
                for match in pattern.finditer(text):
                    start, end = match.span("block")
                    if any(a < end and start < b for a, b in stacked_spans):
                        continue
                    raw = match["block"]
                    if re.match(r"(?i)(?:equation|eq\.?|figure|table|where)\b", raw.splitlines()[-1].strip()):
                        # A caption following a one-line equation is not its denominator.
                        continue
                    stacked_spans.append((start, end))
                    local = text[max(0, start - 350):min(len(text), end + 350)]
                    layout = normalize_extracted_equation(raw, local)
                    layout_events.append({"source_id": source["evidence_id"],
                                          "span_start": start, "span_end": end,
                                          "candidate_count": layout.candidate_count,
                                          "transformations": list(layout.transformations),
                                          "ambiguous": layout.is_ambiguous,
                                          "reason": layout.reason})
                    relation = layout.normalized_expression
                    if not relation:
                        continue
                    left, right = (ast.parse(part.strip(), mode="eval").body
                                   for part in relation.split("=", 1))
                    targets = ([left.id] if isinstance(left, ast.Name) else
                               [right.right.id] if isinstance(right, ast.BinOp)
                               and isinstance(right.op, ast.Div) and isinstance(right.right, ast.Name) else
                               [right.id] if isinstance(right, ast.Name) else [])
                    for target in targets:
                        candidate = relation if isinstance(left, ast.Name) else isolate_equation(relation, target)
                        variables = expression_variables(candidate or "")
                        if variables is None:
                            continue
                        records.append(FormulaSourceRecord(
                            formula_id=f"FORMULA{len(records) + 1}", source_id=str(source["evidence_id"]),
                            source_type=str(source["source_type"]), raw_span=raw,
                            normalized_span=normalize_formula(raw), locator=source.get("locator"),
                            span_start=start, span_end=end, expression_candidate=candidate,
                            normalized_expression=candidate,
                            source_equation=relation,
                            formula_derivation="algebraic_isolation" if not isinstance(left, ast.Name) else None,
                            target_variable=target, layout_transformations=list(layout.transformations),
                            equation_ast=equation_ast(candidate), lhs=target,
                            rhs=candidate.split("=", 1)[1].strip(), required_variables=sorted(variables),
                            source_document=source.get("document"), source_page=source.get("page"),
                            context=text[max(0, start - 180):start].strip(),
                        ))
            for definition in EXPLICIT_DEFINITION.finditer(text):
                numerator = definition.group("ratio_a") or definition.group("difference_a")
                denominator = definition.group("ratio_b") or definition.group("difference_b")
                operator = "/" if definition.group("ratio_a") else "-"
                candidate = f"{definition['lhs']} = {numerator} {operator} {denominator}"
                records.append(FormulaSourceRecord(
                    formula_id=f"FORMULA{len(records) + 1}", source_id=str(source["evidence_id"]),
                    source_type=str(source["source_type"]), raw_span=definition.group(),
                    normalized_span=normalize_formula(candidate), locator=source.get("locator"),
                    span_start=definition.start(), span_end=definition.end(),
                    expression_candidate=candidate, equation_ast=equation_ast(candidate),
                    lhs=definition["lhs"], rhs=candidate.split("=", 1)[1].strip(),
                    required_variables=sorted(expression_variables(candidate) or []),
                    source_document=source.get("document"), source_page=source.get("page"),
                    context=str(source.get("heading") or text[max(0, definition.start()-180):definition.start()]).strip(),
                ))
            for match in EQUATION.finditer(text):
                if match.start() and text[match.start() - 1] in "*^":
                    # A superscript suffix is not a new LHS symbol.
                    continue
                if any(start < match.end() and match.start() < end for start, end in stacked_spans):
                    # Never promote the middle row of a stacked equation to n=F.
                    continue
                raw = match.group("equation").rstrip(" .\t")
                # A PDF definition can be clipped by the equation regex at a
                # prose word boundary (e.g. "SG = specific gravity"). A bare
                # symbol followed by another noun is not an executable span.
                rhs_literal = raw.split("=", 1)[1].strip()
                tail = text[match.start() + len(raw):]
                if (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rhs_literal)
                        and re.match(rf"\s*\({UNIT}\)", tail, re.I)):
                    continue  # A variable definition with units is not an equation dependency.
                if (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rhs_literal)
                        and re.match(r"[ \t]+(?!where\b|and\b|or\b|if\b|with\b|for\b|in\b|at\b|is\b)"
                                     r"[A-Za-z][A-Za-z-]*", tail, re.I)):
                    continue
                candidate = _source_expression(raw, text, match.start(), match.start() + len(raw))
                variables = expression_variables(candidate)
                if variables is not None and _clipped_addition(text, candidate):
                    continue
                if variables is None:
                    # OCR/excerpts often continue with prose after a valid equation.
                    # Keep the longest parseable prefix, never a paraphrased equation.
                    for boundary in reversed([item.start() for item in re.finditer(r"\s+", raw)]):
                        prefix = raw[:boundary].rstrip(" .\t")
                        normalized_prefix = _source_expression(prefix, text, match.start(), match.start() + len(prefix))
                        parsed = expression_variables(normalized_prefix)
                        if parsed:
                            raw, candidate, variables = prefix, normalized_prefix, parsed
                            break
                rhs = raw.split("=", 1)[1]
                if variables is None and not (re.search(r"[+\-*/×÷−·]", rhs) and re.search(r"[A-Za-z_]", rhs)):
                    continue
                start, end = match.start(), match.start() + len(raw)
                if _unconsumed_continuation(text, end):
                    continue
                if (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", candidate.split("=", 1)[1].strip())
                        and re.match(rf"\s*\({UNIT}\)", text[end:], re.I)):
                    continue
                if (candidate and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", candidate.split("=", 1)[1].strip())
                        and re.match(r"[ \t]+(?!where\b|and\b|or\b|if\b|with\b|for\b|in\b|at\b|is\b)"
                                     r"[A-Za-z][A-Za-z-]*", text[end:], re.I)):
                    continue
                layout = normalize_extracted_equation(
                    raw, text[max(0, start - 350):min(len(text), end + 350)])
                if layout.transformations or layout.is_ambiguous:
                    layout_events.append({"source_id": source["evidence_id"],
                                          "span_start": start, "span_end": end,
                                          "candidate_count": layout.candidate_count,
                                          "transformations": list(layout.transformations),
                                          "ambiguous": layout.is_ambiguous,
                                          "reason": layout.reason})
                records.append(FormulaSourceRecord(
                    formula_id=f"FORMULA{len(records) + 1}", source_id=str(source["evidence_id"]),
                    source_type=str(source["source_type"]), raw_span=raw,
                    normalized_span=normalize_formula(raw), locator=source.get("locator"),
                    span_start=start, span_end=end, expression_candidate=candidate if variables is not None else None,
                    normalized_expression=candidate if variables is not None and layout.transformations else None,
                    source_equation=layout.normalized_expression if layout.transformations else None,
                    target_variable=candidate.split("=", 1)[0].strip() if layout.transformations else None,
                    layout_transformations=list(layout.transformations),
                    equation_ast=equation_ast(candidate) if variables is not None else None,
                    lhs=candidate.split("=", 1)[0].strip(), rhs=candidate.split("=", 1)[1].strip(),
                    required_variables=sorted(variables or []),
                    source_document=source.get("document"), source_page=source.get("page"),
                    context=str(source.get("heading") or text[max(0, start-180):start]).strip(),
                ))
        return cls(records=records, layout_events=layout_events)
