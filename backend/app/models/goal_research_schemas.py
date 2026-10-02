from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.research_schemas import FigureEvidence, InternalEvidence, WebEvidence


class CriterionStatus(str, Enum):
    MET = "met"
    PARTIAL = "partial"
    UNMET = "unmet"
    BLOCKED = "blocked"


class ExpectedResultStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_PROVIDED = "not_provided"


class GoalRunStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    CANCELED = "canceled"


class GoalStatus(str, Enum):
    PENDING = "pending"
    ACHIEVED = "achieved"
    NOT_SUPPORTED = "not_supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    STOPPED = "stopped"
    FAILED = "failed"
    CANCELED = "canceled"


class GoalStopReason(str, Enum):
    GOAL_ACHIEVED = "goal_achieved"
    MAX_ITERATIONS = "max_iterations"
    NO_PROGRESS = "no_progress"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    GOAL_CONFLICTS_WITH_EVIDENCE = "goal_conflicts_with_evidence"
    CANCELED = "canceled"
    ERROR = "error"


class GoalCriterion(BaseModel):
    criterion_id: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=1000)
    required: bool = True

    @field_validator("criterion_id", "description")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class GoalResearchRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=2000)
    goal: str | None = Field(default=None, max_length=2000)
    expected_result: str | None = Field(default=None, max_length=2000)
    success_criteria: list[GoalCriterion] = Field(default_factory=list, max_length=20)
    use_internal: bool = True
    use_external: bool = False
    engineering_validation: bool = True
    model: str = Field(default="qwen3:8b", min_length=1, max_length=100)
    max_iterations: int = Field(default=4, ge=1, le=8)
    no_progress_patience: int = Field(default=2, ge=1, le=3)
    internal_top_k: int = Field(default=5, ge=1, le=20)
    external_top_k: int = Field(default=5, ge=1, le=20)
    temperature: float | None = Field(default=None, ge=0, le=2)
    seed: int | None = Field(default=None, ge=0)

    @field_validator("topic", "model")
    @classmethod
    def strip_required_fields(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("goal", "expected_result")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_sources_and_criteria(self) -> "GoalResearchRequest":
        if not self.use_internal and not self.use_external:
            raise ValueError("at least one evidence source must be enabled")
        ids = [item.criterion_id for item in self.success_criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("criterion_id values must be unique")
        if self.success_criteria and not any(item.required for item in self.success_criteria):
            raise ValueError("at least one success criterion must be required")
        return self


class CriterionEvaluation(BaseModel):
    criterion_id: str
    status: CriterionStatus
    reason: str
    supporting_evidence: list[str] = Field(default_factory=list)


class GoalResearchPlan(BaseModel):
    research_question: str
    focus_criteria: list[str]
    reason: str


class GoalIterationTiming(BaseModel):
    planning_seconds: float = 0.0
    research_seconds: float = 0.0
    synthesis_seconds: float = 0.0
    evaluation_seconds: float = 0.0
    iteration_seconds: float = 0.0


class GoalIterationRecord(BaseModel):
    iteration: int
    research_query: str
    plan: GoalResearchPlan
    evidence_added: list[str] = Field(default_factory=list)
    candidate_answer: str
    criteria: list[CriterionEvaluation]
    goal_coverage: float = Field(ge=0, le=1)
    expected_result_status: ExpectedResultStatus
    engineering_validation_passed: bool
    engineering_contradiction_count: int = 0
    unsupported_engineering_claim_count: int = 0
    gap_analysis: list[str] = Field(default_factory=list)
    next_research_need: str | None = None
    timing: GoalIterationTiming = Field(default_factory=GoalIterationTiming)


class GoalResearchResponse(BaseModel):
    run_id: str
    topic: str
    goal: str | None = None
    expected_result: str | None = None
    run_status: GoalRunStatus = GoalRunStatus.PLANNED
    status: GoalStatus = GoalStatus.PENDING
    stop_reason: GoalStopReason | None = None
    final_answer: str = ""
    goal_coverage: float = Field(default=0.0, ge=0, le=1)
    goal_coverage_percent: float = Field(default=0.0, ge=0, le=100)
    criteria_source: str = "user"
    criteria_hash: str = ""
    criteria: list[CriterionEvaluation] = Field(default_factory=list)
    frozen_criteria: list[GoalCriterion] = Field(default_factory=list)
    expected_result_status: ExpectedResultStatus = ExpectedResultStatus.NOT_PROVIDED
    iterations_completed: int = 0
    current_iteration: int = 0
    max_iterations: int
    current_stage: str = "initialize"
    iterations: list[GoalIterationRecord] = Field(default_factory=list)
    internal_sources: list[InternalEvidence] = Field(default_factory=list)
    web_sources: list[WebEvidence] = Field(default_factory=list)
    figures: list[FigureEvidence] = Field(default_factory=list)
    timing: dict[str, float] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    cancel_requested: bool = False
    error: str | None = None
