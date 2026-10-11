# Performance comparison using the same base model

| Metric | qwen3:8b closed-book | Petroleum RAG Agent | Agent − Qwen | Paired 95% CI |
|---|---:|---:|---:|---:|
| Goal Success | 45.8% | 12.5% | -33.3 pp | [-54.2, -12.5] pp |
| Claim Coverage | 68.8% | 24.7% | -44.1 pp | [-61.5, -26.0] pp |
| Hallucination-free | 50.0% | 87.5% | +37.5 pp | [+20.8, +58.3] pp |
| Numerical Accuracy | 100.0% | 20.0% | -80.0 pp | [-100.0, -50.0] pp |

## External reference

| Metric | Petroleum RAG Agent | GPT-5.4 mini closed-book (reference) |
|---|---:|---:|
| Goal Success | 12.5% | 70.8% |
| Claim Coverage | 24.7% | 86.8% |
| Hallucination-free | 87.5% | 75.0% |
| Numerical Accuracy | 20.0% | 100.0% |

## Optional combined layout

| Metric | qwen3:8b closed-book | Petroleum RAG Agent | GPT reference |
|---|---:|---:|---:|
| Goal Success | 45.8% | 12.5% | 70.8% |
| Claim Coverage | 68.8% | 24.7% | 86.8% |
| Hallucination-free | 50.0% | 87.5% | 75.0% |
| Numerical Accuracy | 100.0% | 20.0% | 100.0% |

24 tasks; numeric denominator 10. GPT is not a same-base-model ablation. Percentage-point CI: paired bootstrap, 10,000 resamples, seed 16161012.
