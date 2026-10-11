"""Strict development-only acceptance checks for autonomous calculation runs."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ExpectedRun:
    intent: str
    source_requirement: str
    actions: tuple[str, ...]
    facts: tuple[str, ...] = ()
    output: float | None = None
    unit: str | None = None
    resume: bool = False
    fact_values: tuple[tuple[str, float, str], ...] = ()
    operation: str | None = None
    missing_variables: tuple[str, ...] = ()


def assess(observed: dict, expected: ExpectedRun) -> dict:
    """A correct intermediate number never substitutes for a completed goal."""
    actions = observed.get("actions") or []
    expected_actions = list(expected.actions)
    sequence = iter(actions)
    action_pass = all(any(action == candidate for candidate in sequence)
                      for action in expected_actions)
    facts = set(observed.get("facts") or [])
    fact_values = observed.get("fact_values") or {}
    numeric = observed.get("numeric")
    answer = str(observed.get("answer") or "")
    numeric_pass = expected.output is None or (
        isinstance(numeric, (int, float)) and
        math.isclose(numeric, expected.output, rel_tol=1e-6, abs_tol=1e-8))
    reported = [float(match.group()) for match in re.finditer(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", answer)]
    adoption = bool(answer.strip()) and (expected.output is None or (
        bool(re.search(r"\[CALC\d+\]", answer)) and any(
            math.isclose(value, expected.output, rel_tol=1e-4, abs_tol=0.011)
            for value in reported)))
    checks = {
        "intent_pass": observed.get("intent") == expected.intent,
        "source_requirement_pass": observed.get("source_requirement") == expected.source_requirement,
        "fact_pass": set(expected.facts) <= facts and all(
            name in fact_values and fact_values[name][1] == unit and
            math.isclose(float(fact_values[name][0]), value, rel_tol=0, abs_tol=1e-9)
            for name, value, unit in expected.fact_values),
        "action_pass": action_pass,
        "operation_pass": expected.operation is None or expected.operation in
                          str(observed.get("operation") or "").split(","),
        "binding_pass": bool(observed.get("binding_pass")),
        "calc_validated": bool(observed.get("calc_validated")),
        "numeric_pass": numeric_pass,
        "unit_pass": expected.unit is None or (observed.get("unit") == expected.unit and
                                                expected.unit in answer),
        "provenance_complete": bool(observed.get("provenance_complete")),
        "final_answer_adopted": adoption,
        "run_completed": observed.get("run_status") == "completed",
        "goal_achieved": observed.get("status") == "achieved" and
                         observed.get("stop_reason") == "goal_achieved",
    }
    if expected.resume:
        checks.update({
            "initial_waiting": bool(observed.get("initial_waiting")),
            "missing_variable_pass": bool(observed.get("missing_variable_pass")) and all(
                any(variable.casefold() in item.casefold() for item in observed.get("required_inputs") or [])
                for variable in expected.missing_variables),
            "same_run": bool(observed.get("same_run")),
            "prior_facts_kept": bool(observed.get("prior_facts_kept")),
            "followup_facts_merged": bool(observed.get("followup_facts_merged")),
        })
    checks["overall_pass"] = all(checks.values())
    checks["failure_stage"] = next((name for name, passed in checks.items() if not passed), "")
    return checks
