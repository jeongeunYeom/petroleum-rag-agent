# Python Tool Heldout v6 — post-freeze validity audit and exploratory result

## Status and scope

**INVALIDATED_POST_FREEZE_DISCOVERY.** The frozen reference calculator uses raw binary-float ordering for rankings and a sole leader. It has no evaluation-owned `isclose` tie grouping; the frozen policy and preflight omit the mandatory synthetic regression. For `A=0.3, B=0.30000000000000004`, `ranked()` returns `B,A` and sole leader `B`, though these must be treated as a tie under a defined tolerance. This violates the requested GT hard gate. The defect was discovered after the one complete pair and descriptive adjudication. No frozen asset was repaired, no task was rerun, and no result below is a valid product-performance baseline. See `python_tool_heldout_v6_validity_audit.json`.

A secondary authoring caveat is `PT6-WT-S2`: its prose defines `T2` in seconds, but its four expected USERF records have empty unit strings. The arithmetic reference is internally consistent, but the preflight's 51/51 representability claim does not establish unit-level representability for this case.

## Identity and process

- Starting product branch: `feature/python-tool-v7`; product SHA: `ec987f074648a6eb442b911044dff4808bc87d84`.
- Evaluation branch: `feature/python-tool-heldout-v6`; freeze commit: `3ec6fa0556fad991556a66385343890d709c2b24`; final commit: recorded in Git history after this report is committed.
- No product file or previous heldout was changed. No previous heldout was rerun. No merge to `main`.
- Twelve tasks: REQUIRED 8, OPTIONAL 2, NOT_NEEDED 2. Required strata: generic direct 2, specialist direct 3, recovery challenge 1, end-to-end 2. Domains: reservoir engineering 5, well test 4, formation evaluation 3.
- Frozen preflight reported USERF 51/51, EFACT 13/13, formula 5/5; 86 required canonical outputs, 70 numeric, 16 typed, 8 ranking. GT consistency reported 0 conflicts; old-task, old-source and smoke reuse were 0. Preflight LLM/Agent/planner/binder/contract/retrieval calls were 0. The subsequent tie audit supersedes the preflight PASS.
- Existing KB only: `D:\petroleum-rag-agent\data`, `petroleum_knowledge`, 18,976 chunks, 12 documents; legacy retrieval. No DB recreation, ingest or reindex.
- Frozen hashes (SHA-256): benchmark `f40cd96f92da09b4363e31d0ab81574f5e6f217d69a8da3be36dab01d3ccd296`; rubric `9e24ef93d701dcb4e55a401b4a62c371b8fa9cf76d1601500f9e3845710fd627`; source catalog `f956ac14c2286f5c2c6ec1da34844269aab4890b68757790e130c993cdf210e8`; reference calculator `5a8f04395f612796d73c36aa3e882136eabf8ac`; reference outputs `a45af7f1b004302286a0cf5e31969bc4354700819468ceafd9315098b85e02e6`; preflight `aea9815edd81218d0b750af9ecd1b1402fbd92a6cf87f6c3a59630c85b162021`.
- One complete OFF12 then ON12 run, ID `python-tool-v6-first-ab-20261007T063843Z`; partial reruns 0; infrastructure failures 0. Research model `qwen3:8b`, temperature 0, seed 42; blind reviewer `gemma4:latest`; internal KB on, web off. Only Python permission differed. OpenAI API and Gemini API were not used.
- Raw responses stay local at `D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v6\raw\first-ab-20261007T063836Z`; blind packets, mapping and reviewer output stay local at `D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v6\review`. Raw output hashes are recorded in `python_tool_heldout_v6_run_provenance.json`.

## Descriptive paired scores — **not a valid baseline**

| Required 8 | Python OFF | Python ON |
|---|---:|---:|
| Strict goal success | 0/8 | 0/8 |
| External criterion coverage | 16.67% | 12.50% |
| Numeric accuracy | 21.43% | 21.43% |
| Unit accuracy | 21.43% | 21.43% |
| Typed accuracy | 25.00% | 25.00% |
| Ranking accuracy | 25.00% | 25.00% |
| Scenario completeness | 12.50% | 12.50% |
| Citation correctness | 12.50% | 12.50% |
| Mean latency | 301.68 s | 337.19 s |
| Median / P95 latency | 362.92 / 475.35 s | 406.03 / 546.05 s |

Across all 12, strict goal success was 1/12 under both settings; numeric and unit accuracy were each 23.61% under both. The only strict success was `PT6-WT-N1`, a NOT_NEEDED conceptual task. Ten of twelve answer pairs had identical answer hashes; all twelve had identical citation-mapping hashes. Required paired bootstrap (10,000 samples, seed 42): goal delta 0.00, 95% interval [0.00, 0.00]; coverage delta -0.0417, interval [-0.125, 0.00]; numeric and unit deltas 0.00, intervals [0.00, 0.00]. These intervals describe this invalidated task set only.

## Exploratory workflow funnel

| Required-8 checkpoint, Python ON | Observed |
|---|---:|
| Tool selected / plan present | 7/8 / 7/8 |
| Explicit CalculationRequestIR present | 5/8 |
| Correct generic class among two generic tasks | 2/2 |
| Other emitted IRs mislabeled generic statistics | 3/3 |
| Generic fast-path complete success | 0/2 |
| Formula source found against frozen catalog | 3/5 required formula-bearing tasks |
| Complete semantic binding | 0/8 |
| Initial / post-recovery externally source complete | 5/8 / 5/8 |
| Recovery triggered / rounds / required gain | 2 tasks / 2 rounds / 0 |
| Checklist generated / fully complete | 7/8 / 0/8 |
| Contract generated / externally complete | 7/8 / 0/8 |
| Call boundary / code generated / sandbox / subprocess | 4/8 / 2/8 / 2/8 / 2/8 |
| Product VALIDATED CALC / externally valid CALC / GT-correct CALC | 0 / 0 / 0 |
| Grounded adoption / strong Python benefit | 0 / 0 |

The two subprocess tasks were `PT6-FE-S3` and `PT6-RE-R1`; both failed before a product-validated CALC. The two generic USERF-only tasks selected Python and attempted it four times each but code generation failed before subprocess. OPTIONAL tasks selected/executed Python 0/2; NOT_NEEDED tasks selected/executed Python 0/2. Required manual unsupported-claim counts were OFF 16, ON 21; engineering contradictions were 1 each; user-input-as-KB errors were 6 each; formula-provenance errors were 1 each; CALC overclaim and final internal leakage were 0. ON source-complete false-positive occurrences totaled 14 across two tasks. Trace-integrity errors were 0.

All twelve task-pair outcomes were neutral in strict goal success. Exploratory coverage was neutral on seven REQUIRED tasks and lower ON on one (`PT6-RE-S1`); no Python-attributable numeric improvement was found. The dominant observed bottlenecks were incomplete checklist/contract, non-scenario-specific binding, false source-complete decisions, failed code generation for generic arithmetic, and result validation after subprocess. Retrieval also missed required source passages on the evidence-heavy tasks. These are diagnostic observations, not a validated estimate of product performance.

## Per-task manual findings

| Task | Stratum | Main observed issue |
|---|---|---|
| PT6-RE-G1 | generic | USERF-only arithmetic refused as needing KB evidence; ON code generation failed. |
| PT6-WT-G2 | generic | Gauge-error arithmetic refused; ON code generation failed. |
| PT6-RE-S1 | specialist | Numeric geometric ratios were right using an equivalent passage, but user-derived numbers were attributed to KB and frozen source was not retrieved; ON coverage fell. |
| PT6-WT-S2 | specialist | Formula and case ranking supported, but mean was wrong and the answer falsely claimed the cited source lacked the formula. Input-unit caveat noted above. |
| PT6-FE-S3 | specialist | NMR formula retrieved; subprocess reached but result validation failed, with no CALC. |
| PT6-RE-R1 | recovery | Klinkenberg formula retrieved; subprocess reached but result validation failed, with no CALC or required recovery gain. |
| PT6-RE-E1 | end-to-end | Required C13/C14 exercise passages absent; no justified numeric comparison. |
| PT6-WT-E2 | end-to-end | Wrong well-test page retrieved; answer fabricated four permeability-thickness products. |
| PT6-RE-O1 | optional | Drawdown arithmetic right, but blanket citations did not support all claims. |
| PT6-FE-O2 | optional | Numeric gap coincidentally right; cited page gave a different source porosity. |
| PT6-WT-N1 | not needed | Correct conceptual answer with adequate citation; no Python needed. |
| PT6-FE-N2 | not needed | Irrelevant citation and incorrect bound-water conductivity claim. |

One local `gemma4:latest` blind review completed 24/24; manual QA completed 24/24 and disagreed on 19 qualitative criterion judgments. Manual review documented 16 numeric and two typed target overrides across the 24 responses. The local reviewer was advisory, not a quantitative ground-truth source. The strict adjudication JSON/CSV are preserved as descriptive artifacts and are superseded on validity by the audit above.

## Verification, preservation and next step

Before the validity finding, `cd backend && python -m pytest -q` passed **669 tests, 6 warnings**; `cd frontend && pnpm build` passed. Those are product regression checks, not a successful heldout validity test. No v6 evaluation unit tests were added before freeze; specifically, the mandatory synthetic tie regression was missing. A postfreeze process-only correction removed an unrelated, stale v5 task ID (`PT6-FE-D3`) from the v6 adjudicator; it changed no frozen task, GT, rubric, raw response or score. Do not reinterpret or rerun v6. A separately named `python_tool_heldout_v6r1` needs a frozen tolerance/tie-group policy, a synthetic `0.3` vs `0.30000000000000004` regression that blocks freeze, stronger unit preflight, and fresh unseen tasks.
