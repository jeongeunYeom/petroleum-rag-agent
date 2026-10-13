# V21 development report — candidate, not evaluation-frozen

## Scope and integrity

- Repository branch: `feature/agent-generalization-v21` from base product SHA `c82ef66070695e6a13f7a6f3eb35f2714e4e5811`.
- Candidate product commit: `029e00f5a833fa2301a74a10eebb2459319fb424` (`feat: improve agent generalization and calculation orchestration`).
- Product files changed: `backend/app/services/{calculation_request_ir,calculation_requirements,direct_operation_v3,goal_action_planner,goal_execution_agent,goal_intent,goal_knowledge_retrieval,goal_simulation,user_fact_registry}.py`.
- Added `backend/tests/test_v21_generalization.py` and `backend/scripts/run_v21_dev_smoke.py`.
- The previous 24-task benchmark's individual questions, answers, raw runs and judge outputs were not inspected. Only V20.1 aggregate reporting was used. No benchmark-ID rule, page exception, old-task literal, model/dependency addition, Chroma edit or reindex was introduced.

## Architecture changes

1. Direct arithmetic now recognizes role-bearing Korean/English values (initial/final, inlet/outlet, injected/recovered), checks compatible units, and can calculate recovery percentage without KB retrieval. Ambiguous or mismatched operands remain blocked.
2. Sourced-formula selection uses a user-request target contract (quantity, units, known inputs, semantic dimension), guards the requested LHS, and scores source-local variable/unit support. Formula-recovery queries retain the requested target and inputs and expand standard formation-evaluation symbols only as retrieval terms; they never supply an equation.
3. If a clipped PDF chunk initially pins an unusable equation, a later chunk may replace it only when the *same literal equation*, document and page are proven and the contextual interpretation fully binds the supplied inputs. Raw source spans and normal provenance checks remain intact.
4. Bilingual KB query planning includes broader engineering vocabulary; an English-only concept retry is bounded to missing-support/empty-result recovery. Translation is a search aid, not answer evidence.
5. Resume re-evaluates unresolved inputs instead of carrying stale blockers. Added request/operand/formula/retrieval/clarification telemetry for diagnosis. Normal user answers do not show it.

## Fresh synthetic development checks

`backend/tests/test_v21_generalization.py`: **66 passed**. Classification 8/8, semantic-role extraction 8/8, direct calculations 6/6, sourced target selection 8/8, dependency planning 4/4, bilingual query concepts 4/4, same-run resume 4/4, near-miss guards 6/6, synthetic KB retrieve→calculate 10/10, synthetic two-calculation chains 4/4, plus focused recovery/selection checks. No test accepted a hallucinated formula source or an unsupported calculation target. These are development checks, **not poster or unseen benchmark performance**.

## Real production-KB smoke

Local `qwen3:8b`; hybrid retrieval; existing ChromaDB **12 documents / 18,976 chunks**; internal KB only. Fourteen fresh prompts, no prohibited historical values. Machine-readable run IDs, action histories, source document/pages, outputs and timings: `real_kb_smoke.json`.

| ID | Class | Result | Actual action path | Diagnosis |
| --- | --- | --- | --- | --- |
| K1 | Knowledge | FAIL | RETRIEVE→VERIFY→RETRIEVE→VERIFY→RETRIEVE→STOP | Relevant English spans appeared on refinement, but claim-level semantic support still marked the broad multiphase-flow relation unsupported. |
| K2 | Knowledge | FAIL | RETRIEVE→VERIFY→RETRIEVE→VERIFY→RETRIEVE→STOP | Well-test p19 has a productivity-index/drawdown definition, yet the semantic gate rejected the PDF-layout/hyphenated span. |
| X1 | Korean→English | PASS | RETRIEVE→VERIFY→STOP | English-only terminology recovery found grounded formation-resistivity evidence. |
| X2 | Korean→English | FAIL | RETRIEVE→VERIFY→RETRIEVE→VERIFY→RETRIEVE→STOP | Drilling p360 contains the mud-weight/hydrostatic equation and definitions; answerability still rejected the relation. |
| D1 | Direct | PASS | CALCULATE→VERIFY→SYNTHESIZE→STOP | Initial/final increase; validated Python calculation, no retrieval. |
| D2 | Direct | PASS | CALCULATE→VERIFY→SYNTHESIZE→STOP | Inlet/outlet pressure drop; validated Python calculation, no retrieval. |
| D3 | Direct | PASS | CALCULATE→VERIFY→SYNTHESIZE→STOP | Recovered/injected percentage; validated Python calculation, no retrieval. |
| F1 | KB formula | PASS | RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | Sourced hydrostatic equation and validated calculation. |
| F2 | KB formula | PASS | RETRIEVE→RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | Replaced clipped `F=a/fm` candidate with same-page, literal-context interpretation; validated formation-factor result. |
| F3 | KB formula | FAIL | RETRIEVE→RETRIEVE→RETRIEVE→STOP | Available phase-mobility source requires *relative* permeability; prompt supplied only absolute permeability. Safe stop was appropriate rather than inventing the missing property. |
| C1 | Chain | PASS | RETRIEVE→RETRIEVE→CALCULATE→CALCULATE→VERIFY→SYNTHESIZE→STOP | Formula-focused symbol search recovered the correct source; validated F then Rt, preserving both calculation links. |
| C2 | Chain | FAIL | RETRIEVE→RETRIEVE→WAITING_FOR_USER_INPUT | ECD source equation is line-wrapped; parser retained a clipped `ECD=MW+Pd` candidate, while provided annular pressure loss did not safely bind `Pd`. It did not execute the dimensionally questionable formula. |
| R1 | Resume | PASS | RETRIEVE→RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | Missing `m` supplied on the same run; validated calculation. |
| R2 | Resume | PASS | RETRIEVE→RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | Missing TVD supplied on the same run; validated calculation. |

Overall **9/14**: knowledge 0/2, cross-language 1/2, direct 3/3, KB formula 2/3, chain 1/2, resume 2/2. Failed cases remain failed; no prompts were replaced to inflate this result. The two knowledge misses and X2 are likely claim-support false negatives; F3 is a source/input mismatch; C2 needs safer line-wrapped formula interpretation and source-local variable binding.

## Full regression and old benchmark gate

- Backend: `python -m pytest -q` → **1,620 passed**, 6 dependency warnings.
- Frontend: `pnpm test` → **23 passed**; `pnpm build` → **success**.
- Chroma health: existing `petroleum_knowledge` collection count **18,976**, 12 documents; no reindex.
- Hardcoding review of changed product diff found no `V18P-` IDs, protected numeric examples, expected old answers or page-specific exceptions.
- Product candidate was committed, but **not evaluation-frozen** because smoke was 9/14. The observed old-24 regression was **not run**. No product changes were made from old-24 results; there are none.

| Aggregate legacy metric | V18 | V20.1 | V21 |
| --- | ---: | ---: | ---: |
| Goal Success | 25.0% | 20.8% | Not measured (gate held) |
| Claim Coverage | 39.9% | 39.6% | Not measured |
| Hallucination-free | 95.8% | 91.7% | Not measured |
| Numerical Accuracy | 30.0% | 30.0% | Not measured |

V20.1 aggregate diagnostics were 3/10 numeric correct, 3/10 calculations executed, 5/10 operands complete, 0/3 KB retrieve→calculate, 1/8 cross-language success, and 11/22 answerable-task unnecessary refusals. There is deliberately **no V21 paired comparison** until a freeze gate passes and the one allowed observed-set regression runs.

## Readiness and next fixes

**V21 NOT READY FOR NEW UNSEEN BENCHMARK.** The blocker is 5/14 real-KB smoke failures, especially the QA semantic-support false negatives and unsafe ECD line-wrap/variable-binding path. Fix these generally with fresh synthetic cases and re-run development smoke; do not tune against the old 24 tasks. F3 should either receive a genuinely source-compatible input specification or remain an expected safe stop, with that criterion declared before repeating the smoke.
