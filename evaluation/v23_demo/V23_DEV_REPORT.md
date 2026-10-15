# V23 conference-demo development report — initial candidate (historical)

This preserves the **initial V23 candidate's development results**: at that time its acceptance gate failed and no freeze existed. The later V23.1 candidate passed a new V23B development gate; see [V23B_REPAIR_REPORT.md](V23B_REPAIR_REPORT.md) and [V23_FREEZE_NOTE.md](V23_FREEZE_NOTE.md). The historical figures below were not rewritten and are not unseen final evaluation. No V4 benchmark was authored or run here.

| Item | Value |
|---|---|
| Branch | `feature/conference-demo-v23` |
| Exact V22 product base | `0bfffd45043c9a9f50e76dc6e57b7a44458da665` |
| V23 development candidate | `aa44faad60c21ec685c01e8bb1d5d74aa2f5b838` |
| Frozen V23 product SHA | **None — gate failed** |
| Runtime | local `qwen3:8b`, `RETRIEVAL_MODE=hybrid`, web off |
| KB | existing `petroleum_knowledge`, 12 documents, 18,976 chunks; read-only evaluation |

## Decision and acceptance gate

| Gate | Required | Observed | Result |
|---|---:|---:|---|
| New synthetic regression | >=150 passing | 271/271 passing | Pass |
| Real-KB development, excluding resume | >=90% | 45/50 (90.0%) | Pass at aggregate only |
| Knowledge QA | >=9/10 | 7/10 | **Fail** |
| Direct calculation | 10/10 | 10/10 | Pass |
| User formula | 8/8 | 8/8 | Pass |
| KB formula | >=9/10 | 9/10 | Pass |
| Multi-goal | >=5/6 | 5/6 | Pass |
| False premise | 3/3 | 3/3 | Pass after source-grounded correction recovery |
| Unanswerable | 3/3 | 3/3 | Pass |
| Same-run resume | >=9/10 | 8/10 | **Fail** |
| Conference stress | >=95% | 185/210 (88.1%) | **Fail** |
| Technical crashes / blank replies / raw error leakage | 0 / 0 / 0 | 0 / 0 / 0 observed | Pass in measured runs |
| Backend / frontend / build | pass | 2,093 passed / 23 passed / successful | Pass |

Because the category, resume and stress gates failed, this branch remains a **development candidate**. Do not use its numbers as final poster performance and do not construct V4 from these observed development prompts.

## Product changes and recovery architecture

- `goal_intent.py`, `calculation_request_ir.py`, `goal_simulation.py`, `user_fact_registry.py`, and `required_goals.py`: route varied Korean/English/mixed sum, difference, ratio/GOR, mean, percent decline, ranking and supplied expressions to bounded deterministic execution; distinguish operand roles and percentage units. Fully specified direct/user-formula requests bypass KB retrieval.
- `calculation_requirements.py`, `formula_layout_normalizer.py`, `formula_source_registry.py`: favor the requested output and supplied variables, preserve literal source spans, and normalize only source-verified PDF exponent/layout artifacts. Unverified formulas still cannot execute.
- `goal_action_planner.py`, `goal_knowledge_retrieval.py`, `goal_execution_agent.py`: bounded non-equivalent formula retrieval attempts, retain explicit mixed-language concepts in a bilingual retry, prevent STOP from preceding ready calculations, retain existing provenance checks, and produce a nonblank safe response on failure. Existing same-run clarification/resume remains in place; two real probes still fail to enter or complete it.
- `premise_grounding.py` and the drilling/well-test engineering validators: prefer deterministic corrections only when an exact retrieved source states the relevant engineering relation. In particular, a source sentence placing a derivative feature *before* “during radial flow” is now attributed to radial flow; hyphenated regime wording is recognized. Unsupported corrections still stop safely.
- `source_answerability.py`: ignores generic request filler when checking literal claim support without dropping engineering relation terms.
- `goal_research_service.py` and `frontend/app/page.tsx`: replace raw product/transport errors in the user-facing answer with a short safe message while retaining internal diagnostics. This is the only frontend product change.

Changed product files are the 16 backend service files and `frontend/app/page.tsx` in the candidate commit; the new synthetic suite is `backend/tests/test_v23_conference_reliability.py`. No task-ID checks, fixed benchmark answers, source-page overrides, Chroma mutation, reindexing or V4 artifacts were added.

## Tests and preflight

- `python -m pytest -q tests/test_v23_conference_reliability.py`: **271 passed**.
- `cd backend; python -m pytest -q`: **2,093 passed, 6 warnings** (existing dependency deprecations).
- `cd frontend; pnpm test`: **23 passed**.
- `cd frontend; pnpm build`: **success**.
- `python evaluation/v23_demo/preflight.py`: local Ollama/qwen3:8b responding; BGE-M3 produced a 1,024-dimensional embedding; hybrid retrieved five located KB excerpts (first: Well Test Analysis p.219); bounded direct calculation validated; collection remained **18,976 chunks / 12 documents**.

## Fresh real-KB development set

The catalog contains 50 tasks plus 10 separate resume probes. The runner uses the real from-message product API, local qwen3:8b and the existing ChromaDB. Re-runs append attempts; `dev_summary.json` scores the latest attempt per ID. Results are diagnostic only.

| Category | Handled | Median | P95 |
|---|---:|---:|---:|
| Knowledge | 7/10 | 29.562 s | 80.983 s |
| Direct | 10/10 | 4.390 s | 8.103 s |
| User formula | 8/8 | 5.351 s | 16.738 s |
| KB formula | 9/10 | 21.766 s | 27.595 s |
| Multi-goal | 5/6 | 6.492 s | 56.843 s |
| False premise | 3/3 | 31.703 s | 42.489 s |
| Unanswerable | 3/3 | 23.516 s | 26.792 s |
| Same-run resume | 8/10 | 16.343 s | 71.740 s |

The seven latest unhandled IDs are `KQ03`, `KQ04`, `KQ09`, `KF08`, `MG06`, `RS02`, and `RS09`. `KQ03` was rerun after bilingual query refinement and still did not retrieve a supportable carbonate/sand formula comparison; `KQ04` retrieved relevant well-test pages but failed the relation-level citation gate; `KQ09` produced a sourced partial answer but did not complete the full question. `KF08` did not verify the GOR source span or execute a validated calculation. `MG06` stopped before both requested comparisons were supported. `RS02` and `RS09` stopped without the required clarification and same-run validated calculation. These are distinct retrieval, semantic-support, formula-source and continuation failures, not one aggregate “LLM error.”

## Visitor stress: 210 distinct development prompts

| Category | Handled |
|---|---:|
| Direct | 60/60 |
| User formula | 40/40 |
| Knowledge | 25/30 |
| KB formula | 12/20 |
| Multi-goal | 15/20 |
| False premise | 10/15 |
| Out of domain | 15/15 |
| Resume | 8/10 |
| **Total** | **185/210 (88.1%)** |

Latest-attempt deterministic checks found **0 technical crashes, 0 blank visible replies, 0 raw error leaks, 0 invented citation IDs and 0 validator-flagged unsupported numeric claims**. Seven stress rows requested unnecessary clarification; 20 answerable rows did not complete their goal. A separate human-level fabricated-formula/source audit and a precise unnecessary-*refusal* rate were not performed, so the strict zero-fabrication and <=5% refusal gates are **not certified** merely by the automated checks. No repeated identical clarification was observed in the recorded resume probes. A small Chroma telemetry `capture()` warning appeared on the terminal but was not exposed in user-facing responses.

The most material remaining stress classes are eight failed KB-formula tasks without validated calculations/citations, five incomplete knowledge tasks, five incomplete multi-goal tasks, five false-premise failures, and two failed same-run resumes. A safe-stop is preferable to an invented number but does not meet the conference-demo completion target.

## Retrieval A/B and conference default

The same 40 fresh development queries were run read-only at top-5; 17 included a literal target formula marker. [Detailed A/B report](RETRIEVAL_AB_REPORT.md) and both raw mode files are alongside this report.

| Mode | Target document @5 | Target page @5 | Literal formula span @5 | Median | P95 |
|---|---:|---:|---:|---:|---:|
| hybrid | 97.5% | 80.0% | 70.6% (12/17) | 4.019 s | 16.799 s |
| hybrid_rerank | 97.5% | 85.0% | 64.7% (11/17) | 11.993 s | 37.795 s |

**Selected development default: hybrid.** The reranker gained two target-page hits but lost one exact formula-span hit and roughly tripled median retrieval time on this host. Gold-page MRR was 0.627 vs 0.665. Independent human/AI semantic relevance adjudication of *every* top-k hit was not done; target-page/span hit is not a substitute. Runs overlapped other local tests, so latency is indicative, not a controlled model comparison.

## Leakage and integrity audit

- The 271 synthetic cases, 50 real-KB tasks, 10 resume probes, 210 stress prompts and 40 A/B queries are **observed development material**. They are not unseen test items. No exact V3 tasks were intentionally copied into these files and no V4 data was opened, authored or executed.
- Real-KB and stress scripts assert that `petroleum_knowledge` has 18,976 chunks before use and check its count afterward. Preflight independently confirmed the same 12/18,976 state. No ingest, PDF extraction, embedding rebuild or Chroma write path was run.
- Evaluation artifacts include repeated development attempts to show iteration; summary metrics use one latest row per ID, never the raw number of attempts as the denominator.
- This development set was used to identify and patch generic mechanisms. It therefore cannot provide an unbiased final performance estimate. A future V4 must be independently generated only after a later V23 candidate meets the freeze gate.

## Remaining blocking work

1. Raise actual KB conceptual answering from 7/10 to at least 9/10 without relaxing citation semantic support or inventing missing relations.
2. Fix source-span selection and binding for the remaining KB-formula cases, then demonstrate at least 95% on a **new or controlled development stress run**; the present latest-attempt rate is 88.1%.
3. Resolve the two missing-input routes that stop instead of entering `WAITING_FOR_USER_INPUT`, and reach at least 9/10 same-run completions.
4. Independently audit semantic fabrication and unnecessary refusals before certifying safety thresholds.

**Initial-candidate freeze decision at that time: NOT READY.** The subsequent V23.1 freeze is documented separately above.
