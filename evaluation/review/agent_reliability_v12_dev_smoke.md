# Agent reliability v12 — development smoke

This is a **development regression**, not an unseen or final benchmark. The frozen v4 benchmark and all earlier heldout material were not changed or rerun. Product execution used local `qwen3:8b`, hybrid retrieval, web off, and the existing Chroma collection `petroleum_knowledge` (12 documents, 18,976 chunks). OpenAI API calls: **0**. Gemini API calls: **0**.

## Strict acceptance

The v12 checker requires more than an intermediate numeric result: intent and source-origin match, expected facts and their values/units, operation/action order, variable binding, validated calculation, complete provenance, numeric and output-unit match, final answer adoption, completed run, and `achieved` goal. Resume cases additionally require an initial wait, the missing-variable question, the same run ID, retained prior facts, and merged reply facts. A stopped or partially fulfilled run cannot pass merely because it calculated a correct number.

The synthetic suite has 131 parameterized cases, including 25 fact/unit cases, 27 direct-operation sandbox runs, 20 realistic multi-equation selection cases with four distinct phrasings per equation, bilingual user-formula/sweep/resume variants, dimension inference, and stale-criterion/finalization checks. The six strict-checker false-positive regressions are separate. All 137 targeted tests passed. The full backend suite passed 1,059 tests (six warnings). The frontend `pnpm build` passed; `pnpm test` is unavailable because this package defines no test script.

## Real local smoke

| Category | Passed / total |
| --- | ---: |
| Direct calculation | 8 / 8 |
| KB formula calculation | 8 / 8 |
| User formula calculation | 4 / 4 |
| Simulation | 3 / 3 |
| False-premise | 2 / 2 |
| Knowledge QA | 1 / 2 |
| Clarification and same-run resume | 3 / 3 |
| **Total** | **29 / 30 (96.7%)** |

All 26 calculation/simulation/resume cases finished `completed` and `achieved` with a validated calculation. The only failure was Q02, a literature explanation that stopped safely when the retrieved excerpts did not semantically support the answer. See [failure analysis](agent_reliability_v12_failure_analysis.md).

| Critical counter | Count |
| --- | ---: |
| Formula ready but no CALCULATE | 0 |
| Validated CALC but not achieved | 0 |
| Stale criterion after resume | 0 |
| Value–unit locality rejections in the 30 live prompts | 0 |

Adversarial locality cases are exercised in synthetic tests; zero live rejections means the live prompts did not include a rejected fallback proposal, not that the rejection path was bypassed. Results are in [raw smoke JSON](agent_reliability_v12_dev_smoke.json) and the [strict acceptance matrix](agent_reliability_v12_acceptance_matrix.csv). Neither is a final product accuracy estimate.

## Product changes exercised

- `UserFactRecord` v3 records semantic role, entity, dimension, source spans, confidence, and extraction method. Unit normalization, nearby value–unit checks, series/shared-duration extraction, and fallback rejection reasons prevent misbinding a later time value to an earlier flow-rate unit.
- Intent routing separates user-provided expressions from requests to find a KB equation. Direct operations include conversions, differences/slopes, cylinder volume, energy, concentration, percentage change, and duration-weighted mean; user-only operations do not require KB evidence.
- Formula selection ranks literal candidates on the actual source span with LHS, variables, additive structure/term count, and negative constraints. Variable aliases and evidence-grounded dimensionless inference feed calculation readiness; a selected equation proceeds to CALCULATE when all inputs bind.
- Bounded Python output is independently checked; formula output units are propagated through the bounded AST. A validated CALC can satisfy operational criteria only when provenance and its numbers/units appear in the final cited answer. This removes stale partial criteria after successful execution or resume without waiving engineering and citation checks.
- Clarification/resume merges new facts into the original run. The error taxonomy and telemetry record formula origin, selection, dimension inference, fact rejection, and calculation failure stage.

## Remaining limits

Q02 demonstrates that a general KB question can still retrieve excerpts that fail citation-semantic support and end in a safe stop. Formula-aware unit inference handles the supported bounded arithmetic grammar; more complex compound-unit simplification remains a future task. This development smoke is small and cannot substitute for a new frozen unseen evaluation.
