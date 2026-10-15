"""Bounded, source-neutral query planning and soft evidence reranking for goal QA."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.research_schemas import InternalEvidence


# These are domain vocabulary, never document IDs, pages, answers, or formulas.
DOMAINS = {
    "reservoir_simulation": (r"reservoir simulation|numerical grid|grid block|finite difference|"
                             r"transmissib|discretiz|저류층\s*시뮬레이션|수치\s*격자|격자\s*블록|유한\s*차분|이산화", "reservoir simulation"),
    "well_testing": (r"well test|pressure derivative|drawdown|buildup|wellbore storage|"
                     r"유정\s*시험|압력\s*도함수|압력\s*상승|압력\s*강하", "well test"),
    "drilling": (r"drilling|casing|mud weight|mud density|hydrostatic pressure|lost circulation|"
                 r"well control|\bkick\b|시추|케이싱|이수압|킥", "drilling"),
    "production": (r"production|separator|gravel pack|pump intake|cavitation|\bESP\b|"
                   r"생산\s*설비|분리기|인공\s*채유", "production"),
    "petrophysics": (r"petrophys|formation evaluation|formation factor|well log|porosity|permeability|"
                     r"water saturation|resistivity|검층|공극률|투과도|암석\s*물성", "formation evaluation"),
    "reservoir_engineering": (r"reservoir engineering|material balance|aquifer|reserves|"
                              r"reservoir pore volume|compressibility|저류층\s*공학|물질\s*수지|매장량|대수층", "reservoir engineering"),
}
TERMS = {
    "비자성": "nonmagnetic drill collar", "자기 왜곡": "magnetic distortion",
    "자기 간섭": "magnetic interference", "드릴 칼라": "drill collar",
    "방향 측정기": "directional survey instrument", "방향 측정": "directional survey",
    "저류층 시뮬레이션": "reservoir simulation", "수치 격자": "numerical grid discretization",
    "격자 블록": "grid block", "격자 크기": "grid size", "수치 해상도": "numerical resolution",
    "격자": "grid", "전달률": "transmissibility", "셀 간": "between cells",
    "유한 차분": "finite difference", "조화 평균": "harmonic averaging",
    "유정 시험": "well test", "압력 상승 시험": "pressure buildup test",
    "압력 기록": "pressure recording", "압력 도함수": "pressure derivative",
    "이수 밀도": "mud density", "정수압": "hydrostatic pressure",
    "이수압": "mud hydrostatic pressure", "지층압": "formation pressure",
    "공극률": "porosity", "투과도": "permeability", "검층": "well log",
    "저항도 검층": "resistivity well log", "물 포화도": "water saturation",
    "모세관 진입압": "capillary entry pressure", "밀봉 성능": "seal capacity",
    "모세관압": "capillary pressure", "상대투과도": "relative permeability",
    "다상 유체 흐름": "multiphase fluid flow", "다상 흐름": "multiphase flow",
    "생산 설비": "production equipment", "생산 분리기": "production separator",
    "가스 분리": "gas separation", "분리기": "separator",
    "케이싱": "casing", "물질수지": "material balance", "대수층": "aquifer",
    "물 유입": "water influx", "압력 유지": "pressure support",
    "저류층 압력": "reservoir pressure", "압력": "pressure",
    "진비저항": "true formation resistivity", "지층 비저항": "formation resistivity",
    "비중": "specific gravity", "압력 강하": "pressure drop",
    "생산 지수": "productivity index", "유정 생산 지수": "well productivity index",
    "지층 평가": "formation evaluation", "지층 인자": "formation factor",
    "회수율": "recovery factor", "주입량": "injected volume", "생산량": "produced volume",
    "유입 압력": "inlet pressure", "출구 압력": "outlet pressure",
}
PRESSURE_SYMBOLS = re.compile(r"(?=.*(?<![A-Za-z0-9_])Po(?![A-Za-z0-9_]))"
                              r"(?=.*(?<![A-Za-z0-9_])Pf(?![A-Za-z0-9_]))"
                              r"(?=.*(?<![A-Za-z0-9_])Pc(?![A-Za-z0-9_]))", re.I)
DOMAIN_ALIASES = (
    (PRESSURE_SYMBOLS,
     ("overburden pressure", "fluid pressure", "compacting stress")),
    (re.compile(r"\bfractional\s+flow\b.{0,100}\bwaterflood\b|"
                r"\bwaterflood\b.{0,100}\bfractional\s+flow\b", re.I),
     ("water-oil fractional flow", "water injection", "relative permeability",
      "Buckley-Leverett")),
    (re.compile(r"\bformation[-\s]+(?:resistivity[-\s]+)?factor\b|지층\s*(?:저항\s*)?인자", re.I),
     ("electrical formation factor", "formation resistivity factor", "porosity", "resistivity")),
    (re.compile(r"\bmagnetic\s+(?:directional\s+)?survey\b.{0,100}\bsteel\b|"
                r"\bsteel\b.{0,100}\bmagnetic\s+(?:directional\s+)?survey\b", re.I),
     ("directional survey instrument", "steel drillstring", "magnetic distortion",
      "nonmagnetic drill collar")),
    (re.compile(r"\bmonel\b|\bnon[- ]?magnetic\s+(?:drill\s+)?collar\b|비자성\s*(?:드릴\s*)?(?:collar|칼라)", re.I),
     ("Monel drill collar", "non-magnetic drill collar", "nonmagnetic drill collar",
      "directional survey", "magnetic survey", "survey instrument", "magnetic interference")),
)
STOP = {"explain", "describe", "confirm", "evidence", "source", "sources", "find", "show",
        "internal", "textbook", "chapter", "using", "what", "when", "why", "how", "does",
        "the", "and", "for", "from", "with", "that", "this", "there", "are", "was",
        "자료", "내부", "근거", "설명", "확인", "교재", "관련", "질문", "결과", "내용"}
PREMISE_NOISE = re.compile(
    r"맞지|거지|되나|보면\s*되|무관하지|필요\s*없지|단점\s*없지|항상|언제나|"
    r"\b(?:right|correct|always|isn.t it true that|can i assume)\b|[?？]", re.I)
PRESENTATION_WORDS = {"use", "only", "the", "a", "local", "textbook", "source", "sources",
                      "please", "give", "provide", "short", "brief", "cited", "citation",
                      "explanation", "answer", "focus", "on", "exact", "relation", "with",
                      "evidence", "one", "paragraph", "in", "include", "including",
                      "check", "this", "against", "explicitly", "correct", "my", "premise",
                      "cite", "literal", "internal"}


def substantive_question(text: str) -> str:
    """Discard a colon-separated *presentation* instruction, never a technical clause."""
    prefix, separator, question = text.partition(":")
    if not separator or not question.strip() or len(prefix) > 100 or "=" in prefix:
        return text
    words = re.findall(r"[A-Za-z]+", prefix.casefold())
    english_presentation = (bool(words) and set(words) <= PRESENTATION_WORDS
                            and bool(set(words) & {"use", "give", "provide", "focus",
                                                     "check", "correct", "cite"}))
    korean_presentation = (bool(re.search(r"한\s*문단|간단히|짧게|근거.{0,8}(?:포함|대조)|답해(?:줘|주세요)", prefix))
                           and not domain_hint(prefix))
    return question.strip() if english_presentation or korean_presentation else text


def _tokens(text: str) -> list[str]:
    return list(dict.fromkeys(word.casefold() for word in re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}|[가-힣]{2,}", text.replace("-", " "))
                              if word.casefold() not in STOP))


def domain_hint(text: str) -> str | None:
    matches = [(len(re.findall(pattern, text, re.I)), name) for name, (pattern, _) in DOMAINS.items()]
    best = max(matches, default=(0, ""))
    return best[1] if best[0] else None


@dataclass(frozen=True)
class QueryPlan:
    queries: tuple[str, ...]
    domain: str | None
    concepts: tuple[str, ...]
    relation_terms: tuple[str, ...]
    translated_concepts: tuple[str, ...] = ()

    @property
    def search_text(self) -> str:
        return "\n".join(self.queries)


def bilingual_recovery_query(plan: QueryPlan) -> str:
    """Keep explicit English concepts when retrying a Korean/mixed KB query."""
    terms: list[str] = []
    for token in [*plan.relation_terms[:6], *plan.translated_concepts[:6]]:
        if not token.isascii() or (token.endswith("s") and token[:-1] in terms) or token in terms:
            continue
        terms.append(token)
        if len(terms) >= 8:
            break
    return " ".join(terms)


def plan_query(question: str, *, premise: bool = False, refined: bool = False) -> QueryPlan:
    """Use only user terms and fixed domain synonyms; never inject an answer."""
    question = substantive_question(question)
    cleaned = PREMISE_NOISE.sub(" ", question) if premise else question
    translations = [english for korean, english in sorted(TERMS.items(), key=lambda row: -len(row[0]))
                    if korean in cleaned]
    aliases = [term for cue, terms in DOMAIN_ALIASES if cue.search(cleaned) for term in terms]
    domain = domain_hint(cleaned)
    if domain:
        translations.append(DOMAINS[domain][1])
    if domain == "petrophysics" and re.search(r"(?<![A-Za-z0-9_])F(?![A-Za-z0-9_])", cleaned):
        # The established symbol expands a search term; it supplies no equation.
        translations.insert(0, "formation factor")
    english = _tokens(" ".join([*translations, *aliases]))
    original = _tokens(cleaned)
    # Short equation symbols disappear from prose tokenization, yet are often
    # the only discriminating terms in an indexed literal formula span.
    formula_symbols = []
    if re.search(r"\b(?:equation|formula|correlation|relation)\b|공식|수식|관계식|교재\s*식", cleaned, re.I):
        formula_symbols = list(dict.fromkeys(re.findall(
            r"\b([A-Za-z][A-Za-z0-9_]{0,2})\s*(?==)|"
            r"\b(?:for|calculate|compute|find|derive)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_]{0,2})\b",
            cleaned, re.I)))
        formula_symbols = [part.casefold() for pair in formula_symbols for part in pair if part]
    original_ascii = [word for word in original if re.fullmatch(r"[a-z][a-z0-9_-]+", word)]
    # Textbook prose commonly uses plural lithologies while visitors use the
    # singular. Keep both lexical forms without asserting any relation.
    lithology_forms = {"carbonate": "carbonates", "sand": "sands", "sandstone": "sandstones"}
    original_ascii = list(dict.fromkeys(
        form for word in original_ascii for form in (word, lithology_forms.get(word, word))))
    # "Informs" is a request for a relation, not a source keyword. A short
    # synonym query preserves the user's engineering nouns while avoiding
    # lengthy presentation wording that can dominate the original query.
    relation_query = (" ".join("determines" if word in {"inform", "informs"} else word
                               for word in original_ascii if word not in {"text", "internal", "material"})[:180]
                      if re.search(r"\binforms?\b", cleaned, re.I) else "")
    # A comparison is often printed as parallel source-local clauses ("in X ...;
    # in Y ..."). Search that relationship before broad domain expansions.
    compared = re.search(
        r"\b([A-Za-z][A-Za-z-]{2,})\s*(?:와|과|and|vs\.?|versus)\s*"
        r"([A-Za-z][A-Za-z-]{2,})(?=$|[^A-Za-z])", cleaned, re.I)
    comparative_query = ""
    if compared:
        left, right = (part.casefold() for part in compared.groups())
        comparison_noise = STOP | {"relation", "formula", "equation", "model", "evaluate",
                                   "calculate", "compute", "obtain", "determine", "derive"}
        if left not in comparison_noise and right not in comparison_noise and left != right:
            relation_nouns = [word for word in original_ascii if word not in {
                left, right, left + "s", right + "s"}][:3]
            if domain == "petrophysics" and re.search(
                    r"(?<![A-Za-z0-9_])F(?![A-Za-z0-9_])", cleaned):
                relation_nouns = ["formation", "factor", *relation_nouns]
            if relation_nouns:
                plural = lambda word: word if word.endswith("s") else word + "s"
                comparative_query = (f"in {plural(left)} in {plural(right)} "
                                     + " ".join(relation_nouns))
    # Korean clauses are kept as-is for retrieval, while fixed translations make
    # bilingual document titles and technical paragraphs reachable.
    # Preserve the visitor's explicit English engineering nouns ahead of broad
    # domain expansions; otherwise a short mixed-language question can lose
    # its discriminating terms before the bounded query is built.
    concepts = list(dict.fromkeys([*formula_symbols, *original_ascii, *english, *original]))
    core = " ".join(concepts[:10]) or cleaned.strip()[:180]
    domain_words = DOMAINS[domain][1] if domain else ""
    secondary = " ".join(dict.fromkeys([*original_ascii[:6], *english[:7], *original[:4]]))
    if premise:
        secondary = (secondary + " relationship definition").strip()
    elif domain_words:
        secondary = (domain_words + " " + secondary).strip()
    if refined:
        secondary = (secondary + " " + ("relationship" if premise else "chapter concepts")).strip()
        if aliases:
            secondary = " ".join(aliases)[:220]
    pressure_query = ("overburden pressure fluid pressure compacting stress Po Pf Pc"
                      if PRESSURE_SYMBOLS.search(cleaned) else "")
    factor_query = ("formation factor porosity cementation factor constant a m"
                    if re.search(r"\bformation[-\s]+(?:resistivity[-\s]+)?factor\b", cleaned, re.I)
                    and re.search(r"(?<![A-Za-z0-9_])a\s*[:=]", cleaned)
                    and re.search(r"(?<![A-Za-z0-9_])m\s*[:=]", cleaned) else "")
    lithology_query = ("in carbonates formation factor porosity" if
                       re.search(r"\bcarbonate\b", cleaned, re.I) and
                       re.search(r"\bformation[-\s]+(?:resistivity[-\s]+)?factor\b", cleaned, re.I)
                       else "")
    queries = tuple(dict.fromkeys(value[:220] for value in
                                  (comparative_query, pressure_query, factor_query, lithology_query,
                                   relation_query,
                                   core, secondary) if value))
    if not queries:
        queries = (core[:220],)
    # Terms supplied in a relation question receive extra weight during reranking.
    relation = tuple(dict.fromkeys(word for word in [*original_ascii, *english]
                                   if word not in _tokens(domain_words)))[:8]
    return QueryPlan(queries[:3], domain, tuple(concepts[:16]), relation,
                     tuple(english[:10]))


def _document_domain(document: str) -> str | None:
    name = document.replace("_", " ").replace("-", " ").casefold()
    for domain, (_, title) in DOMAINS.items():
        if title in name:
            return domain
    if "production technology" in name:
        return "production"
    if "well test analysis" in name:
        return "well_testing"
    return None


def rerank_sources(sources: list[InternalEvidence], plan: QueryPlan, *, limit: int = 5
                   ) -> tuple[list[InternalEvidence], dict]:
    """Soft domain prior plus concept coverage; do not exclude a direct cross-domain source."""
    ranked = []
    diagnostics = []
    for rank, source in enumerate(sources):
        text = source.excerpt.casefold()
        title = source.document.replace("_", " ").replace("-", " ").casefold()
        text_present = [word for word in plan.concepts if word in text]
        present = [word for word in plan.concepts if word in text or word in title]
        relation = [word for word in plan.relation_terms if word in text]
        family = _document_domain(source.document)
        family_match = bool(plan.domain and family == plan.domain)
        wrong_family = bool(plan.domain and family and family != plan.domain)
        score = min(len(present), 6) * 2 + min(len(relation), 3) * 2
        score += 5 if family_match else -2 if wrong_family else 0
        score += 2 if any(word in title for word in plan.concepts[:8]) else 0
        score += 1 / (rank + 1)
        confidence = "HIGH" if len(text_present) >= 3 and (relation or family_match) else \
                     "MEDIUM" if len(text_present) >= 2 or (len(text_present) >= 1 and family_match) else "LOW"
        ranked.append((score, source, confidence, family))
        diagnostics.append({"id": source.evidence_id, "document": source.document,
                            "page": source.page, "score": round(score, 4),
                            "concept_matches": text_present, "relation_matches": relation,
                            "family": family, "confidence": confidence})
    ranked.sort(key=lambda row: row[0], reverse=True)
    selected = []
    per_document: dict[str, int] = {}
    for _, source, confidence, _ in ranked:
        if confidence == "LOW" or per_document.get(source.document, 0) >= 3:
            continue
        selected.append(source)
        per_document[source.document] = per_document.get(source.document, 0) + 1
        if len(selected) == limit:
            break
    selected_ids = {source.evidence_id for source in selected}
    return selected, {"domain_hint": plan.domain,
                      "candidate_documents": list(dict.fromkeys(item.document for item in sources)),
                      "scores": diagnostics, "selected_sources": sorted(selected_ids),
                      "dropped_sources": [item.evidence_id for item in sources
                                          if item.evidence_id not in selected_ids],
                      "confidence": "HIGH" if any(row[2] == "HIGH" and row[1].evidence_id in selected_ids
                                                  for row in ranked) else "MEDIUM" if selected else "LOW"}
