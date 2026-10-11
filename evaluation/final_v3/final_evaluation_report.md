# Final unseen benchmark v3 — Agent reliability v10

## Evaluation integrity

- Evaluated product: `feature/agent-reliability-v10` at `1fd303255ea151869905092d55096d29f6771128`. Product code was not edited during this evaluation.
- Evaluation branch: `evaluation/final-benchmark-v3`. Freeze commit: `350e3d5eecaee438ca4b529d6c46024ae5cec851`. Frozen benchmark SHA-256: `e8a92fb47b7571d9263dc4a5fb0ff2fb0ff949cd15e4d64b981dc0544d6453c1`.
- 60 frozen, 60 valid, 0 invalid tasks. The same valid tasks feed all five tracks; zero missing raw records (0 absent files).
- Existing Chroma collection `petroleum_knowledge`: 12 documents / 18,976 chunks. Agent used `hybrid` retrieval, local Qwen3:8b, web OFF, and its normal autonomous Python/simulation policies. No reindex or PDF re-extraction.
- Actual model IDs: Agent and local baselines `qwen3:8b`; OpenAI `gpt-5.4-mini-2026-03-17`; reviewer `gemma4:latest`. Gemini was not used.
- Benchmark composition: literature 16, direct_calculation 10, kb_calculation 12, user_formula_calculation 3, user_formula_simulation 3, false_premise 6, clarification 4, unsupported 3, figure 3. Domains: petrophysics 7, reservoir_engineering 10, drilling 11, reservoir_simulation 8, well_testing 10, production 14.
- Pre-freeze dedup compared 284 questions from v1, v2, older heldouts, well-test and development prompts using semantic and numeric-masked similarity. See `benchmark_preflight.json` and the frozen manifest for maxima and source/page checks. v1/v2 results were not rerun.

## Protocol and scoring

Track A is end-to-end Agent versus tool-free, retrieval-free Qwen and OpenAI closed-book. Track B gives the Agent's **actual retrieved KB/FIG excerpts** to separate tool-free Qwen and OpenAI baselines, with no additional retrieval, Python, tools, or web. Agent's Track A row is reused, not rerun.

Three layers were used: deterministic evaluator, structured expected-claim comparison, and **single-reviewer AI-assisted semantic adjudication** by local `gemma4:latest`. The reviewer receives anonymized A–E answers, frozen expected claims and source text, then scores factual support and numeric/unit/formula correctness. Its initial citation-score format failure was preserved in `review/local_gemma_schema`; a clarified fraction-scale protocol scored every valid task uniformly in `review/local_gemma_schema_v2`. Frozen questions, answers, raw system results, and product code remained unchanged.

For machine-verifiable Agent calculations, validated formula AST, bound-input provenance, execution hash, CALC citation, final numeric value and unit take precedence over an AI reviewer's missed arithmetic/formula label. For user-formula calculation tasks, the frozen operational claim that the supplied expression was used is likewise proven by that complete chain. Semantic engineering/citation judgments remain with the single reviewer. A numerical answer with no numeric expression cannot pass numeric accuracy merely because the reviewer says it does.

Agent Goal Success is stricter than answer-only Exact Accuracy: intent route, source requirement, action sequence, actual evidence/citation support and, for calculations, validated Python/CALC adoption, normalized formula provenance, correct formula span/source, numeric value and unit must also pass. Direct calculations cannot have unnecessary RETRIEVE. A retrieved KB formula without CALCULATE fails its transition gate. Thus an answer may be exact but fail Goal Success.

## Track A — End-to-End

| System | Goal Success | Exact Accuracy | Claim Coverage | Hallucination | Numeric Accuracy | Median latency |
|---|---|---|---|---|---|---|
| Petroleum-RAG-Agent v10 | 16.67% | 20.00% | 25.83% | 0.00% | 9.38% | 18.43 s |
| Qwen3:8b closed-book | 61.67% | 61.67% | 64.17% | 3.33% | 78.12% | 1.94 s |
| OpenAI closed-book | 80.00% | 80.00% | 85.00% | 0.00% | 93.75% | 2.71 s |

## Track B — Same-Evidence

| System | Goal Success | Exact Accuracy | Claim Coverage | Hallucination | Numeric Accuracy | Median latency |
|---|---|---|---|---|---|---|
| Petroleum-RAG-Agent v10 | 16.67% | 20.00% | 25.83% | 0.00% | 9.38% | 18.43 s |
| Qwen3:8b same-evidence | 80.00% | 80.00% | 83.33% | 3.33% | 78.12% | 2.03 s |
| OpenAI same-evidence | 91.67% | 91.67% | 93.33% | 0.00% | 100.00% | 2.47 s |

The same-evidence rows are tool-free answer generation over the Agent's retrieved excerpts; they do not inherit the Agent's Python/validation workflow. Hence Goal Success is scored as response correctness for those baselines, not as Agent operational compliance.

## Agent reliability diagnostics

| Agent diagnostic | Result | Denominator |
|---|---:|---:|
| Intent routing | 55.00% | 60 |
| Source requirement | 75.00% | 60 |
| Document recall@K | 87.18% | 39 |
| Page recall@K | 58.97% | 39 |
| Exact formula span recall | 64.29% | 14 |
| Formula source correctness | 0.00% | 14 |
| Formula → CALCULATE | 0.00% | 14 |
| Formula → CALCULATE given span | 0.00% | 9 |
| Calculation provenance completeness | 9.38% | 32 |
| Python/simulation execution | 9.38% | 32 |
| Validated CALC adoption | 9.38% | 32 |
| Correct action selection | 51.67% | 60 |
| False-premise handling | 0.00% | 6 |
| Clarification success | 25.00% | 4 |
| Same-run resume | 0.00% | 4 |
| Figure retrieval | 66.67% | 3 |
| Citation ID correctness | 25.64% | 39 |
| Citation semantic support | 98.30% | 10 |
| Empty final answer | 11.67% | 60 |
| Repeated/no-progress actions | 0.83% | 60 |

Agent run statuses: completed 13, stopped 40, waiting_for_user_input 7. The denominator of each diagnostic is shown explicitly. `Formula → CALCULATE given span` conditions on tasks where the correct formula span was retrieved; all other formula-transition rows use the full KB-formula denominator.

Direct calculations with zero RETRIEVE actions: 0/10. Among tasks requiring KB formulas, exact formula span found: 9/14; subsequent formula→CALCULATE transition: 0/14. Routing errors are shown separately above.

### Category outcomes

| Category | n | Agent Goal Success | Agent Exact Accuracy |
|---|---:|---:|---:|
| clarification | 4 | 0.00% | 0.00% |
| direct_calculation | 10 | 0.00% | 0.00% |
| false_premise | 6 | 0.00% | 0.00% |
| figure | 3 | 66.67% | 66.67% |
| kb_calculation | 12 | 0.00% | 0.00% |
| literature | 16 | 31.25% | 43.75% |
| unsupported | 3 | 0.00% | 0.00% |
| user_formula_calculation | 3 | 33.33% | 33.33% |
| user_formula_simulation | 3 | 66.67% | 66.67% |

### Latency

| Track | Mean | Median | p95 |
|---|---:|---:|---:|
| Petroleum-RAG-Agent v10 | 21.10 s | 18.43 s | 40.59 s |
| Qwen3:8b closed-book | 2.15 s | 1.94 s | 3.80 s |
| OpenAI closed-book | 2.85 s | 2.71 s | 4.71 s |
| Qwen3:8b same-evidence | 2.11 s | 2.03 s | 3.30 s |
| OpenAI same-evidence | 2.60 s | 2.47 s | 4.13 s |

Agent mean stage timings (telemetry, not guaranteed additive): retrieval 6.26 s; planning 2.10 s; LLM generation 10.55 s; Python 0.47 s; calculation/simulation 1.43 s; verification 11.06 s. Latency includes actual model and infrastructure time; same-evidence excludes the preceding Agent retrieval time.

## Uncertainty

Paired task-ID bootstrap, 4000 resamples, seed 20261010, percentile 95% confidence intervals. These describe sampling uncertainty on this 60-task frozen set, not uncertainty from the single AI reviewer or source selection.

| Paired contrast, percentage points | Metric | 95% CI |
|---|---|---:|
| agent_minus_qwen_closed_book | goal_success | [-61.67, -28.33] |
| agent_minus_qwen_closed_book | exact_accuracy | [-60.00, -23.33] |
| agent_minus_qwen_closed_book | claim_coverage | [-56.67, -19.17] |
| agent_minus_qwen_closed_book | hallucination | [-8.33, 0.00] |
| agent_minus_qwen_closed_book | numeric_accuracy | [-85.72, -48.39] |
| agent_minus_openai_closed_book | goal_success | [-76.67, -48.33] |
| agent_minus_openai_closed_book | exact_accuracy | [-73.33, -45.00] |
| agent_minus_openai_closed_book | claim_coverage | [-72.50, -45.00] |
| agent_minus_openai_closed_book | hallucination | [0.00, 0.00] |
| agent_minus_openai_closed_book | numeric_accuracy | [-96.30, -70.00] |
| qwen_same_evidence_minus_qwen_closed_book | goal_success | [5.00, 33.33] |
| qwen_same_evidence_minus_qwen_closed_book | exact_accuracy | [5.00, 33.33] |
| qwen_same_evidence_minus_qwen_closed_book | claim_coverage | [5.83, 32.50] |
| qwen_same_evidence_minus_qwen_closed_book | hallucination | [0.00, 0.00] |
| qwen_same_evidence_minus_qwen_closed_book | numeric_accuracy | [-17.86, 17.24] |
| openai_same_evidence_minus_openai_closed_book | goal_success | [5.00, 20.00] |
| openai_same_evidence_minus_openai_closed_book | exact_accuracy | [5.00, 20.00] |
| openai_same_evidence_minus_openai_closed_book | claim_coverage | [1.67, 16.67] |
| openai_same_evidence_minus_openai_closed_book | hallucination | [0.00, 0.00] |
| openai_same_evidence_minus_openai_closed_book | numeric_accuracy | [0.00, 16.00] |

Full per-system intervals and paired contrasts are in `statistical_analysis.json`.

## Limitations

- Sixty curated tasks over existing local course PDFs are not representative of all petroleum engineering requests, all document quality, or all future user inputs.
- A single local semantic reviewer may misjudge nuanced engineering meaning and citation support. Deterministic provenance and action gates reduce, but do not eliminate, that risk.
- The denominator for formula, figure, false-premise, and clarification subgroups is small; their percentages can shift sharply with one task.
- Same-evidence baselines have no Python/tools and receive only the Agent's actual evidence; this isolates answer generation but is not a full parity comparison of capabilities or cost.
- v2 was used diagnostically to design v10; it is not an independent same-test comparator. No numerical v2→v3 improvement claim is made.

## Poster-safe conclusions

1. Agent Goal Success was 16.67%, below Qwen closed-book 61.67% and OpenAI closed-book 80.00%; the paired intervals above exclude zero for these deficits. v10 did not generalize sufficiently on this unseen set.
2. Routing/execution remains the central failure: intent routing 55.00%, direct calculations with zero retrieval 0/10, formula-span recall 64.29%, but formula→CALCULATE 0.00%. Correct source availability alone did not produce reliable calculation.
3. Calculation provenance completeness was 9.38%, false-premise handling 0.00%, and same-run resume 0.00%. These subgroup results do not substantiate a general reliability claim.
4. Agent Hallucination was 0.00%, versus Qwen closed-book 3.33%; however 40 stopped and 7 waiting runs suppressed answer production. Lower hallucination must not be presented as better task performance.
5. Same-evidence Qwen Goal Success was 80.00% versus 61.67% closed-book, and same-evidence OpenAI 91.67% versus 80.00%. Retrieved context helped tool-free answer generation on this set; the Agent's larger gap points to routing/action/verification and finalization, not just missing knowledge.
6. Agent median latency was 18.43 s versus Qwen closed-book 1.94 s; the Agent incurred a substantial latency trade-off without a success advantage here.
