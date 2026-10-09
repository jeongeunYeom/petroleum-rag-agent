"""Compact, user-visible goal progress; no private model reasoning is persisted."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.goal_research_schemas import CriterionStatus, GoalCriterion


class GoalActionType(str, Enum):
    RETRIEVE = "retrieve"
    CALCULATE = "calculate"
    SIMULATE = "simulate"
    ANALYZE = "analyze"
    VERIFY = "verify"
    SYNTHESIZE = "synthesize"
    STOP = "stop"


class CriterionState(BaseModel):
    criterion_id: str
    description: str
    required: bool = True
    status: CriterionStatus = CriterionStatus.UNMET
    support_ids: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    requires_research: bool = False
    requires_calculation: bool = False
    requires_simulation: bool = False
    requires_comparison: bool = False
    requires_output: bool = False
    requires_verification: bool = True


class DerivedFact(BaseModel):
    fact_id: str
    source_type: Literal["calculation"] = "calculation"
    parent_calc_id: str
    output_id: str
    name: str
    value: float
    unit: str | None = None
    underlying_provenance_ids: list[str] = Field(default_factory=list)


class SimulationParameter(BaseModel):
    name: str
    start: float
    stop: float
    step: float
    unit: str | None = None
    source_fact_id: str | None = None

    @model_validator(mode="after")
    def finite_range(self) -> "SimulationParameter":
        if not all(math.isfinite(value) for value in (self.start, self.stop, self.step)):
            raise ValueError("simulation values must be finite")
        if self.step <= 0 or self.stop < self.start:
            raise ValueError("simulation range must be ascending with a positive step")
        return self


class SimulationSpec(BaseModel):
    simulation_type: Literal["parameter_sweep"] = "parameter_sweep"
    parameter: SimulationParameter
    expression: str
    output_name: str = "result"
    output_unit: str | None = None
    objective: Literal["max", "min"] = "max"
    max_cases: int = Field(default=100, ge=1, le=100)

    @model_validator(mode="after")
    def bounded(self) -> "SimulationSpec":
        cases = math.floor((self.parameter.stop - self.parameter.start) / self.parameter.step + 1e-10) + 1
        if cases > self.max_cases:
            raise ValueError("simulation case budget exceeded")
        return self


class GoalAction(BaseModel):
    action_id: str
    action_type: GoalActionType
    target_criteria: list[str] = Field(default_factory=list)
    objective: str
    query: str | None = None
    reason_code: str
    calculation_intent: str | None = None
    formula_id: str | None = None
    required_inputs: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    simulation_spec: SimulationSpec | None = None

    def fingerprint(self, input_ids: list[str]) -> str:
        payload = {
            "type": self.action_type.value,
            "criteria": sorted(self.target_criteria),
            "query": " ".join((self.query or "").casefold().split()),
            "inputs": sorted(input_ids),
            "formula_id": self.formula_id,
            "simulation": self.simulation_spec.model_dump(mode="json") if self.simulation_spec else None,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class ActionRecord(BaseModel):
    iteration: int
    action_id: str
    action_type: GoalActionType
    target_criteria: list[str]
    status: Literal["completed", "blocked", "failed"]
    reason_code: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    new_evidence_count: int = 0
    evidence_added: list[str] = Field(default_factory=list)
    computation_ids: list[str] = Field(default_factory=list)
    coverage_before: float = 0.0
    coverage_after: float = 0.0
    failure_reason: str | None = None
    details: dict = Field(default_factory=dict)


class GoalExecutionState(BaseModel):
    run_id: str
    goal: str
    criteria: list[CriterionState]
    iteration: int = 0
    evidence_ids: list[str] = Field(default_factory=list)
    computation_ids: list[str] = Field(default_factory=list)
    derived_facts: list[DerivedFact] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    generated_artifacts: list[str] = Field(default_factory=list)
    unresolved_information: list[str] = Field(default_factory=list)
    pending_calculations: list[str] = Field(default_factory=list)
    pending_simulations: list[str] = Field(default_factory=list)
    pending_verifications: list[str] = Field(default_factory=list)
    completed_actions: list[ActionRecord] = Field(default_factory=list)
    current_coverage: float = 0.0
    goal_achieved: bool = False
    blocked_reasons: list[str] = Field(default_factory=list)
    source_complete: bool | None = None
    no_progress_count: int = 0
    verified: bool = False
    synthesized: bool = False
    analyzed: bool = False

    @classmethod
    def from_criteria(cls, run_id: str, goal: str, criteria: list[GoalCriterion]) -> "GoalExecutionState":
        states = []
        for item in criteria:
            text = item.description
            states.append(CriterionState(
                criterion_id=item.criterion_id, description=text, required=item.required,
                requires_research=bool(re.search(r"\b(?:cite|source|evidence|document|retrieve|find)\b|근거|검색|출처", text, re.I)),
                requires_calculation=bool(re.search(r"\b(?:calculate|compute|numeric|mean|average)\b|계산|평균", text, re.I)),
                requires_simulation=bool(re.search(r"\b(?:simulate|sweep|simulation)\b|시뮬레이션", text, re.I)),
                requires_comparison=bool(re.search(r"\b(?:compare|rank|best|worst|range|sensitivity)\b|비교|순위|최적|범위", text, re.I)),
                requires_output=bool(re.search(r"\b(?:report|provide|chart|table)\b|보고|표|차트", text, re.I)),
            ))
        return cls(run_id=run_id, goal=goal, criteria=states,
                   pending_calculations=[item.criterion_id for item in states if item.requires_calculation],
                   pending_simulations=[item.criterion_id for item in states if item.requires_simulation],
                   pending_verifications=[item.criterion_id for item in states if item.required])

    def fingerprint(self) -> str:
        payload = {
            "criteria": [(item.criterion_id, item.status.value, sorted(item.support_ids),
                          sorted(item.missing_requirements)) for item in self.criteria],
            "evidence": sorted(self.evidence_ids),
            "computations": sorted(self.computation_ids),
            "facts": sorted(self.known_facts),
            "gaps": sorted(self.unresolved_information),
            "pending_calculations": sorted(self.pending_calculations),
            "pending_simulations": sorted(self.pending_simulations),
            "pending_verifications": sorted(self.pending_verifications),
            "blocked": sorted(self.blocked_reasons),
            "source_complete": self.source_complete,
            "verified": self.verified,
            "analyzed": self.analyzed,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def snapshot(self) -> dict:
        return {
            "iteration": self.iteration,
            "criteria": {item.criterion_id: item.status.value for item in self.criteria},
            "evidence_ids": self.evidence_ids.copy(),
            "computation_ids": self.computation_ids.copy(),
            "known_fact_ids": self.known_facts.copy(),
            "generated_artifacts": self.generated_artifacts.copy(),
            "unresolved_information": self.unresolved_information.copy(),
            "coverage": self.current_coverage,
            "goal_achieved": self.goal_achieved,
            "blocked_reasons": self.blocked_reasons.copy(),
            "source_complete": self.source_complete,
        }
