from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    domain: str
    code: str
    claim: str
    reason: str
    expected_relation: str = ""
    severity: str = "error"


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)


@dataclass
class ClaimValidationResult:
    passed: bool
    reasons: list[dict[str, Any]] = field(default_factory=list)
    engineering_contradiction_count: int = 0
    unsupported_engineering_claim_count: int = 0
