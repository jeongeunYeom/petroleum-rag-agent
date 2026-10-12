# Petroleum RAG Agent v18 — final independent paired poster evaluation

Frozen products: v17 `3c5f0fd1da77ac46cb8447ed13f9b8ad9b30d7c3`, v18 `740206d6de8e3be6cb4b21792b2c3429c65fcd6a`. Benchmark freeze `e91cdc25705766e40c11e98f045eb5344887aba9`; SHA256 `6913d38c697e00cc4601db3d53e3e4270350520600de0d9e9ac2fc25169e2b1f`. Same 24 exact questions, same 12-document / 18,976-chunk production KB, hybrid retrieval, web off. Integrity FINALIZED=true.

# Poster results tables

## A. Version effect

| Metric | V17 | V18 | V18 − V17 (95% CI) |
| --- | ---: | ---: | ---: |
| Goal Success | 25.0% | 25.0% | +0.0 pp [+0.0, +0.0] |
| Claim Coverage | 39.9% | 39.9% | +0.0 pp [+0.0, +0.0] |
| Hallucination-free | 95.8% | 95.8% | +0.0 pp [+0.0, +0.0] |
| Numerical Accuracy | 30.0% | 30.0% | +0.0 pp [+0.0, +0.0] |

## B. Same base model

| Metric | qwen3:8b Closed-book | V18 Agent | Agent − Qwen (95% CI) |
| --- | ---: | ---: | ---: |
| Goal Success | 37.5% | 25.0% | -12.5 pp [-33.3, +8.3] |
| Claim Coverage | 63.2% | 39.9% | -23.3 pp [-45.8, +0.0] |
| Hallucination-free | 45.8% | 95.8% | +50.0 pp [+29.2, +70.8] |
| Numerical Accuracy | 90.0% | 30.0% | -60.0 pp [-90.0, -30.0] |

## C. Reference

| System | Goal Success | Claim Coverage | Hallucination-free | Numerical Accuracy | Median latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| qwen3:8b (Closed-book) | 37.5% | 63.2% | 45.8% | 90.0% | 1.20s |
| Petroleum RAG Agent v17 | 25.0% | 39.9% | 95.8% | 30.0% | 23.26s |
| Petroleum RAG Agent v18 | 25.0% | 39.9% | 95.8% | 30.0% | 14.40s |
| GPT-5.4 mini (Closed-book reference) | 54.2% | 77.4% | 66.7% | 100.0% | 2.08s |

## Poster-safe diagnostic callouts

- Unnecessary refusals: v17 12/22 answerable; v18 12/22.
- Calculation executions: v17 3; v18 3.
- Numerical Accuracy: v17 30.0%; v18 30.0% (n=10).
- V18 KB formula retrieve→calculate: 0/3.
- V18 relevant evidence but failed: 11/14.
- V18 verified support but refused: 2 tasks.

## Category and pipeline diagnostics

Knowledge n=6; Reasoning n=4; Calculation n=10; Safety n=4. See `poster_category_metrics.csv`. V18 numeric pipeline: {'n': 10, 'correct_route': 3, 'operands_complete': 7, 'formula_ready': 4, 'formula_source_verified': 1, 'calculation_executed': 3, 'calculation_validated': 3, 'numeric_correct': 3}. V18 KB formula pipeline: {'n': 3, 'retrieval_success': 3, 'correct_span': 1, 'retrieve_to_calculate': 0, 'numeric_correct': 0}. Cross-language Korean/English evidence: {'n': 8, 'v17_success': 2, 'v18_success': 2, 'v17_unnecessary_refusals': 5, 'v18_unnecessary_refusals': 5}. Citation diagnostics: {'v17_agent': {'bearing_responses': 10, 'link_count': 27, 'semantic_support_true': 8, 'exact_span_validation_passes': 10}, 'v18_agent': {'bearing_responses': 10, 'link_count': 27, 'semantic_support_true': 8, 'exact_span_validation_passes': 10}}.

### Multi-claim reasoning (claim scores are external adjudication)

| Task | Required claims | V17 detected/supported | V18 detected/supported | External coverage V17/V18 |
| --- | ---: | ---: | ---: | ---: |
| V18P-007 | 2 | 5/4 | 5/4 | 50.0% / 50.0% |
| V18P-008 | 2 | 2/0 | 2/0 | 0.0% / 0.0% |
| V18P-009 | 3 | 5/5 | 5/5 | 100.0% / 100.0% |
| V18P-010 | 3 | 2/2 | 2/2 | 83.3% / 83.3% |

### V18 unsuccessful tasks

| Task | Category | V17 success | V18 error labels | V18 status |
| --- | --- | ---: | --- | --- |
| V18P-001 | knowledge_qa | False | unsupported_claim | completed |
| V18P-002 | knowledge_qa | False | omission | completed |
| V18P-003 | knowledge_qa | False | incorrect_refusal, omission | stopped |
| V18P-004 | knowledge_qa | False | incorrect_refusal, omission | stopped |
| V18P-006 | knowledge_qa | False | omission | completed |
| V18P-007 | multi_claim_reasoning | False | omission | stopped |
| V18P-008 | multi_claim_reasoning | False | omission | stopped |
| V18P-010 | multi_claim_reasoning | False | omission | completed |
| V18P-011 | direct_calculation | False | incorrect_refusal, omission | stopped |
| V18P-012 | direct_calculation | False | incorrect_refusal, omission | stopped |
| V18P-013 | direct_calculation | False | omission, incorrect_refusal | waiting_for_user_input |
| V18P-017 | user_formula | False | omission, incorrect_refusal | waiting_for_user_input |
| V18P-018 | kb_formula | False | incorrect_refusal, omission | stopped |
| V18P-019 | kb_formula | False | incorrect_refusal, omission | stopped |
| V18P-020 | kb_formula | False | omission, incorrect_refusal | waiting_for_user_input |
| V18P-021 | false_premise | False | incorrect_refusal, omission | stopped |
| V18P-022 | false_premise | False | omission | completed |
| V18P-023 | unanswerable | False | incorrect_refusal, omission | stopped |

## Latency and cost

| System | Mean | Median | P95 |
| --- | ---: | ---: | ---: |
| qwen3:8b (Closed-book) | 2.89s | 1.20s | 7.17s |
| Petroleum RAG Agent v17 | 21.40s | 23.26s | 46.34s |
| Petroleum RAG Agent v18 | 17.17s | 14.40s | 31.08s |
| GPT-5.4 mini (Closed-book reference) | 2.57s | 2.08s | 5.54s |

Stage means (seconds; stages may overlap and are not summed into total): {"v17_agent": {"planning_seconds": 0.5050670416666666, "retrieval_seconds": 6.566613416666667, "llm_generation_seconds": 11.928687083333335, "python_seconds": 0.01734933333333333, "verification_seconds": 11.985643083333335, "calculation_seconds": 0.0, "synthesis_seconds": 3.028771375}, "v18_agent": {"planning_seconds": 0.5149883333333333, "retrieval_seconds": 6.696895708333333, "llm_generation_seconds": 4.9551079583333335, "python_seconds": 0.016590625, "verification_seconds": 6.217005708333333, "calculation_seconds": 0.0, "synthesis_seconds": 1.173611125}}

GPT reference: {'model': 'gpt-5.4-mini-2026-03-17', 'calls': 24, 'input_tokens': 1760, 'output_tokens': 5904, 'cached_tokens': 0, 'estimated_list_price_usd': 0.02789, 'pricing_source': 'https://developers.openai.com/api/docs/models/gpt-5.4-mini'}. Judge: {'model': 'gpt-5.4-2026-03-05', 'calls': 24, 'input_tokens': 73146, 'output_tokens': 10450, 'cached_tokens': 0, 'estimated_list_price_usd': 0.33962, 'pricing_source': 'https://developers.openai.com/api/docs/models/gpt-5.4'}. Local inference; hardware/electricity cost not estimated. List-price sources: [mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini) and [judge](https://developers.openai.com/api/docs/models/gpt-5.4).

## Separate same-run resume diagnostic

{'n': 3, 'passed': 0, 'same_run_preserved': 2, 'repeated_clarification_count': 1}. Its 3 tasks are excluded from all primary denominators; see `poster_resume_suite.csv`.

## Poster-safe conclusions

1. V18 and v17 had identical Goal Success on all 24 paired tasks (difference 0.0 pp; sample bootstrap CI [0.0, 0.0]); this sample shows no version gain and does not establish population equivalence.
2. The same-base Goal Success comparison does not establish an Agent advantage at 95% CI on this sample.
3. In KB formula tasks, v18 retrieved the exact formula span in 1/3 and made a retrieve→calculate transition in 0/3. This isolates remaining retrieval-versus-orchestration failures without assuming a positive result.

## Limitations

Only 24 primary tasks and 10 numeric tasks; paired bootstrap intervals remain wide. The semantic adjudication is one AI reviewer, not human review. Retrieved-evidence relevance and citation support are reviewer labels; deterministic numeric checks and raw traces are separate. V17 and V18 were run sequentially; latency differences may reflect cache/order effects and are not a causal speed claim. Seven reviewer records had material-error labels inconsistent with their hallucination-free flag; derived scoring follows the frozen error-label policy. Some frozen domain labels for arithmetic tasks are broad legacy metadata labels and are not used in scoring. No post-result tuning was performed.
