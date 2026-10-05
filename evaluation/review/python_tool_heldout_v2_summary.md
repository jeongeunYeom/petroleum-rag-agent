# Python Tool Heldout v2 Baseline

This is an exploratory, paired 12-task evaluation of unchanged product v3 (`f48287799ca9a780c46c1285f95d01baadc92de5`). The benchmark, GT, rubric, runner, and scorer were frozen at `21fd587140eb084e6f0f3f7fa9882b9d58fb0685` before one complete run: all 12 Python OFF, then all 12 Python ON. No task was rerun and no prior frozen evaluation was rerun. The real local Chroma contained 18,976 chunks from 12 documents. Research used local `qwen3:8b`; one blinded AI-assisted qualitative reviewer used local `gemma4:latest`. No OpenAI or Gemini API was used.

## Main finding

The Agent selected Python on all eight required tasks but never reached the execution boundary or produced a validated CALC. All 12 paired final answers **and their KB citation mappings were byte-for-byte identical** between OFF and ON. Consequently there is no observed quantitative benefit, regardless of qualitative-reviewer noise. ON added 50.54 seconds per task on average. The largest bottleneck was plan/input/formula verification after correct tool selection, with retrieval failures in several tasks also limiting input availability.

The original deterministic-plus-blind-review comparison is preserved. Manual QA of all 24 answer rows found 13 reviewer field corrections, documented separately in `python_tool_heldout_v2_strict_adjudicated_v1_1.json`; no numeric scores were changed. The strict results below are the headline results. The uncorrected AI reviewer had reported a spurious one-task ON harm and a negative coverage delta despite identical paired answers/evidence.

## Primary required-task comparison (8 paired tasks)

| Metric | Python OFF | Python ON |
| --- | ---: | ---: |
| External goal success | 1/8 (12.5%) | 1/8 (12.5%) |
| External criterion coverage, strict | 31.25% | 31.25% |
| Numeric target accuracy | 6/46 (13.04%) | 6/46 (13.04%) |
| Unit accuracy | 6/46 (13.04%) | 6/46 (13.04%) |
| Hallucinated/unsupported-claim count, strict | 4 | 4 |
| Engineering contradiction count, strict | 3 | 3 |
| Mean total time | 402.85 s | 468.88 s |

Across all 12 tasks, each condition achieved 3/12 goals, 43.06% strict external coverage, 8/50 numeric targets and 8/50 units (16% each), five hallucinated/unsupported claims, and four engineering contradictions. Paired benefit/neutral/harm among required tasks was **0/8, 8/8, 0/8**. Paired 10,000-bootstrap 95% CIs (seed 42) for all strict success, coverage, numeric and unit deltas were `[0, 0]`; this is a consequence of identical paired outputs, not evidence of equivalence beyond these 12 tasks.

## Python ON execution funnel (required 8)

| Stage | Tasks |
| --- | ---: |
| Decision parsed on first attempt | 8/8 |
| Python selected | 8/8 |
| At least one plan parsed and materialized | 6/8 |
| Facts and specialist formula verified | 0/8 |
| Execution boundary reached | 0/8 |
| Code generated | 0/8 |
| Sandbox passed | 0/8 |
| Subprocess reached | 0/8 |
| Result validated / CALC created | 0/8 |

Plan retry success was 0; two tasks never parsed a valid plan, although six tasks had at least one parse-failed iteration. Decision parsing had zero total failures. Tool-selection precision, recall and F1 were each 1.00 on required versus not-needed tasks. Optional tasks were excluded from these metrics: 2/2 were selected, 0/2 executed. Not-needed tasks: 0/2 selected and 0/2 executed.

The six required USER_FACT tasks contained 65 expected facts. The deterministic registry extracted 65/65, while the planner selected 37/65 (56.9%) across task iterations; extra and unknown selected IDs were both zero. Fact verification succeeded on 0/6 materialized required plans. No valid CALC incorporated USERF provenance. The two KB-numeric tasks could not retrieve their frozen numeric-table pages. Formula-provenance success, execution success, and final CALC citation rate were all zero. CALC numeric/unit accuracy and completeness are **N/A**, not zero-percent accuracy, because the CALC denominator is zero.

## Task-level manual QA

| Task | Class | OFF/ON goal | OFF/ON numeric | ON furthest stage | Principal failure or result |
| --- | --- | --- | --- | --- | --- |
| PY2-RE-001 | required | fail/fail | 0/8 each | plan materialized | Wrong parallel-flow geometric averaging; plan eventually `source_span_mismatch`; frozen p314 not retrieved. |
| PY2-RE-002 | required | fail/fail | 0/5 each | selected | Every plan parse failed; series formula omitted total-length normalization; frozen p316 not retrieved. |
| PY2-RE-003 | required | fail/fail | 0/7 each | plan materialized | Plan `source_span_mismatch`; final STOIIP equation puts Bo in numerator rather than denominator. |
| PY2-RE-004 | required | fail/fail | 0/5 each | selected | Every plan parse failed; formula pages 32/33 were retrieved, but no calculation. |
| PY2-WT-001 | required | fail/fail | 0/5 each | plan materialized | All plans failed `source_span_mismatch`; PI formula was available, but no well PIs. |
| PY2-WT-002 | required | pass/pass | 6/6 each | plan materialized | Model computed rounded plateaus directly; Python formula verification rejected `formula_text_mismatch`, no CALC. |
| PY2-WT-003 | required | fail/fail | 0/5 each | plan materialized | Actual Sleipner p363 table absent from retrieval; plan lacked numeric input facts; safe refusal. |
| PY2-WT-004 | required | fail/fail | 0/5 each | plan materialized | Actual shut-in p173 table absent from retrieval; plan lacked numeric input facts; safe refusal. |
| PY2-RE-005 | optional | pass/pass | 2/2 each | plan materialized | Direct arithmetic answer correct; Python formula provenance failed, but tool was optional. |
| PY2-WT-005 | optional | fail/fail | 0/2 each | plan materialized | Unit type `psi/ft` was not in canonical USER_FACT grammar; plan then had registry/duplicate-fact failures; cautious interpretation only. |
| PY2-RE-006 | not needed | pass/pass | N/A | decision parsed | Legitimately did not select Python; conceptual answer adequate. |
| PY2-WT-006 | not needed | fail/fail | N/A | decision parsed | Legitimately did not select Python, but final answer wrongly tied radial plateau to wellbore-storage-dominated flow; half-slope source p775 not retrieved/cited. |

The four required source-page misses were PY2-RE-001 (p314), PY2-RE-002 (p316), PY2-WT-003 (p363), and PY2-WT-004 (p173). PY2-WT-006 retrieved radial p774 but not linear half-slope p775. The other relevant pages were present, so retrieval alone cannot explain the zero-CALC result. Plan validation recorded `source_span_mismatch` in three required tasks, `formula_text_mismatch` in one, and `insufficient_input_facts` in two; two had no materialized plan at all. The trace does not name the exact failing input fact for `source_span_mismatch`, so attributing that specifically to USER_FACT rather than an additional evidence fact would exceed the recorded evidence.

## Time, calibration, provenance and limitations

Overall latency OFF mean/median/P95 was 347.62/369.14/505.67 s; ON was 398.16/432.57/585.20 s. ON mean Python-stage time was 51.94 s. Evaluation-only observation (no product mutation) measured mean tool decision 8.793 s, plan generation 43.141 s, verification 0.00027 s, and zero code generation/subprocess time. All 12 ON tasks were non-executed; their mean decision+plan overhead was 51.93 s. Strict mean absolute internal-versus-external coverage calibration error was 0.2083 for both conditions. USER_FACT scientific-evidence leakage and trace-integrity errors were both zero. Successful direct-answer numeric tasks did not cite `[CALC#]` because no CALC existed; no final answer cited `[USERF#]`, so explicit user-input derivation provenance remains incomplete.

The qualitative reviewer was a **single AI-assisted semantic reviewer**. It was blind to the A/B condition and did not control numeric scoring. Review variability nevertheless affected identical paired answers; 24/24 manual QA corrected this only in a separate strict result. The sample is small (12 total, eight required) and is an exploratory held-out evaluation, not a generalizable proof. The benchmark intentionally includes hard retrieval targets; product code and retrieval were not tuned after seeing failures.

## Artifacts

- Raw run: `D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v2\raw\python-heldout-v2-20261005T044234Z\python_off.json` and `python_on.json`.
- Immutable original scoring outputs: `D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v2_{deterministic,comparison}.json`, plus `_comparison.csv`, `_funnel.csv`, `_iterations.csv`, and `_poster.csv`.
- Preserved raw qualitative reviewer output: `evaluation/review/python_tool_heldout_v2_reviewer_raw.json`.
- Separate 24-row manual QA and strict adjudication: `evaluation/review/python_tool_heldout_v2_strict_adjudicated_v1_1.json`.
- Benchmark SHA256 `ee10228ff6f1094927d03a4b313977a5fa9535cdef8e4cfd284de9e645b30f81`; manifest SHA256 `2bb3fb42d72515862290097b0bd281dd3fe12df84e010eb12efed905ebba3bd8`; rubric SHA256 `deff6503a312a91fac6628b8c595ee5ff4cfbc1c63ab186b392aec40ac7a74e8`.

The next product version should first address plan JSON reliability, identify the precise failing fact in verification traces, improve formula/excerpt matching without weakening provenance, and recover numeric-table pages. Those are proposed follow-ups only; **no product code was changed in this evaluation**.
