# Python Tool Evaluation v1 — frozen exploratory held-out result

This evaluates frozen Goal Agent v2 (`9ac0de4f1715cc494d0c6a8c5949e9a50a9a5212`) on ten new paired tasks. Python OFF and Python ON differ only in the two permission flags. The product, benchmark, ground truth, tolerance, and scoring policy were not changed after the first task began. The sample is exploratory (N=10; Python-required N=6), not a population-level claim.

## Run integrity

- Evaluation branch: `feature/python-tool-heldout-v1`. Frozen evaluation commit at first complete run: `1227807144bb877035f2dbb50fc7d7c5289bfd6d`.
- One complete A-all-10/B-all-10 run: `python-heldout-v1-20261004T143509Z`. An earlier Chroma preflight-option mismatch stopped before any task row; `abort.json` is retained. The evaluation-runner-only fix was made on `fix/python-heldout-chroma-preflight` and cherry-picked. No task-level rerun occurred.
- The 20 rows are complete. All ten paired final answers and retrieved source lists are identical byte-for-byte. SHA-256 of all previously frozen evaluation assets was equal before/after. Product files and prior benchmark outputs were untouched.
- Benchmark SHA-256: `8ae1b9a1a95ea43b0b68e679a4b249aadbb44bed52c8e19e20c0aac4f17f4173`; manifest SHA-256: `398b1b438ec7c4624be827facf38c9e3a41270298d1e1032d787f02657426a18`; policy SHA-256: `17e5426c34171a670b8ceae49cdf5dc3b2b037e48aba1920244cc3cb70d468af`.
- Settings: `qwen3:8b`, temperature 0, seed 42; real `petroleum_knowledge` Chroma collection (18,976 chunks, 12 documents); product-default `legacy` retrieval, internal top-k 5, external top-k 5, web OFF, max iterations 4, patience 2, Python budget 4 calls/2 attempts per call. `gemma4:latest` handled only condition-blind qualitative review. OpenAI/Gemini APIs were not used.
- Full backend suite before the run: 568 passed, 6 warnings. Pushed evaluation branch CI passed at commit `1227807`; final-commit CI is checked separately.

## Strict adjudicated result

The original single AI-assisted semantic reviewer missed explicit correct qualitative claims and failed to flag several invented or contradictory facts. Its unaltered review and original comparison remain in the run directory. All 20 responses were checked against raw text, citations, KB locators, deterministic targets, and trace; because every A/B answer and source list matched exactly, each task-level decision applies to both rows. Itemized reasons are in `python_tool_heldout_v1_strict_adjudication_v1_1.json`. Numeric target pass remains deterministic; manual QA separately corrects qualitative, hallucination, contradiction, and unit-presence judgments. This is an adjudication of the same frozen run, not another model run.

| Metric | Python OFF | Python ON |
| --- | ---: | ---: |
| External goal success | 3/10 (30.0%) | 3/10 (30.0%) |
| External goal coverage | 50.0% | 50.0% |
| Numeric targets correct | 3/32 (9.375%) | 3/32 (9.375%) |
| Unit support across targets | 4/32 (12.5%) | 4/32 (12.5%) |
| Hallucination (task incidence) | 6/10 (60.0%) | 6/10 (60.0%) |
| Engineering contradiction (task incidence) | 4/10 (40.0%) | 4/10 (40.0%) |
| Latency mean / median / p95 | 297.0 / 378.4 / 454.9 s | 321.2 / 404.9 / 505.0 s |

Required-only N=6:

| Metric | Python OFF | Python ON |
| --- | ---: | ---: |
| Goal success | 0/6 | 0/6 |
| External goal coverage | 22.22% | 22.22% |
| Numeric targets correct | 1/30 (3.33%) | 1/30 (3.33%) |
| Unit support | 2/30 (6.67%) | 2/30 (6.67%) |

The required-only numerator is the correct 70-ft total thickness in `PY-RE-001`; its claimed effective permeability is wrong. The two other correct numeric targets are optional tasks `PY-RE-007` and `PY-WT-008`. No required task has complete scenario output. The three successful full goals are `PY-WT-008`, `PY-WT-009`, and `PY-WT-010` (one optional, two not-needed). The original unadjudicated reviewer reported 20% overall success and 0% hallucination/engineering errors; these were corrected by raw-text QA.

## Python selection and execution

Strict selection excludes optional tasks: true positives 3/6, false positives 2/2 not-needed; precision 60.0%, recall 50.0%, F1 54.5%. Optional selected/executed = 1/0 of 2; not-needed selected/executed = 2/0 of 2. The observed over-selection never reached a subprocess.

| Required-task funnel stage | Count / 6 |
| --- | ---: |
| Tool selected | 3 |
| Plan present | 3 |
| Permission passed after selection | 3 |
| Input facts verified | 0 |
| Call boundary reached | 0 |
| Code generated | 0 |
| Sandbox passed | 0 |
| Subprocess reached | 0 |
| Result validated | 0 |
| Validated CALC created | 0 |

No Python call or attempt was recorded, so execution success and validated CALC rate among required tasks are 0/6; conditional success among actual subprocesses is not estimable. There were zero repair opportunities and zero repair successes. The Python-stage timing field averaged 30.43 s per Python-ON task, reflecting planning/verification overhead, **not** executed Python time. USER_FACT required tasks: five total, two selected for Python, zero facts verified, zero validated `source_input_ids`, zero final CALC/USER-backed results. Formula provenance and CALC numeric accuracy are not estimable among zero CALCs (coverage 0/6). In the KB-numeric RFT task, the planner incorrectly attributed the absent table to `USER1`; its actual KB page-81 table was not retrieved.

Required-task failure attribution: `tool_not_selected` 3 (`PY-RE-001`, `003`, `006`); `input_fact_failure` 3 (`PY-RE-002`, `004`, `PY-WT-005`). The original ungated telemetry's `permission_passed=6` meant the request was approved even when no tool was selected; the adjudicated funnel correctly gates each stage by the prior stage. The original `blocked_stage` can show a later `not_selected` iteration after an earlier input-fact failure; adjudicated root attribution uses all iterations.

Python benefit/neutral/harm across required tasks = 0% / 100% / 0%. Every paired answer was identical. B−A goal-success, coverage, required numeric, and required goal-success deltas are all 0 with 10,000-paired-bootstrap seed-42 95% percentile intervals `[0, 0]`. This degenerate interval reflects identical outcomes in a small fixed sample; it is not evidence of general equivalence.

## Task-level QA

| Task | Expected | ON selected / subprocess / CALC | OFF→ON goal | Numeric targets OFF→ON | Principal failure or success |
| --- | --- | --- | --- | --- | --- |
| PY-RE-001 | required | no / no / no | fail→fail | 1/5→1/5 | No selection; wrong `k_eff` (134.36 vs 121.5 mD), wrong kh-share relation/rank; KB1 supports the formula despite reviewer false negative. |
| PY-RE-002 | required | yes / no / no | fail→fail | 0/3→0/3 | Input-fact gate; no numeric comparison; invented `B2=9 mD` bottleneck (actual minimum B1=30 mD). |
| PY-RE-003 | required | no / no / no | fail→fail | 0/5→0/5 | No selection or PI results; unrelated vitamin-D/depression limitations leaked into answer. |
| PY-RE-004 | required | yes / no / no | fail→fail | 0/7→0/7 | Input-fact gate; missing volumes/deltas; falsely assigns largest drop to Sw instead of reduced porosity. |
| PY-WT-005 | required | yes / no / no | fail→fail | 0/3→0/3 | KB page-81 RFT table not retrieved; planner misidentified USER1 as table source, then failed fact verification; safe numeric refusal. |
| PY-RE-006 | required | no / no / no | fail→fail | 0/7→0/7 | No selection; cited KB formulas are valid, but no block values and false North-largest in-place claim. |
| PY-RE-007 | optional | yes / no / no | fail→fail | 1/1→1/1 | Correct 80,000 stock-tank m3; incomplete/ambiguous distinction between assumed RF sensitivity and proven forecast. |
| PY-WT-008 | optional | no / no / no | pass→pass | 1/1→1/1 | Correct 0.03 psi/ft and hydrostatic context; reviewer C2 false negative. |
| PY-WT-009 | not_needed | yes / no / no | pass→pass | n/a | Correct linear half-slope, radial plateau and uncertainty; unnecessary tool selection and reviewer C1 false negative. |
| PY-WT-010 | not_needed | yes / no / no | pass→pass | n/a | Correct produced-field/supercharging caution; unnecessary tool selection. |

No Python-tool network attempt, workspace escape, permission violation, sandbox rejection, or unexpected tracked/frozen file modification was observed. The subprocess boundary was never reached, so sandbox behavior is untested rather than proven safe by this benchmark.

## Files and limits

- Complete raw JSON: `D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v1\raw\python-heldout-v1-20261004T143509Z\python_off.json` and `python_on.json`.
- Original blind packet, mapping, and reviewer: same run directory under `review\`; original comparison JSON/CSV: `D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v1_comparison.{json,csv}`.
- Strict adjudicated JSON/CSV: `D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v1_comparison_strict_v1_1.{json,csv}`. Strict poster/funnel CSV: `python_tool_heldout_v1_poster_strict_v1_1.csv` and `python_tool_heldout_v1_funnel_strict_v1_1.csv` in that evaluation directory. Original poster/funnel CSV remain untouched.
- The task set was verified against real KB locators before freezing, but retrieval did not consistently surface those pages at runtime. No reranking, product, task, or GT tuning was done after seeing outcomes. A future product fix should occur separately, followed by a **new** evaluation version; never rerun only the failures or relabel this v1 result.

**Conclusion:** Agent v2 produced zero validated Python calculations on six required held-out tasks and did not improve quantitative goal performance over Python OFF in this run. The primary observed gates were no tool selection and input-fact verification failure; the 20 final answers were identical across conditions.
