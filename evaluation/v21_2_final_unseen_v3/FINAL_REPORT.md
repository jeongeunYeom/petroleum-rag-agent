# V21.2 final unseen V3 evaluation

V21.2 was evaluated once on a newly authored V3 benchmark frozen after the product freeze and before any evaluated product call. Generation attempts were not retried. Technical execution failures were handled according to a predeclared deterministic missing-response scoring rule.

- FINALIZED: **true**
- Frozen product: `f5182b8ae2907452e1c53373055e66c5182c9b90`; freeze commit: `b16c3e78a52b1daf648064533fdb6a0e0ae83732`
- Benchmark SHA256: `a720ff0282038fd89a11f94dc6ce435cfe8fcda39e16cffa1cef82d171cca6a5`; rubric SHA256: `3e50b3faf93041a001b6741a05df57fb038d2e87e7bb158784b1fb76d65de4d2`
- Primary tasks: 36; numeric denominator: 16; Korean questions with English source: 12; multi-goal: 6; independent resume probes: 4.
- Excluded prior document/page pairs: 352; unique primary gold source pages: 23.
- Novelty screen: character-four-gram Jaccard maximum 0.272 (< 0.45) and multilingual BGE-M3 cosine maximum 0.730 (< 0.90). V2 question text was processed only mechanically.

## Headline (all 36; numeric 16)

| System | Goal Success | Claim Coverage | Hallucination-free | Numerical Accuracy | Technical failures | Median latency | P95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3:8b Closed-book | 33.3% | 66.0% | 58.3% | 68.8% | 0/36 | 1.5s | 3.3s |
| V21.2 Agent | 5.6% | 17.4% | 83.3% | 6.2% | 0/36 | 19.3s | 70.3s |
| GPT Reference | 50.0% | 79.9% | 86.1% | 93.8% | 1/36 | 2.6s | 7.2s |

## Paired differences (V21.2 minus baseline)

| Baseline | Metric | Delta | 95% CI | Interpretation |
| --- | --- | ---: | --- | --- |
| Qwen3:8b Closed-book | goal_success | -27.8% | [-41.7%, -13.9%] | 95% CI excludes zero |
| Qwen3:8b Closed-book | claim_coverage | -48.6% | [-63.2%, -34.0%] | 95% CI excludes zero |
| Qwen3:8b Closed-book | hallucination_free | +25.0% | [+5.6%, +44.4%] | 95% CI excludes zero |
| Qwen3:8b Closed-book | numeric_correct | -62.5% | [-87.5%, -37.5%] | 95% CI excludes zero |
| GPT Reference | goal_success | -44.4% | [-61.1%, -27.8%] | 95% CI excludes zero |
| GPT Reference | claim_coverage | -62.5% | [-77.3%, -45.6%] | 95% CI excludes zero |
| GPT Reference | hallucination_free | -2.8% | [-22.2%, +13.9%] | descriptive difference; superiority not established |
| GPT Reference | numeric_correct | -87.5% | [-100.0%, -68.8%] | 95% CI excludes zero |

## Agent diagnostics

- calculation executed /16: 3/16
- calculation validated /16: 3/16
- numeric correct /16: 1/16
- formula source retrieved /6: 5/6
- correct formula span /6: 5/6
- retrieve to calculate /6: 1/6
- KB-formula numeric correct /6: 0/6
- KB-formula provenance correct /6: 1/6
- calculation provenance complete /16: 3/16
- citation semantic support / source tasks: 3/26
- cross-language Goal Success /12: 0/12
- multi-goal Goal Success /6: 0/6
- unnecessary refusals: 23
- resume final completion /4: 0/4

## Category Goal Success

| Category | Qwen | V21.2 | GPT |
| --- | ---: | ---: | ---: |
| direct_calculation | 66.7% | 0.0% | 100.0% |
| false_premise | 66.7% | 0.0% | 66.7% |
| kb_formula | 0.0% | 0.0% | 0.0% |
| knowledge_qa | 12.5% | 12.5% | 37.5% |
| multi_claim_reasoning | 0.0% | 0.0% | 16.7% |
| unanswerable | 33.3% | 0.0% | 66.7% |
| user_formula | 100.0% | 25.0% | 100.0% |

## Protocol and limitations

The baseline systems had no KB, tools, or Python. The frozen Goal Success rubric requires a literal formula source and validated calculation path for KB-formula tasks; this requirement is not satisfiable by a closed-book system and should be considered when interpreting that category. Numerical Accuracy separately measures the final values.
Technical failures are retained in the 36-task denominators as no responses: Goal Success and Claim Coverage 0, numeric incorrect where applicable, Hallucination-free true, not a refusal. A systemic infrastructure failure threshold of >20% per required system was fixed before execution.
Semantic correctness and citation support were assessed by one blinded AI reviewer per completed answer, not human review. The exact judge was gpt-5.4-2026-03-05 at temperature 0. Its judgments may have residual error, particularly for subtle engineering interpretation. Structured numeric and provenance gates were applied deterministically afterward.
The 4 resume probes are diagnostic and excluded from the primary denominator. The previous V2 evaluation is observed and was not reused as a final unseen estimate.

Integrity: product unchanged=True; benchmark unchanged=True; rubric unchanged=True; KB unchanged=True; one attempt per system/task=True; generation retries=0.

## Poster-safe conclusions

- This estimate describes only the newly frozen 36-task V3 corpus; V2 is not an independent final benchmark.
- Technical failures were retained as predeclared missing responses rather than repaired or excluded.
- Qwen exceeded V21.2 on Goal Success on this corpus, with a paired 95% CI below zero.
