"""Literal equation anchors; neither semantic rewriting nor executable code."""

from __future__ import annotations

import ast
import re
from typing import Any

from pydantic import BaseModel, Field


EQUATION = re.compile(
    r"(?P<equation>\b[A-Za-z][A-Za-z0-9_₀-₉]*\s*=\s*"
    r"(?:(?!\.\s+[A-Za-z]|,\s*[A-Za-z][A-Za-z0-9_₀-₉]*\s*=)[A-Za-z0-9_₀-₉φ+\-*/().×÷−· \t])+)"
)
STACKED_SATURATION = re.compile(
    r"(?P<equation>\bSw[ \t]*(?:\r?\n[ \t]*){1,3}n[ \t]*=[ \t]*F[ \t]+Rw"
    r"[ \t]*(?:\r?\n[ \t]*){1,3}Rt\b)", re.I
)
EXPLICIT_DEFINITION = re.compile(
    r"\b(?P<lhs>[A-Za-z][A-Za-z0-9_]*)\s+"
    r"(?:is|equals|is\s+defined\s+as)\s+(?:the\s+)?"
    r"(?:(?:ratio\s+of\s+(?P<ratio_a>[A-Za-z][A-Za-z0-9_]*)\s+to\s+"
    r"(?P<ratio_b>[A-Za-z][A-Za-z0-9_]*))|"
    r"(?:(?P<difference_a>[A-Za-z][A-Za-z0-9_]*)\s+minus\s+"
    r"(?P<difference_b>[A-Za-z][A-Za-z0-9_]*)))\b", re.I)
TRANSLATION = str.maketrans({"×": "*", "÷": "/", "−": "-", "–": "-", "·": "*",
                            "φ": "phi",
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


def source_contains_equation(record: "FormulaSourceRecord", text: str,
                             formula: str | None = None) -> bool:
    """A locator or neighboring chunk never substitutes for this exact source span."""
    if text[record.span_start:record.span_end] != record.raw_span:
        return False
    if record.source_equation or record.formula_derivation:
        source_equation = _stacked_saturation_equation(
            record.raw_span, text, record.span_start, record.span_end)
        derived = _isolate_denominator(source_equation, "Rt") if source_equation else None
        return bool(source_equation and record.source_equation == source_equation
                    and record.formula_derivation == "denominator_isolation"
                    and derived and record.equation_ast == equation_ast(derived)
                    and record.equation_ast == equation_ast(record.expression_candidate or "")
                    and record.equation_ast == equation_ast(formula or record.expression_candidate or ""))
    # Recreate the candidate from the literal span and its local source context.
    # A record whose executable formula was changed after extraction is not evidence.
    expected = _source_expression(record.raw_span, text, record.span_start, record.span_end)
    return bool(record.expression_candidate and record.equation_ast
                and equation_ast(expected) == record.equation_ast
                and record.equation_ast == equation_ast(record.expression_candidate)
                and record.equation_ast == equation_ast(formula or record.expression_candidate))


def _stacked_saturation_equation(raw: str, text: str, start: int, end: int) -> str | None:
    """Reconstruct only the ordered, captioned Archie stack in its own source window."""
    if not STACKED_SATURATION.fullmatch(raw):
        return None
    before = text[max(0, start - 350):start]
    after = text[end:min(len(text), end + 350)]
    local = before + raw + after
    archie_caption = bool(re.search(r"Archie.{0,100}water\s+saturation\s+equation", local, re.I | re.S))
    definitions = all(re.search(pattern, local, re.I | re.S) for pattern in (
        r"\bSw\b.{0,45}\bwater\s+saturation\b",
        r"\bRw\b.{0,45}\bformation\s+water\s+resistivity\b",
        r"\bRt\b.{0,45}\btrue\s+formation\s+resistivity\b",
        r"\bF\b.{0,45}\bformation\s+resistivity\s+factor\b",
    ))
    competing = re.search(r"\b(?:Sw|Rt)\s*(?:(?:\*\*|\^)\s*n\s*)?=\s*[A-Za-z0-9_(]",
                          before + after, re.I)
    if not (archie_caption or definitions) or competing:
        return None
    return "Sw**n = (F*Rw)/Rt"


def _isolate_denominator(source_equation: str, target: str) -> str | None:
    """Single-occurrence isolation: left = numerator / target."""
    try:
        lhs, rhs = (ast.parse(part.strip(), mode="eval").body
                    for part in source_equation.split("=", 1))
    except (SyntaxError, ValueError):
        return None
    if not isinstance(rhs, ast.BinOp) or not isinstance(rhs.op, ast.Div):
        return None
    if not isinstance(rhs.right, ast.Name) or rhs.right.id != target:
        return None
    if any(not isinstance(node, ALLOWED) for tree in (lhs, rhs)
           for node in ast.walk(tree)):
        return None
    if any(isinstance(node, ast.Name) and node.id == target
           for tree in (lhs, rhs.left) for node in ast.walk(tree)):
        return None
    return f"{target} = ({ast.unparse(rhs.left)})/({ast.unparse(lhs)})"


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
    """Interpret one documented porosity-exponent PDF layout, not arbitrary `fm`."""
    if definition := EXPLICIT_DEFINITION.fullmatch(raw):
        numerator = definition.group("ratio_a") or definition.group("difference_a")
        denominator = definition.group("ratio_b") or definition.group("difference_b")
        operator = "/" if definition.group("ratio_a") else "-"
        return f"{definition['lhs']} = {numerator} {operator} {denominator}"
    candidate = raw.translate(TRANSLATION)
    if not re.search(r"(?<![A-Za-z0-9_])fm(?![A-Za-z0-9_])", candidate, re.I):
        return candidate
    local = text[max(0, start - 240):min(len(text), end + 240)]
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
    source_equation: str | None = None
    formula_derivation: str | None = None
    equation_ast: str | None = None
    lhs: str | None = None
    rhs: str | None = None
    required_variables: list[str] = Field(default_factory=list)
    source_document: str | None = None
    source_page: int | str | None = None
    context: str = ""


class FormulaSourceRegistry(BaseModel):
    records: list[FormulaSourceRecord] = Field(default_factory=list)

    @classmethod
    def from_evidence(cls, evidence: list[dict[str, Any]]) -> "FormulaSourceRegistry":
        records: list[FormulaSourceRecord] = []
        for source in evidence:
            if source.get("source_type") not in {"knowledge_base", "figure", "web"}:
                continue
            text = str(source.get("text") or "")
            stacked_spans = []
            for stacked in STACKED_SATURATION.finditer(text):
                start, end = stacked.span("equation")
                raw = stacked.group("equation")
                stacked_spans.append((start, end))
                source_equation = _stacked_saturation_equation(raw, text, start, end)
                candidate = _isolate_denominator(source_equation, "Rt") if source_equation else None
                if not candidate:
                    continue
                records.append(FormulaSourceRecord(
                    formula_id=f"FORMULA{len(records) + 1}", source_id=str(source["evidence_id"]),
                    source_type=str(source["source_type"]), raw_span=raw,
                    normalized_span=normalize_formula(raw), locator=source.get("locator"),
                    span_start=start, span_end=end, expression_candidate=candidate,
                    source_equation=source_equation, formula_derivation="denominator_isolation",
                    equation_ast=equation_ast(candidate), lhs="Rt",
                    rhs=candidate.split("=", 1)[1].strip(),
                    required_variables=sorted(expression_variables(candidate) or []),
                    source_document=source.get("document"), source_page=source.get("page"),
                    context=text[max(0, start-180):start].strip(),
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
                candidate = _source_expression(raw, text, match.start(), match.start() + len(raw))
                variables = expression_variables(candidate)
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
                records.append(FormulaSourceRecord(
                    formula_id=f"FORMULA{len(records) + 1}", source_id=str(source["evidence_id"]),
                    source_type=str(source["source_type"]), raw_span=raw,
                    normalized_span=normalize_formula(raw), locator=source.get("locator"),
                    span_start=start, span_end=end, expression_candidate=candidate if variables is not None else None,
                    equation_ast=equation_ast(candidate) if variables is not None else None,
                    lhs=candidate.split("=", 1)[0].strip(), rhs=candidate.split("=", 1)[1].strip(),
                    required_variables=sorted(variables or []),
                    source_document=source.get("document"), source_page=source.get("page"),
                    context=str(source.get("heading") or text[max(0, start-180):start]).strip(),
                ))
        return cls(records=records)
