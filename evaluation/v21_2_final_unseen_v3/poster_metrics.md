# V21.2 final unseen V3 poster metrics

| Metric | Qwen3:8b Closed-book | V21.2 Agent | GPT Reference |
| --- | ---: | ---: | ---: |
| Goal Success | 33.3% | 5.6% | 50.0% |
| Claim Coverage | 66.0% | 17.4% | 79.9% |
| Hallucination Free | 58.3% | 83.3% | 86.1% |
| Numeric Accuracy | 68.8% | 6.2% | 93.8% |

## V21.2 minus Qwen (paired bootstrap 95% CI)

| Metric | Delta | 95% CI |
| --- | ---: | --- |
| Goal Success | -27.8% | [-41.7%, -13.9%] |
| Claim Coverage | -48.6% | [-63.2%, -34.0%] |
| Hallucination Free | +25.0% | [+5.6%, +44.4%] |
| Numeric Correct | -62.5% | [-87.5%, -37.5%] |

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

Technical failures: Qwen3:8b Closed-book 0/36, V21.2 Agent 0/36, GPT Reference 1/36.

Single-reviewer AI-assisted semantic adjudication; not human review. All technical failures remain in the denominators.
