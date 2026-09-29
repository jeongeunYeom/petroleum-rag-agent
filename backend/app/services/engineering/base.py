from __future__ import annotations

from typing import Protocol

from app.services.engineering.types import ClaimValidationResult


class DomainValidator(Protocol):
    domain: str
    name: str

    def matches_query(self, query: str) -> bool: ...

    def validate_claim(
        self,
        claim: str,
        evidence: str = "",
        *,
        evidence_conflict: bool = False,
        require_evidence_support: bool = True,
    ) -> ClaimValidationResult: ...

    def detect_false_premises(self, question: str) -> list[dict[str, str]]: ...

    def false_premise_correction(
        self,
        question: str,
        answer: str,
    ) -> tuple[bool, bool, list[dict[str, str]]]: ...
