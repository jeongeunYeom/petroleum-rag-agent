"""Keep internal response-schema instructions out of user-facing research text."""

from __future__ import annotations

import re
from typing import Any


LEAK = re.compile(
    r"\b(?:output_ids|source_fact_ids|expected_hypothesis|expected_result|structured goal evaluation|"
    r"response schema|system instruction|untrusted evidence|untrusted data|"
    r"every material claim must|return json|cite every material claim|"
    r"hypothesis_assessment|frozen_criteria|calc_[a-z_]+|formula_variable_[a-z_]+|"
    r"source_complete|calculation_plan|underlying source evidence citations)\b",
    re.IGNORECASE,
)


def leaked_text(value: str, user_text: str = "") -> bool:
    return any(match.group().casefold() not in user_text.casefold() for match in LEAK.finditer(value))


def synthesis_has_leak(candidate: dict[str, Any], user_text: str = "") -> bool:
    claims = [str(item.get("claim") or "") for item in candidate.get("claims", [])]
    claims.append(str((candidate.get("hypothesis_assessment") or {}).get("claim") or ""))
    claims.extend(str(item) for item in candidate.get("limitations", []))
    return any(leaked_text(value, user_text) for value in claims)


def strip_synthesis_leaks(candidate: dict[str, Any], user_text: str = "") -> dict[str, Any]:
    cleaned = dict(candidate)
    cleaned["claims"] = [item for item in candidate.get("claims", [])
                         if not leaked_text(str(item.get("claim") or ""), user_text)]
    assessment = candidate.get("hypothesis_assessment") or {}
    cleaned["hypothesis_assessment"] = {} if leaked_text(str(assessment.get("claim") or ""), user_text) else assessment
    cleaned["limitations"] = [item for item in candidate.get("limitations", [])
                              if not leaked_text(str(item), user_text)]
    return cleaned
