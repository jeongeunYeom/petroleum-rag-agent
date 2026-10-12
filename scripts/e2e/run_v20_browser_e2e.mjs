/** Real Chromium/Edge UI validation; no product mocks or synthetic run results. */
import { chromium } from "playwright-core";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const out = path.join(root, "evaluation", "v20_1_browser_e2e");
const screenshots = path.join(out, "screenshots");
const logs = path.join(out, "logs");
const appUrl = process.env.V20_APP_URL || "http://127.0.0.1:3000";
const apiUrl = process.env.V20_API_URL || "http://127.0.0.1:8001/api";
const edgePath = process.env.V20_BROWSER_EXE || "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const terminal = new Set(["completed", "stopped", "failed", "canceled", "waiting_for_user_input"]);
const prompts = {
  A: "방향 측정기 근처에 Monel drill collar를 사용하는 이유를 내부 자료에 근거해 설명해줘.",
  B: "비중(SG)이 0.918인 원유의 API gravity를 내부 교재의 관계식을 이용해 계산하고, 사용한 식과 출처를 검증해줘.",
  C: "그럼 0.85면?",
  D: "내부 Formation Evaluation 자료에서 공극률, 물 포화도, 물의 비저항과 지층의 진비저항 사이의 관계를 찾아서, φ=0.22, Sw=0.35, Rw=0.08 Ω·m, a=1, m=2, n=2일 때 Rt를 계산하고 근거와 계산 결과를 검증해줘.",
  E: "내부 Drilling Engineering 자료에서 mud weight와 TVD를 이용한 hydrostatic pressure 관계식을 찾아서, MW=10.1 ppg일 때 압력을 계산하고 검증해줘.",
  E_reply: "TVD는 8000 ft야.",
  F: "A=187, B=234, C=163 stb/d의 평균을 구하고 큰 순서대로 정렬해줘.",
};

await mkdir(screenshots, { recursive: true });
await mkdir(logs, { recursive: true });
const browser = await chromium.launch({ executablePath: edgePath, headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1.5, locale: "ko-KR" });
const page = await context.newPage();
const browserErrors = [];
page.on("console", (message) => { if (message.type() === "error") browserErrors.push(`console: ${message.text()}`); });
page.on("pageerror", (error) => browserErrors.push(`pageerror: ${error.message}`));
const results = { environment: { browser: `Microsoft Edge ${browser.version()}`, viewport: "1440x1000 @1.5x", app_url: appUrl, api_url: apiUrl }, ui_integration: {}, scenarios: [] };

async function save() {
  await writeFile(path.join(out, "results.json"), JSON.stringify(results, null, 2) + "\n", "utf8");
  await writeFile(path.join(logs, "browser_console.log"), browserErrors.join("\n") + (browserErrors.length ? "\n" : ""), "utf8");
}

async function screenshot(filename) {
  await page.screenshot({ path: path.join(screenshots, filename), animations: "disabled" });
  return `screenshots/${filename}`;
}

async function newChat() {
  await page.getByRole("button", { name: /새 채팅/ }).click();
  await page.locator("textarea").waitFor({ state: "visible" });
}

async function getRun(runId) {
  const response = await fetch(`${apiUrl}/research/goal-runs/${encodeURIComponent(runId)}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Run metadata HTTP ${response.status}: ${runId}`);
  return response.json();
}

async function waitForRun(runId, timeoutMs = 480000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const run = await getRun(runId);
    if (terminal.has(run.run_status) && !Object.values(run.deliverable_status || {}).some((value) => ["pending", "running"].includes(value))) {
      // The send button remains disabled for an empty textarea even after completion.
      await page.waitForTimeout(1000);
      return run;
    }
    await page.waitForTimeout(750);
  }
  throw new Error(`Run did not finish within ${timeoutMs / 1000}s: ${runId}`);
}

async function submit(prompt, endpoint) {
  const input = page.locator("textarea");
  await input.fill(prompt);
  const sent = page.waitForResponse((response) => response.request().method() === "POST" &&
    response.url().includes(`/api/research/goal-runs/${endpoint}`), { timeout: 45000 });
  await page.getByRole("button", { name: "Send message" }).click();
  const response = await sent;
  if (!response.ok()) throw new Error(`Submission HTTP ${response.status()}: ${(await response.text()).slice(0, 600)}`);
  const started = await response.json();
  return waitForRun(started.run_id);
}

async function expandProcess() {
  const summary = page.locator("summary").filter({ hasText: "작업 과정" }).last();
  if (await summary.count()) {
    if ((await summary.locator("..").getAttribute("open")) === null) await summary.click();
    await summary.scrollIntoViewIfNeeded();
  }
}

function outputs(run) {
  return (run.computations || []).filter((calc) => calc.validation_passed).flatMap((calc) =>
    Object.entries(calc.output_manifest || {}).map(([key, value]) => ({ calculation_id: calc.computation_id, key, name: value.name, value: value.value, unit: value.unit ?? null })));
}

function target(run, name) {
  return outputs(run).find((item) => (item.name || item.key || "").toLowerCase() === name.toLowerCase()) || null;
}

function summary(id, prompt, run, images, pass, notes = [], extra = {}) {
  const chosen = extra.target_name ? target(run, extra.target_name) : null;
  return {
    scenario_id: id, prompt, run_id: run.run_id, pass, run_status: run.run_status,
    goal_status: run.status, stop_reason: run.stop_reason, actual_iterations: run.iterations_completed,
    actions: (run.action_history || []).map((action) => action.action_type),
    internal_sources: (run.internal_sources || []).length, web_sources: (run.web_sources || []).length,
    validated_calculations: (run.computations || []).filter((calc) => calc.validation_passed).length,
    calculation_outputs: outputs(run), final_target: extra.target_name || null,
    final_value: chosen?.value ?? null, final_unit: chosen?.unit ?? null,
    clarification_turns: run.telemetry?.clarification_turns ?? 0,
    conversation_context_used: run.telemetry?.conversation_context_used ?? false,
    source_refs: (run.internal_sources || []).map((source) => ({ id: source.evidence_id, document: source.document, page: source.page })),
    screenshot_paths: images, notes,
    ...Object.fromEntries(Object.entries(extra).filter(([key]) => key !== "target_name")),
  };
}

async function runScenario(id, prompt, filename, evaluate, { fresh = true, endpoint = "from-message", targetName = null } = {}) {
  console.log(`[${id}] Starting`);
  const errorsBefore = browserErrors.length;
  const images = [];
  try {
    if (fresh) await newChat();
    const run = await submit(prompt, endpoint);
    await expandProcess();
    images.push(await screenshot(filename));
    const text = await page.locator("body").innerText();
    const [pass, notes] = evaluate(run, text);
    const result = summary(id, prompt, run, images, pass, notes, { target_name: targetName, browser_errors: browserErrors.slice(errorsBefore) });
    results.scenarios.push(result);
    await save();
    console.log(`[${id}] ${pass ? "PASS" : "FAIL"} ${run.run_id} ${run.run_status} ${result.actions.join(" → ")}`);
    return { run, result };
  } catch (error) {
    try { images.push(await screenshot(`${id.toLowerCase()}_failure.png`)); } catch { /* browser itself may have failed */ }
    const result = { scenario_id: id, prompt, run_id: null, pass: false, run_status: null, goal_status: null,
      stop_reason: null, actual_iterations: null, actions: [], internal_sources: null, web_sources: null,
      validated_calculations: null, final_target: targetName, final_value: null, final_unit: null,
      clarification_turns: null, screenshot_paths: images, notes: [String(error)], browser_errors: browserErrors.slice(errorsBefore) };
    results.scenarios.push(result);
    await save();
    console.log(`[${id}] FAIL ${error}`);
    return { run: null, result };
  }
}

const has = (run, action) => (run.action_history || []).some((item) => item.action_type === action);
const near = (value, expected, tolerance = 0.03) => typeof value === "number" && Math.abs(value - expected) <= tolerance;

try {
  await page.goto(appUrl, { waitUntil: "networkidle", timeout: 60000 });
  await page.locator("textarea").waitFor();
  results.ui_integration = {
    one_chat_input: await page.locator("textarea:visible").count() === 1,
    goal_research_button_absent: await page.getByRole("button", { name: /목표 연구/ }).count() === 0,
    goal_research_drawer_absent: await page.getByRole("dialog", { name: /목표 연구/ }).count() === 0,
    maximum_iteration_selector_absent: !(await page.locator("body").innerText()).includes("최대 반복"),
    unified_header: (await page.locator("body").innerText()).includes("검색 · 계산 · 검증"),
  };
  results.ui_integration.pass = Object.values(results.ui_integration).every(Boolean);
  results.ui_integration.screenshot = await screenshot("00_unified_chat_home.png");
  await save();
  console.log(`[UI] ${results.ui_integration.pass ? "PASS" : "FAIL"}`);

  await runScenario("A", prompts.A, "01_monel_final.png", (run, text) => [
    run.status === "achieved" && has(run, "retrieve") && has(run, "verify") &&
    !has(run, "calculate") && (run.internal_sources || []).length > 0 &&
    (run.web_sources || []).length === 0 && text.includes("작업 과정"),
    ["Grounded QA; no calculation expected."]]);

  const b = await runScenario("B", prompts.B, "02_api_gravity_final.png", (run, text) => {
    const api = target(run, "API_gravity");
    const p90 = (run.internal_sources || []).some((source) => source.page === 90 && /Reservoir Engineering/i.test(source.document));
    return [run.status === "achieved" && ["retrieve", "calculate", "verify", "synthesize"].every((action) => has(run, action)) &&
      near(api?.value, 22.64) && p90 && text.includes("작업 과정"),
      [`API output=${api?.value ?? "absent"}; p.90 source=${p90}`]];
  }, { targetName: "API_gravity" });

  await runScenario("C", prompts.C, "03_api_followup_final.png", (run, text) => {
    const api = target(run, "API_gravity");
    const corrected = (run.computations || []).some((calc) => (calc.input_facts || []).some((fact) => fact.name?.toLowerCase() === "sg" && near(fact.value, 0.85, 0.00001)));
    return [!!b.run && run.status === "achieved" && !!run.telemetry?.conversation_context_used && corrected &&
      near(api?.value, 34.97) && text.includes(prompts.C),
      [`Context used=${run.telemetry?.conversation_context_used}; SG corrected=${corrected}; API=${api?.value ?? "absent"}`]];
  }, { fresh: false, targetName: "API_gravity" });

  await runScenario("D", prompts.D, "04_archie_final.png", (run, text) => {
    const f = target(run, "F");
    const rt = target(run, "Rt");
    const validated = (run.computations || []).filter((calc) => calc.validation_passed).length;
    return [run.status === "achieved" && validated >= 2 && near(f?.value, 20.661157, 0.01) &&
      near(rt?.value, 13.493, 0.03) && /ohm|Ω/i.test(rt?.unit || "") &&
      (run.action_history || []).filter((action) => action.action_type === "calculate").length >= 2 &&
      has(run, "verify") && !/\bFm\b|\bN\s*=\s*20\.66\b/.test(run.clarification_question || "") && text.includes("작업 과정"),
      [`F=${f?.value ?? "absent"}; Rt=${rt?.value ?? "absent"} ${rt?.unit || ""}; validated=${validated}`]];
  }, { targetName: "Rt" });

  const e = await runScenario("E_wait", prompts.E, "05_clarification_waiting.png", (run, text) => [
    run.run_status === "waiting_for_user_input" && !!run.clarification_question &&
    /TVD|수직|깊이|depth/i.test(run.clarification_question) && text.includes(run.clarification_question),
    [`Question: ${run.clarification_question || "none"}`]], { targetName: "pressure" });
  if (e.run?.run_status === "waiting_for_user_input") {
    await runScenario("E_resume", prompts.E_reply, "06_clarification_resumed.png", (run, text) => [
      run.run_id === e.run.run_id && run.status === "achieved" && has(run, "calculate") &&
      (run.computations || []).some((calc) => calc.validation_passed) && text.includes(prompts.E_reply),
      [`Same run=${run.run_id === e.run.run_id}; validated=${(run.computations || []).filter((calc) => calc.validation_passed).length}`]],
    { fresh: false, endpoint: `${e.run.run_id}/resume`, targetName: "pressure" });
  } else {
    console.log("[E_resume] Not attempted: E did not reach waiting_for_user_input");
  }

  await runScenario("F", prompts.F, "07_direct_calculation_final.png", (run) => [
    run.status === "achieved" && has(run, "calculate") && has(run, "analyze") &&
    has(run, "verify") && !has(run, "retrieve") &&
    (run.computations || []).some((calc) => calc.validation_passed),
    ["Direct arithmetic; no KB retrieval expected."]]);
} finally {
  await save();
  await browser.close();
}
