from __future__ import annotations

import re


STRICT_REFUSAL = "제공된 문서 근거로는 확인할 수 없습니다."
NO_EVIDENCE_REFUSAL = (
    "확인 가능한 내부 또는 외부 근거를 찾지 못했습니다. "
    "근거 없이 답을 추측하지 않습니다."
)

_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?%?")
_EVIDENCE_ABSENCE_RE = re.compile(
    r"근거.{0,20}(?:없|찾지\s*못|부족)|"
    r"확인.{0,20}(?:할\s*수\s*없|불가)|"
    r"(?:no|insufficient|unavailable).{0,20}evidence|"
    r"cannot\s+(?:verify|confirm|determine)",
    re.IGNORECASE,
)
_RESTRAINT_RE = re.compile(
    r"추측하지\s*않|결론을?\s*제공하지\s*않|"
    r"확인.{0,20}(?:할\s*수\s*없|불가)|"
    r"(?:will\s+not|do\s+not|won't)\s+(?:guess|speculate)|"
    r"cannot\s+(?:verify|confirm|determine)",
    re.IGNORECASE,
)


def is_safe_refusal(answer: str) -> bool:
    """Accept a narrow evidence-based refusal without accepting invented facts."""
    text = " ".join(str(answer or "").split()).strip()
    if not text or _NUMBER_RE.search(text):
        return False
    if not _EVIDENCE_ABSENCE_RE.search(text) or not _RESTRAINT_RE.search(text):
        return False
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", text)
        if part.strip()
    ]
    return len(sentences) <= 3 and all(
        _EVIDENCE_ABSENCE_RE.search(sentence) or _RESTRAINT_RE.search(sentence)
        for sentence in sentences
    )
