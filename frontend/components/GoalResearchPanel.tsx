"use client";

import { FormEvent, useEffect, useState } from "react";

import { MarkdownMath } from "@/components/MarkdownMath";
import {
  cancelGoalResearch,
  getGoalResearch,
  goalArtifactUrl,
  GoalCriterion,
  GoalResearchRun,
  startGoalResearch,
} from "@/lib/goalResearchApi";


const TERMINAL = new Set(["completed", "stopped", "failed", "canceled"]);
const STATUS_ICON = { met: "✓", partial: "△", unmet: "✗", blocked: "□" } as const;
const ACTION_LABEL: Record<string, string> = {
  retrieve: "근거 검색", calculate: "Python 계산", simulate: "수치 시뮬레이션",
  analyze: "결과 분석", verify: "근거 검증", synthesize: "답변 정리", stop: "종료",
};

function parseCriteria(value: string): GoalCriterion[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((description, index) => ({
      criterion_id: `C${index + 1}`,
      description,
      required: true,
    }));
}

export function GoalResearchPanel() {
  const [open, setOpen] = useState(false);
  const [topic, setTopic] = useState("");
  const [goal, setGoal] = useState("");
  const [expected, setExpected] = useState("");
  const [criteria, setCriteria] = useState("");
  const [maxIterations, setMaxIterations] = useState(4);
  const [autonomous, setAutonomous] = useState(true);
  const [useInternal, setUseInternal] = useState(true);
  const [useExternal, setUseExternal] = useState(false);
  const [allowPython, setAllowPython] = useState(false);
  const [pythonApproved, setPythonApproved] = useState(false);
  const [docx, setDocx] = useState(false);
  const [pptx, setPptx] = useState(false);
  const [run, setRun] = useState<GoalResearchRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!run || (TERMINAL.has(run.run_status) && !Object.values(run.deliverable_status || {}).some((status) => status === "pending" || status === "running"))) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await getGoalResearch(run.run_id);
        setRun(next);
      } catch (value) {
        setError(value instanceof Error ? value.message : "진행 상태를 불러오지 못했습니다.");
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [run]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!topic.trim()) return;
    setError(null);
    try {
      setRun(await startGoalResearch({
        topic: topic.trim(),
        goal: goal.trim() || undefined,
        expected_result: expected.trim() || undefined,
        success_criteria: parseCriteria(criteria),
        use_internal: useInternal,
        use_external: useExternal,
        max_iterations: maxIterations,
        execution_mode: autonomous ? "autonomous_goal_execution" : "legacy_goal_research",
        allow_python_execution: allowPython,
        python_execution_approved: allowPython && pythonApproved,
        deliverables: [...(docx ? ["docx" as const] : []), ...(pptx ? ["pptx" as const] : [])],
      }));
    } catch (value) {
      setError(value instanceof Error ? value.message : "Goal Research를 시작하지 못했습니다.");
    }
  }

  return (
    <section className="rounded-2xl border border-violet-200 bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between px-5 py-4 text-left"
      >
        <span>
          <strong className="text-sm text-slate-900">Goal Research</strong>
          <span className="ml-2 text-xs text-slate-500">목표별 검색 · 계산 · 검증</span>
        </span>
        <span className="text-violet-600">{open ? "−" : "+"}</span>
      </button>

      {open && (
        <div className="border-t border-violet-100 p-5">
          <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
            <label className="md:col-span-2 text-xs font-semibold text-slate-600">
              연구 주제
              <input value={topic} onChange={(event) => setTopic(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" required />
            </label>
            <label className="text-xs font-semibold text-slate-600">
              연구 목표
              <textarea value={goal} onChange={(event) => setGoal(event.target.value)} className="mt-1 min-h-20 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" />
            </label>
            <label className="text-xs font-semibold text-slate-600">
              예상 결과 / 가설
              <textarea value={expected} onChange={(event) => setExpected(event.target.value)} className="mt-1 min-h-20 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" />
            </label>
            <label className="md:col-span-2 text-xs font-semibold text-slate-600">
              성공 조건 — 한 줄에 하나, 비우면 자동 생성
              <textarea value={criteria} onChange={(event) => setCriteria(event.target.value)} className="mt-1 min-h-24 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm" />
            </label>
            <div className="flex flex-wrap items-center gap-4 text-xs text-slate-600">
              <label><input type="checkbox" checked={autonomous} onChange={(event) => setAutonomous(event.target.checked)} className="mr-1" />목표 지향 자율 실행</label>
              <label><input type="checkbox" checked={useInternal} onChange={(event) => setUseInternal(event.target.checked)} className="mr-1" />내부 문서</label>
              <label><input type="checkbox" checked={useExternal} onChange={(event) => setUseExternal(event.target.checked)} className="mr-1" />웹 사용</label>
              <label>최대 반복 <input type="number" min={1} max={8} value={maxIterations} onChange={(event) => setMaxIterations(Number(event.target.value))} className="ml-1 w-14 rounded border border-slate-200 px-1 py-0.5" /></label>
            </div>
            <div className="md:col-span-2 space-y-2 text-xs text-slate-600">
              <label className="block"><input type="checkbox" checked={allowPython} onChange={(event) => { setAllowPython(event.target.checked); setPythonApproved(false); }} className="mr-1" />Python 계산 허용</label>
              {allowPython && <label className="block rounded-lg border border-amber-200 bg-amber-50 p-3"><input type="checkbox" checked={pythonApproved} onChange={(event) => setPythonApproved(event.target.checked)} className="mr-1" />Agent가 제한된 로컬 Python 환경에서 계산 코드를 자동 작성·실행합니다. 인터넷과 작업공간 밖 파일 접근은 차단됩니다. 이를 승인합니다.</label>}
              <p className="font-semibold">최종 산출물</p>
              <label className="mr-4"><input type="checkbox" checked={docx} onChange={(event) => setDocx(event.target.checked)} className="mr-1" />DOCX 연구보고서</label>
              <label><input type="checkbox" checked={pptx} onChange={(event) => setPptx(event.target.checked)} className="mr-1" />PPTX 발표자료</label>
            </div>
            <button disabled={!topic.trim() || (!useInternal && !useExternal) || (allowPython && !pythonApproved) || Boolean(run && (!TERMINAL.has(run.run_status) || Object.values(run.deliverable_status || {}).some((status) => status === "pending" || status === "running")))} className="rounded-xl bg-violet-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-40">
              Goal Research 시작
            </button>
          </form>

          {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}</p>}
          {run && (
            <div className="mt-5 space-y-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-violet-100 px-3 py-1 font-bold text-violet-700">{run.run_status}</span>
                <span>Iteration {run.current_iteration}/{run.max_iterations}</span>
                <span>Coverage {run.goal_coverage_percent.toFixed(0)}%</span>
                <span>현재 작업: {ACTION_LABEL[run.current_action || ""] || run.current_stage}</span>
                {!TERMINAL.has(run.run_status) && (
                  <button type="button" onClick={async () => setRun(await cancelGoalResearch(run.run_id))} className="ml-auto rounded-lg border border-red-200 px-3 py-1 text-xs text-red-600">중단</button>
                )}
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-violet-600" style={{ width: `${run.goal_coverage_percent}%` }} /></div>
              <div className="grid gap-2 sm:grid-cols-2">
                {run.criteria.map((item) => (
                  <div key={item.criterion_id} className="rounded-xl bg-slate-50 p-3 text-xs">
                    <strong>{STATUS_ICON[item.status]} {item.criterion_id} · {item.status}</strong>
                    <p className="mt-1 text-slate-500">{item.reason}</p>
                  </div>
                ))}
              </div>
              {!!run.action_history?.length && (
                <div className="rounded-xl border border-slate-200 p-3 text-xs">
                  <strong>진행 과정</strong>
                  <ol className="mt-2 space-y-1">
                    {run.action_history.map((item, index) => (
                      <li key={index}>
                        {index + 1}. {ACTION_LABEL[item.action_type] || item.action_type} · {item.status === "completed" ? "완료" : "진행 불가"}
                        {item.evidence_added.length > 0 ? ` · 근거 +${item.evidence_added.length}` : ""}
                        {item.computation_ids.length > 0 ? ` · 검증된 계산 +${item.computation_ids.length}` : ""}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              {run.iterations.map((item) => (
                <details key={item.iteration} className="rounded-xl border border-slate-200 p-3">
                  <summary className="cursor-pointer font-semibold">Iteration {item.iteration} · coverage {(item.goal_coverage * 100).toFixed(0)}% · evidence +{item.evidence_added.length}</summary>
                  <p className="mt-2 whitespace-pre-wrap text-xs text-slate-500">Query: {item.research_query}</p>
                  {item.gap_analysis.length > 0 && <p className="mt-2 text-xs text-amber-700">Gaps: {item.gap_analysis.join(" · ")}</p>}
                  {item.python_requested && <p className="mt-2 text-xs text-slate-600">Python Analysis: {item.python_executed ? "실행됨" : "미실행"} · {item.python_decision_reason} · {item.computation_ids.join(", ") || "검증된 계산 없음"}</p>}
                  {item.generated_artifacts.length > 0 && <p className="mt-1 text-xs text-slate-500">생성: {item.generated_artifacts.map((path) => path.split("/").pop()).join(", ")}</p>}
                  {item.next_research_need && <p className="mt-1 text-xs text-violet-700">다음 작업: {item.next_research_need}</p>}
                </details>
              ))}
              {TERMINAL.has(run.run_status) && (
                <div className="rounded-xl border border-violet-100 bg-violet-50/40 p-4">
                  <p className="text-xs font-bold uppercase text-violet-700">{run.status} · {run.stop_reason} · hypothesis {run.expected_result_status}</p>
                  <div className="mt-3"><MarkdownMath content={(run.final_answer || "최종 답변이 없습니다.").replace(/\[USERF\d+\]/g, "[사용자 입력]")} /></div>
                  <p className="mt-3 text-xs text-slate-500">근거: 내부 {run.internal_sources.length} · 웹 {run.web_sources.length} · Figure {run.figures.length}</p>
                  {run.computations.length > 0 && <div className="mt-3 text-xs"><strong>Calculations</strong>{run.computations.map((item) => <p key={item.computation_id}>{item.computation_id} {item.validation_passed ? "✓" : "실패"} · {item.purpose} · {item.summary}</p>)}</div>}
                  {Object.keys(run.deliverable_status || {}).length > 0 && <div className="mt-3 text-xs"><strong>Deliverables</strong>{Object.entries(run.deliverable_status).map(([kind, status]) => <p key={kind}>{kind.toUpperCase()}: {status} {run.deliverable_errors?.[kind] || ""}</p>)}{run.artifacts.map((artifact) => <a key={artifact.artifact_id} className="mr-4 text-violet-700 underline" href={goalArtifactUrl(run.run_id, artifact.artifact_id)} download>{artifact.artifact_type.toUpperCase()} 다운로드</a>)}</div>}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
