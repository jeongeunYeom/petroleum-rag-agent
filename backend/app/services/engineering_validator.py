"""Compatibility facade for domain-specific engineering validators."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.services.engineering import (
    ClaimValidationResult,
    EngineeringValidatorRegistry,
    DrillingValidator,
    ReservoirValidator,
    ValidationResult,
    WellTestValidator,
)
from app.services.refusal_policy import STRICT_REFUSAL


class EngineeringValidator:
    def __init__(self, registry: EngineeringValidatorRegistry | None = None) -> None:
        self.well_test = WellTestValidator()
        self.reservoir = ReservoirValidator()
        self.drilling = DrillingValidator()
        self.registry = registry or EngineeringValidatorRegistry(
            [self.well_test, self.reservoir, self.drilling]
        )

    def validators_for(self, query: str) -> list[Any]:
        return self.registry.route(query)

    def engineering_domains(self, query: str) -> list[str]:
        return self.registry.domains(query)

    def engineering_validator_names(self, query: str) -> list[str]:
        return self.registry.validator_names(query)

    def validate_claim(
        self,
        claim: str,
        evidence: str = "",
        *,
        query: str = "",
        evidence_conflict: bool = False,
        require_evidence_support: bool = True,
    ) -> ClaimValidationResult:
        return self.registry.validate_claim(
            query or claim,
            claim,
            evidence,
            evidence_conflict=evidence_conflict,
            require_evidence_support=require_evidence_support,
        )

    def detect_false_premises(self, question: str) -> list[dict[str, str]]:
        return self.registry.detect_false_premises(question)

    def false_premise_correction(
        self,
        question: str,
        answer: str,
    ) -> tuple[bool, bool, list[dict[str, str]]]:
        return self.registry.false_premise_correction(question, answer)

    def validate_well_test_answer(
        self,
        question: str,
        answer: str,
        *,
        retrieved_sources: Iterable[Mapping[str, Any]] | None = None,
    ) -> ValidationResult:
        return self.well_test.validate_well_test_answer(
            question,
            answer,
            retrieved_sources=retrieved_sources,
        )

    @staticmethod
    def regimes_in_text(value: str) -> set[str]:
        return WellTestValidator.regimes_in_text(value)

    @staticmethod
    def expected_relation(regime: str) -> str:
        return WellTestValidator.expected_relation(regime)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.well_test, name)


__all__ = [
    "ClaimValidationResult",
    "EngineeringValidator",
    "STRICT_REFUSAL",
    "ValidationResult",
]
