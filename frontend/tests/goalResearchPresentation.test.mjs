import assert from "node:assert/strict";
import test from "node:test";

import { actionIterationLabel, clarificationDetails, criterionText, currentActionLabel,
  hypothesisLabel, isBusyExecution, isStaleRun, resumeExistingRun, runStatusLabel } from "../lib/goalResearchPresentation.ts";

const run = {
  run_id: "same-run", run_status: "waiting_for_user_input", current_stage: "waiting_for_user_input",
  clarification_question: "C 값을 알려주세요.", required_inputs: ["C 값과 단위"],
  expected_result: null, expected_result_status: "not_provided",
  frozen_criteria: [{ criterion_id: "C1", description: "내부 식을 확인하고 결과를 검증" }],
  action_history: [{ iteration: 1, action_type: "retrieve", status: "completed" },
    { iteration: 2, action_type: "calculate", status: "completed" }],
};

test("waiting label is user-facing", () => {
  assert.equal(runStatusLabel(run.run_status), "추가 입력 필요");
  assert.equal(currentActionLabel(run), "사용자 입력 대기");
});

test("clarification question is displayed verbatim", () => {
  assert.equal(clarificationDetails(run).question, "C 값을 알려주세요.");
});

test("required inputs are retained separately", () => {
  assert.deepEqual(clarificationDetails(run).requiredInputs, ["C 값과 단위"]);
});

test("reply uses the existing resume contract with the original run ID", async () => {
  const calls = [];
  await resumeExistingRun(run, "  C=3 kg  ", async (id, text) => {
    calls.push([id, text]); return { ...run, run_status: "running" };
  });
  assert.deepEqual(calls, [["same-run", "C=3 kg"]]);
});

test("same run and action history continue after reply", async () => {
  const next = await resumeExistingRun(run, "C=3 kg", async () => ({ ...run,
    run_status: "running", action_history: [...run.action_history,
      { iteration: 3, action_type: "calculate", status: "completed" }] }));
  assert.equal(next.run_id, run.run_id);
  assert.equal(next.action_history.length, 3);
});

test("unprovided hypothesis is hidden", () => {
  assert.equal(hypothesisLabel(run), null);
  assert.equal(hypothesisLabel({ ...run, expected_result: "Higher", expected_result_status: "supported" }), "가설 지지");
});

test("criterion description takes precedence over generic reason", () => {
  const result = criterionText(run, "C1", "현재 입력과 검증된 계산 결과로 조건을 충족했습니다.");
  assert.equal(result.description, "내부 식을 확인하고 결과를 검증");
  assert.equal(result.detail, null);
});

test("action labels use actual iteration values", () => {
  assert.equal(actionIterationLabel({ iteration: 7, action_type: "retrieve" }), "Iteration 7 · 근거 검색");
});

test("two real calculation iterations remain distinct", () => {
  assert.deepEqual([2, 3].map((iteration) => actionIterationLabel({ iteration, action_type: "calculate" })),
    ["Iteration 2 · Python 계산", "Iteration 3 · Python 계산"]);
});

test("waiting is not busy execution, while running remains busy", () => {
  assert.equal(isBusyExecution(run), false);
  assert.equal(isBusyExecution({ ...run, run_status: "running" }), true);
});

test("stale warning is informational and only for a running run", () => {
  assert.equal(isStaleRun({ ...run, run_status: "running" }, 0, 46000), true);
  assert.equal(isStaleRun(run, 0, 46000), false);
});
