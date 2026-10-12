# V19 orchestration reliability — development report

This is a **synthetic development smoke and regression check**, not an independent final evaluation or a performance claim. No sealed v18 benchmark item, answer, raw response, or source span was inspected or rerun.

## Version and verification

- Branch: `feature/agent-reliability-v19`
- Frozen v18 product base SHA: `740206d6de8e3be6cb4b21792b2c3429c65fcd6a`
- V19 implementation result SHA: `0e9bcdc1e64e1c2a90bb4edc908c8a202bbd4d07`
- Backend suite: `python -m pytest -q` → **1,469 passed**, 6 pre-existing deprecation warnings
- Fresh v19 tests: `python -m pytest -q tests/test_agent_reliability_v19_dev.py` → **19 passed**
- Development smoke: `python scripts/run_v19_dev_smoke.py` → **9/9 passed**
- Frontend: unchanged; frontend tests/build were not required or run for this backend-only patch.

## Changes and observed development results

| Area | Change | Synthetic verification |
|---|---|---|
| Formula recovery | After an unsuccessful KB-formula retrieval, issue a distinct deterministic equation-oriented query, with at most two additional retrievals and within the request's retrieval budget. Query uses requested text, supplied variable names/units, known engineering translations, and retrieved document context; it never proposes an equation. | One smoke recovery attempted and succeeded. A separate no-equation test stopped safely after exactly two additional attempts; no calculation or invented formula. |
| Local source expansion | At most once per run, read up to eight original indexed chunks near two leading retrieved chunks, on the same/neighboring pages. Original document, page, chunk ID and text become new evidence; no Chroma write occurs. | One smoke local expansion succeeded and produced a validated sourced calculation. A separate mock-collection test checked the bounded original-chunk reader. |
| Formula selection/readiness | LHS and variable overlap remain primary; explicit local source unit hints now influence ranking. A scale-different unit is not silently converted, and an explicit source/user unit conflict blocks Python. Exact literal formula span and source ID checks remain mandatory. | 3/3 KB smoke calculations executed, validated, and numerically correct. A two-candidate synthetic case selected the compatible source; a conflict case executed zero Python calls. |
| Deterministic calculation transition | Verified sourced formula plus complete facts/units forces CALCULATE ahead of no-progress or model planning. Ready direct/user-formula calculations take the same bounded deterministic path. | 7 ready smoke calculations, 7 forced transitions, 7 executed, 7 validated, 7 numerically correct. Action traces include `RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP` and direct `CALCULATE → VERIFY → SYNTHESIZE → STOP`. |
| Refusal/partial grounding guard | Before STOP, check claim support. A model's generic unsupported verdict may be overridden only by a literal relation span that also passes engineering validation; conflicts are excluded. Supported subsets yield cited partial answers without full goal success. | 4 smoke guard checks; 2 grounded QA refusals prevented; 0 verified-supported smoke cases refused. Fresh tests also verified one bounded partial answer and one genuinely unsupported request remaining unanswered. |
| Clarification/resume | Rebuild user facts and readiness on resume, including corrected assignments that retain a USERF ID. Clear stale blockers only when the current formula, bindings and units are ready; ask only for genuinely remaining inputs. | 2/2 smoke runs preserved their run ID, recomputed readiness, cleared the prior block, suppressed repeated clarification, completed a validated calculation, and achieved the goal. A third fresh two-turn regression also passed. |
| Cross-language | Recovery query includes known English engineering terms and canonical symbols/units for Korean input; evidence remains literal and cited. | 2/2 fresh Korean-question/English-source cases succeeded without unnecessary refusal. |

## Smoke case trace

| Case | Type | Result | Action trace |
|---|---|---|---|
| KB-A | Immediate sourced formula | PASS | RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP |
| KB-B | Original indexed neighbor expansion | PASS | RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP |
| KB-C | Formula-recovery retrieval | PASS | RETRIEVE → RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP |
| DIRECT-A | User-only arithmetic | PASS | CALCULATE → VERIFY → SYNTHESIZE → STOP |
| DIRECT-B | User-supplied formula | PASS | CALCULATE → VERIFY → SYNTHESIZE → STOP |
| QA-A | Grounded source answer | PASS | RETRIEVE → VERIFY → STOP (grounded finalization) |
| QA-B | Grounded source answer | PASS | RETRIEVE → VERIFY → STOP (grounded finalization) |
| RESUME-A | KB formula, missing operand then reply | PASS | RETRIEVE → WAITING_FOR_USER_INPUT → CALCULATE → VERIFY → SYNTHESIZE → STOP |
| RESUME-B | User formula, missing operand then reply | PASS | WAITING_FOR_USER_INPUT → CALCULATE → VERIFY → SYNTHESIZE → STOP |

`WAITING_FOR_USER_INPUT` is a run state, not an invented action-history entry. All sources in these cases were newly authored in-memory fixtures; the production ChromaDB was neither modified nor reindexed.

## Safety and limits

- Tested safety regressions: invented formulas **0**, unsupported calculations **0**, tested provenance failures **0**, infinite recovery loops **0**, false full goal success in a partially supported claim case **0**.
- Unit compatibility is a **ranking and readiness** signal, not a conversion engine. Different scales require an explicit validated conversion.
- Recovery remains constrained by a user's `max_retrieval_actions` and `max_iterations`. A short iteration budget can expire before retrieval, calculation, verification, and synthesis all complete; the patch does not silently raise user-configured limits.
- Results use controlled synthetic evidence and LLM-boundary stubs. They do not establish production-KB or unseen-benchmark performance; a separate independent evaluation would be required.
- Sealed v18 benchmark inspected: **NO**. Sealed v18 benchmark rerun: **NO**. Main modified/merged: **NO**. New final benchmark started: **NO**.
