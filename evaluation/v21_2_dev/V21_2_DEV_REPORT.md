# V21.2 development report — multi-goal completion

## Scope and freeze

- Branch: `fix/v21-2-goal-completeness`; base `72a43487cbcc4c2d63529a78ebdd578c7e916e77`.
- Frozen product: `f5182b8ae2907452e1c53373055e66c5182c9b90` ([freeze note](V21_2_FREEZE_NOTE.md)). No product change occurred after the observed old-24 regression began.
- Product files: `backend/app/services/required_goals.py` (new), `goal_execution_state.py`, `goal_execution_agent.py`; synthetic tests: `backend/tests/test_v21_2_goal_completeness.py`. No UI, model, retrieval, embeddings, ChromaDB, benchmark questions, scoring rules or calculation IR were changed.
- The `RequiredGoal` checklist is derived from user wording before retrieval, frozen in `GoalExecutionState`, and retained on same-run resume. Explicit coordinated verbs or an explicit “each relation, then calculate” structure create separate obligations; bare noun conjunctions do not. `CalculationRequestIR` still performs numerical execution.
- A conceptual goal requires a literal, locally supported source span cited in the answer. A numeric goal requires a validated computation adopted with its value, unit and CALC citation; the pre-existing formula/target/provenance and engineering evaluation gates remain in force. Comparison/ranking cannot become MET from answer text alone: it needs a cited validated derived output and a comparative conclusion.
- After synthesis, the agent checks each multi-goal obligation. If a supported relation was omitted, it appends the already verified raw quote and citation once, without retrieval, Python or an invented claim. Telemetry records missing IDs, whether repair was attempted/succeeded, and each goal's final status. Full ACHIEVED additionally requires all required goals MET. Single-goal behavior continues through its existing evaluators.

## Validation before the observed regression

| Check | Result |
| --- | --- |
| V21/V21.1/V21.2 targeted tests | **139 passed** |
| New V21.2 synthetic cases | **39 passed** (parsing, conceptual/numeric coverage, multiple outputs/claims, omission, bounded repair and false-split guards) |
| Full backend `pytest -q` | **1,693 passed**, 6 warnings |
| Frontend `pnpm test` | **23 passed** |
| Frontend `pnpm build` | **success** |
| Product-diff leakage scan | No old task IDs, development case branches, run-ID/page exceptions or smoke-specific values |

The 14-case smoke used the unchanged prompts, local `qwen3:8b`, hybrid retrieval and the original read-only 12-document/18,976-chunk production KB. Its unchanged runner's original boolean is preserved in [raw output](real_kb_smoke.json). The [V21.2 acceptance rule](V21_2_PREDECLARED_ACCEPTANCE.md) was written before that run: C2 needs both user goals, **not** two calculations; F3 is the only expected safe stop.

| ID | V21.2 acceptance | Action path | Validated CALCs | Time (s) |
| --- | --- | --- | ---: | ---: |
| K1 | PASS | RETRIEVE→VERIFY→RETRIEVE→VERIFY→STOP | 0 | 49.079 |
| K2 | PASS | RETRIEVE→VERIFY→STOP | 0 | 13.312 |
| X1 | PASS | RETRIEVE→VERIFY→STOP | 0 | 17.609 |
| X2 | PASS | RETRIEVE→VERIFY→STOP | 0 | 13.079 |
| D1 | PASS | CALCULATE→VERIFY→SYNTHESIZE→STOP | 1 | 4.171 |
| D2 | PASS | CALCULATE→VERIFY→SYNTHESIZE→STOP | 1 | 4.141 |
| D3 | PASS | CALCULATE→VERIFY→SYNTHESIZE→STOP | 1 | 4.141 |
| F1 | PASS | RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 1 | 19.640 |
| F2 | PASS | RETRIEVE→RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 1 | 48.672 |
| F3 | EXPECTED_SAFE_STOP | RETRIEVE→RETRIEVE→RETRIEVE→STOP | 0 | 55.360 |
| C1 | PASS | RETRIEVE→RETRIEVE→CALCULATE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 2 | 45.110 |
| C2 | PASS by predeclared completeness rule; historical runner flag remains FAIL | RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 1 | 26.265 |
| R1 | PASS | RETRIEVE→RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 1 | 47.985 |
| R2 | PASS | RETRIEVE→RETRIEVE→CALCULATE→VERIFY→SYNTHESIZE→STOP | 1 | 53.062 |

**Development gate: 13 achieved + 1 expected safe stop + 0 unexpected failures.** C2 required goals were `G1 knowledge_relation=MET` and `G2 numeric_calculation=MET` (2/2). Its final answer includes the literal hydrostatic relation `P = 0.052 × MW × TVD` with source `Heriot-Watt_University_-_Drilling_Engineering.pdf` p.75 `[KB1]`, and validated `ECD = 10.294444444444444 ppg` `[CALC1]`, with formula provenance from the same book p.192 and variable definitions p.193. The first synthesis omitted G1; a single append-only repair supplied the verified quotation. `engineering_validation_passed=true`, `citation_semantic_passed=true`, unsupported citation/numeric claim counts 0. The unchanged legacy runner still marks C2 FAIL solely for its two-CALC `chain` counter; that historical output was **not** edited.

F3 stopped with `insufficient_evidence`, zero computations and no invented relative permeability or mobility value. Its explanation of the missing input/source remains generic.

The only post-smoke product addition was a comparison/ranking proof guard. The stored 14 run records show none had a comparison/ranking RequiredGoal, and the full backend suite passed after the addition. No second full-smoke run is claimed.

## Observed legacy 24-task regression — **not unseen**

After product freeze, the unchanged 24 questions (SHA-256 `6913d38c697e00cc4601db3d53e3e4270350520600de0d9e9ac2fc25169e2b1f`) were each submitted once; 24/24 raw runs completed or entered their terminal waiting/stopped state. A blinded **single-reviewer AI-assisted semantic adjudication** used `gpt-5.4-2026-03-05` once per task alongside the existing frozen numeric/diagnostic scoring functions; 24/24 reviews completed. This is an observed development regression, not a new final estimate. All raw, reviewer and score artifacts are under [`evaluation/v21_2_regression_old24`](../v21_2_regression_old24/).

| Same-reviewer scoring on the observed set | V18 | V20.1 | V21.2 |
| --- | ---: | ---: | ---: |
| Goal Success | 20.83% | 16.67% | **20.83%** |
| Claim Coverage | 38.89% | 38.54% | **39.93%** |
| Hallucination-free | 91.67% | 91.67% | **87.50%** |
| Numerical Accuracy | 30.00% | 30.00% | **30.00%** |
| Median latency | 14.40 s | 20.31 s | **16.23 s** |

The previously published V20.1 aggregate used its original reviewer call and reported 20.83% Goal Success, 39.58% Claim Coverage, 91.67% hallucination-free and 30.00% Numerical Accuracy. Its re-adjudicated 16.67%/38.54% values above are a different reviewer call, not a corrected historical publication. For a like-for-like comparison within **this** adjudication, V21.2 minus V20.1 is +4.16 pp Goal Success, +1.39 pp Claim Coverage, −4.17 pp hallucination-free and 0 pp Numerical Accuracy. Reviewer variability and the small, already observed set limit inference.

| V21.2 diagnostic | Observed result |
| --- | ---: |
| Numeric operands complete | 5/10 |
| Numeric calculation executed | 3/10 |
| Numeric correct | 3/10 |
| KB-formula retrieval | 3/3 |
| Correct source span retrieved | 1/3 |
| KB `RETRIEVE→CALCULATE` | 0/3 |
| KB numeric correct | 0/3 |
| Cross-language Goal Success | 1/8 |
| Unnecessary refusals | 9/22 answerable tasks |
| Same-run resume success | 0/3 (one did not wait; two remained waiting after the supplied second turn) |

These weaknesses were **not** used to patch product code. The numerical/provenance and resume results do not support a broad reliability improvement claim from the old set. The narrow C2 development failure is repaired, but performance beyond the development cases needs a new unseen benchmark.

## Integrity and limitations

- No old-24 individual question, answer, raw output or judge output was inspected before freeze; no old-24 result informed implementation. The observed benchmark, prior raw data and ChromaDB were not modified.
- Explicitly coordinated user obligations are handled; ambiguous discourse, anaphora and open-ended lists may still need clarification. One bounded append-only source repair cannot create unsupported evidence.
- The old24 reviewer is a single AI adjudicator, not human review; this observed regression cannot establish final generalization. The slight hallucination-free decline and 0/3 resume successes are material limitations.
- The generated evaluation harness reads the immutable benchmark by Git object ID and writes only the new regression directory. It does not alter the frozen product.

**V21.2 product is frozen for a new unseen benchmark, not certified as broadly reliable.**
