"""Conservative literal answers: match every requested relation, not topic overlap alone."""
import re
from dataclasses import asdict, dataclass, field
from enum import Enum

from app.services.goal_action_planner import ENGINEERING_TERMS
from app.services.goal_intent import explicitly_underdetermined, prefers_korean


STOP = set("what why how does do is are the a an of for to and in with from explain describe define purpose function definition please internal source sources evidence relationship relation provide about its determine exact optimal value needed inputs data missing not provided without no calculate find".split())
STOP.update({"requested", "result", "supported", "answer", "validated"})
STOP.update("state discuss tell me us please briefly according using cited material materials text explain explanation describe description identify give precise can be could would should when which required unavailable information engineering grounded citation citations correctly include whether between affects affect".split())
RELATIONS = {
    "definition": r"\b(?:means|defined|refers|is|are)\b|정의|의미|이다|입니다",
    "function": r"\b(?:prevents?|reduces?|separates?|removes?|protects?|measures?|controls?|allows?|function|purpose)\b|방지|측정|제거|보호|분리|역할|기능",
    "dependency": r"\b(?:depends?|requires?|site[- ]specific|field\s+test|laboratory|cannot\s+be\s+determined)\b|의존|필요|현장|결정할\s*수\s*없",
    "relation": r"\b(?:depends?|increases?|decreases?|affects?|related|ratio|varies|because|function\s+of)\b|관계|증가|감소|의존|때문",
}


def _terms(text):
    for korean, english in ENGINEERING_TERMS.items():
        text = text.replace(korean, english)
    text = re.sub(r"설명해(?:줘|주세요)|알려(?:줘|주세요)|무엇인가요|무엇|기능|역할|정의|의미|내부\s*자료|근거|필요한|입력|정확한|최적|구해줘", " ", text)
    text = re.sub(r"\b([a-z]+)ies\b", r"\1y", text.casefold())
    words = re.findall(r"[A-Za-z][A-Za-z_-]*|[가-힣]+", text)
    return {re.sub(r"(?:에서|으로|에는|이란|의|은|는|을|를|가)$", "", w) for w in words
            if w not in STOP and len(w) > 1}


class SupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass
class RequiredClaim:
    claim_id: str
    description: str
    required: bool = True
    support_status: SupportStatus = SupportStatus.UNSUPPORTED
    supporting_evidence_ids: list[str] = field(default_factory=list)
    supporting_spans: list[str] = field(default_factory=list)


@dataclass
class ClaimSupport:
    claims: list[RequiredClaim]
    underdetermined: bool = False

    @property
    def all_required_supported(self):
        required = [c for c in self.claims if c.required]
        return bool(required) and all(c.support_status == SupportStatus.SUPPORTED for c in required)

    @property
    def some_supported(self):
        return any(c.supporting_spans for c in self.claims)

    def telemetry(self):
        required = [c for c in self.claims if c.required]
        return {"claim_support_checked": True, "required_claim_count": len(required),
                "supported_claim_count": sum(c.support_status == SupportStatus.SUPPORTED for c in required),
                "partially_supported_claim_count": sum(c.support_status == SupportStatus.PARTIALLY_SUPPORTED for c in required),
                "answerability_status": "ANSWERABLE" if self.all_required_supported else
                    "PARTIAL" if self.some_supported else "UNSUPPORTED",
                "relevant_evidence_present": self.some_supported,
                "required_claims": [asdict(c) for c in self.claims]}


def _parts(text):
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    requested = [s for s in sentences if s.rstrip().endswith("?") or re.search(
        r"\b(?:what|why|how|explain|describe|define|state|identify|determine|find|provide|compare)\b|"
        r"설명|알려|정의|구해|비교|무엇", s, re.I)]
    return [p.strip(" .?") for sentence in (requested or sentences) for p in re.split(
        r"[?;]+|\band\s+(?=(?:what|why|how|describe|explain|define)\b)", sentence, flags=re.I)
        if p.strip(" .?")]


def _opposes(left, right):
    """Conservative literal polarity conflicts; arbitrary semantic conflicts stay with VERIFY."""
    def signature(text):
        text = text.casefold()
        negative = bool(re.search(r"\b(?:not|never)\b|않|아니", text))
        text = re.sub(r"\b(?:does|do|not|never)\b", " ", text)
        for pattern, family, sign in ((r"\b(?:increases?|raises?)\b", "change", 1),
                                       (r"\b(?:decreases?|reduces?)\b", "change", -1),
                                       (r"\brequires?\b", "require", 1),
                                       (r"\bdepends?\b", "depend", 1)):
            match = re.search(pattern, text)
            if match:
                return (_terms(text[:match.start()]), _terms(text[match.end():]), family,
                        -sign if negative else sign)
        return None
    a, b = signature(left), signature(right)
    return bool(a and b and a[:3] == b[:3] and a[3] != b[3])


def _relation(question, underdetermined):
    return ("dependency" if underdetermined else "function" if re.search(r"purpose|function|역할|기능", question, re.I)
            else "definition" if re.search(r"define|definition|means|what\s+is|정의|의미", question, re.I) else "relation")


def evaluate_claim_support(request, evidence, requirements=None):
    """Proof is a literal relation span, never a similarity score or an inferred fact."""
    underdetermined = explicitly_underdetermined(request.topic)
    questions = [request.topic]
    if request.goal and request.goal != request.topic:
        questions.append(request.goal)
    # Presentation-only criteria add no factual claim. Specific criteria do remain mandatory.
    questions += [c.description for c in (requirements or request.success_criteria) if c.required]
    parts = []
    seen = set()
    for question in questions:
        for part in _parts(question):
            signature = (frozenset(_terms(part)), _relation(part, underdetermined))
            if signature[0] and signature not in seen:
                parts.append(part)
                seen.add(signature)
    # For explicitly missing-data queries, the requested target precedes the missing-data clause.
    if underdetermined:
        cleaned = []
        for part in parts:
            if re.search(r"\b(?:exact|optimal|precise|specific)\b|정확한|최적", part, re.I):
                part = re.split(r"[,;]|\b(?:but|without|no)\b|(?:없|미제공|주어지지)", part, flags=re.I)[0]
            elif re.search(r"\b(?:unavailable|unknown|missing|unspecified|not\s+(?:provided|known|available))\b|"
                           r"없|미제공|주어지지|제공되지", part, re.I):
                continue
            cleaned.append(part)
        parts = list(dict.fromkeys(cleaned))
    claims = []
    for index, question in enumerate(parts, 1):
        claim = RequiredClaim(f"CLAIM{index}", question)
        claims.append(claim)
        relation = _relation(question, underdetermined and bool(re.search(
            r"\b(?:exact|optimal|precise|specific)\b|정확한|최적", question, re.I)))
        terms = _terms(question)
        if not terms:
            continue
        candidates = []
        for row in evidence:
            if (row.get("source_type") not in {"knowledge_base", "figure", "web"}
                    or not re.fullmatch(r"(?:KB|WEB|FIG)\d+", str(row.get("evidence_id") or ""))):
                continue
            for quote in re.split(r"(?<=[.!?])\s+|\n(?=[A-Z])", str(row.get("text") or "")):
                quote = re.sub(r"\s+", " ", quote).strip()
                if not 20 <= len(quote) <= 650:
                    continue
                if underdetermined and re.search(r"\b(?:not|never)\s+(?:depend|require)|필요하지\s*않|의존하지\s*않", quote, re.I):
                    continue
                covers = terms <= _terms(quote)
                predicate = re.search(RELATIONS[relation], quote, re.I)
                # A concept mentioned in an unrelated clause is not the subject of this relation.
                subject = _terms(quote[:predicate.start()]) if predicate else set()
                if predicate and re.search(r"[가-힣]", predicate.group()):
                    # Korean predicates follow their objects; use the topic/subject particle.
                    topic = re.match(r"^(.+?(?:은|는|이|가))\s+", quote)
                    subject = _terms(topic.group(1)) if topic else set()
                informative = not re.search(r"\b(?:mentioned|listed|discussed|catalogue|catalog|chapter)\b", quote, re.I)
                if relation == "function" and re.search(r"\b(?:not|never)\b|않|아니", quote, re.I):
                    informative = False
                if predicate and terms & subject and subject <= terms and informative:
                    # A direct relation about the requested subject can answer a portion,
                    # but omitted qualifiers/objects never count as complete support.
                    partial = len(terms & _terms(quote)) >= 2 and len(terms & subject) >= 2
                    if covers or partial:
                        candidates.append((not covers, len(quote), str(row["evidence_id"]), quote))
        if not candidates:
            continue
        partial, _, source_id, quote = min(candidates)
        claim.support_status = SupportStatus.PARTIALLY_SUPPORTED if partial else SupportStatus.SUPPORTED
        claim.supporting_evidence_ids = [source_id]
        claim.supporting_spans = [quote]
        for _, _, other_id, other_quote in candidates:
            if _opposes(quote, other_quote):
                claim.support_status = SupportStatus.PARTIALLY_SUPPORTED
                claim.supporting_evidence_ids.append(other_id)
                claim.supporting_spans.append(other_quote)
    return ClaimSupport(claims, underdetermined)


def grounded_answer(request, support):
    chosen = [(sid, span) for c in support.claims
              for sid, span in zip(c.supporting_evidence_ids, c.supporting_spans)]
    if not chosen:
        return None
    prefix = ("현재 정보만으로 정확한 값을 결정할 수 없습니다. 근거가 명시한 필요한 정보: "
              if prefers_korean(request) else "An exact value cannot be determined from the supplied information. The source identifies the required data: ") if support.underdetermined else (
              "근거 자료에 명시된 내용: " if prefers_korean(request) else "The source states: ")
    answer = prefix + "\n".join(f'"{quote}" [{source_id}]' for source_id, quote in dict.fromkeys(chosen))
    missing = [c.description for c in support.claims if c.required and c.support_status != SupportStatus.SUPPORTED]
    if missing:
        answer += "; " + ("현재 근거에서 확인되지 않거나 근거가 충돌하는 요청: " if prefers_korean(request)
                           else "Not established by the available evidence (incomplete or conflicting support): ") + "; ".join(missing)
    return answer


def literal_answer(request, evidence, requirements=None, *, allow_partial=False):
    support = evaluate_claim_support(request, evidence, requirements)
    return grounded_answer(request, support) if support.all_required_supported or allow_partial else None
