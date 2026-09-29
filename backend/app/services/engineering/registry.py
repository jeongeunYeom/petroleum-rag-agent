from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services.engineering.base import DomainValidator
from app.services.engineering.types import ClaimValidationResult


class EngineeringValidatorRegistry:
    def __init__(self, validators: Iterable[DomainValidator] = ()) -> None:
        self._validators: dict[str, DomainValidator] = {}
        for validator in validators:
            self.register(validator)

    def register(self, validator: DomainValidator) -> None:
        self._validators.setdefault(validator.domain, validator)

    def route(self, query: str) -> list[DomainValidator]:
        return [
            validator
            for validator in self._validators.values()
            if validator.matches_query(query)
        ]

    def domains(self, query: str) -> list[str]:
        return [validator.domain for validator in self.route(query)]

    def validator_names(self, query: str) -> list[str]:
        return [validator.name for validator in self.route(query)]

    def validate_claim(
        self,
        query: str,
        claim: str,
        evidence: str = "",
        *,
        evidence_conflict: bool = False,
        require_evidence_support: bool = True,
    ) -> ClaimValidationResult:
        reasons: list[dict[str, Any]] = []
        contradictions = 0
        unsupported = 0
        seen: set[tuple[str, str, str]] = set()
        for validator in self.route(query or claim):
            result = validator.validate_claim(
                claim,
                evidence,
                evidence_conflict=evidence_conflict,
                require_evidence_support=require_evidence_support,
            )
            contradictions += result.engineering_contradiction_count
            unsupported += result.unsupported_engineering_claim_count
            for raw in result.reasons:
                reason = {
                    "domain": validator.domain,
                    "code": str(raw.get("code") or raw.get("rule_id") or ""),
                    **raw,
                    "claim": str(raw.get("claim") or raw.get("failed_claim") or claim),
                }
                key = (reason["domain"], reason["code"], reason["claim"])
                if key not in seen:
                    seen.add(key)
                    reasons.append(reason)
        return ClaimValidationResult(
            passed=not reasons,
            reasons=reasons,
            engineering_contradiction_count=contradictions,
            unsupported_engineering_claim_count=unsupported,
        )

    def detect_false_premises(self, question: str) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for validator in self.route(question):
            for raw in validator.detect_false_premises(question):
                reason = {
                    "domain": validator.domain,
                    "code": str(raw.get("code") or raw.get("rule_id") or ""),
                    **raw,
                }
                key = (
                    reason["domain"],
                    reason["code"],
                    str(reason.get("failed_claim") or question),
                )
                if key not in seen:
                    seen.add(key)
                    results.append(reason)
        return results

    def false_premise_correction(
        self,
        question: str,
        answer: str,
    ) -> tuple[bool, bool, list[dict[str, str]]]:
        detected = False
        corrected = True
        failures: list[dict[str, str]] = []
        for validator in self.route(question):
            local_detected, local_corrected, local_failures = (
                validator.false_premise_correction(question, answer)
            )
            detected = detected or local_detected
            corrected = corrected and local_corrected
            failures.extend(
                {"domain": validator.domain, **failure}
                for failure in local_failures
            )
        return detected, corrected, failures
