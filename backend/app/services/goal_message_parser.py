"""Turn one user message into the existing, bounded goal-execution request."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.models.goal_research_schemas import GoalResearchRequest


class GoalMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    context_message: str | None = Field(default=None, max_length=2000)
    model: str = Field(default="qwen3:8b", min_length=1, max_length=100)


DEICTIC = re.compile(r"이\s*(?:주제|내용)|앞서|위의|this topic|same topic", re.I)
WEB_REQUEST = re.compile(
    r"웹에서|인터넷에서|온라인에서|최신\s*(?:자료|연구|논문|기술|동향)|"
    r"최근\s*(?:웹|자료|연구|논문)|\b(?:on the web|web search|online sources|"
    r"latest (?:sources|studies|papers|research|technologies))\b", re.I)
WEB_NEGATION = re.compile(r"웹\s*(?:검색|사용)?\s*(?:없이|제외)|인터넷\s*없이|without (?:the )?web", re.I)
HYPOTHESIS = re.compile(
    r"(?:^|[\n.!?]\s*)(?:가설\s*(?:은|는|:|：)|예상\s*결과\s*(?:는|:|：)|"
    r"my hypothesis is\s+|I hypothesize that\s+)(?P<claim>[^\n]+)", re.I)
MAKE_DOCUMENT = re.compile(r"만들|작성|생성|제작|\b(?:create|write|generate|make)\b", re.I)


def parse_goal_message(payload: GoalMessageRequest) -> GoalResearchRequest:
    message = payload.message.strip()
    context = (payload.context_message or "").strip()
    if DEICTIC.search(message) and not context:
        raise ValueError("이 주제/this topic이 가리키는 이전 연구 주제가 필요합니다.")
    hypothesis = HYPOTHESIS.search(message)
    deliverables = []
    if MAKE_DOCUMENT.search(message):
        if re.search(r"보고서|\breport\b", message, re.I):
            deliverables.append("docx")
        if re.search(r"발표\s*자료|슬라이드|\b(?:ppt|pptx|presentation|slides?)\b", message, re.I):
            deliverables.append("pptx")
    return GoalResearchRequest(
        topic=context if DEICTIC.search(message) else message,
        goal=f"{context}\n{message}" if DEICTIC.search(message) else message,
        expected_result=hypothesis.group("claim").strip(" .") if hypothesis else None,
        success_criteria=[],  # The v8 agent derives only criteria supported by the goal.
        use_internal=True,
        use_external=bool(WEB_REQUEST.search(message) and not WEB_NEGATION.search(message)),
        execution_mode="autonomous_goal_execution",
        deliverables=deliverables,
        max_iterations=6,
        model=payload.model,
    )
