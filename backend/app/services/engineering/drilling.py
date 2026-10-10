"""Evidence-gated mud/formation pressure premise checks."""

from __future__ import annotations

import re

from app.services.engineering.types import ClaimValidationResult


class DrillingValidator:
    domain = "drilling"
    name = "DrillingValidator"
    _topic = re.compile(r"\bkick(?:\b|[가-힣])|\bwell\s*control\b|\bmud\s*(?:pressure|weight|hydrostatic)\b|킥|이수압", re.I)
    _wrong = re.compile(
        r"(?:mud|hydrostatic|이수압|정수압).{0,75}(?:higher|greater|above|exceed|높|크).{0,75}"
        r"(?:formation|pore|지층압|공극압)|"
        r"(?:formation|pore|지층압|공극압).{0,75}(?:lower|less|below|낮|작).{0,75}"
        r"(?:mud|hydrostatic|이수압|정수압)|"
        r"(?:mud|hydrostatic|이수압|정수압).{0,75}(?:formation|pore|지층압|공극압)"
        r".{0,15}(?:보다|than).{0,20}(?:높|크|higher|greater)", re.I)
    _correct = re.compile(
        r"(?:formation|pore|지층압|공극압).{0,75}(?:higher|greater|above|exceed|높|크).{0,75}"
        r"(?:mud|hydrostatic|이수압|정수압)|"
        r"(?:mud|hydrostatic|이수압|정수압).{0,75}(?:lower|less|below|낮|작).{0,75}"
        r"(?:formation|pore|지층압|공극압)|"
        r"(?:formation|pore|지층압|공극압).{0,75}(?:mud|hydrostatic|이수압|정수압)"
        r".{0,15}(?:보다|than).{0,20}(?:높|크|higher|greater)|"
        r"(?:underbalanced|압력이\s*부족|정수압이\s*공극압보다\s*낮)", re.I)
    _rejection = re.compile(r"\b(?:not|incorrect|false|wrong|rather\s+than)\b|아니|틀|잘못|반대", re.I)

    def matches_query(self, query: str) -> bool:
        return bool(self._topic.search(query or ""))

    def detect_false_premises(self, question: str) -> list[dict[str, str]]:
        if not self.matches_query(question) or not self._wrong.search(question) or self._rejection.search(question):
            return []
        return [{"domain": self.domain, "rule_id": "DRILL-KICK-PRESSURE",
                 "failed_claim": question,
                 "expected_engineering_relation": "Kick risk occurs when formation/pore pressure exceeds mud hydrostatic pressure."}]

    def false_premise_correction(self, question: str, answer: str) -> tuple[bool, bool, list[dict[str, str]]]:
        premises = self.detect_false_premises(question)
        if not premises:
            return False, True, []
        corrected = bool(self._rejection.search(answer) and self._correct.search(answer))
        return True, corrected, [] if corrected else [{**premises[0],
            "message": "Explicitly reject the reversed pressure relation and state the supported kick condition."}]

    def grounded_correction(self, question: str, evidence: list[dict], korean: bool) -> str | None:
        """Use a fixed relation only when a cited passage states that relation."""
        if not self.detect_false_premises(question):
            return None
        for row in evidence:
            if row.get("source_type") not in {"knowledge_base", "web", "figure"}:
                continue
            source_text = str(row.get("text") or "")
            if not self._topic.search(source_text) or not self._correct.search(source_text):
                continue
            source_id = str(row["evidence_id"])
            if korean:
                return ("그 전제는 잘못되었습니다.\n"
                        "Kick은 지층압(공극압)이 이수의 정수압보다 높아 유체가 유입될 때 "
                        f"발생할 수 있습니다. [{source_id}]")
            return ("That premise is incorrect.\n"
                    "A kick may occur when formation (pore) pressure exceeds mud hydrostatic "
                    f"pressure and fluid enters the wellbore. [{source_id}]")
        return None

    def validate_claim(self, claim: str, evidence: str = "", *, evidence_conflict: bool = False,
                       require_evidence_support: bool = True) -> ClaimValidationResult:
        if not self.matches_query(claim):
            return ClaimValidationResult(passed=True, reasons=[], engineering_contradiction_count=0,
                                         unsupported_engineering_claim_count=0)
        wrong = bool(self._wrong.search(claim) and not self._rejection.search(claim))
        correct = bool(self._correct.search(claim))
        unsupported = bool(correct and require_evidence_support and not self._correct.search(evidence))
        reasons = []
        if wrong:
            reasons.append({"code": "DRILL-KICK-REVERSED", "type": "engineering_contradiction",
                            "message": "The mud/formation pressure relation for kick risk is reversed.",
                            "expected_engineering_relation": "Formation pressure exceeds mud hydrostatic pressure."})
        if unsupported:
            reasons.append({"code": "DRILL-KICK-CITATION", "type": "unsupported_engineering_claim",
                            "message": "The cited passage does not state the corrected pressure relation."})
        return ClaimValidationResult(passed=not reasons, reasons=reasons,
                                     engineering_contradiction_count=int(wrong),
                                     unsupported_engineering_claim_count=int(unsupported))
