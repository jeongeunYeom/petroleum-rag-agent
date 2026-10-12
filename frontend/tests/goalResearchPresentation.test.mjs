import assert from "node:assert/strict";
import test from "node:test";

import {
  actionProgressText, criterionPresentation, hypothesisStatusLabel,
  iterationActionSummary,
} from "../lib/goalResultPresentation.ts";

test("hypothesis status is shown only when a hypothesis was supplied", () => {
  assert.equal(hypothesisStatusLabel({ expected_result: null, expected_result_status: "not_provided" }), null);
  assert.equal(hypothesisStatusLabel({ expected_result: "  ", expected_result_status: "supported" }), null);
  assert.equal(hypothesisStatusLabel({ expected_result: "API가 높다", expected_result_status: "supported" }), "가설 지지");
  assert.equal(hypothesisStatusLabel({ expected_result: "API가 높다", expected_result_status: "partially_supported" }), "가설 일부 지지");
  assert.equal(hypothesisStatusLabel({ expected_result: "API가 높다", expected_result_status: "contradicted" }), "가설 반박");
  assert.equal(hypothesisStatusLabel({ expected_result: "API가 높다", expected_result_status: "insufficient_evidence" }), "가설 판단 근거 부족");
});

test("criterion description takes priority over generic reason", () => {
  const frozen = [{ criterion_id: "C1", description: "내부 교재에서 관계식 근거를 확인함", required: true }];
  const item = { criterion_id: "C1", status: "met", supporting_evidence: [] };
  assert.deepEqual(criterionPresentation({ ...item, reason: "현재 입력과 검증된 계산 결과로 조건을 충족했습니다." }, frozen),
    { description: frozen[0].description, detail: null });
  assert.deepEqual(criterionPresentation({ ...item, reason: "p.90에 해당 식이 있습니다." }, frozen),
    { description: frozen[0].description, detail: "p.90에 해당 식이 있습니다." });
  assert.deepEqual(criterionPresentation({ ...item, reason: "구체적 검증 근거" }, []),
    { description: "구체적 검증 근거", detail: null });
});

test("progress and iteration details use the actual action iteration", () => {
  const action = (action_id, iteration, action_type) => ({
    action_id, iteration, action_type, status: "completed", reason_code: "ok",
    evidence_added: [], computation_ids: [], coverage_after: 1,
  });
  const history = [
    action("A1", 1, "retrieve"), action("A2", 2, "calculate"),
    action("A3", 3, "verify"), action("A4", 4, "synthesize"),
    action("A5", 4, "stop"),
  ];
  assert.deepEqual(history.map(actionProgressText), [
    "Iteration 1 · 근거 검색 · 완료", "Iteration 2 · Python 계산 · 완료",
    "Iteration 3 · 근거 검증 · 완료", "Iteration 4 · 답변 정리 · 완료",
    "Iteration 4 · 종료 · 완료",
  ]);
  assert.equal(iterationActionSummary(history, 4), "답변 정리 / 종료");
  assert.equal(iterationActionSummary(history, 2), "Python 계산");
  assert.equal(iterationActionSummary(history, 5), "");
});
