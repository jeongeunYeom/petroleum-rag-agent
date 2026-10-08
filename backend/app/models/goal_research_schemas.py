from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    WAITING_FOR_USER_INPUT = "waiting_for_user_input"
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
    CALCULATION_BLOCKED = "calculation_blocked"
    SIMULATION_BLOCKED = "simulation_blocked"


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
    allow_python_execution: bool = False
    python_execution_approved: bool = False
    max_python_calls: int = Field(default=4, ge=0, le=8)
    max_python_attempts_per_call: int = Field(default=2, ge=1, le=3)
    execution_mode: Literal["legacy_goal_research", "autonomous_goal_execution"] = "legacy_goal_research"
    max_retrieval_actions: int = Field(default=3, ge=0, le=8)
    max_simulation_actions: int = Field(default=1, ge=0, le=3)
    max_verification_actions: int = Field(default=2, ge=1, le=4)
    simulation_spec: dict[str, Any] | None = None
    deliverables: list[Literal["docx", "pptx"]] = Field(default_factory=list)
    include_generated_charts: bool = True

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
    python_seconds: float = 0.0
    iteration_seconds: float = 0.0


class VerificationFailure(BaseModel):
    stage: str
    reason: str
    fact_id: str | None = None
    formula_id: str | None = None
    source_id: str | None = None
    expected_unit: str | None = None
    observed_unit: str | None = None
    expected_value: float | None = None
    observed_value: float | None = None
    span_hash: str | None = None


class CalculationScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    input_bindings: dict[str, str]


class CalculationOutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output_id: str
    name: str
    semantic_type: Literal["numeric", "ranking", "label", "list", "boolean"]
    unit: str | None = None
    required: bool = True
    scenario_id: str | None = None
    source_fact_ids: list[str] = Field(default_factory=list)
    formula_id: str | None = None


class CalculationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_id: str
    purpose: str
    target_criteria: list[str]
    input_fact_ids: list[str]
    formula_id: str | None = None
    operation_type: str
    scenarios: list[CalculationScenario]
    required_outputs: list[CalculationOutputSpec]


class PythonExecutionTrace(BaseModel):
    request_ir: dict[str, Any] | None = None
    computation_class: str | None = None
    generic_fast_path: bool = False
    initial_readiness_snapshot: dict[str, Any] | None = None
    recovery_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    formula_candidates: list[dict[str, Any]] = Field(default_factory=list)
    resolved_formula_id: str | None = None
    formula_resolution_reason: str | None = None
    binding_map: dict[str, dict[str, str]] = Field(default_factory=dict)
    contract_skeleton: dict[str, Any] | None = None
    contract_final: dict[str, Any] | None = None
    contract_skeleton_diff: list[str] = Field(default_factory=list)
    execution_path: str | None = None
    input_ready: bool | None = None
    method_ready: bool | None = None
    tie_policy: str = "isclose_rel_1e-9_abs_1e-12"
    tool_selected: bool = False
    tool_type: Literal["none", "python_calculation", "python_plot"] = "none"
    plan_present: bool = False
    planner_decision_attempts: int = 0
    planner_decision_status: str | None = None
    planner_plan_attempts: int = 0
    planner_plan_status: str | None = None
    available_user_fact_ids: list[str] = Field(default_factory=list)
    available_evidence_fact_ids: list[str] = Field(default_factory=list)
    selected_fact_ids: list[str] = Field(default_factory=list)
    available_formula_ids: list[str] = Field(default_factory=list)
    selected_formula_id: str | None = None
    fact_materialization_status: str | None = None
    formula_materialization_status: str | None = None
    verification_failures_structured: list[VerificationFailure] = Field(default_factory=list)
    selected_user_fact_ids: list[str] = Field(default_factory=list)
    verification_failures: list[str] = Field(default_factory=list)
    plan_summary: dict[str, Any] | None = None
    permission_requested: bool = False
    permission_passed: bool = False
    permission_manager_passed: bool = False
    input_fact_count: int = 0
    input_source_types: list[str] = Field(default_factory=list)
    facts_verified: bool = False
    formula_verified: bool = False
    blocked_stage: str | None = None
    error_summary: str | None = None
    call_boundary_reached: bool = False
    code_generated: bool = False
    sandbox_validation_passed: bool = False
    subprocess_reached: bool = False
    result_validation_passed: bool = False
    computation_id: str | None = None
    calculation_contract_id: str | None = None
    contract_status: str | None = None
    contract_attempts: int = 0
    required_output_ids: list[str] = Field(default_factory=list)
    produced_output_ids: list[str] = Field(default_factory=list)
    missing_output_ids: list[str] = Field(default_factory=list)
    used_input_ids: list[str] = Field(default_factory=list)
    unused_required_input_ids: list[str] = Field(default_factory=list)
    used_formula_id: str | None = None
    contract_validation_passed: bool = False
    execution_validated: bool = False
    contract_complete: bool = False
    provenance_validated: bool = False
    calc_grounding_validation_passed: bool | None = None
    calc_grounding_failures: list[str] = Field(default_factory=list)
    calc_output_adoption_count: int = 0
    calc_required_output_count: int = 0
    calc_adoption_coverage: float = 0.0
    recovery_triggered: bool = False
    recovery_reason: str | None = None
    recovery_query_count: int = 0
    recovery_new_source_ids: list[str] = Field(default_factory=list)
    recovery_efact_count: int = 0
    recovery_formula_count: int = 0
    recovery_materialization_success: bool = False
    requirement_graph_schema_version: int | None = None
    calculation_contract_schema_version: int | None = None
    requirement_graph: dict[str, Any] | None = None
    calculation_contract: dict[str, Any] | None = None
    required_output_checklist: list[dict[str, Any]] = Field(default_factory=list)
    missing_requested_outputs: list[str] = Field(default_factory=list)
    extra_contract_outputs: list[str] = Field(default_factory=list)
    source_complete: bool | None = None
    required_variable_count: int = 0
    bound_variable_count: int = 0
    missing_variables: list[str] = Field(default_factory=list)
    ambiguous_variables: list[str] = Field(default_factory=list)
    unit_mismatch_variables: list[str] = Field(default_factory=list)
    formula_source_available: bool = False
    required_evidence_ids: list[str] = Field(default_factory=list)
    recovery_rounds_used: int = 0
    recovery_rounds: list[dict[str, Any]] = Field(default_factory=list)
    source_complete_after_recovery: bool | None = None
    assumption_guard_passed: bool | None = None
    assumption_guard_failures: list[str] = Field(default_factory=list)
    final_response_leakage_detected: bool = False
    final_response_leakage_repaired: bool = False
    final_response_leakage_stripped: bool = False


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
    python_requested: bool = False
    python_decision_reason: str = ""
    python_executed: bool = False
    python_calls: int = 0
    python_trace: PythonExecutionTrace | None = None
    computation_ids: list[str] = Field(default_factory=list)
    generated_artifacts: list[str] = Field(default_factory=list)


class ComputationRecord(BaseModel):
    computation_id: str
    analysis_id: str
    purpose: str
    target_criteria: list[str] = Field(default_factory=list)
    source_evidence_ids: list[str] = Field(default_factory=list)
    source_input_ids: list[str] = Field(default_factory=list)
    formula_evidence_ids: list[str] = Field(default_factory=list)
    formula_source_id: str | None = None
    canonical_fact_ids: list[str] = Field(default_factory=list)
    canonical_formula_ids: list[str] = Field(default_factory=list)
    input_facts: list[dict[str, Any]] = Field(default_factory=list)
    formula: str | None = None
    code_record: str = ""
    output_files: list[str] = Field(default_factory=list)
    summary: str = ""
    validation_passed: bool = False
    attempts: int = 0
    attempt_records: list[dict[str, Any]] = Field(default_factory=list)
    fingerprint: str = ""
    contract_id: str | None = None
    required_output_ids: list[str] = Field(default_factory=list)
    produced_output_ids: list[str] = Field(default_factory=list)
    used_input_ids: list[str] = Field(default_factory=list)
    used_formula_id: str | None = None
    output_manifest: dict[str, dict[str, Any]] = Field(default_factory=dict)
    contract_validation_passed: bool = False


class GeneratedArtifact(BaseModel):
    artifact_id: str
    artifact_type: Literal["docx", "pptx", "csv", "png", "json"]
    path: str
    size_bytes: int
    validation_passed: bool
    source_computations: list[str] = Field(default_factory=list)


class GoalResearchResponse(BaseModel):
    run_id: str
    topic: str
    goal: str | None = None
    expected_result: str | None = None
    run_status: GoalRunStatus = GoalRunStatus.PLANNED
    status: GoalStatus = GoalStatus.PENDING
    stop_reason: GoalStopReason | None = None
    final_answer: str = ""
    clarification_question: str | None = None
    required_inputs: list[str] = Field(default_factory=list)
    # Persisted by the run service, never exposed by the API.
    resume_checkpoint: dict[str, Any] = Field(default_factory=dict, exclude=True)
    final_limitations: list[str] = Field(default_factory=list)
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
    current_action: str | None = None
    action_history: list[dict[str, Any]] = Field(default_factory=list)
    state_history: list[dict[str, Any]] = Field(default_factory=list)
    iterations: list[GoalIterationRecord] = Field(default_factory=list)
    internal_sources: list[InternalEvidence] = Field(default_factory=list)
    web_sources: list[WebEvidence] = Field(default_factory=list)
    figures: list[FigureEvidence] = Field(default_factory=list)
    computations: list[ComputationRecord] = Field(default_factory=list)
    artifacts: list[GeneratedArtifact] = Field(default_factory=list)
    deliverable_status: dict[str, str] = Field(default_factory=dict)
    deliverable_errors: dict[str, str] = Field(default_factory=dict)
    python_calls_total: int = 0
    python_attempts_total: int = 0
    python_failures: int = 0
    python_call_budget_exhausted: bool = False
    timing: dict[str, float] = Field(default_factory=dict)
    telemetry: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    cancel_requested: bool = False
    error: str | None = None
