# Frozen Agentic v1 Python path: post-hoc diagnosis

Scope: read-only analysis of `agentic-v1-20261004T075903Z`, Full Agent condition (18 tasks). No held-out task, condition, reviewer, or ground truth was rerun or edited. The pre-analysis SHA-256 of `full_agent.json` was `dced17b8d7d540f27f927d0651d739603266a916437d881697dc486a2b080225`, matching the committed provenance manifest. The diagnostic script checks every listed raw-artifact hash before reading it.

## Confirmed failure mechanism

The held-out runner constructs IDs like `agentic-v1-20261004T075903Z-AG-Q-006-full_agent` (`backend/scripts/run_agentic_heldout.py`, lines 124–131, 201). `GoalResearchAgent` passes that ID unchanged to its default `GoalPythonAnalysis` factory when a non-null plan is selected (`backend/app/services/goal_research_agent.py`, lines 181–183, 289–298). The constructor accepts only `GR-[A-Z0-9-]+` and raises `ValueError("Invalid goal research run ID")` otherwise (`backend/app/services/goal_python_analysis.py`, lines 120–122). The caller catches that exception, leaving `analysis=None` and the call counter at zero. Thus none of the 12 selected iterations can enter `execute()`, regardless of facts, formula, budget, permissions, or sandbox health.

`GoalToolPlanner.decide()` returns `tool_needed=true` only if its parsed decision also has a non-null plan; otherwise it returns an unselected decision (`backend/app/services/goal_tool_planner.py`, lines 102–105). Consequently all 12 recorded `python_requested=true` iterations had a plan at the planner boundary. The plan's facts, formula, and tool type were not serialized in the frozen result, so their validity cannot be judged post hoc. This is a code-path inference, not direct plan telemetry.

The exact error appears in the final task-level `validation.python_analysis_error` for four tasks: `AG-WT-002`, `AG-Q-008`, `AG-Q-010`, `AG-IE-015`. For the other six selected tasks, their last iteration did not select Python, so the task-level `validation` object was overwritten without that earlier error. The same invalid ID and same factory path apply to those earlier selected iterations. No other pre-call gate is observable in this frozen run.

| Frozen stage | Count | Evidence |
| --- | ---: | --- |
| Full Agent tasks | 18 | Frozen raw |
| Python-required tasks | 5 | Frozen benchmark `python_expected=required` |
| Python-selected tasks / iterations | 10 / 12 | Frozen raw |
| Plan present | 12 iterations | Planner return contract; content unknown |
| Request approval enabled | 12 iterations | Frozen requests |
| Constructor ID rejected | 12 iterations | Deterministic ID/code-path mismatch; direct final error on 4 tasks |
| Fact verification reached | 0 | Constructor fails first |
| `self.calls += 1` reached | 0 | Frozen counters and code order |
| Code generation / sandbox / result validation reached | 0 | Constructor fails first; attempts total 0 |
| Validated CALC | 0 | Frozen computation records |

The *stop stage* is deterministically identifiable for all 12 selected iterations; unknown stop-stage count is zero. The **plan content and any later hypothetical gate outcome are unknown for all 12**. This distinction matters: prompt-only numeric provenance is a real issue in synthetic fixtures, but it did not cause the frozen zero-call result because the run-ID check came first.

| Selected task | Iteration(s) | Evidence IDs available at first selection | Final error directly visible? | Stop stage |
| --- | --- | --- | --- | --- |
| AG-WT-002 | 2 | KB1–KB10 | yes | RUN_ID_REJECTED |
| AG-RE-003 | 2, 3 | KB1–KB9 | no | RUN_ID_REJECTED |
| AG-Q-006 | 1 | KB1–KB5 | no | RUN_ID_REJECTED |
| AG-Q-007 | 1, 2 | KB1–KB5 | no | RUN_ID_REJECTED |
| AG-Q-008 | 1 | KB1–KB5 | yes | RUN_ID_REJECTED |
| AG-Q-009 | 1 | KB1–KB5 | no | RUN_ID_REJECTED |
| AG-Q-010 | 1 | KB1–KB3, FIG1–FIG2 | yes | RUN_ID_REJECTED |
| AG-FP-011 | 1 | KB1–KB3, FIG1–FIG2 | no | RUN_ID_REJECTED |
| AG-FP-012 | 1 | KB1–KB5 | no | RUN_ID_REJECTED |
| AG-IE-015 | 1 | KB1–KB5 | yes | RUN_ID_REJECTED |

The machine-readable diagnostic JSON preserves every selected iteration's exact `python_decision_reason`, evidence IDs available by that iteration, frozen criteria, prior criterion evaluations/gaps, and available Python counters. Values absent from the frozen raw, including each plan's input facts and supporting formula IDs, are recorded as `unknown`.

## Why five non-required tasks were selected

These are selection precision errors independent of the execution-ID failure, not proof that Python would have helped. `AG-WT-002` selected after a partial pseudo-skin/anisotropy explanation gap despite conceptual criteria. `AG-RE-003` selected twice because explicit arithmetic/harmonic formula sources were missing; calculation could not manufacture those citations. `AG-FP-011` mistook a conceptual flow-regime label audit for numerical plot analysis. `AG-FP-012` selected for harmonic-vs-arithmetic numerical comparison although its frozen expectation was `not_needed`. `AG-IE-015` selected for an OOIP/reserves distinction, even though the critical missing recovery factor cannot be calculated from provided evidence. The frozen reason strings and prior gaps are in the diagnostic JSON; no task labels or results were changed.

## Root-cause confidence and boundaries

| Candidate | Status for frozen zero calls | Basis |
| --- | --- | --- |
| Runner/analysis run-ID integration mismatch | **confirmed primary** | Runner ID, constructor regex, caller sequence, zero calls; four direct errors |
| Planner selection false positives | **confirmed secondary**, not cause of zero calls | Five `not_needed` tasks selected |
| Input provenance model mismatch | **confirmed in synthetic fixture; not observable in frozen plans** | D2/D3 fail with task-only numeric facts, but frozen execution never reached this gate |
| Specialist formula provenance gate | **working in synthetic fixture; frozen effect unknown** | D4 passes, D6 fails as intended |
| Permission integration | **not supported as frozen cause** | Frozen requests approved; constructor fails before `PermissionManager` |
| Python code generation / sandbox / runtime / result validation | **not supported as frozen cause** | Frozen never reached them; D1/D4 execute and validate locally |

The frozen v1 scores, Goal Success, and C–B differences remain unchanged. A future v2 could make the run-ID contract consistent, then add stage-specific trace fields and separately tracked `USER_FACT`/`KB`/`FIG`/`WEB`/`CALC` provenance rather than silently treating prompt numbers as source citations. Those are proposals only; no product fix is in this branch.
