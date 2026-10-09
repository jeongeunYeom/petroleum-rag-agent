from __future__ import annotations

import re
from typing import Any

from app.services.engineering.types import ClaimValidationResult


class ReservoirValidator:
    """Conservative consistency checks for basic reservoir-engineering claims."""

    domain = "reservoir"
    name = "ReservoirValidator"
    _QUERY_RE = re.compile(
        r"porosity|permeability|relative\s+permeability|capillary\s+pressure|"
        r"(?:oil|water|gas)\s+saturation|\b(?:s[owg]|ooip|giip|pvt)\b|"
        r"material\s+balance|formation\s+volume\s+factor|compressibility|"
        r"drive\s+mechanism|solution[- ]gas\s+drive|gas[- ]cap\s+drive|"
        r"water\s+drive|darcy|volumetric\s+estimation|"
        r"공극률|투과도|상대\s*투과도|모세관\s*압력|포화도|물질\s*수지|"
        r"용적\s*계수|압축성|수추진|가스캡|용해가스",
        re.IGNORECASE,
    )
    _NEGATION_RE = re.compile(
        r"not\s+(?:necessarily|always|the\s+same)|does\s+not|is\s+not|"
        r"incorrect|false|아니|않|항상.{0,20}(?:아니|않)|잘못|틀",
        re.IGNORECASE,
    )
    _POROSITY_EQ_PERM_RE = re.compile(
        r"porosity\s+(?:means|is|equals?)\s+permeability|"
        r"porosity\s+(?:and|=)\s*permeability\s+(?:are\s+)?(?:the\s+)?same|"
        r"공극률(?:은|이|과|와)?\s*투과도(?:와|과)?\s*(?:같|동일|뜻)",
        re.IGNORECASE,
    )
    _POROSITY_ALWAYS_PERM_RE = re.compile(
        r"(?:higher|high|increasing)\s+porosity.{0,60}"
        r"(?:always|necessarily).{0,30}(?:higher|increasing)\s+permeability|"
        r"공극률(?:이|은)?\s*(?:높|증가).{0,50}투과도(?:도|가|는)?\s*"
        r"(?:항상|반드시).{0,20}(?:높|증가)",
        re.IGNORECASE,
    )
    _SATURATION_OVER_ONE_RE = re.compile(
        r"(?:saturation|s[owg]).{0,100}(?:sum|total|합).{0,30}"
        r"(?:>|exceed(?:s|ed)?|greater\s+than)\s*1(?:\.0)?|"
        r"(?:포화도|s[owg]).{0,100}(?:합|총합).{0,30}"
        r"(?:1(?:\.0)?\s*(?:초과|보다\s*크)|>\s*1)",
        re.IGNORECASE,
    )
    _DARCY_WRONG_DIRECTION_RE = re.compile(
        r"flow.{0,50}(?:from\s+)?low(?:er)?\s+pressure.{0,30}"
        r"(?:to|toward)\s+high(?:er)?\s+pressure|"
        r"낮은\s*압력.{0,30}높은\s*압력.{0,20}(?:흐|이동)",
        re.IGNORECASE,
    )
    _PERM_REDUCES_FLOW_RE = re.compile(
        r"(?:higher|increasing)\s+permeability.{0,50}"
        r"(?:decreases?|reduces?)\s+(?:fluid\s+)?flow|"
        r"투과도(?:가|는)?\s*(?:높|증가).{0,40}유동(?:률|량)?(?:이|을)?\s*(?:감소|줄)",
        re.IGNORECASE,
    )
    _FVF_REVERSED_RE = re.compile(
        r"formation\s+volume\s+factor.{0,100}"
        r"standard(?:-condition)?\s+volume\s*/\s*reservoir\s+volume|"
        r"용적\s*계수.{0,100}표준\s*상태\s*부피.{0,20}/.{0,20}저류층\s*부피",
        re.IGNORECASE,
    )

    def matches_query(self, query: str) -> bool:
        return bool(self._QUERY_RE.search(query or ""))

    def validate_claim(
        self,
        claim: str,
        evidence: str = "",
        *,
        evidence_conflict: bool = False,
        require_evidence_support: bool = True,
    ) -> ClaimValidationResult:
        reasons: list[dict[str, Any]] = []
        contradictions = 0
        unsupported = 0
        normalized = self._normalize(claim)

        checks = (
            (
                self._POROSITY_EQ_PERM_RE,
                "RES-POR-001",
                "Porosity and permeability are distinct properties.",
                "porosity = pore volume / bulk volume; permeability describes fluid-flow capacity",
            ),
            (
                self._SATURATION_OVER_ONE_RE,
                "RES-SAT-001",
                "Phase saturations cannot sum above one for the stated pore-volume system.",
                "for the active phases, their saturation fractions sum to 1",
            ),
            (
                self._DARCY_WRONG_DIRECTION_RE,
                "RES-DARCY-001",
                "The claim reverses the basic pressure-driven flow direction.",
                "Darcy flow follows decreasing pressure and opposes the pressure gradient",
            ),
            (
                self._PERM_REDUCES_FLOW_RE,
                "RES-DARCY-002",
                "The claim reverses the basic permeability/flow relation.",
                "under comparable conditions, easier flow generally accompanies higher permeability",
            ),
            (
                self._FVF_REVERSED_RE,
                "RES-PVT-001",
                "The formation-volume-factor ratio is reversed.",
                "formation volume factor relates reservoir-condition volume to standard-condition volume",
            ),
        )
        for pattern, code, message, expected in checks:
            if pattern.search(normalized) and not self._NEGATION_RE.search(normalized):
                contradictions += 1
                reasons.append(self._reason(code, "engineering_contradiction", claim, message, expected))

        if self._POROSITY_ALWAYS_PERM_RE.search(normalized) and not self._NEGATION_RE.search(normalized):
            unsupported += 1
            reasons.append(
                self._reason(
                    "RES-PERM-001",
                    "unsupported_engineering_claim",
                    claim,
                    "Porosity does not uniquely determine permeability.",
                    "porosity/permeability correlation is conditional on pore connectivity and structure",
                )
            )

        concepts = self._concepts(normalized)
        if require_evidence_support and concepts and not reasons:
            evidence_n = self._normalize(evidence)
            evidence_concepts = self._concepts(evidence_n)
            specifically_supported = bool(concepts & evidence_concepts)
            if "porosity_definition" in concepts:
                specifically_supported = bool(
                    re.search(r"pore\s+volume|공극\s*부피", evidence_n)
                    and re.search(r"bulk\s+volume|전체\s*부피", evidence_n)
                )
            elif "saturation_sum" in concepts:
                specifically_supported = bool(
                    re.search(r"s[owg]|oil.{0,20}water.{0,20}gas", evidence_n)
                    and re.search(r"(?:sum|total|합).{0,20}(?:=|is|은|는)?\s*1", evidence_n)
                )
            if not evidence or not specifically_supported:
                unsupported += 1
                reasons.append(
                    self._reason(
                        "RES-CITATION-MEANING",
                        "unsupported_engineering_claim",
                        claim,
                        "The cited evidence does not explicitly support this reservoir-engineering relation.",
                        "Use evidence that states the same reservoir property or relationship.",
                    )
                )

        if concepts and evidence_conflict and not re.search(
            r"may|might|depends|uncertain|conflict|조건|불확실|단정", normalized
        ):
            unsupported += 1
            reasons.append(
                self._reason(
                    "RES-EVIDENCE-CONFLICT",
                    "unsupported_engineering_claim",
                    claim,
                    "Conflicting evidence requires a qualified reservoir interpretation.",
                    "Report the conflicting evidence and avoid an unconditional conclusion.",
                )
            )

        return ClaimValidationResult(
            passed=not reasons,
            reasons=reasons,
            engineering_contradiction_count=contradictions,
            unsupported_engineering_claim_count=unsupported,
        )

    def detect_false_premises(self, question: str) -> list[dict[str, str]]:
        normalized = self._normalize(question)
        premises: list[dict[str, str]] = []
        candidates = (
            (
                self._POROSITY_EQ_PERM_RE,
                "RES-FALSE-POROSITY-PERMEABILITY",
                "porosity = pore volume / bulk volume; permeability describes fluid-flow capacity",
                "Porosity does not mean permeability.",
            ),
            (
                self._SATURATION_OVER_ONE_RE,
                "RES-FALSE-SATURATION-SUM",
                "for the active phases, their saturation fractions sum to 1",
                "Phase saturation fractions cannot sum above one in the stated system.",
            ),
            (
                self._POROSITY_ALWAYS_PERM_RE,
                "RES-FALSE-POROSITY-PERM",
                "higher porosity does not necessarily imply higher permeability; pore connectivity and structure matter",
                "The claimed necessary porosity/permeability relation is invalid.",
            ),
        )
        for pattern, code, expected, message in candidates:
            if pattern.search(normalized) and not self._NEGATION_RE.search(normalized):
                premises.append(
                    {
                        "domain": self.domain,
                        "rule_id": code,
                        "code": code,
                        "failed_claim": question,
                        "message": message,
                        "expected_engineering_relation": expected,
                    }
                )
        return premises

    def false_premise_correction(
        self,
        question: str,
        answer: str,
    ) -> tuple[bool, bool, list[dict[str, str]]]:
        premises = self.detect_false_premises(question)
        if not premises:
            return False, True, []
        answer_n = self._normalize(answer)
        failures = [
            {
                **premise,
                "message": (
                    "The answer must reject the false reservoir premise and state the "
                    f"supported conditional relation: {premise['expected_engineering_relation']}."
                ),
            }
            for premise in premises
            if not (
                self._NEGATION_RE.search(answer_n)
                and self._correction_terms_present(premise["rule_id"], answer_n)
            )
        ]
        return True, not failures, failures

    def expected_relations(self, query: str) -> list[str]:
        normalized = self._normalize(query)
        relations: list[str] = []
        if "porosity" in normalized or "공극률" in normalized:
            relations.append("porosity = pore volume / bulk volume")
        if re.search(r"saturation|포화도|s[owg]", normalized):
            relations.append("for the active phases, their saturation fractions sum to 1")
        if "permeability" in normalized or "투과도" in normalized:
            relations.append("permeability describes fluid-flow capacity, not pore-volume fraction")
        return relations

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").lower()).strip()

    @classmethod
    def _concepts(cls, value: str) -> set[str]:
        concepts: set[str] = set()
        patterns = {
            "porosity": r"porosity|공극률",
            "permeability": r"permeability|투과도",
            "saturation": r"saturation|포화도|\bs[owg]\b",
            "darcy": r"darcy|pressure\s+gradient|압력\s*구배",
            "formation_volume_factor": r"formation\s+volume\s+factor|용적\s*계수",
            "material_balance": r"material\s+balance|물질\s*수지|질량\s*보존",
            "drive_mechanism": r"solution[- ]gas\s+drive|gas[- ]cap\s+drive|water\s+drive|용해가스|가스캡|수추진",
            "compressibility": r"compressibility|압축성",
        }
        for concept, pattern in patterns.items():
            if re.search(pattern, value, re.IGNORECASE):
                concepts.add(concept)
        if "porosity" in concepts and re.search(r"pore\s+volume|공극\s*부피", value):
            concepts.add("porosity_definition")
        if "saturation" in concepts and re.search(r"(?:sum|total|합).{0,20}(?:=|is|to|은|는)?\s*1", value):
            concepts.add("saturation_sum")
        return concepts

    @staticmethod
    def _correction_terms_present(rule_id: str, answer: str) -> bool:
        if rule_id == "RES-FALSE-SATURATION-SUM":
            return bool(re.search(r"saturation|포화도|s[owg]", answer) and re.search(r"(?:sum|합).{0,20}1", answer))
        if rule_id == "RES-FALSE-POROSITY-PERM":
            return bool(re.search(r"porosity|공극률", answer) and re.search(r"connectivity|structure|연결|구조", answer))
        return bool(
            re.search(r"porosity|공극률", answer)
            and re.search(r"pore\s+volume|공극\s*부피", answer)
            and re.search(r"permeability|투과도", answer)
        )

    @staticmethod
    def _reason(
        code: str,
        category: str,
        claim: str,
        message: str,
        expected_relation: str,
    ) -> dict[str, Any]:
        return {
            "domain": "reservoir",
            "code": code,
            "rule_id": code,
            "category": category,
            "claim": claim,
            "message": message,
            "expected_engineering_relation": expected_relation,
        }
