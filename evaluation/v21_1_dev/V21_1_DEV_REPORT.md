# V21.1 development report — acceptance gate held

## Scope and integrity

- Branch: `fix/v21-1-semantic-support-formula-binding`.
- Base: `feature/agent-generalization-v21` at `1ae729e967ed2cbebc92241e091f2cddf0e365c6`. Section 1 of the request has a different SHA; the actual repository HEAD and the request's `CURRENT REPORT HEAD` both identify this base.
- Product changes: `source_answerability.py`, `source_verification_text.py`, `formula_layout_normalizer.py`, `formula_source_registry.py`, `formula_units.py`, `sourced_conversion_units.py`, `source_local_aliases.py`, `formula_dependency.py`, `goal_clarification.py`, `goal_simulation.py`, `goal_execution_agent.py`.
- Added 34 fresh synthetic test cases in `test_v21_1_stabilization.py`. This work did not edit the retrieval stack, model, prompts in `run_v21_dev_smoke.py`, UI, ChromaDB, or benchmark/scoring files. Existing DB health remained 12 documents / 18,976 chunks; local `qwen3:8b`, hybrid retrieval, internal KB only.
- Individual old-24 benchmark tasks, answers, raw runs, and judge outputs were not inspected or run. The old observed set was not used for implementation tuning.

## Root causes and narrow changes

| Case | Diagnosed mechanism | Change |
| --- | --- | --- |
| K1 | The Korean morphology/term translation left request-noise tokens, and the relevant fractional-flow sentence and gas/oil relative-permeability definitions were split within one retrieved page. | Verification-only PDF normalization, longest-term-first bilingual matching, and at most two same-document/same-page raw spans with a relation bridge. The answer still quotes literal source spans; it does not infer a numeric/directional effect absent from them. |
| K2 | The productivity-index/rate-per-drawdown sentence followed broken PDF equation lines; strict subject-token subset and hyphen tokenization rejected the literal relation. | Mechanical hyphenation normalization and relation predicate matching across the local sentence; raw quote and page remain unchanged. |
| X2 | Korean relational filler survived as a required factual token, while `P = coefficient × MW × TVD` and the source-local `P`/`MW` definitions were treated as separate QA pieces. | Remove question-only relation filler from matching and accept a literal, parseable source equation plus its local definitions as non-calculation relational evidence. No Python call was added. |
| C2 | PDF extraction placed the denominator on the next line; the clipped additive expression was unsafe. `Pd` and `D` definitions occurred on the immediately next page, and `D = depth (ft)` was wrongly promoted to a dependency equation. | Reconstruct only bounded, source-anchored wrapped fractions; reject explicitly incompatible clipped additions; bind unique source-local definitions to labelled user facts with compatible units; infer the printed coefficient's dimensions only from declared local variable units. Keep the raw formula span, offsets, formula-source chunk and alias-definition chunk. Treat a unit-bearing definition as a definition, not an executable equation. |

F3 was **predeclared EXPECTED_SAFE_STOP** in `F3_PREDECLARED_ACCEPTANCE.md` before the smoke. The sourced phase-mobility relation requires relative permeability, but only absolute permeability was supplied. The agent made no calculation and did not substitute the latter for the former. The final message was safe but generic about the missing relation/input; a more specific explanation remains desirable.

## Validation

- V21/V21.1 and formula-layout/dependency targeted tests: **153 passed**.
- Full backend: **1,654 passed**, 6 third-party/deprecation warnings.
- Frontend: **23 passed**; `pnpm build`: **success**. No frontend file changed.
- Added negative cases for lexical hyphens, unrelated relation words, cross-document joins, ordinary prose after an equation, incompatible clipped additions, same-unit-but-wrong-concept aliasing, competing definitions and duplicate user labels.
- Changed-product diff scan: no `V18P`/case-ID branches, smoke-specific numeric literals, document/page exceptions, run-ID exceptions or old benchmark answers. Synthetic test fixtures contain their own invented values.

## Same 14 development prompts on the real KB

The unchanged runner was executed twice with separate output files. The first pass was retained rather than overwritten; after diagnosing K1/X2 verifier false negatives and C2's unit-definition-as-formula error, the second pass used a restarted backend. No case text, value or reply was changed. `PASS` below is the runner's original rule; only F3 receives its *predeclared* expected-safe-stop interpretation.

| ID | Second-pass result | Actual actions | Validated CALC / core output | Cited KB page | Seconds |
| --- | --- | --- | --- | --- | ---: |
| K1 | PASS | RETRIEVE→VERIFY→RETRIEVE→VERIFY→STOP | 0; literal supported relation | Petroleum Engineering Handbook Vol. V p.1116 | 44.469 |
| K2 | PASS | RETRIEVE→VERIFY→STOP | 0; productivity index per drawdown | Well Test Analysis p.19 | 13.219 |
| X1 | PASS | RETRIEVE→VERIFY→STOP | 0; formation resistivity | Formation Evaluation p.86 | 17.765 |
| X2 | PASS | RETRIEVE→VERIFY→STOP | 0; sourced pressure/mud-density relation | Drilling Engineering p.360 | 13.141 |
| D1 | PASS | CALCULATE→VERIFY→SYNTHESIZE→STOP | 1; 25% | User facts | 4.172 |
| D2 | PASS | CALCULATE→VERIFY→SYNTHESIZE→STOP | 1; 240 psi | User facts | 4.156 |
| D3 | PASS | CALCULATE→VERIFY→SYNTHESIZE→STOP | 1; 77.5% | User facts | 4.156 |
| F1 | PASS | RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 1; 3177.20 psi | Drilling Engineering p.75 | 19.797 |
| F2 | PASS | RETRIEVE→RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 1; F≈12.4291 | Formation Evaluation p.164 | 52.906 |
| F3 | EXPECTED_SAFE_STOP (runner FAIL) | RETRIEVE→RETRIEVE→RETRIEVE→STOP | 0; no fabricated mobility | Retrieved mobility sources; no numeric citation | 60.484 |
| C1 | PASS | RETRIEVE→RETRIEVE→CALCULATE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 2; F≈12.4291, Rt≈8.4552 ohm-m | Formation Evaluation, including p.164 | 43.047 |
| C2 | FAIL (product ACHIEVED) | RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 1; ECD≈10.2944 ppg | Drilling Engineering p.192 formula, p.193 definitions | 26.063 |
| R1 | PASS | RETRIEVE→RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 1; F≈12.6357 | Formation Evaluation p.164 | 54.219 |
| R2 | PASS | RETRIEVE→RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 1; P≈3300.96 psi | Drilling Engineering p.75 | 45.625 |

Second pass: **12 runner PASS + 1 predeclared safe stop + 1 unexpected C2 runner FAIL = 13/14 expected behavior**. K1/K2/X2 changed from first-pass FAIL to PASS. C2 progressed from waiting for an unnecessary `depth` input to a validated ECD calculation with `D→USERF2`, `MW→USERF1`, `Pd→USERF3`, a literal p.192 equation and p.193 definitions. The observed run had one CALC, whereas the unchanged `chain` smoke rule requires two; its final answer also did not separately explain the requested hydrostatic relation despite an `ACHIEVED` status. A post-smoke record-only patch preserves the wrapped raw formula span on future computation records; the full suite passed after that patch, but it is **not** claimed as a new real-KB smoke result.

The remaining C2 issue is goal/action/answer completeness, not source-text reconstruction or variable binding. Adding an otherwise unrequested hydrostatic Python calculation solely to satisfy the 2-CALC counter, or changing the smoke rule after seeing results, would breach the narrow patch/no-benchmark-rule-change policy. It remains an explicit blocker.

## Freeze and old-24 decision

**No V21.1 product freeze**: the required 14/14 gate did not pass. No `V21_1_FREEZE_NOTE.md` is issued. The observed old-24 regression was **not run**, so V21.1 Goal Success, Claim Coverage, hallucination-free rate, numerical accuracy and V20.1→V21.1 deltas are **not measured**. The previously reported V20.1 aggregates (20.8% Goal Success, 39.6% Claim Coverage, 91.7% hallucination-free, 30.0% numerical accuracy) are historical context only, not a paired comparison here.

## Remaining limitations

1. C2 goal completeness/action-sequence mismatch as above. Its one correct ECD value is not enough to call the 14-case gate successful.
2. K1's extractive answer gives the relative-permeability/fractional-flow source relation, but not a quantified direction or magnitude; none should be inferred from these excerpts alone.
3. F3's safe refusal could name relative permeability more explicitly without inventing a value.
4. Source-local dimensional inference for printed conversion coefficients is bounded to the accepted wrapped additive fraction shape; other PDF layouts still stop rather than guess.

**V21.1 NOT READY FOR NEW UNSEEN BENCHMARK.**
