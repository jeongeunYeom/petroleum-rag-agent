"""Infer a printed coefficient's dimensions only from local source unit definitions."""

import ast

from app.services.calculation_requirements import source_variable_unit
from app.services.compound_units import format_unit_factors, unit_factors
from app.services.formula_source_registry import FormulaSourceRecord


def sourced_conversion_units(formula: FormulaSourceRecord, evidence: list[dict]) -> tuple[dict[float, str], list[str]]:
    if "wrapped_fraction" not in formula.layout_transformations or not formula.expression_candidate:
        return {}, []
    try:
        lhs, rhs = (part.strip() for part in formula.expression_candidate.split("=", 1))
        tree = ast.parse(rhs, mode="eval").body
        if not isinstance(tree, ast.BinOp) or not isinstance(tree.op, (ast.Add, ast.Sub)):
            return {}, []
        if not isinstance(tree.left, ast.Name) or not isinstance(tree.right, ast.BinOp) or not isinstance(tree.right.op, ast.Div):
            return {}, []
        fraction = tree.right
        if not isinstance(fraction.left, ast.Name) or not isinstance(fraction.right, ast.BinOp) or not isinstance(fraction.right.op, ast.Mult):
            return {}, []
        coefficient, depth = fraction.right.left, fraction.right.right
        if not isinstance(coefficient, ast.Constant) or type(coefficient.value) not in {int, float} or coefficient.value == 0 or not isinstance(depth, ast.Name):
            return {}, []
        names = (lhs, tree.left.id, fraction.left.id, depth.id)
        rows = [row for row in evidence if row.get("document") == formula.source_document and
                isinstance(row.get("page"), int) and isinstance(formula.source_page, int) and
                abs(row["page"] - formula.source_page) <= 1]
        units = {}
        ids = []
        for name in names:
            matches = [(source_variable_unit(str(row.get("text") or ""), name), row.get("evidence_id"))
                       for row in rows]
            matches = [(unit, source_id) for unit, source_id in matches if unit]
            if len({unit for unit, _ in matches}) != 1:
                return {}, []
            units[name] = matches[0][0]
            ids.append(str(matches[0][1]))
        if unit_factors(units[lhs]) != unit_factors(units[tree.left.id]):
            return {}, []
        # numerator / (coefficient * depth) must have the declared output unit.
        factors = unit_factors(units[fraction.left.id])
        for atom, power in unit_factors(units[lhs]).items():
            factors[atom] = factors.get(atom, 0) - power
        for atom, power in unit_factors(units[depth.id]).items():
            factors[atom] = factors.get(atom, 0) - power
        factors = {atom: power for atom, power in factors.items() if power}
        if not factors:
            return {}, []
        return {float(coefficient.value): format_unit_factors(factors)}, list(dict.fromkeys(ids))
    except (SyntaxError, ValueError, KeyError):
        return {}, []
