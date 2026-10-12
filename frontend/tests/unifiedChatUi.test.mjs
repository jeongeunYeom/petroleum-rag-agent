import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("main chat has one autonomous entry and no visible Goal Research drawer", () => {
  assert.match(page, /startGoalResearchFromMessage\(/);
  assert.match(page, /pendingGoalRun\(messages\)/);
  assert.match(page, /resumeGoalResearch\(pendingRun\.run_id/);
  assert.match(page, /const assistantId = crypto\.randomUUID\(\)/);
  assert.match(page, /updateAssistant\(completed\)/);
  assert.doesNotMatch(page, /GoalResearchPanel|goal-research-drawer|🎯 목표 연구|최대 반복|askResearch\(/);
  assert.match(page, /<AgentProcessSummary run=\{message\.goalRun\}/);
  assert.match(page, /goalArtifactUrl\(/);
});
