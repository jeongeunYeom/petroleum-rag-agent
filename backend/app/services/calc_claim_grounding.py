"""Check that each CALC-cited final claim names an actual validated output."""

from __future__ import annotations

import math
import re
from typing import Any

from app.models.goal_research_schemas import ComputationRecord


NUMERIC = re.compile(r"(?<![A-Za-z_\d.])[-+]?(?:\d+(?:,\d{3})*(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![A-Za-z_\d.])")
ARITHMETIC = re.compile(r"calculat|difference|change|average|mean|rms|ratio|percent|계산|차이|변화율|평균", re.I)


def _matches_reported_value(match: re.Match[str], value: float) -> bool:
    reported = float(match.group().replace(",", ""))
    if math.isclose(reported, value, rel_tol=1e-5, abs_tol=1e-8):
        return True
    # Two-or-more decimal places are a display rounding, not a new measurement.
    literal = match.group().replace(",", "")
    if "." not in literal or "e" in literal.casefold():
        return False
    places = len(literal.split(".", 1)[1])
    return places >= 2 and reported == round(value, places)


def validate_calc_claim(claim: str, citations: list[str], output_ids: list[str],
                        computations: dict[str, ComputationRecord],
                        evidence: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    adopted: list[str] = []
    cited_calcs = [computations[value] for value in citations if value in computations]
    user_sources = {str(item["evidence_id"]): item for item in evidence if item.get("source_type") == "user_fact"}
    numeric_claim = re.sub(r"(?<!\w)\d+\s+(?:measurements|stations|cases|readings|wells)\b", " ", claim, flags=re.I)
    number_matches = list(NUMERIC.finditer(numeric_claim))
    numbers = [float(match.group().replace(",", "")) for match in number_matches]
    if not cited_calcs:
        if numbers and user_sources and not any(value in user_sources for value in citations):
            user_values = [float(item["value"]) for item in user_sources.values() if "value" in item]
            if ARITHMETIC.search(claim) or any(math.isclose(number, value, rel_tol=1e-9, abs_tol=1e-9)
                                               for number in numbers for value in user_values):
                issues.append("provenance_attribution_error")
        return issues, adopted
    if all(not item.output_manifest for item in cited_calcs):
        return issues, adopted

    available = {f"{record.computation_id}:{output_id}": (record, spec)
                 for record in cited_calcs for output_id, spec in record.output_manifest.items()}
    known_units = {str(spec["unit"]).casefold() for _, spec in available.values() if spec.get("unit")}
    known_units.update({"psi", "md", "ft", "stb/d/psi", "psi/ft", "percent", "percentage_point", "%", "kpa", "pa"})
    local_units = []
    for match in number_matches:
        following = re.match(r"\s*([A-Za-z%][A-Za-z0-9_/%^.-]*)", numeric_claim[match.end():])
        observed_unit = following.group(1).rstrip(".,;").casefold() if following else ""
        if observed_unit and observed_unit in known_units:
            local_units.append((float(match.group().replace(",", "")), observed_unit))
    resolved_ids: list[str] = []
    for value in output_ids:
        matches = [key for key in available if key == value or key.endswith(f":{value}")]
        if len(matches) != 1:
            issues.append("calc_output_not_found")
        else:
            resolved_ids.append(matches[0])
    output_ids = resolved_ids
    if issues:
        return issues, adopted
    if not output_ids and numbers:
        # Prefer a semantic name match; numeric coincidence alone is not sufficient when named outputs exist.
        named = [value for value, (_, spec) in available.items()
                 if str(spec.get("name", "")).replace("_", " ").casefold() in claim.casefold()]
        if not named and re.search(r"\b(?:mean|average|rms|maximum|max|difference|ratio|sum)\b", claim, re.I):
            issues.append("calc_output_not_found")
            return issues, adopted
        output_ids = named or [value for value, (_, spec) in available.items()
                               if spec.get("semantic_type") == "numeric" and any(
                                   _matches_reported_value(match, float(spec["value"]))
                                   for match in number_matches)]
        if not output_ids:
            issues.append("calc_output_not_found")
            return issues, adopted
    if not output_ids and ARITHMETIC.search(claim):
        issues.append("calc_output_not_found")
        return issues, adopted

    matched_numbers: list[float] = []
    for output_id in output_ids:
        record, spec = available[output_id]
        value = spec["value"]
        semantic = next((key for key in ("mean", "rms", "max", "ratio", "sum", "difference")
                         if re.search(rf"\b{key}(?:imum)?\b", claim, re.I)), None)
        if semantic and semantic not in str(spec.get("name", "")).casefold():
            issues.append("calc_output_not_found")
            continue
        if spec.get("semantic_type") == "numeric":
            if not isinstance(value, (int, float)) or not any(
                _matches_reported_value(match, float(value)) for match in number_matches
            ):
                issues.append("calc_value_mismatch")
                continue
            matched_numbers.append(float(value))
            unit = str(spec.get("unit") or "")
            value_units = [observed_unit for number, observed_unit in local_units
                           if math.isclose(number, float(value), rel_tol=1e-5, abs_tol=1e-8)]
            if unit and unit != "dimensionless" and (
                (value_units and unit.casefold() not in value_units)
                or (not value_units and not re.search(rf"(?<!\w){re.escape(unit)}(?!\w)", claim, re.I))
            ):
                issues.append("calc_unit_mismatch")
                continue
        elif isinstance(value, list):
            if not all(str(part).casefold() in claim.casefold() for part in value):
                issues.append("calc_value_mismatch")
                continue
            if value and all(isinstance(part, str) and re.fullmatch(r"[A-Za-z]+\d+", part) for part in value):
                prefix = re.match(r"[A-Za-z]+", value[0]).group()
                observed_labels = set(re.findall(rf"\b{re.escape(prefix)}\d+\b", claim, re.I))
                if {part.casefold() for part in observed_labels} != {part.casefold() for part in value}:
                    issues.append("calc_value_mismatch")
                    continue
        elif isinstance(value, (str, bool)) and str(value).casefold() not in claim.casefold():
            issues.append("calc_value_mismatch")
            continue
        sources = set(spec.get("source_fact_ids") or [])
        source_map = {str(item.get("canonical_fact_id") or item.get("evidence_id")): str(item.get("evidence_id"))
                      for item in record.input_facts}
        required_sources = {source_map.get(value, value) for value in sources}
        required_sources.update(record.formula_evidence_ids)
        if not required_sources.issubset(citations):
            issues.append("provenance_attribution_error")
            continue
        adopted.append(output_id)
    if any(not any(_matches_reported_value(match, value) for value in matched_numbers)
           for match in number_matches):
        issues.append("calc_value_mismatch")
    return list(dict.fromkeys(issues)), list(dict.fromkeys(adopted))
