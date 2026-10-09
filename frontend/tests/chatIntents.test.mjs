import assert from "node:assert/strict";
import test from "node:test";

import { goalStageLabel, wantsFigureReview } from "../lib/chatIntents.ts";

test("figure review opens only on an explicit viewer request", () => {
  assert.equal(wantsFigureReview("방금 추가한 문서의 Figure 보여줘"), true);
  assert.equal(wantsFigureReview("추출된 그림 확인하고 싶어"), true);
  assert.equal(wantsFigureReview("최근 추가한 문서에서 추출된 Figure를 확인하고 싶어."), true);
  assert.equal(wantsFigureReview("새로 등록한 PDF의 그림 검토 화면을 열어줘"), true);
  assert.equal(wantsFigureReview("Please show the extracted figures from the new document"), true);
  assert.equal(wantsFigureReview("Open Figure Review"), true);
  assert.equal(wantsFigureReview("Figure 3의 의미를 설명해줘"), false);
  assert.equal(wantsFigureReview("저장량을 계산해줘"), false);
});

test("agent progress is phrased for users", () => {
  assert.equal(goalStageLabel("retrieve"), "자료 검색 중");
  assert.equal(goalStageLabel("calculate"), "계산 중");
  assert.equal(goalStageLabel("simulate"), "시뮬레이션 중");
  assert.equal(goalStageLabel("waiting_for_user_input"), "추가 정보 필요");
  assert.equal(goalStageLabel("verify"), "결과 검증 중");
  assert.equal(goalStageLabel("synthesize"), "답변 작성 중");
});
