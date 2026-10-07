"""Trusted generic operations and sandbox-compatible code templates."""

from __future__ import annotations

import math
import re

from app.models.goal_research_schemas import CalculationContract
from app.services.goal_tool_planner import PythonAnalysisPlan


OPERATIONS = frozenset({"add", "subtract", "multiply", "divide", "ratio", "percent_change",
    "normalize_by_max", "mean", "median", "sum", "minimum", "maximum", "range", "rms",
    "variance_population", "std_population", "std_sample", "coefficient_of_variation",
    "ranking", "leader_ids", "linear_regression", "slope", "intercept", "r_squared", "difference", "result"})

MIN_ARITY = {"result": 1, "subtract": 2, "difference": 2, "divide": 2, "ratio": 2,
             "percent_change": 2, "std_sample": 2, "range": 2, "variance_population": 2,
             "std_population": 2, "coefficient_of_variation": 2}


def tie_leaders(values: dict[str, float], *, rel_tol: float = 1e-9, abs_tol: float = 1e-12) -> list[str]:
    maximum = max(values.values())
    return sorted(key for key, value in values.items()
                  if math.isclose(value, maximum, rel_tol=rel_tol, abs_tol=abs_tol))


def tie_ranking(values: dict[str, float]) -> list[str]:
    groups: list[list[str]] = []
    for key in sorted(values, key=lambda item: (-values[item], item)):
        if groups and math.isclose(values[key], values[groups[-1][0]], rel_tol=1e-9, abs_tol=1e-12):
            groups[-1].append(key)
        else:
            groups.append([key])
    return ["=".join(sorted(group)) for group in groups]


EXPRESSIONS = {
    "add": "sum(selected)", "sum": "sum(selected)", "subtract": "selected[0] - selected[1]",
    "difference": "selected[0] - selected[1]", "multiply": "math.prod(selected)",
    "divide": "selected[0] / selected[1]", "ratio": "selected[0] / selected[1]",
    "percent_change": "(selected[1] - selected[0]) / selected[0] * 100",
    "normalize_by_max": "[value / max(selected) for value in selected]",
    "mean": "statistics.mean(selected)", "median": "statistics.median(selected)",
    "minimum": "min(selected)", "maximum": "max(selected)",
    "range": "max(selected) - min(selected)",
    "rms": "math.sqrt(statistics.mean([value * value for value in selected]))",
    "variance_population": "statistics.pvariance(selected)",
    "std_population": "statistics.pstdev(selected)", "std_sample": "statistics.stdev(selected)",
    "coefficient_of_variation": "statistics.pstdev(selected) / statistics.mean(selected) * 100",
    "slope": "regression.slope", "intercept": "regression.intercept",
    "r_squared": "correlation * correlation",
    "result": "selected[0]",
}


def generic_code(plan: PythonAnalysisPlan, contract: CalculationContract, output_json: str) -> str | None:
    if contract.formula_id or contract.operation_type not in {"generic_arithmetic", "generic_statistics"}:
        return None
    facts = {fact.canonical_fact_id or fact.evidence_id: {"value": fact.value, "unit": fact.unit}
             for fact in plan.input_facts}
    if not facts or any(item.name.removeprefix(f"{item.scenario_id}_" if item.scenario_id else "") not in OPERATIONS
                        for item in contract.required_outputs):
        return None
    lines = ["import json, math, statistics", f"facts = {facts!r}",
             "values = [" + ", ".join(f"facts[{key!r}]['value']" for key in facts) + "]",
             "by_case = {}"]
    for scenario in contract.scenarios:
        keys = list(dict.fromkeys(scenario.input_bindings.values()))
        lines.append(f"by_case[{scenario.scenario_id!r}] = [" +
                     ", ".join(f"facts[{key!r}]['value']" for key in keys) + "]")
    lines.extend(["scores = {key: values[0] for key, values in by_case.items() if len(values) == 1}",
                  "leaders = sorted(key for key, value in scores.items() if math.isclose(value, max(scores.values()), rel_tol=1e-9, abs_tol=1e-12)) if scores else []",
                  "rank_groups = []",
                  "for key in sorted(scores, key=lambda item: (-scores[item], item)):",
                  "    if rank_groups and math.isclose(scores[key], scores[rank_groups[-1][0]], rel_tol=1e-9, abs_tol=1e-12):",
                  "        rank_groups[-1].append(key)",
                  "    else:",
                  "        rank_groups.append([key])",
                  "ranking = ['='.join(sorted(group)) for group in rank_groups]", "outputs = {}"])
    if any(item.name in {"slope", "intercept", "r_squared"} for item in contract.required_outputs):
        pairs: dict[str, dict[str, str]] = {}
        for fact in plan.input_facts:
            match = re.fullmatch(r"(?i)(?:(?P<axis1>[xy])_?(?P<index1>\d+)|(?P<index2>[A-Za-z0-9]+)_(?P<axis2>[xy]))", fact.name)
            if match:
                pairs.setdefault(match.group("index1") or match.group("index2"), {})[(match.group("axis1") or match.group("axis2")).casefold()] = fact.canonical_fact_id or fact.evidence_id
        ordered = [pairs[key] for key in sorted(pairs) if set(pairs[key]) == {"x", "y"}]
        if len(ordered) < 2 or len(ordered) * 2 != len(plan.input_facts):
            return None
        lines.extend(["xs = [" + ", ".join(f"facts[{pair['x']!r}]['value']" for pair in ordered) + "]",
                      "ys = [" + ", ".join(f"facts[{pair['y']!r}]['value']" for pair in ordered) + "]",
                      "regression = statistics.linear_regression(xs, ys)",
                      "correlation = statistics.correlation(xs, ys)"])
    for spec in contract.required_outputs:
        operation = spec.name.removeprefix(f"{spec.scenario_id}_" if spec.scenario_id else "")
        available = len(next((scenario.input_bindings for scenario in contract.scenarios
                              if scenario.scenario_id == spec.scenario_id), {})) if spec.scenario_id else len(facts)
        if available < MIN_ARITY.get(operation, 1) or (operation == "result" and available != 1):
            return None
        lines.append(f"selected = by_case[{spec.scenario_id!r}]" if spec.scenario_id else "selected = values")
        expression = ("ranking" if operation == "ranking" else "leaders" if operation == "leader_ids"
                      else EXPRESSIONS.get(operation))
        if expression is None:
            return None
        lines.append(f"outputs[{spec.output_id!r}] = {{'value': {expression}, 'unit': {spec.unit!r}}}")
    lines.append(f"with open({output_json!r}, 'w') as output:")
    lines.append("    json.dump({" + f"'contract_id': {contract.contract_id!r}, 'outputs': outputs, "
                 + f"'used_input_ids': {contract.input_fact_ids!r}, 'used_formula_id': None, "
                 + "'summary': 'Generic calculation from verified inputs.'}, output)")
    return "\n".join(lines) + "\n"
