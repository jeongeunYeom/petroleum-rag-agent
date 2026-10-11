# Agent reliability v11 — development smoke

This is a **development regression and smoke check**, not an unseen final benchmark. No `final_benchmark_v3` task was rerun or rescored. The product under test is `feature/agent-reliability-v11`, branched from v10 `1fd303255ea151869905092d55096d29f6771128`.

## Environment and method

- Local model: `qwen3:8b` (`500a1f067a9f` in the local Ollama installation).
- Retrieval: `hybrid`; web off; existing read-only Chroma collection `petroleum_knowledge` with **12 documents / 18,976 chunks**. No reindexing or PDF re-extraction.
- Nine newly written live prompts used the same natural-language message parser and autonomous goal-execution agent in-process. They are not browser/API end-to-end tests. Two cases sent a follow-up to the **same run ID** after `WAITING_FOR_USER_INPUT`.
- The full case-level trace, timings, evidence identifiers, and telemetry are in [agent_reliability_v11_dev_smoke.json](agent_reliability_v11_dev_smoke.json). Timing is wall-clock for this local run, not a controlled latency benchmark.

## Synthetic regression

The suite covers **51 semantic cases**, with **3 wording variants each (153 variants)**. The checked invariant was consistent in **153/153 variants (100%)**. This is a templated development paraphrase check: full sandbox execution was run on the representative direct-calculation wording, not on every wording variant.

| Area | Synthetic result | What was checked |
| --- | ---: | --- |
| Natural-language fact extraction | 36/36 (100%) | 12 fact classes × 3 phrasings, names, units and literal source spans |
| Unit normalization | 11/11 (100%) | Unicode/engineering spelling and preserved raw unit |
| Intent routing | 78/78 (100%) | 13 direct + 8 premise + 5 user-formula classes, each with 3 variants; simulation-textbook noun separately checked |
| Premise cue detection | 24/24 (100%) | Eight assertion classes with three phrasings |
| Direct calculation execution | 13/13 (100%) | One representative wording per operation class through the bounded Python sandbox |
| Formula candidate selection | 24/24 (100%) | Eight synthetic literal equation/context spans × 3 phrasings |
| Clarification/resume fact merge | 15/15 (100%) | Five missing-input classes × 3 replies; stable fact IDs and new bindings |
| User-formula/sweep routing | 15/15 (100%) | Five classes × 3 phrasings; fixed sweep variables bound to USERF IDs |

## Live smoke

**7/9 passed**, mean **12.85 s**, median **3.42 s**. Seven Python calls yielded seven validated CALC records, all seven with complete checked provenance. No repeated/no-progress action was recorded. A pass here requires the case-specific action/result/provenance conditions in the smoke script, not merely a plausible answer.

| Case | Result | Action sequence | Key observation | Time |
| --- | --- | --- | --- | ---: |
| Direct median | PASS | CALCULATE → VERIFY → SYNTHESIZE → STOP | Median 11; no retrieval | 2.841 s |
| Direct weighted average | PASS | CALCULATE → VERIFY → SYNTHESIZE → STOP | Weighted average 16; no retrieval | 3.420 s |
| User equation | PASS | CALCULATE → VERIFY → SYNTHESIZE → STOP | Output 20 from literal user formula | 2.475 s |
| Fixed-variable sweep | PASS | SIMULATE → ANALYZE → VERIFY → SYNTHESIZE → STOP | Three cases; best score 15 | 4.214 s |
| KB formula | PASS | RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP | API gravity 29.4783845 °API; literal KB equation span and calculation provenance verified | 27.904 s |
| False premise | **FAIL** | RETRIEVE → VERIFY → RETRIEVE → VERIFY → STOP | Premise cue routed correctly, but no explicit correction; safe stop | 41.414 s |
| Literature | **FAIL** | RETRIEVE → VERIFY → STOP | Correct `KNOWLEDGE_QA` route, but irrelevant well-test pages retrieved; safe stop | 27.488 s |
| User-formula clarification | PASS | WAITING → CALCULATE → VERIFY → SYNTHESIZE → STOP | Follow-up supplied missing `b`; result 35 in same run | 2.928 s |
| Direct clarification | PASS | WAITING → CALCULATE → VERIFY → SYNTHESIZE → STOP | Follow-up supplied X/Y; weighted average 15.6 in same run | 2.964 s |

The two failures emitted no fabricated numeric answer. The KB-formula case used one validated Python calculation and a source span that actually contains the selected equation. Its long retrieval time is dominated by the local hybrid retrieval path; premise/literature time is dominated by retrieval plus local LLM verification.

## Metric readout and development gates

These denominators are intentionally small and mix synthetic checks with the nine live cases only where explicitly labeled. They must **not** be presented as final product accuracy.

| Metric | Observed | Gate | Status |
| --- | ---: | ---: | --- |
| Natural-language fact extraction recall, synthetic | 36/36 = 100% | ≥95% | Met |
| Unit normalization accuracy, synthetic | 11/11 = 100% | ≥95% | Met |
| Intent routing, tested synthetic variants | 78/78 = 100% | ≥90% | Met |
| Premise detection, synthetic | 24/24 = 100% | ≥90% | Met |
| Direct calculation execution, synthetic representative wording | 13/13 = 100% | ≥90% | Met |
| Direct calculation execution, live | 2/2 = 100% | ≥90% | Met, small n |
| KB formula retrieval/selection, live | 1/1 = 100% | — | Small n |
| Formula → CALCULATE transition, live | 1/1 = 100% | ≥85% | Met, small n |
| Calculation provenance completeness, live validated CALCs | 7/7 = 100% | ≥90% | Met |
| Python execution success, live attempted calls | 7/7 = 100% | — | Small n |
| False-premise correction, live | **0/1 = 0%** | ≥85% | **Not met** |
| Clarification trigger / same-run resume, live | 2/2 = 100% / 2/2 = 100% | resume ≥90% | Met, small n |
| User-formula calculation / simulation, live | 1/1 / 1/1 | — | Small n |
| Paraphrase consistency, checked synthetic invariants | 153/153 = 100% | ≥90% | Met |
| Repeated/no-progress action rate, live | 0/9 = 0% | — | No repeated blocker observed |

## Interpretation

The v11 parser/routing/execution paths are supported by synthetic paraphrases and seven successful live runs. The false-premise correction gate is **not** achieved: the retrieved seal-capacity text discusses capillary entry pressure, yet premise grounding did not produce a supported explicit correction. The literature case is a separate retrieval relevance failure, not a simulation-intent mistake. Neither failure justifies a v3-versus-v11 performance claim; a new unseen evaluation is still required after further development.

## Verification

- Backend: `python -m pytest -q` → **883 passed**, 6 dependency deprecation warnings.
- Frontend: `node --test tests/*.test.mjs` → **9 passed**; `pnpm build` → **passed**.
- Failure diagnosis: [agent_reliability_v11_failure_analysis.md](agent_reliability_v11_failure_analysis.md).
