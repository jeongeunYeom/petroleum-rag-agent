import { requestJson } from "./http";

export type CriterionStatus = "met" | "partial" | "unmet" | "blocked";

export type GoalCriterion = {
  criterion_id: string;
  description: string;
  required: boolean;
};

export type CriterionEvaluation = {
  criterion_id: string;
  status: CriterionStatus;
  reason: string;
  supporting_evidence: string[];
};

export type GoalIteration = {
  iteration: number;
  research_query: string;
  evidence_added: string[];
  candidate_answer: string;
  criteria: CriterionEvaluation[];
  goal_coverage: number;
  expected_result_status: string;
  engineering_validation_passed: boolean;
  gap_analysis: string[];
  next_research_need?: string | null;
};

export type GoalResearchRun = {
  run_id: string;
  topic: string;
  goal?: string | null;
  expected_result?: string | null;
  run_status: "planned" | "running" | "completed" | "stopped" | "failed" | "canceled";
  status: string;
  stop_reason?: string | null;
  final_answer: string;
  goal_coverage: number;
  goal_coverage_percent: number;
  criteria_source: "user" | "inferred";
  criteria: CriterionEvaluation[];
  frozen_criteria: GoalCriterion[];
  expected_result_status: string;
  iterations_completed: number;
  current_iteration: number;
  max_iterations: number;
  current_stage: string;
  iterations: GoalIteration[];
  internal_sources: unknown[];
  web_sources: unknown[];
  figures: unknown[];
  cancel_requested: boolean;
  error?: string | null;
};

export type GoalResearchInput = {
  topic: string;
  goal?: string;
  expected_result?: string;
  success_criteria: GoalCriterion[];
  use_internal: boolean;
  use_external: boolean;
  max_iterations: number;
};

export function startGoalResearch(input: GoalResearchInput): Promise<GoalResearchRun> {
  return requestJson("/research/goal-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function getGoalResearch(runId: string): Promise<GoalResearchRun> {
  return requestJson(`/research/goal-runs/${runId}`, { cache: "no-store" });
}

export function cancelGoalResearch(runId: string): Promise<GoalResearchRun> {
  return requestJson(`/research/goal-runs/${runId}/cancel`, { method: "POST" });
}
