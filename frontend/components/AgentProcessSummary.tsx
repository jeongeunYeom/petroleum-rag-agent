import type { GoalResearchRun } from "@/lib/goalResearchApi";
import { processSteps } from "@/lib/goalResultPresentation";

export function AgentProcessSummary({ run }: { run: GoalResearchRun }) {
  const steps = processSteps(run);
  if (!steps.length) return null;
  return <details className="mt-4 border-t border-slate-100 pt-3 text-xs text-slate-500">
    <summary className="cursor-pointer font-medium">작업 과정 · {steps.length}단계 완료</summary>
    <ol className="mt-2 space-y-1 pl-1">
      {steps.map((step, index) => <li key={`${index}:${step}`}>✓ {step}</li>)}
    </ol>
  </details>;
}
