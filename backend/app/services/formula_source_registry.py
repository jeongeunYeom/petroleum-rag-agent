"""Literal equation anchors; neither semantic rewriting nor executable code."""

from __future__ import annotations

import ast
import re
from typing import Any

from pydantic import BaseModel, Field


EQUATION = re.compile(
    r"(?P<equation>\b[A-Za-z][A-Za-z0-9_₀-₉]*\s*=\s*"
    r"(?:(?!\.\s+[A-Za-z]|,\s*[A-Za-z][A-Za-z0-9_₀-₉]*\s*=)[A-Za-z0-9_₀-₉+\-*/().×÷−· \t])+)"
)
TRANSLATION = str.maketrans({"×": "*", "÷": "/", "−": "-", "–": "-", "·": "*",
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
    return bool(record.expression_candidate and record.equation_ast
                and record.equation_ast == equation_ast(record.expression_candidate)
                and record.equation_ast == equation_ast(formula or record.expression_candidate))


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
    equation_ast: str | None = None


class FormulaSourceRegistry(BaseModel):
    records: list[FormulaSourceRecord] = Field(default_factory=list)

    @classmethod
    def from_evidence(cls, evidence: list[dict[str, Any]]) -> "FormulaSourceRegistry":
        records: list[FormulaSourceRecord] = []
        for source in evidence:
            if source.get("source_type") not in {"knowledge_base", "figure", "web"}:
                continue
            text = str(source.get("text") or "")
            for match in EQUATION.finditer(text):
                raw = match.group("equation").rstrip(" .\t")
                candidate = raw.translate(TRANSLATION)
                variables = expression_variables(candidate)
                if variables is None:
                    # OCR/excerpts often continue with prose after a valid equation.
                    # Keep the longest parseable prefix, never a paraphrased equation.
                    for boundary in reversed([item.start() for item in re.finditer(r"\s+", raw)]):
                        prefix = raw[:boundary].rstrip(" .\t")
                        parsed = expression_variables(prefix.translate(TRANSLATION))
                        if parsed:
                            raw, candidate, variables = prefix, prefix.translate(TRANSLATION), parsed
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
                ))
        return cls(records=records)
