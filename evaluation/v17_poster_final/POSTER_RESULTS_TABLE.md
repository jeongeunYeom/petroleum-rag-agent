# Performance comparison using the same base model

| Metric | qwen3:8b closed-book | Petroleum RAG Agent | Agent − Qwen | Paired 95% CI |
|---|---:|---:|---:|---:|
| Goal Success | 37.5% | 16.7% | -20.8 pp | [-45.8, +4.2] pp |
| Claim Coverage | 62.5% | 30.9% | -31.6 pp | [-54.2, -8.3] pp |
| Hallucination-free | 62.5% | 100.0% | +37.5 pp | [+20.8, +58.3] pp |
| Numerical Accuracy | 80.0% | 10.0% | -70.0 pp | [-100.0, -40.0] pp |

## External reference

| Metric | Petroleum RAG Agent | GPT-5.4 mini closed-book (reference) |
|---|---:|---:|
| Goal Success | 16.7% | 45.8% |
| Claim Coverage | 30.9% | 88.2% |
| Hallucination-free | 100.0% | 83.3% |
| Numerical Accuracy | 10.0% | 90.0% |

## Optional combined layout

| Metric | qwen3:8b closed-book | Petroleum RAG Agent | GPT reference |
|---|---:|---:|---:|
| Goal Success | 37.5% | 16.7% | 45.8% |
| Claim Coverage | 62.5% | 30.9% | 88.2% |
| Hallucination-free | 62.5% | 100.0% | 83.3% |
| Numerical Accuracy | 80.0% | 10.0% | 90.0% |

## Category Goal Success

| Category | N | qwen3:8b | Petroleum RAG Agent | GPT reference |
|---|---:|---:|---:|---:|
| Knowledge | 6 | 16.7% | 50.0% | 33.3% |
| Reasoning | 4 | 0.0% | 0.0% | 0.0% |
| Calculation | 10 | 70.0% | 10.0% | 80.0% |
| Safety | 4 | 25.0% | 0.0% | 25.0% |

24 tasks; numeric denominator 10. GPT is not a same-base-model ablation. Percentage-point CI: paired bootstrap, 10,000 resamples, seed 17172026.
