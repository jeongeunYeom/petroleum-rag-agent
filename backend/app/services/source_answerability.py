"""Conservative literal answers: match every requested relation, not topic overlap alone."""
import re

from app.services.goal_action_planner import ENGINEERING_TERMS
from app.services.goal_intent import explicitly_underdetermined, prefers_korean


STOP = set("what why how does do is are the a an of for to and in with from explain describe define purpose function definition please internal source sources evidence relationship relation provide about its determine exact optimal value needed inputs data missing not provided without no calculate find".split())
STOP.update({"requested", "result", "supported", "answer", "validated"})
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


def literal_answer(request, evidence, requirements=None, *, allow_partial=False):
    """All required questions need a direct relation span; one missing part cancels fallback."""
    underdetermined = explicitly_underdetermined(request.topic)
    questions = [request.topic]
    if request.goal and request.goal != request.topic:
        questions.append(request.goal)
    questions += [c.description for c in (requirements or request.success_criteria) if c.required]
    parts = list(dict.fromkeys(p.strip(" .?") for q in questions for p in
        re.split(r"[?;\n]+|\band\s+(?=(?:what|why|how|describe|explain)\b)", q, flags=re.I) if p.strip(" .?")))
    # For explicitly missing-data queries, the requested target precedes the missing-data clause.
    if underdetermined:
        parts = [re.split(r"[,;]|\b(?:but|without|no)\b|(?:없|미제공|주어지지)", request.topic, flags=re.I)[0]]
    chosen = []
    for question in parts:
        relation = ("dependency" if underdetermined else "function" if re.search(r"purpose|function|역할|기능", question, re.I)
                    else "definition" if re.search(r"define|definition|means|정의|의미", question, re.I) else "relation")
        terms = _terms(question)
        if not terms:
            continue
        candidates = []
        for row in evidence:
            if row.get("source_type") not in {"knowledge_base", "figure", "web"}:
                continue
            for quote in re.split(r"(?<=[.!?])\s+", str(row.get("text") or "")):
                quote = re.sub(r"\s+", " ", quote).strip()
                if not 20 <= len(quote) <= 650 or re.search(r"\d", quote):
                    continue
                if underdetermined and re.search(r"\b(?:not|never)\s+(?:depend|require)|필요하지\s*않|의존하지\s*않", quote, re.I):
                    continue
                overlap = terms & _terms(quote)
                covers = terms <= _terms(quote) or (allow_partial and len(overlap) >= 2 and len(overlap) / len(terms) >= .75)
                if covers and re.search(RELATIONS[relation], quote, re.I):
                    candidates.append((len(quote), str(row["evidence_id"]), quote))
        if not candidates:
            return None
        _, source_id, quote = min(candidates)
        chosen.append((source_id, quote))
    if not chosen:
        return None
    prefix = ("현재 정보만으로 정확한 값을 결정할 수 없습니다. 근거가 명시한 필요한 정보: "
              if prefers_korean(request) else "An exact value cannot be determined from the supplied information. The source identifies the required data: ") if underdetermined else (
              "근거 자료에 명시된 내용: " if prefers_korean(request) else "The source states: ")
    return prefix + "\n".join(f'"{quote}" [{source_id}]' for source_id, quote in dict.fromkeys(chosen))
