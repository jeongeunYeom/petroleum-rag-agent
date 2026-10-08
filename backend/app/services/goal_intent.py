"""Small, request-only language and quantity cues; never a source of formulas."""

from __future__ import annotations

import re

from app.models.goal_research_schemas import GoalResearchRequest


def prefers_korean(request: GoalResearchRequest) -> bool:
    return bool(re.search(r"[가-힣]", " ".join((request.topic, request.goal or ""))))


def asks_for_api_gravity(request: GoalResearchRequest) -> bool:
    text = " ".join((request.topic, request.goal or ""))
    return bool(re.search(r"\bAPI(?:\s+gravity)?\b|API도", text, re.I)
                and re.search(r"\bSG\b|specific\s+gravity|비중", text, re.I))


def asks_for_api_gravity_calculation(request: GoalResearchRequest) -> bool:
    text = " ".join((request.topic, request.goal or ""))
    return asks_for_api_gravity(request) and bool(re.search(
        r"\b(?:calculat\w*|comput\w*|convert|determine)\b|계산|산출|구해|구하", text, re.I))
