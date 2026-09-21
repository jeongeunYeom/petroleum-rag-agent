import { API_BASE, requestJson } from "./http";

export type AgentPermissionLevel = 1 | 2 | 3;
export type AgentChartType = "scatter" | "line" | "bar" | "histogram";
export type AgentTaskStatus =
  | "planned"
  | "running"
  | "completed"
  | "failed"
  | "canceled";

export type AgentToolName =
  | "list_directory"
  | "read_file"
  | "search_knowledge_base"
  | "get_related_figures"
  | "create_file"
  | "edit_file"
  | "run_python";

export type AgentAction = {
  action_id: string;
  tool: AgentToolName;
  description: string;
  arguments: Record<string, unknown>;
  target_files: string[];
  requires_approval: boolean;
  preview?: string | null;
};

export type AgentTask = {
  task_id: string;
  conversation_id?: string | null;
  context_source_task_id?: string | null;
  context_files: string[];
  request: string;
  status: AgentTaskStatus;
  permission_level: AgentPermissionLevel;
  plan: string[];
  required_tools: AgentToolName[];
  actions: AgentAction[];
  requires_approval: boolean;
  approved: boolean;
  workspace: string;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  current_action?: string | null;
  progress_step: number;
  progress_total: number;
  tools_used: string[];
  read_files: string[];
  created_files: string[];
  modified_files: string[];
  backups: string[];
  execution_records: Array<Record<string, unknown>>;
  results: Array<{
    action_id: string;
    tool: AgentToolName;
    description: string;
    result: Record<string, unknown>;
  }>;
  validation_passed?: boolean | null;
  validation_records: Array<{
    action_id: string;
    tool: AgentToolName;
    passed: boolean;
    checks: Array<{
      name: string;
      passed: boolean;
      detail: string;
      path?: string;
    }>;
    errors: string[];
  }>;
  error?: string | null;
  cancel_requested: boolean;
};

export type AgentPlanInput = {
  request: string;
  research_mode?: boolean;
  conversation_id?: string;
  target_path?: string;
  target_paths?: string[];
  output_path?: string;
  compare_column?: string;
  x_column?: string;
  y_column?: string;
  chart_type?: AgentChartType;
  content?: string;
  old_text?: string;
  new_text?: string;
  python_code?: string;
  permission_level: AgentPermissionLevel;
};

export function createAgentPlan(input: AgentPlanInput): Promise<AgentTask> {
  return requestJson("/agent/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function executeAgentTask(
  taskId: string,
  approved: boolean,
): Promise<AgentTask> {
  return requestJson(`/agent/tasks/${taskId}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
}

export function getAgentTask(taskId: string): Promise<AgentTask> {
  return requestJson(`/agent/tasks/${taskId}`, { cache: "no-store" });
}

export function getAgentFileUrl(path: string, download = false): string {
  const query = new URLSearchParams({ path, download: String(download) });
  return `${API_BASE}/agent/files/content?${query}`;
}
