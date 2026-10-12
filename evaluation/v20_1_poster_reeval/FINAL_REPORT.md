# Petroleum RAG Agent V20.1 — frozen paired poster re-evaluation

V20.1 was evaluated by frozen paired re-evaluation on the same 24-task benchmark previously used for V18. It is therefore a controlled version comparison, not a new unseen held-out benchmark.

Product SHA `c82ef66070695e6a13f7a6f3eb35f2714e4e5811`; old frozen benchmark SHA256 `6913d38c697e00cc4601db3d53e3e4270350520600de0d9e9ac2fc25169e2b1f`; policy SHA256 `32da6b7220c86a1872910d159418412618a70616a0976aaf078277d388af77f9`. Exact local qwen3:8b, hybrid retrieval, 12-document/18,976-chunk KB, web off. Integrity FINALIZED=true.

# Frozen paired poster metrics

| Metric | qwen3:8b Closed-book | V18 Agent | V20.1 Agent |
| --- | ---: | ---: | ---: |
| Goal Success | 37.5% | 25.0% | 20.8% |
| Claim Coverage | 63.2% | 39.9% | 39.6% |
| Hallucination-free | 45.8% | 95.8% | 91.7% |
| Numerical Accuracy | 90.0% | 30.0% | 30.0% |

## V20.1 − V18

| Metric | Difference | Paired 95% CI |
| --- | ---: | ---: |
| Goal Success | -4.2 pp | [-12.5, +0.0] pp |
| Claim Coverage | -0.3 pp | [-4.2, +3.1] pp |
| Hallucination-free | -4.2 pp | [-12.5, +0.0] pp |
| Numerical Accuracy | +0.0 pp | [+0.0, +0.0] pp |

## V20.1 − Qwen

| Metric | Difference | Paired 95% CI |
| --- | ---: | ---: |
| Goal Success | -16.7 pp | [-37.5, +0.0] pp |
| Claim Coverage | -23.6 pp | [-45.8, -0.7] pp |
| Hallucination-free | +45.8 pp | [+25.0, +66.7] pp |
| Numerical Accuracy | -60.0 pp | [-90.0, -30.0] pp |

## Diagnostics

Numeric pipeline (n=10): {"n": 10, "correct_route": 3, "operands_complete": 5, "formula_ready": 4, "formula_source_verified": 3, "calculation_executed": 3, "calculation_validated": 3, "numeric_correct": 3}.

KB formula pipeline (n=3): {"n": 3, "retrieval_success": 3, "correct_span": 1, "retrieve_to_calculate": 0, "numeric_correct": 0}.

Unnecessary refusals: {"v18_agent": {"count": 12, "rate_answerable": 0.5454545454545454, "rate_all": 0.5}, "v20_1_agent": {"count": 11, "rate_answerable": 0.5, "rate_all": 0.4583333333333333}}.

Relevant evidence and answer conversion: {"relevant": 13, "relevant_but_failed": 11, "relevant_to_non_refusal": 9, "relevant_to_success": 2, "verified_support_but_refused": 2}.

Cross-language: {"n": 8, "success": 1, "unnecessary_refusals": 4}. Citation: {"bearing_responses": 11, "link_count": 29, "semantic_support_true": 8, "exact_span_validation_passes": 11}.

## V20.1 unsuccessful tasks

| Task | Category | V18 success | V20.1 status | Error labels |
| --- | --- | ---: | --- | --- |
| V18P-001 | knowledge_qa | False | completed | unsupported_claim |
| V18P-002 | knowledge_qa | False | completed | omission |
| V18P-003 | knowledge_qa | False | stopped | incorrect_refusal, omission |
| V18P-004 | knowledge_qa | False | stopped | incorrect_refusal, omission |
| V18P-006 | knowledge_qa | False | completed | omission |
| V18P-007 | multi_claim_reasoning | False | stopped | omission |
| V18P-008 | multi_claim_reasoning | False | stopped | incorrect_refusal, omission |
| V18P-009 | multi_claim_reasoning | True | stopped | incorrect_refusal, omission |
| V18P-010 | multi_claim_reasoning | False | completed | omission |
| V18P-011 | direct_calculation | False | stopped | incorrect_refusal, omission |
| V18P-012 | direct_calculation | False | stopped | incorrect_refusal, omission |
| V18P-013 | direct_calculation | False | waiting_for_user_input | omission, incorrect_refusal |
| V18P-017 | user_formula | False | waiting_for_user_input | omission, incorrect_refusal |
| V18P-018 | kb_formula | False | waiting_for_user_input | omission, incorrect_refusal |
| V18P-019 | kb_formula | False | waiting_for_user_input | omission, incorrect_refusal |
| V18P-020 | kb_formula | False | waiting_for_user_input | omission, incorrect_refusal |
| V18P-021 | false_premise | False | stopped | omission |
| V18P-022 | false_premise | False | completed | omission |
| V18P-023 | unanswerable | False | stopped | incorrect_refusal, omission |

## Latency

| System | Mean | Median | P95 |
| --- | ---: | ---: | ---: |
| qwen_closed_book | 2.89s | 1.20s | 7.17s |
| v18_agent | 17.17s | 14.40s | 31.08s |
| v20_1_agent | 28.60s | 20.31s | 87.07s |

Stage means (seconds; stages may overlap and are not summed into total): {"planning_seconds": 0.56038075, "retrieval_seconds": 10.097246375, "llm_generation_seconds": 10.075689166666667, "python_seconds": 0.020201125, "verification_seconds": 13.737913749999999, "calculation_seconds": 0.0, "synthesis_seconds": 2.3173635}

## Separate same-run resume diagnostic

{"n": 3, "passed": 0, "same_run_preserved": 2, "repeated_clarification_count": 1}. Three probes are excluded from all primary denominators.

## Poster-safe conclusions

1. Goal Success differed from V18 by -4.2 pp, but the paired 95% CI includes zero.
2. Numerical Accuracy differed from V18 by +0.0 pp, but the paired 95% CI includes zero.
3. Goal Success differed from Qwen closed-book by -16.7 pp, but the paired 95% CI includes zero.

## Limitations

This unchanged 24-task set was previously used for V18, so it is not unseen for V20.1. Numerical Accuracy has only ten tasks and KB formula diagnostics only three. Semantic adjudication used one AI reviewer, not human review. Agent runs were sequential; latency may reflect cache/order effects and is not a causal speed claim. No benchmark, rubric, product, or KB changes were made after results.

**KEEP EXISTING POSTER METRICS**
