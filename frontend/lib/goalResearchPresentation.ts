import type { GoalResearchRun } from "./goalResearchApi";

export const ACTION_LABEL: Record<string, string> = {
  retrieve: "근거 검색", calculate: "Python 계산", simulate: "수치 시뮬레이션",
  analyze: "결과 분석", verify: "근거 검증", synthesize: "답변 정리", stop: "종료",
};

export function runStatusLabel(status: string): string {
  return ({ planned: "대기 중", running: "실행 중", waiting_for_user_input: "추가 입력 필요",
    completed: "완료", stopped: "중단됨", failed: "실패", canceled: "취소됨" } as Record<string, string>)[status] || status;
}

export function isBusyExecution(run: GoalResearchRun | null): boolean {
  return Boolean(run && (run.run_status === "running" || run.run_status === "planned" ||
    Object.values(run.deliverable_status || {}).some((status) => status === "pending" || status === "running")));
}

export function isStaleRun(run: GoalResearchRun | null, lastProgressAt: number, now: number): boolean {
  return Boolean(run?.run_status === "running" && now - lastProgressAt > 45000);
}

export function currentActionLabel(run: GoalResearchRun): string {
  if (run.run_status === "waiting_for_user_input") return "사용자 입력 대기";
  return ACTION_LABEL[run.current_action || ""] || ACTION_LABEL[run.current_stage] || "준비 중";
}

export function clarificationDetails(run: GoalResearchRun): { question: string; requiredInputs: string[] } {
  return { question: run.clarification_question || "계산을 계속하려면 다음 정보가 필요합니다.",
    requiredInputs: run.required_inputs || [] };
}

export function criterionText(run: GoalResearchRun, criterionId: string, reason: string): {
  description: string; detail: string | null;
} {
  const description = run.frozen_criteria.find((item) => item.criterion_id === criterionId)?.description || "";
  const generic = /^(?:현재 입력과 검증된 계산 결과로 조건을 충족했습니다\.|조건을 충족했습니다\.|검증된 결과로 충족했습니다\.)$/;
  return { description: description || (generic.test(reason.trim()) ? "조건 확인" : reason),
    detail: description && reason.trim() && reason.trim() !== description.trim() && !generic.test(reason.trim())
      ? reason : null };
}

export function actionIterationLabel(item: NonNullable<GoalResearchRun["action_history"]>[number]): string {
  return `Iteration ${item.iteration} · ${ACTION_LABEL[item.action_type] || item.action_type}`;
}

export function hypothesisLabel(run: GoalResearchRun): string | null {
  if (!run.expected_result?.trim() || run.expected_result_status === "not_provided") return null;
  return ({ supported: "가설 지지", partially_supported: "가설 일부 지지",
    contradicted: "가설 반박", insufficient_evidence: "가설 판단 근거 부족" } as Record<string, string>)[run.expected_result_status] || null;
}

export async function resumeExistingRun(
  run: GoalResearchRun, message: string,
  resume: (runId: string, text: string) => Promise<GoalResearchRun>,
): Promise<GoalResearchRun> {
  const next = await resume(run.run_id, message.trim());
  if (next.run_id !== run.run_id) throw new Error("기존 연구 실행을 이어가지 못했습니다.");
  return next;
}
