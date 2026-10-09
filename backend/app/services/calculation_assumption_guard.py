"""Static preflight for unsupported numeric inputs in generated calculations."""

from __future__ import annotations

import ast


def preflight_calculation_code(code: str, required_fact_ids: list[str],
                               allowed_numeric_literals: set[float] | None = None) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ["code_generation_syntax_error"]
    invalid = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id in {"null", "true", "false"}}
    if invalid:
        return ["code_generation_invalid_literal"]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, (int, float)) or isinstance(value.value, bool):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) for target in targets):
                return ["unsupported_numeric_assumption"]
        if isinstance(node, ast.BinOp) and allowed_numeric_literals is not None:
            for operand in (node.left, node.right):
                if isinstance(operand, ast.Constant) and isinstance(operand.value, (int, float)) \
                        and not isinstance(operand.value, bool) and float(operand.value) not in allowed_numeric_literals:
                    return ["unsupported_numeric_assumption"]
    used = {node.slice.value for node in ast.walk(tree) if isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)}
    if set(required_fact_ids) - used:
        return ["required_input_not_referenced"]
    return []
