# Python Tool Evaluation v1 — frozen evaluation policy

This is an exploratory paired held-out evaluation (10 tasks; six Python-required). It compares the same frozen Goal Agent v2 with Python OFF and ON. Product SHA `9ac0de4f1715cc494d0c6a8c5949e9a50a9a5212` is fixed. No earlier held-out, strict review, or D1–D8 diagnostic is rerun or edited.

## Freeze and run

- Freeze tasks, expected tool labels, formulas, inputs, ground truth, tolerances, and criteria before the first full run. After that run, never change them or repeat only failures. A changed benchmark requires a clearly named v2 evaluation.
- Execute A: all ten Python OFF, then B: all ten Python ON, once. Preserve raw responses incrementally. Do not tune the product or benchmark after seeing outputs. Existing bounded product-level retries are allowed; benchmark-level retries are not.
- A pure infrastructure failure invalidating the comparison stops the run, preserves partial raw output and its reason, and requires a separate fix/restart decision. Model refusals, wrong answers, missing Python use, validator blocks, and tool failures are outcome data, not reasons to retry.
- `python_expected=required` is the positive class, `not_needed` is the negative class, and `optional` is excluded from strict selection precision/recall/F1. Optional and not-needed use is reported separately.
- One paired task is the sampling unit. Bootstrap 10,000 paired resamples with seed 42; report percentile 95% intervals. A six-task result is exploratory, not a general performance estimate.

## Independent scoring

- Numeric targets and tolerances are fixed in the benchmark. A numeric target passes only when an answer value lies inside its tolerance and its required unit is present next to that value. `stock-tank m3` accepts explicit stock-tank/standard cubic metres; it does not accept an unqualified reservoir volume. Missing scenarios fail; input numbers alone are not counted as outputs. For overall numeric accuracy, divide passed targets by all applicable targets. A required task's numeric criterion is met only when every target mapped to that criterion passes.
- C2 is numeric-only for all quantitative tasks except `PY-WT-008`, where C1 is numeric-only. Other criteria require qualitative support, and any mapped numeric target must also pass. A condition's external goal success requires all three criteria and no engineering contradiction. Numeric matching should be checked against answer context during manual QA to avoid crediting a restated input as an output.
- CALC output JSON is scored separately against the same frozen targets; validated execution alone is not numerical correctness. The deterministic scorer is authoritative on numbers, units, provenance and tool traces. The local `gemma4:latest` single AI-assisted semantic reviewer only assesses qualitative engineering/interpretation criteria and receives blind `AR-###` packets with no condition, Python telemetry, CALC, or A/B labels. Retain the original review; manual QA of all 20 rows can be recorded separately as `strict_adjudicated_v1_1` without overwriting it.
- External goal coverage is the fraction of prewritten criteria passed by deterministic and, only for qualitative criteria, manually QA-checked semantic judgments. Goal success requires every required criterion; internal `goal_coverage` is telemetry only. Python execution and CALC creation are process metrics, never a proxy for goal success.
- Required-task benefit means B has greater external coverage, or B passes a numeric target that A fails. Harm is the reverse with no benefit; otherwise neutral. Report paired outcomes, not an assertion that execution itself improved accuracy.
- For USER_FACT tasks, source creation/selection/verification, `source_input_ids`, KB-backed formula IDs, and final citations are separate checks. USER_FACT is never counted as literature evidence. Cite CALC, USER, and KB formula sources distinctly. Source IDs are resolved against the actual evidence list; a citation token alone does not establish correctness.
- A safety event is a network attempt, workspace escape attempt, permission violation, sandbox rejection, or unexpected file modification. Count from trace/attempt records and filesystem checks; zero is expected. Do not infer an unobservable event as zero—mark it unverified.

## Interpretation

Report selection, plan, permission, facts, call boundary, code generation, sandbox, subprocess, result validation and CALC funnel for B's six required tasks, plus calls, attempts, repair opportunity/success, latency, and failures by first blocked stage. Include optional/not-needed overuse. Use the exact label “single AI-assisted semantic reviewer”. Do not claim Python improved accuracy when OFF and ON are equal. Keep `main` untouched.
