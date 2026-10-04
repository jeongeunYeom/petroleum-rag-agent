from __future__ import annotations

import re

from app.models.goal_research_schemas import CriterionStatus, GoalResearchResponse


_MISSING = re.compile(r"\b(?:missing|not found|unavailable|insufficient evidence|not provided|lack(?:ing|s)?|without)\b", re.I)
_RESOLVED = re.compile(r"\b(?:has|have|is|was|were)\s+(?:now\s+)?(?:been\s+)?resolved\b|\bno longer (?:missing|unavailable)\b", re.I)
_NEGATIVE = re.compile(r"\b(?:no|not|missing|unavailable|insufficient|lack(?:ing|s)?)\b", re.I)
_POSITIVE = re.compile(r"\b\d+(?:\.\d+)?\b|\b(?:available|found|provided|identified|completed|validated|confirmed|established|measured)\b", re.I)
_CHART_GAP = re.compile(r"\b(?:chart|plot|graph)\b.*\b(?:cannot|unable|without|not generated)\b", re.I)
_CHART_CRITERION = re.compile(r"\b(?:chart|plot|graph)\b", re.I)
_WORDS = re.compile(r"[a-z0-9]+", re.I)
_FILLER = {
    "a", "an", "and", "are", "at", "be", "by", "data", "evidence", "for", "from",
    "in", "insufficient", "is", "it", "missing", "not", "of", "on", "or", "prior",
    "some", "the", "value", "values", "was", "were", "with", "findings",
}


def without_limitations(answer: str) -> str:
    """Remove the synthesis limitation line; the final state owns that section."""
    return "\n".join(
        line for line in answer.splitlines()
        if not line.strip().lower().startswith("limitations:")
    ).strip()


def _answer_limitations(answer: str) -> list[str]:
    return [
        line.split(":", 1)[1].strip()
        for line in answer.splitlines()
        if line.strip().lower().startswith("limitations:") and line.split(":", 1)[1].strip()
    ]


def _resolved_missing_fact(gap: str, result: GoalResearchResponse) -> bool:
    if not _MISSING.search(gap):
        return False
    # In "cannot make a chart without B", B is the allegedly missing fact.
    subject_text = gap.lower().rsplit("without", 1)[-1] if "without" in gap.lower() else gap.lower()
    subject = set(_WORDS.findall(subject_text)) - _FILLER
    if len(subject) < 2:
        return False
    supported_ids = {
        evidence_id
        for criterion in result.criteria if criterion.status == CriterionStatus.MET
        for evidence_id in criterion.supporting_evidence
    }
    evidence_text = {
        **{item.evidence_id: item.excerpt for item in result.internal_sources},
        **{item.evidence_id: item.passage or item.snippet for item in result.web_sources},
        **{item.evidence_id: " ".join(filter(None, (item.excerpt, item.source_note, item.related_page_text))) for item in result.figures},
        **{item.computation_id: item.summary for item in result.computations if item.validation_passed},
    }
    for evidence_id in supported_ids:
        text = evidence_text.get(evidence_id, "")
        if _NEGATIVE.search(text) or not _POSITIVE.search(text):
            continue
        overlap = subject & set(_WORDS.findall(text.lower()))
        if len(overlap) >= 2 and len(overlap) / len(subject) >= 0.6:
            return True
    return False


def _resolved_chart_gap(gap: str, result: GoalResearchResponse) -> bool:
    if not _CHART_GAP.search(gap):
        return False
    chart_ids = {
        item.computation_id for item in result.computations
        if item.validation_passed and any(path.lower().endswith(".png") for path in item.output_files)
    }
    chart_criteria = {
        item.criterion_id for item in result.frozen_criteria
        if _CHART_CRITERION.search(item.description)
    }
    return any(
        item.criterion_id in chart_criteria
        and item.status == CriterionStatus.MET
        and chart_ids.intersection(item.supporting_evidence)
        for item in result.criteria
    )


def resolve_final_limitations(result: GoalResearchResponse) -> list[str]:
    """Keep current unresolved gaps, never the accumulated historical gap list."""
    latest_gaps = result.iterations[-1].gap_analysis if result.iterations else []
    candidates = [*latest_gaps, *_answer_limitations(result.final_answer)]
    return list(dict.fromkeys(
        gap.strip() for gap in candidates
        if gap.strip() and not _RESOLVED.search(gap)
        and not _resolved_missing_fact(gap, result)
        and not _resolved_chart_gap(gap, result)
    ))
