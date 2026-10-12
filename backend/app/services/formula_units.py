"""Bounded unit propagation for arithmetic equations; no implicit conversions."""

from __future__ import annotations

import ast
import math

from app.services.compound_units import format_unit_factors, unit_factors


def formula_output_unit(node: ast.AST, units: dict[str, str],
                        values: dict[str, float] | None = None) -> str:
    def dimensions(item: ast.AST) -> dict[str, int]:
        if isinstance(item, ast.Constant) and type(item.value) in {int, float}:
            return {}
        if isinstance(item, ast.Name):
            return unit_factors(units[item.id])
        if isinstance(item, ast.UnaryOp) and isinstance(item.op, (ast.UAdd, ast.USub)):
            return dimensions(item.operand)
        if not isinstance(item, ast.BinOp):
            raise ValueError("unsupported user formula expression")
        left, right = dimensions(item.left), dimensions(item.right)
        if isinstance(item.op, (ast.Add, ast.Sub)):
            if left != right:
                raise ValueError("incompatible user formula units")
            return left
        if isinstance(item.op, (ast.Mult, ast.Div)):
            sign = -1 if isinstance(item.op, ast.Div) else 1
            combined = dict(left)
            for atom, power in right.items():
                combined[atom] = combined.get(atom, 0) + sign * power
            combined = {atom: power for atom, power in combined.items() if power}
            if sum(abs(power) for power in combined.values()) > 64:
                raise ValueError("unit expansion limit")
            return combined
        if isinstance(item.op, ast.Pow):
            if right:
                raise ValueError("unsupported dimensional exponent")
            exponent = (item.right.value if isinstance(item.right, ast.Constant) else
                        (values or {}).get(item.right.id) if isinstance(item.right, ast.Name) else None)
            if not left:
                return {}
            if (type(exponent) not in {int, float} or not math.isfinite(exponent)
                    or int(exponent) != exponent or abs(exponent) > 8):
                raise ValueError("unsupported dimensional exponent")
            powered = {atom: power * int(exponent) for atom, power in left.items()
                       if power * int(exponent)}
            if sum(abs(power) for power in powered.values()) > 64:
                raise ValueError("unit expansion exceeds safe bounds")
            return powered
        raise ValueError("unsupported user formula expression")

    return format_unit_factors(dimensions(node))
