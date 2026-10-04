# Agentic Baseline v1 — strict adjudicated v1 2

Run: `agentic-v1-20261004T075903Z`. Product code remains frozen. Single AI-assisted semantic reviewer: `gemma4:latest`. Exploratory N=18; interval estimates are paired 10,000-bootstrap percentile 95% CIs.

| Metric | Single-shot | Goal Agent | Full Agent |
|---|---:|---:|---:|
| External goal success | 27.8% | 72.2% | 77.8% |
| External goal coverage | 49.1% | 86.1% | 89.8% |
| Hallucination | 0.0% | 11.1% | 11.1% |
| Engineering contradiction | 0.0% | 11.1% | 11.1% |
| System-level latency mean (s) | 121.9 | 261.0 | 280.6 |

## Process and Python

The iteration curve uses last observation carried forward after a task stops. Internal goal coverage is reported only as calibration telemetry; it never determines external success.

Python-required task count: 5. Python selection precision/recall: 50.0% / 100.0%.

## Paired differences

- goal_agent-single_shot: success +0.444 [+0.111, +0.778]; coverage +0.370 [+0.139, +0.583].
- full_agent-goal_agent: success +0.056 [+0.000, +0.167]; coverage +0.037 [+0.000, +0.093].
- full_agent-single_shot: success +0.500 [+0.167, +0.778]; coverage +0.407 [+0.194, +0.611].

## Review QA

Original semantic reviews are preserved in the run directory. Deterministic checks control numeric target/units and provenance. Reviewer quote-gating and process-ID disagreements are flagged in task scores. Adjudicated versions are separate files; no original review is overwritten.
Manual QA corrected 13 task-condition rows in v1.2; see the separately hashed adjudication file for itemized reasons.
The strict reviewer had 26 missing/non-verbatim criterion quotes; these criteria were gated to zero before any itemized adjudication.
