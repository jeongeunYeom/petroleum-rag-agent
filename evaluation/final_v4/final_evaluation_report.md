# Final unseen benchmark v4 — Agent reliability v11.1

## Evaluation integrity

- Evaluated product: `feature/agent-reliability-v11-1` at `9739350b95db212fd01d49683fb0d027f77d1fc7`; product code, ChromaDB, and frozen benchmarks were not modified.
- Evaluation branch: `evaluation/final-benchmark-v4`; freeze commit `bc3a0d7444e94c7f35b4b1ba00e1baa2610113b0`; committed benchmark SHA-256 `8d8bc2366a6fe5fbd4c335f68f92961e04794d3dfe5ba6e08ea9f676035feba8`.
- 60 frozen, 60 valid, 0 INVALID. The same valid tasks are used in all five rows.
- Agent: local `qwen3:8b`, `hybrid` retrieval, existing 12-document/18,976-chunk ChromaDB, web OFF, autonomous Python/simulation enabled. Qwen baseline: `qwen3:8b`; OpenAI baseline: `gpt-6.1-sol`; independent reviewer: `gpt-6-astra`. Gemini was not used.
- Categories: literature 14, direct_calculation 10, kb_calculation 12, user_formula_calculation 4, user_formula_simulation 4, false_premise 6, clarification 4, unsupported 3, figure 3. Domains: reservoir_engineering 10, reservoir_simulation 7, well_testing 10, petrophysics 10, drilling 10, production 13.
- Formula ambiguity was explicitly tagged on 4 KB-formula tasks; it is part of the frozen set, not post-hoc filtering.
- Pre-freeze audit compared 769 prior questions/dev prompts, including semantic, normalized, numeric-masked and equation-structure similarity plus source-page overlap. Flagged near duplicates: 0; old source-page overlap: 0. Generic equation-shape matches (65) were manually reviewed rather than equated with duplicate tasks. See `benchmark_preflight.json` for thresholds and results. v3 was used diagnostically, not as an independent final comparator.

## Protocol and scoring

Track A compares end-to-end Agent with Qwen and OpenAI closed-book (no retrieval, tools, Python or web). Track B gives tool-free Qwen/OpenAI **only the KB/FIG text actually captured by the Agent**, without further retrieval; no figure pixels. The Agent row is reused, not rerun.

For four frozen clarification tasks, the same follow-up message was provided to each baseline after its initial response whether or not it asked the correct question. Agent operational scoring additionally requires an appropriate clarification and a successful same-run resume.

The three scoring layers are deterministic operational/numeric checks, structured expected-claim comparison, and **single-reviewer AI-assisted semantic adjudication**. The reviewer sees anonymized A–E answers, frozen gold claims/spans and each answer's actual cited evidence. It does not repair answers. Raw reviews, model IDs and per-task scores are retained.

An initial reviewer request returned HTTP 400 because JSON mode required an explicit JSON instruction in the input message. Its error record is preserved in `review/error_history`; the request format was corrected before any semantic score was produced. Product outputs and gold were unchanged.

Agent Goal Success has stricter operational gates than baseline answer-only Goal Success: correct intent/source route and action sequence, evidence and citation semantic support, plus validated CALC/provenance/formula binding/source and numeric/unit adoption when relevant. Thus the Agent can have an accurate final text but fail its end-to-end goal. Exact Accuracy, Claim Coverage and Hallucination are reported separately to expose this asymmetry.

False-premise correction is counted only when the answer explicitly rejects and corrects the premise without additional unsupported or contradictory claims; the Agent must also have a valid, semantically supporting citation. A reviewer-level correction verdict alone does not suffice.

## Track A — End-to-End

| System | Goal Success | Exact Accuracy | Claim Coverage | Hallucination | Numeric Accuracy | Median latency |
|---|---:|---:|---:|---:|---:|---:|
| Petroleum-RAG-Agent v11.1 | 8.33% | 13.33% | 25.28% | 13.33% | 14.71% | 17.00 s |
| Qwen3:8b closed-book | 43.33% | 43.33% | 63.06% | 45.00% | 79.41% | 1.85 s |
| OpenAI closed-book | 78.33% | 78.33% | 84.72% | 0.00% | 94.12% | 5.51 s |

## Track B — Same-Evidence

| System | Goal Success | Exact Accuracy | Claim Coverage | Hallucination | Numeric Accuracy | Median latency |
|---|---:|---:|---:|---:|---:|---:|
| Petroleum-RAG-Agent v11.1 | 8.33% | 13.33% | 25.28% | 13.33% | 14.71% | 17.00 s |
| Qwen3:8b same-evidence | 50.00% | 50.00% | 75.00% | 36.67% | 76.47% | 1.62 s |
| OpenAI same-evidence | 78.33% | 78.33% | 86.39% | 1.67% | 94.12% | 5.54 s |

Descriptive exact-accuracy gaps relative to the Agent: Qwen same-evidence +36.67 percentage points; OpenAI same-evidence +65.00 points. These are not a pure causal estimate of orchestration because model capabilities and operational gates differ.

## Agent reliability diagnostics

| Agent diagnostic | Result | Denominator |
|---|---:|---:|
| Natural-language fact extraction recall (count proxy) | 52.07% | 22 |
| Unit normalization (canonical-unit record proxy) | 100.00% | 13 |
| Intent routing | 70.00% | 60 |
| Source requirement | 83.33% | 60 |
| Document recall@K | 75.00% | 36 |
| Page recall@K | 58.33% | 36 |
| Domain-matched document recall@K | 77.78% | 36 |
| Relevant gold-span chunk@K | 58.33% | 36 |
| Top-3 gold-span precision | 17.59% | 36 |
| Wrong-domain dominance | 20.69% | 29 |
| Refined retrieval triggered (probe tasks) | 0.00% | 2 |
| Refined retrieval recovery (probe tasks) | — | 0 |
| Exact formula span recall | 46.15% | 13 |
| Formula candidate selection | 7.69% | 13 |
| Formula → CALCULATE | 0.00% | 13 |
| Formula → CALCULATE given span | 0.00% | 6 |
| Formula source correctness | 0.00% | 13 |
| Variable binding | 17.65% | 34 |
| Calculation provenance completeness | 17.65% | 34 |
| Python/simulation execution | 17.65% | 34 |
| Validated CALC adoption | 17.65% | 34 |
| Correct action selection | 53.33% | 60 |
| Premise relevant-source retrieval | 66.67% | 6 |
| False-premise handling | 33.33% | 6 |
| Clarification success | 100.00% | 4 |
| Same-run ID | 100.00% | 4 |
| Resume fact ingestion | 50.00% | 4 |
| Resume completion | 0.00% | 4 |
| Figure retrieval | 100.00% | 3 |
| Citation ID correctness | 38.89% | 36 |
| Citation semantic support | 78.57% | 14 |
| Empty final answer | 25.00% | 60 |
| Repeated/no-progress actions | 0.83% | 60 |

Agent run status counts: completed 18, stopped 27, waiting_for_user_input 15. Direct calculations with no retrieval: 9/10; entered CALCULATE: 5/10. KB-formula exact spans: 6/12; subsequent formula→CALCULATE: 0/12. Predesignated refined-retrieval probes' initial confidence: L02=MEDIUM, L05=HIGH.

The formula-source diagnostic denominator is 13 rather than 12 because one clarification task also requires a KB formula. An exact formula span without a subsequent validated calculation is not counted as formula-source correctness.

`Domain-Matched Document Recall` uses the domain/source document set in the frozen catalog. `Relevant Chunk@K` and `Top-3 Relevant Precision` require a frozen gold page plus ≥60% lexical overlap with its gold span. These are conservative proxies, not exhaustive semantic relevance labels; alternate valid passages can be scored as misses. `Fact Extraction Recall` counts observable extracted versus digit-form inputs, capped at 1; `Unit Normalization` checks recorded canonical-unit fields. Neither proxy proves correct semantic variable binding, which is scored separately. `Refined Retrieval Recovery` applies only to the two predesignated probe tasks and requires a gold-page hit after a triggered refinement when the initial candidate set lacked it. If neither probe triggers refinement, recovery is not estimable rather than 0%.

### Category outcomes

| Category | n | Agent Goal Success | Agent Exact Accuracy |
|---|---:|---:|---:|
| clarification | 4 | 0.00% | 0.00% |
| direct_calculation | 10 | 0.00% | 0.00% |
| false_premise | 6 | 33.33% | 33.33% |
| figure | 3 | 0.00% | 0.00% |
| kb_calculation | 12 | 0.00% | 0.00% |
| literature | 14 | 7.14% | 7.14% |
| unsupported | 3 | 0.00% | 100.00% |
| user_formula_calculation | 4 | 0.00% | 0.00% |
| user_formula_simulation | 4 | 50.00% | 50.00% |

The three unsupported tasks were all judged correct safe refusals on final-text Exact Accuracy, but none passed the Agent's expected unsupported-intent/source-route gate. This explains the 100% versus 0% contrast rather than treating safe refusal as a content failure.

### Latency

| Track | Mean | Median | p95 |
|---|---:|---:|---:|
| Petroleum-RAG-Agent v11.1 | 16.45 s | 17.00 s | 35.20 s |
| Qwen3:8b closed-book | 2.13 s | 1.85 s | 3.93 s |
| OpenAI closed-book | 6.43 s | 5.51 s | 13.56 s |
| Qwen3:8b same-evidence | 1.87 s | 1.62 s | 3.56 s |
| OpenAI same-evidence | 5.91 s | 5.54 s | 11.95 s |

Agent mean stage timings (telemetry, overlapping/non-additive): parsing 0.00 s, planning 1.68 s, retrieval 5.72 s, LLM generation 6.84 s, calculation/simulation 2.69 s, Python 0.81 s, verification 6.42 s, evaluation 3.92 s, synthesis 1.85 s. Reranking and premise-grounding are not separately timed by the product telemetry and are included in overlapping retrieval/verification stages. Same-evidence latency excludes prior Agent retrieval.

## Statistical uncertainty

Paired bootstrap by valid task ID, 5000 resamples, seed 20261011, percentile 95% confidence intervals. The intervals reflect task sampling only, not uncertainty from one AI reviewer or corpus selection. Small-category percentages are exploratory.

| Paired contrast (percentage points) | Metric | 95% CI |
|---|---|---:|
| agent_minus_qwen_closed_book | goal_success | [-50.00, -20.00] |
| agent_minus_qwen_closed_book | exact_accuracy | [-45.00, -15.00] |
| agent_minus_qwen_closed_book | claim_coverage | [-52.50, -22.22] |
| agent_minus_qwen_closed_book | hallucination | [-45.00, -16.67] |
| agent_minus_qwen_closed_book | numeric_accuracy | [-82.36, -45.71] |
| agent_minus_openai_closed_book | goal_success | [-81.67, -56.67] |
| agent_minus_openai_closed_book | exact_accuracy | [-76.67, -51.67] |
| agent_minus_openai_closed_book | claim_coverage | [-72.50, -45.83] |
| agent_minus_openai_closed_book | hallucination | [5.00, 23.33] |
| agent_minus_openai_closed_book | numeric_accuracy | [-92.31, -65.00] |
| qwen_same_evidence_minus_qwen_closed_book | goal_success | [-5.00, 18.33] |
| qwen_same_evidence_minus_qwen_closed_book | exact_accuracy | [-5.00, 18.33] |
| qwen_same_evidence_minus_qwen_closed_book | claim_coverage | [3.89, 20.83] |
| qwen_same_evidence_minus_qwen_closed_book | hallucination | [-23.33, 6.67] |
| qwen_same_evidence_minus_qwen_closed_book | numeric_accuracy | [-16.13, 10.34] |
| openai_same_evidence_minus_openai_closed_book | goal_success | [-10.00, 10.00] |
| openai_same_evidence_minus_openai_closed_book | exact_accuracy | [-10.00, 10.00] |
| openai_same_evidence_minus_openai_closed_book | claim_coverage | [-5.83, 9.17] |
| openai_same_evidence_minus_openai_closed_book | hallucination | [0.00, 5.00] |
| openai_same_evidence_minus_openai_closed_book | numeric_accuracy | [-8.33, 8.57] |

Full per-system intervals and contrasts: `statistical_analysis.json`.

## Limitations

- Sixty curated tasks over an existing 12-PDF corpus (gold spans in 8 documents) do not represent all petroleum-engineering use cases or document quality.
- One AI reviewer can misclassify nuanced engineering/citation meaning; deterministic checks complement but do not eliminate this limitation.
- Figure baselines received text notes, not image pixels. Figure gold was visually inspected before freeze, but the semantic reviewer judged text claims/notes rather than raw image pixels; visual interpretation parity is limited.
- Formula, clarification, premise, figure, and refined-retrieval subgroups are small; one task changes percentages materially.
- Agent and baselines have intentionally different operational capabilities and Goal Success gates. Compare Exact Accuracy and Coverage alongside Goal Success.
- v3 exposed failure modes that informed v11/v11.1 development. v3 and v4 are not a same-test before/after comparison.

## Poster-safe conclusions

1. Agent Goal Success was 8.33%; closed-book Qwen and OpenAI were 43.33% and 78.33%. Paired Agent-minus-Qwen 95% CI was [-50.00, -20.00] percentage points. This is a frozen-v4 finding, not a v3→v4 same-test improvement claim.
2. Among 12 KB-formula tasks, exact spans were retrieved in 6 and the formula→CALCULATE transition occurred in 0. Formula source correctness was 0.00%; calculation provenance completeness was 17.65% on its applicable subset.
3. Direct calculations avoided retrieval in 9/10 cases, but actually entered CALCULATE in 5/10. False-premise handling was 33.33%; same-run completion was 0.00%. Small subgroup denominators limit precision.
4. Figure retrieval reached 100.00% across three tasks, but figure Exact Accuracy was 0.00%. Retrieving the figure note did not ensure a correct supported visual interpretation.
5. Agent hallucination was 13.33%, versus closed-book Qwen 45.00%; their paired difference 95% CI was [-45.00, -16.67] points. Refusals and empty answers must be considered alongside this rate; lower hallucination alone does not imply better task completion.
6. Same-evidence Qwen/OpenAI Goal Success was 50.00%/78.33%, compared with their closed-book 43.33%/78.33%. The baselines had no retrieval or tools. Differences are conditional on the Agent's actual captured evidence.
7. Agent median/p95 latency was 17.00 s/35.20 s; Qwen closed-book was 1.85 s/3.93 s.
