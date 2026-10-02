"use client";

import { FormEvent, useEffect, useState } from "react";

import { MarkdownMath } from "@/components/MarkdownMath";
import {
  cancelGoalResearch,
  getGoalResearch,
  GoalCriterion,
  GoalResearchRun,
  startGoalResearch,
} from "@/lib/goalResearchApi";


const TERMINAL = new Set(["completed", "stopped", "failed", "canceled"]);
const STATUS_ICON = { met: "✓", partial: "△", unmet: "✗", blocked: "□" } as const;

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
  const [useInternal, setUseInternal] = useState(true);
  const [useExternal, setUseExternal] = useState(false);
  const [run, setRun] = useState<GoalResearchRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!run || TERMINAL.has(run.run_status)) return;
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
          <span className="ml-2 text-xs text-slate-500">반복 연구 · gap 기반 재검색</span>
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
              <label><input type="checkbox" checked={useInternal} onChange={(event) => setUseInternal(event.target.checked)} className="mr-1" />내부 문서</label>
              <label><input type="checkbox" checked={useExternal} onChange={(event) => setUseExternal(event.target.checked)} className="mr-1" />웹 사용</label>
              <label>최대 반복 <input type="number" min={1} max={8} value={maxIterations} onChange={(event) => setMaxIterations(Number(event.target.value))} className="ml-1 w-14 rounded border border-slate-200 px-1 py-0.5" /></label>
            </div>
            <button disabled={!topic.trim() || (!useInternal && !useExternal) || Boolean(run && !TERMINAL.has(run.run_status))} className="rounded-xl bg-violet-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-40">
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
                <span>Stage {run.current_stage}</span>
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
              {run.iterations.map((item) => (
                <details key={item.iteration} className="rounded-xl border border-slate-200 p-3">
                  <summary className="cursor-pointer font-semibold">Iteration {item.iteration} · coverage {(item.goal_coverage * 100).toFixed(0)}% · evidence +{item.evidence_added.length}</summary>
                  <p className="mt-2 whitespace-pre-wrap text-xs text-slate-500">Query: {item.research_query}</p>
                  {item.gap_analysis.length > 0 && <p className="mt-2 text-xs text-amber-700">Gaps: {item.gap_analysis.join(" · ")}</p>}
                  {item.next_research_need && <p className="mt-1 text-xs text-violet-700">다음 작업: {item.next_research_need}</p>}
                </details>
              ))}
              {TERMINAL.has(run.run_status) && (
                <div className="rounded-xl border border-violet-100 bg-violet-50/40 p-4">
                  <p className="text-xs font-bold uppercase text-violet-700">{run.status} · {run.stop_reason} · hypothesis {run.expected_result_status}</p>
                  <div className="mt-3"><MarkdownMath content={run.final_answer || "최종 답변이 없습니다."} /></div>
                  <p className="mt-3 text-xs text-slate-500">근거: 내부 {run.internal_sources.length} · 웹 {run.web_sources.length} · Figure {run.figures.length}</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
