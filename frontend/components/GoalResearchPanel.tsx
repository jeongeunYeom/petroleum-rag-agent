"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { MarkdownMath } from "@/components/MarkdownMath";
import {
  cancelGoalResearch,
  getGoalResearch,
  goalArtifactUrl,
  GoalCriterion,
  GoalResearchRun,
  resumeGoalResearch,
  startGoalResearch,
} from "@/lib/goalResearchApi";
import { ACTION_LABEL, actionIterationLabel, clarificationDetails, criterionText, currentActionLabel,
  hypothesisLabel, isBusyExecution, isStaleRun, resumeExistingRun, runStatusLabel } from "@/lib/goalResearchPresentation";
import {
  clampIterations, displayAnswer, displayValue, evidenceCounts, formatNumber,
  outputLabel, simulationTable,
} from "@/lib/goalResultPresentation";


const TERMINAL = new Set(["completed", "stopped", "failed", "canceled"]);
const STATUS_ICON = { met: "✓", partial: "△", unmet: "✗", blocked: "□" } as const;
const GOAL_LABEL: Record<string, string> = {
  pending: "진행 중", achieved: "목표 달성", not_supported: "근거 부족",
  insufficient_evidence: "근거 부족", stopped: "진행 중단", failed: "실패", canceled: "취소됨",
};
const STOP_LABEL: Record<string, string> = {
  goal_achieved: "목표 달성으로 종료", max_iterations: "최대 반복 횟수 도달",
  no_progress: "진전 없어 종료", insufficient_evidence: "근거 부족으로 종료",
  goal_conflicts_with_evidence: "근거와 목표 충돌", canceled: "사용자 취소",
  error: "오류로 종료", calculation_blocked: "계산 진행 불가",
  simulation_blocked: "시뮬레이션 진행 불가",
};
const CRITERION_LABEL = { met: "충족", partial: "일부 충족", unmet: "미충족", blocked: "진행 불가" } as const;

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
  const [topic, setTopic] = useState("");
  const [goal, setGoal] = useState("");
  const [expected, setExpected] = useState("");
  const [criteria, setCriteria] = useState("");
  const [maxIterations, setMaxIterations] = useState(6);
  const [iterationDraft, setIterationDraft] = useState("6");
  const [autonomous, setAutonomous] = useState(true);
  const [useInternal, setUseInternal] = useState(true);
  const [useExternal, setUseExternal] = useState(false);
  const [docx, setDocx] = useState(false);
  const [pptx, setPptx] = useState(false);
  const [run, setRun] = useState<GoalResearchRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [resuming, setResuming] = useState(false);
  const resumeLock = useRef(false);
  const [lastProgressAt, setLastProgressAt] = useState(Date.now());
  const [now, setNow] = useState(Date.now());
  const activeRun = Boolean(run && !TERMINAL.has(run.run_status));
  const busy = isBusyExecution(run);
  const progressKey = run && [run.run_id, run.run_status, run.current_iteration, run.current_stage,
    run.action_history?.length || 0, run.internal_sources.length, run.computations.length].join(":");
  useEffect(() => { setLastProgressAt(Date.now()); }, [progressKey]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(timer);
  }, []);
  const simulations = run?.computations.flatMap((computation) => {
    const table = simulationTable(computation);
    return table ? [{ computation, table }] : [];
  }) || [];

  function setIterations(value: number) {
    const bounded = Math.min(8, Math.max(1, value));
    setMaxIterations(bounded);
    setIterationDraft(String(bounded));
  }

  function commitIterations() {
    const bounded = clampIterations(iterationDraft, maxIterations);
    setIterations(bounded);
    return bounded;
  }

  function resetResearch() {
    if (activeRun || busy) return;
    setTopic("");
    setGoal("");
    setExpected("");
    setCriteria("");
    setRun(null);
    setError(null);
  }

  useEffect(() => {
    if (!run || run.run_status === "waiting_for_user_input" ||
        (TERMINAL.has(run.run_status) && !Object.values(run.deliverable_status || {}).some((status) => status === "pending" || status === "running"))) return;
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
        max_iterations: commitIterations(),
        execution_mode: autonomous ? "autonomous_goal_execution" : "legacy_goal_research",
        deliverables: [...(docx ? ["docx" as const] : []), ...(pptx ? ["pptx" as const] : [])],
      }));
    } catch (value) {
      setError(value instanceof Error ? value.message : "Goal Research를 시작하지 못했습니다.");
    }
  }

  async function submitReply(event: FormEvent) {
    event.preventDefault();
    if (!run || run.run_status !== "waiting_for_user_input" || !reply.trim() || resumeLock.current) return;
    resumeLock.current = true;
    setResuming(true);
    setError(null);
    try {
      setRun(await resumeExistingRun(run, reply, resumeGoalResearch));
      setReply("");
    } catch (value) {
      setError(value instanceof Error ? value.message : "연구를 이어가지 못했습니다.");
    } finally {
      resumeLock.current = false;
      setResuming(false);
    }
  }

  return (
    <section className="bg-white" aria-label="목표 연구 설정 및 실행 결과">
        <div className="p-5">
          <form onSubmit={submit} noValidate className="grid gap-3 md:grid-cols-2">
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
            <div className="flex flex-wrap items-center gap-4 text-xs text-slate-600 md:col-span-2">
              <label><input type="checkbox" checked={autonomous} onChange={(event) => setAutonomous(event.target.checked)} className="mr-1" />목표 지향 자율 실행</label>
              <label><input type="checkbox" checked={useInternal} onChange={(event) => setUseInternal(event.target.checked)} className="mr-1" />내부 문서</label>
              <label><input type="checkbox" checked={useExternal} onChange={(event) => setUseExternal(event.target.checked)} className="mr-1" />웹 사용</label>
              <div className="flex items-center gap-1">
                <label htmlFor="goal-max-iterations" className="mr-1">최대 반복</label>
                <button type="button" aria-label="반복 횟수 감소" disabled={maxIterations <= 1} onClick={() => setIterations(maxIterations - 1)} className="rounded border border-slate-200 px-2 py-0.5 disabled:opacity-40">−</button>
                <input id="goal-max-iterations" type="text" inputMode="numeric" pattern="[0-9]*" value={iterationDraft} onChange={(event) => setIterationDraft(event.target.value)} onBlur={commitIterations} onKeyDown={(event) => { if (event.key === "ArrowUp" || event.key === "ArrowDown") { event.preventDefault(); setIterations(clampIterations(iterationDraft, maxIterations) + (event.key === "ArrowUp" ? 1 : -1)); } }} className="w-14 rounded border border-slate-200 px-1 py-0.5 text-center" />
                <button type="button" aria-label="반복 횟수 증가" disabled={maxIterations >= 8} onClick={() => setIterations(maxIterations + 1)} className="rounded border border-slate-200 px-2 py-0.5 disabled:opacity-40">+</button>
              </div>
            </div>
            <div className="md:col-span-2 space-y-2 text-xs text-slate-600">
              {autonomous && <p className="rounded-lg bg-violet-50 p-2 text-violet-700">필요한 경우 Agent가 제한된 로컬 Python 환경에서 계산·시뮬레이션을 자동 수행합니다. 인터넷과 허용된 작업공간 밖 접근은 차단됩니다.</p>}
              <p className="font-semibold">최종 산출물</p>
              <label className="mr-4"><input type="checkbox" checked={docx} onChange={(event) => setDocx(event.target.checked)} className="mr-1" />DOCX 연구보고서</label>
              <label><input type="checkbox" checked={pptx} onChange={(event) => setPptx(event.target.checked)} className="mr-1" />PPTX 발표자료</label>
            </div>
            <button disabled={!topic.trim() || (!useInternal && !useExternal) || activeRun || busy} className="rounded-xl bg-violet-600 px-4 py-2 text-sm font-bold text-white disabled:opacity-40">
              연구 시작
            </button>
          </form>

          {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}</p>}
          {run && (
            <div className="mt-5 space-y-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-violet-100 px-3 py-1 font-bold text-violet-700">{runStatusLabel(run.run_status)}</span>
                <span>반복 {run.current_iteration}/{run.max_iterations}</span>
                <span>목표 달성률 {run.goal_coverage_percent.toFixed(0)}%</span>
                <span>현재 작업: {currentActionLabel(run)}</span>
                {!TERMINAL.has(run.run_status) && (
                  <button type="button" onClick={async () => setRun(await cancelGoalResearch(run.run_id))} className="ml-auto rounded-lg border border-red-200 px-3 py-1 text-xs text-red-600">중단</button>
                )}
                {TERMINAL.has(run.run_status) && <button type="button" onClick={resetResearch} disabled={busy} className="ml-auto rounded-lg border border-violet-200 px-3 py-1 text-xs font-semibold text-violet-700 disabled:opacity-40">새 연구</button>}
              </div>
              {isStaleRun(run, lastProgressAt, now) &&
                <p className="rounded-lg bg-amber-50 p-3 text-xs text-amber-800">진행 상태가 오랫동안 갱신되지 않았습니다.</p>}
              {run.run_status === "waiting_for_user_input" &&
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm" role="status">
                  <strong className="text-amber-900">추가 입력 필요</strong>
                  <p className="mt-2 whitespace-pre-wrap text-slate-700">{clarificationDetails(run).question}</p>
                  {!!clarificationDetails(run).requiredInputs.length && <ul className="mt-2 list-inside list-disc text-xs text-slate-700">
                    {clarificationDetails(run).requiredInputs.map((item) => <li key={item}>{item}</li>)}
                  </ul>}
                  <form onSubmit={submitReply} className="mt-3 space-y-2">
                    <label className="block text-xs font-semibold text-slate-700" htmlFor="goal-clarification-reply">필요한 값을 입력해 주세요</label>
                    <textarea id="goal-clarification-reply" value={reply} onChange={(event) => setReply(event.target.value)}
                      className="min-h-20 w-full rounded-lg border border-amber-200 bg-white p-2 text-sm" />
                    <button type="submit" disabled={!reply.trim() || resuming}
                      className="rounded-lg bg-violet-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-40">{resuming ? "연결 중…" : "계속하기"}</button>
                  </form>
                </div>}
              <div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-violet-600" style={{ width: `${run.goal_coverage_percent}%` }} /></div>
              <div className="grid gap-2 sm:grid-cols-2">
                {run.criteria.map((item) => (
                  <div key={item.criterion_id} className="rounded-xl bg-slate-50 p-3 text-xs">
                    <strong>{STATUS_ICON[item.status]} {item.criterion_id} · {CRITERION_LABEL[item.status]}</strong>
                    <p className="mt-1 text-slate-700">{criterionText(run, item.criterion_id, item.reason).description}</p>
                    {criterionText(run, item.criterion_id, item.reason).detail &&
                      <p className="mt-1 text-slate-500">{displayAnswer(criterionText(run, item.criterion_id, item.reason).detail || "", run.computations)}</p>}
                  </div>
                ))}
              </div>
              {!!run.action_history?.length && (
                <div className="rounded-xl border border-slate-200 p-3 text-xs">
                  <strong>진행 과정</strong>
                  <ol className="mt-2 space-y-1">
                    {run.action_history.map((item, index) => (
                      <li key={index}>
                        {actionIterationLabel(item)} · {item.status === "completed" ? "완료" : "진행 불가"}
                        {item.evidence_added.length > 0 ? ` · 근거 +${item.evidence_added.length}` : ""}
                        {item.computation_ids.length > 0 ? ` · 검증된 계산 +${item.computation_ids.length}` : ""}
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              {run.iterations.map((item) => (
                <details key={item.iteration} className="rounded-xl border border-slate-200 p-3">
                  <summary className="cursor-pointer font-semibold">반복 {item.iteration} · {run.action_history?.filter((action) => action.iteration === item.iteration).map((action) => ACTION_LABEL[action.action_type] || action.action_type).join(" / ") || "진행"} · 목표 달성률 {(item.goal_coverage * 100).toFixed(0)}%</summary>
                  <p className="mt-2 whitespace-pre-wrap text-xs text-slate-500">검색어: {item.research_query}</p>
                  {item.gap_analysis.length > 0 && <p className="mt-2 text-xs text-amber-700">남은 문제: {item.gap_analysis.join(" · ")}</p>}
                  {item.python_requested && <p className="mt-2 text-xs text-slate-600">Python 계산: {item.python_executed ? "실행됨" : "미실행"} · {item.python_decision_reason} · {item.computation_ids.join(", ") || "검증된 계산 없음"}</p>}
                  {item.generated_artifacts.length > 0 && <p className="mt-1 text-xs text-slate-500">생성: {item.generated_artifacts.map((path) => path.split("/").pop()).join(", ")}</p>}
                  {item.next_research_need && <p className="mt-1 text-xs text-violet-700">다음 작업: {item.next_research_need}</p>}
                </details>
              ))}
              {TERMINAL.has(run.run_status) && (
                <div className="rounded-xl border border-violet-100 bg-violet-50/40 p-4">
                  <p className="text-sm font-bold text-violet-700">{GOAL_LABEL[run.status] || "연구 종료"}</p>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-700">
                    <span className="rounded-full bg-white px-2 py-1">달성률 {run.goal_coverage_percent.toFixed(0)}%</span>
                    <span className="rounded-full bg-white px-2 py-1">반복 {run.iterations_completed}회</span>
                    <span className="rounded-full bg-white px-2 py-1">{STOP_LABEL[run.stop_reason || ""] || "종료"}</span>
                    {hypothesisLabel(run) && <span className="rounded-full bg-white px-2 py-1">{hypothesisLabel(run)}</span>}
                  </div>
                  {simulations.length === 0 && <div className="mt-3"><MarkdownMath content={displayAnswer(run.final_answer || "최종 답변이 없습니다.", run.computations)} /></div>}
                  {simulations.map(({ computation, table }) => {
                    const manifest = computation.output_manifest;
                    return <section key={computation.computation_id} className="mt-4 rounded-xl border border-violet-100 bg-white p-3">
                      <h3 className="font-semibold">시뮬레이션 결과</h3>
                      <div className="mt-2 max-h-80 overflow-auto">
                        <table className="w-full text-left text-xs"><thead className="sticky top-0 bg-slate-100"><tr><th className="px-2 py-1">{table.parameterLabel}</th><th className="px-2 py-1">{table.resultLabel}</th></tr></thead>
                          <tbody>{table.rows.map((row, index) => <tr key={index} className="border-b border-slate-100"><td className="px-2 py-1">{formatNumber(row.parameter.value as number, 2)}</td><td className="px-2 py-1">{displayValue(row.result, computation)}</td></tr>)}</tbody>
                        </table>
                      </div>
                      <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                        {(["OUT_BEST_PARAMETER", "OUT_BEST_RESULT", "OUT_MEAN_RESULT", "OUT_RANGE_RESULT"] as const).map((key) => manifest[key] && <p key={key}><strong>{outputLabel(manifest[key])}:</strong> {key === "OUT_BEST_PARAMETER" && typeof manifest[key].value === "number" ? `${table.parameterLabel} ${formatNumber(manifest[key].value, 2)}` : displayValue(manifest[key], computation)}</p>)}
                      </div>
                      <p className="mt-2 text-xs text-slate-500">근거: 검증된 계산 {computation.computation_id} · 사용자 입력 {new Set(computation.source_input_ids).size}건</p>
                    </section>;
                  })}
                  {simulations.length > 0 && <details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer">검증된 원문 보기</summary><div className="mt-2"><MarkdownMath content={run.final_answer} /></div></details>}
                  {run.computations.filter((item) => item.validation_passed && !simulationTable(item)).map((item) => <section key={item.computation_id} className="mt-4 rounded-xl border border-violet-100 bg-white p-3 text-xs">
                    <h3 className="font-semibold">검증된 계산 · {item.computation_id}</h3>
                    <div className="mt-2 grid gap-2 sm:grid-cols-2">{Object.entries(item.output_manifest).map(([id, output]) => <p key={id}><strong>{outputLabel(output)}</strong><br /><span className="text-base text-slate-900">{displayValue(output, item)}</span></p>)}</div>
                    <p className="mt-2 text-slate-500">근거: {item.input_facts.filter((fact) => item.source_input_ids.includes(fact.evidence_id || fact.canonical_fact_id || "")).map((fact) => `사용자 입력 ${fact.name} = ${formatNumber(fact.value)}${fact.unit && fact.unit !== "dimensionless" ? ` ${fact.unit}` : ""}`).join(" · ") || `사용자 입력 ${new Set(item.source_input_ids).size}건`}{run.internal_sources.filter((source) => [...item.source_evidence_ids, ...item.formula_evidence_ids].includes(source.evidence_id)).map((source) => ` · ${source.document}${source.page ? ` p.${source.page}` : ""}`)}</p>
                  </section>)}
                  <p className="mt-3 text-xs text-slate-500">근거: 내부 문서 {run.internal_sources.length} · 웹 {run.web_sources.length} · Figure {run.figures.length} · 사용자 입력 {evidenceCounts(run).userInputs} · 검증된 계산 {evidenceCounts(run).calculations}</p>
                  {Object.keys(run.deliverable_status || {}).length > 0 && <div className="mt-3 text-xs"><strong>최종 산출물</strong>{Object.entries(run.deliverable_status).map(([kind, status]) => <p key={kind}>{kind.toUpperCase()}: {runStatusLabel(status)} {run.deliverable_errors?.[kind] || ""}</p>)}{run.artifacts.map((artifact) => <a key={artifact.artifact_id} className="mr-4 text-violet-700 underline" href={goalArtifactUrl(run.run_id, artifact.artifact_id)} download>{artifact.artifact_type.toUpperCase()} 다운로드</a>)}</div>}
                </div>
              )}
            </div>
          )}
        </div>
    </section>
  );
}
