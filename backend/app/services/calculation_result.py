"""Authoritative validation of the executed calculation's output manifest."""

from __future__ import annotations

import math
from typing import Any

from app.models.goal_research_schemas import CalculationContract


class CalculationResultError(ValueError):
    def __init__(self, reason: str, missing_output_ids: list[str] | None = None,
                 unused_required_input_ids: list[str] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.missing_output_ids = missing_output_ids or []
        self.unused_required_input_ids = unused_required_input_ids or []


def validate_calculation_result(data: Any, contract: CalculationContract) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict) or data.get("contract_id") != contract.contract_id:
        raise CalculationResultError("calculation_contract_id_mismatch")
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        raise CalculationResultError("CALC_INCOMPLETE_OUTPUTS", [item.output_id for item in contract.required_outputs if item.required])
    missing = [item.output_id for item in contract.required_outputs if item.required and item.output_id not in outputs]
    if missing:
        raise CalculationResultError("CALC_INCOMPLETE_OUTPUTS", missing)
    required_inputs = set(contract.input_fact_ids)
    used_inputs = data.get("used_input_ids")
    if not isinstance(used_inputs, list) or any(not isinstance(value, str) for value in used_inputs):
        raise CalculationResultError("required_input_not_used", sorted(required_inputs))
    unused = sorted(required_inputs - set(used_inputs))
    if unused:
        raise CalculationResultError("required_input_not_used", unused_required_input_ids=unused)
    if set(used_inputs) - required_inputs:
        raise CalculationResultError("unknown_input_used")
    if data.get("used_formula_id") != contract.formula_id:
        raise CalculationResultError("formula_contract_mismatch")
    manifest: dict[str, dict[str, Any]] = {}
    for spec in contract.required_outputs:
        if spec.output_id not in outputs:
            continue
        entry = outputs[spec.output_id]
        if not isinstance(entry, dict) or "value" not in entry:
            raise CalculationResultError("output_value_missing")
        value = entry["value"]
        match spec.semantic_type:
            case "numeric":
                valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            case "boolean":
                valid = isinstance(value, bool)
            case "label":
                valid = isinstance(value, str) and bool(value.strip())
            case "list" | "ranking":
                valid = isinstance(value, list) and bool(value) and all(
                    isinstance(item, (str, int, float, bool)) and (not isinstance(item, float) or math.isfinite(item))
                    for item in value
                )
            case _:
                valid = False
        if not valid:
            raise CalculationResultError("output_type_or_value_invalid")
        observed_unit = entry.get("unit")
        if spec.unit is not None and not observed_unit:
            raise CalculationResultError("output_unit_missing")
        if spec.unit is not None and str(observed_unit).casefold() != spec.unit.casefold():
            raise CalculationResultError("output_unit_mismatch")
        manifest[spec.output_id] = {
            "name": spec.name, "value": value, "unit": spec.unit,
            "semantic_type": spec.semantic_type, "required": spec.required,
            "scenario_id": spec.scenario_id, "source_fact_ids": spec.source_fact_ids,
            "formula_id": spec.formula_id or contract.formula_id,
        }
    return manifest
