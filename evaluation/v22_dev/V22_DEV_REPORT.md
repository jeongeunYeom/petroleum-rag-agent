# V22 task-completion development report

This is a development report, not a final or unseen evaluation. The previously observed V3 tasks are used only for a single post-freeze regression diagnostic. A new, separately authored V4 is required for final evaluation.

## Product and scope

- Branch: `feature/task-completion-v22`
- Exact V21.2 base product: `f5182b8ae2907452e1c53373055e66c5182c9b90`
- Frozen V22 product: `0bfffd45043c9a9f50e76dc6e57b7a44458da665` (`feat: make agent complete actionable user tasks`)
- Frozen production KB: `petroleum_knowledge`, 12 documents / 18,976 chunks, hybrid retrieval. No DB mutation or reindex.
- Model: local `qwen3:8b`. No new model, external API dependency, or web-default change.
- Frontend product code was not changed.

Changed backend product files: `calculation_request_ir.py`, `calculation_requirements.py`, `formula_layout_normalizer.py`, `formula_source_registry.py`, `goal_action_planner.py`, `goal_execution_agent.py`, `goal_intent.py`, `goal_simulation.py`, `required_goals.py`, `user_fact_registry.py`, and new `task_actionability.py` (all under `backend/app/services/`).

## Architecture

`ActionabilityAssessment` is a deterministic liveness check made from required goals, intent, parsed direct/user formula work, verified KB formula readiness, evidence, and unresolved inputs. It prevents STOP or clarification from outranking an executable required action. It is not an alternate calculation or provenance validator: normal unit, execution-contract, Python-result, and source-grounding gates still run.

Direct arithmetic now handles compatible sums, differences, named ratios, weighted means, temporal percentage changes, and amount-over-time rates with user facts as provenance. A complete user-supplied expression likewise goes directly to calculation unless the user explicitly requires an internal source. The execution path is chosen before a KB search when no source is requested.

For KB formulas, the selected formula is tied to a literal retrieved span. `FormulaExecutionContract` records the target, normalized equation, RHS variables, source-local definitions/units, bound fact IDs and binding methods, missing/ambiguous variables, and dimensional status. Selection weighs the requested target and supplied symbols; bounded neighboring evidence may refine a source span. Normalization preserves the original PDF text, including layout artifacts such as `F  = a/fm`, while using a defensible executable expression only when local context and a worked example justify it. Once the verified contract is executable, CALCULATE takes precedence over further retrieval or STOP.

Clarification is last: exact user symbols, semantic roles, source-local aliases, dimensionless source definitions, and validated derived facts are checked first. Requests for already supplied facts are rejected. On a valid answer, the same run ID is resumed, stale blockers are cleared, and readiness is recomputed. Required-goal status is recomputed after actions; one completed sub-result cannot terminate another actionable required goal. No-progress STOP is rejected when executable work remains.

## Development verification before freeze

| Check | Result |
| --- | ---: |
| New V22 synthetic/parameterized cases | 129 passed |
| Full backend `python -m pytest -q` | 1,822 passed, 6 warnings |
| Frontend `pnpm test` | 23 passed |
| Frontend `pnpm build` | passed |

The synthetic suite exercises direct routing/execution, weighted pairing, temporal roles, multiple outputs, ratios, time normalization, explicit symbols, dimensionless bindings, verified-formula transitions, formula completeness, clarification negatives, same-run resume, remaining-goal liveness, and unsafe ambiguity. It uses fresh synthetic values rather than copying V3 tasks.

## Fresh real-KB development smoke

The 20 primary cases and 4 resume probes are in `real_kb_smoke.json`; per-case action sequences, output, source IDs, validation, and timing are in `smoke_results.json`. They were executed via the actual autonomous from-message API, local `qwen3:8b`, and the unchanged production KB.

| Group | Run completion | Notes |
| --- | ---: | --- |
| Direct calculation | 6/6 | All began with CALCULATE; no retrieval or clarification. |
| User formula | 4/4 | All began with CALCULATE; no KB formula source invented. |
| KB formula | 5/6 | K03 stopped safely: the requested literal internal relation could not be verified. |
| Grounded knowledge QA | 2/2 by run status | Q02 includes irrelevant cited boilerplate before its correct supported relation; strict semantic scoring could rate this 1/2. |
| Multi-goal | 2/2 | Required outputs completed without early STOP. |
| **Total** | **19/20 by run status** | Strictly penalizing Q02 would leave 18/20, still at the gate. |

Safety inspection of the primary runs: 0 hallucinated formula sources, 0 unsupported numeric claims reported by validation, 0 redundant clarifications on fully specified cases, and no accepted wrong-unit result found. K04 reports an unsimplified but dimensionally equivalent unit (`m3/s/m2` rather than `m/s`); user-facing unit formatting remains a limitation. All successful calculation records have validation and formula provenance.

| Resume probe | Turn 1 | Turn 2 / outcome |
| --- | --- | --- |
| R01 | Asked for the missing SG input | Same run; calculated and completed. |
| R02 | Asked for the missing porosity input | Same run; sourced formula, calculated, completed. |
| R03 | Safely stopped because its explicitly requested internal relation was not verified | No safe same-run calculation was possible. |
| R04 | Asked for the missing B input | Same run; calculated and completed. |

Thus turn-1 clarification was correct in 3/4, same-run preservation was 3/4, final completion was 3/4, and repeated clarification after a valid turn-2 input was 0. The fourth is a source-verification limitation, not a guessed equation.

## Observed V3 development regression after product freeze

The one permitted replay completed all 36 primary tasks and 4 resume probes with 0 technical errors. The unchanged frozen V3 catalog was read from the separate evaluation worktree. Full per-task states and the scoring code are in `observed_v3_results.json` and `run_observed_v3.py`.

| Development-only diagnostic | Observed V22 result |
| --- | ---: |
| Goal Success, deterministic proxy | 9/36 = 25.0% |
| Claim Coverage, lexical proxy | 18.5% |
| Hallucination-free, validator-count proxy | 29/36 = 80.6% |
| Numerical Accuracy | 3/16 = 18.8% |
| Direct-calculation proxy success | 2/6 |
| User-formula proxy success | 1/4 |
| KB-formula RETRIEVE → CALCULATE | 2/6 |
| Unnecessary-refusal proxy | 22 tasks |
| Korean/cross-language proxy success | 1/12 |
| Multi-goal proxy success | 1/6 |
| Same-run resume final completion | 0/4 |

The 9 goal-success proxy cases include 3 safe completions of unanswerable tasks; 11/36 raw runs reported `achieved`, but achievement alone was not treated as proof of a correct or grounded answer. Of the 4 resume probes, two prematurely marked turn 1 achieved, one re-asked for a unit after the supplied turn-2 fact, and one safely stopped without reaching a clarification. These are real remaining generalization failures, not reasons to rewrite observed questions or patch this frozen product.

The proxy scorer checks run state, validated calculations, formula-source page/span, numerical targets, citation IDs, and conservative lexical overlap. It is **not** the original single-reviewer semantic adjudication. The V21.2 published V3 values (5.6% Goal Success, 17.4% Claim Coverage, 83.3% hallucination-free, 6.2% Numerical Accuracy) use a different grading protocol and must not be presented as directly comparable deltas. This replay is an observed development regression only, never a new unseen final result.

## Leakage and remaining limitations

No product code contains a V3 task ID, exact V3 question string, task-specific answer constant, benchmark branch, or a special case targeting V3. The smoke catalog uses new wording and values. No product patch has been made after the freeze commit; in particular, observed V3 output is not being used for tuning.

Limitations already visible in fresh development smoke: a verified source can still be unavailable for an explicitly requested relation (K03/R03), one knowledge answer contains extraneous cited boilerplate (Q02), and dimensional-equivalent units are not always simplified (K04). The observed V3 replay additionally exposes substantial phrasing/generalization gaps in direct calculation, user-formula handling, KB formula transition, Korean prompts, multi-goal completion, and same-run resume. In particular, passing a narrow fresh smoke gate does not establish robust task completion. V22's unseen generalization is unknown until a new V4 is authored and run separately.
