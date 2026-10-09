# Agentic Baseline v1

Run: `agentic-v1-20261004T075903Z`. Product code remains frozen. Single AI-assisted semantic reviewer: `gemma4:latest`. Exploratory N=18; interval estimates are paired 10,000-bootstrap percentile 95% CIs.

| Metric | Single-shot | Goal Agent | Full Agent |
|---|---:|---:|---:|
| External goal success | 55.6% | 83.3% | 83.3% |
| External goal coverage | 98.1% | 95.4% | 95.4% |
| Hallucination | 0.0% | 0.0% | 0.0% |
| Engineering contradiction | 0.0% | 0.0% | 0.0% |
| System-level latency mean (s) | 121.9 | 261.0 | 280.6 |

## Process and Python

The iteration curve uses last observation carried forward after a task stops. Internal goal coverage is reported only as calibration telemetry; it never determines external success.

Python-required task count: 5. Python selection precision/recall: 50.0% / 100.0%.

## Paired differences

- goal_agent-single_shot: success +0.278 [+0.000, +0.556]; coverage -0.028 [-0.074, +0.000].
- full_agent-goal_agent: success +0.000 [+0.000, +0.000]; coverage +0.000 [+0.000, +0.000].
- full_agent-single_shot: success +0.278 [+0.000, +0.556]; coverage -0.028 [-0.074, +0.000].

## Review QA

Original semantic reviews are preserved in the run directory. Deterministic checks control numeric target/units and provenance. Reviewer quote-gating and process-ID disagreements are flagged in task scores. Adjudicated versions are separate files; no original review is overwritten.
