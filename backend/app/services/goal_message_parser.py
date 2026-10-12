"""Turn one user message into the existing, bounded goal-execution request."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.goal_research_schemas import GoalResearchRequest
from app.services.goal_clarification import parse_user_simulation_spec
from app.services.user_fact_registry import NUMBER, UserFactRegistry


class ContextMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class GoalMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    context_message: str | None = Field(default=None, max_length=2000)
    context_messages: list[ContextMessage] = Field(default_factory=list, max_length=6)
    model: str = Field(default="qwen3:8b", min_length=1, max_length=100)

    @model_validator(mode="after")
    def bound_context(self) -> "GoalMessageRequest":
        if sum(len(item.content) for item in self.context_messages) > 2400:
            raise ValueError("conversation context is too long")
        return self


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
FOLLOWUP = re.compile(r"^\s*(?:그럼|그러면|그렇다면|이번엔|대신|이제|그 값|what about|how about|instead|if\b|[A-Za-z][A-Za-z0-9_]*\s*만\s*)", re.I)


def _contextual_fact_name(message: str, prior: list[str]) -> str | None:
    """Bind one literal follow-up value to an unambiguous prior USER fact only."""
    values = list(re.finditer(NUMBER, message))
    if len(values) != 1 or UserFactRegistry.from_topic(message).records:
        return None
    facts = UserFactRegistry.from_messages(prior).records
    explicit = re.search(r"\b([A-Za-z][A-Za-z0-9_]*)\s*만\b", message, re.I)
    if explicit:
        matches = [fact for fact in facts if fact.name.casefold() == explicit.group(1).casefold()]
    else:
        matches = facts if len(facts) == 1 else []
    return matches[0].name if len(matches) == 1 else None


def _assignment_only(message: str) -> bool:
    return (len(message) <= 80 and bool(UserFactRegistry.from_topic(message).records)
            and not re.search(r"계산|구해|설명|찾아|왜|어떻게|calculate|compute|explain|find|why|how", message, re.I))


def parse_goal_message(payload: GoalMessageRequest) -> GoalResearchRequest:
    message = payload.message.strip()
    # Assistant turns are conversational hints only: never promote them to facts or evidence.
    prior_user = [item.content.strip() for item in payload.context_messages if item.role == "user"]
    context = (payload.context_message or "").strip()
    if context and not prior_user:
        prior_user = [context]
    assignment_only = _assignment_only(message)
    followup = bool((FOLLOWUP.search(message) or DEICTIC.search(message) or assignment_only) and prior_user)
    if followup:
        base_positions = [index for index, item in enumerate(prior_user)
                          if not FOLLOWUP.search(item) and not _assignment_only(item)]
        if not base_positions:
            raise ValueError("이전 목표를 확인할 수 없습니다. 필요한 조건을 다시 적어주세요.")
        prior_user = prior_user[base_positions[-1]:]
    base = prior_user[0] if followup else ""
    if DEICTIC.search(message) and not context:
        if not prior_user:
            raise ValueError("이 주제/this topic이 가리키는 이전 연구 주제가 필요합니다.")
    topic = f"{base}\n{message}" if followup else message
    if len(topic) > 2000:
        raise ValueError("이전 요청이 너무 길어 목표를 안전하게 이어갈 수 없습니다. 필요한 조건을 다시 적어주세요.")
    hypothesis = HYPOTHESIS.search(message)
    deliverables = []
    if MAKE_DOCUMENT.search(message):
        if re.search(r"보고서|\breport\b", message, re.I):
            deliverables.append("docx")
        if re.search(r"발표\s*자료|슬라이드|\b(?:ppt|pptx|presentation|slides?)\b", message, re.I):
            deliverables.append("pptx")
    contextual_name = _contextual_fact_name(message, prior_user) if followup else None
    if (followup and re.search(NUMBER, message) and not contextual_name
            and not UserFactRegistry.from_topic(message).records):
        raise ValueError("변경할 값의 변수를 확인할 수 없습니다. 변수명과 값을 함께 적어주세요.")
    return GoalResearchRequest(
        topic=context if DEICTIC.search(message) and not payload.context_messages else topic,
        goal=topic,
        entrypoint="unified_chat",
        current_message=message,
        context_user_messages=prior_user if followup else [],
        contextual_fact_name=contextual_name,
        context_message_count=len(payload.context_messages) if followup else 0,
        expected_result=hypothesis.group("claim").strip(" .") if hypothesis else None,
        success_criteria=[],  # The v8 agent derives only criteria supported by the goal.
        use_internal=True,
        use_external=bool(WEB_REQUEST.search(message) and not WEB_NEGATION.search(message)),
        execution_mode="autonomous_goal_execution",
        simulation_spec=(spec.model_dump(mode="json") if (spec := parse_user_simulation_spec(message)) else None),
        deliverables=deliverables,
        # Adaptive stopping decides the actual length; eight is only a bounded safety ceiling.
        max_iterations=8,
        model=payload.model,
    )
