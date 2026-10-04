import { API_BASE, requestJson } from "./http";

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
  python_requested: boolean;
  python_decision_reason: string;
  python_executed: boolean;
  computation_ids: string[];
  generated_artifacts: string[];
};

export type Computation = {
  computation_id: string;
  purpose: string;
  summary: string;
  validation_passed: boolean;
  attempts: number;
  output_files: string[];
};

export type GeneratedArtifact = {
  artifact_id: string;
  artifact_type: "docx" | "pptx";
  size_bytes: number;
  validation_passed: boolean;
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
  computations: Computation[];
  artifacts: GeneratedArtifact[];
  deliverable_status: Record<string, string>;
  deliverable_errors: Record<string, string>;
  python_calls_total: number;
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
  allow_python_execution: boolean;
  python_execution_approved: boolean;
  deliverables: ("docx" | "pptx")[];
};

export function goalArtifactUrl(runId: string, artifactId: string): string {
  return `${API_BASE}/research/goal-runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`;
}

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
