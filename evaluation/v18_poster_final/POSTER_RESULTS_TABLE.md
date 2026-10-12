# Poster results tables

## A. Version effect

| Metric | V17 | V18 | V18 − V17 (95% CI) |
| --- | ---: | ---: | ---: |
| Goal Success | 25.0% | 25.0% | +0.0 pp [+0.0, +0.0] |
| Claim Coverage | 39.9% | 39.9% | +0.0 pp [+0.0, +0.0] |
| Hallucination-free | 100.0% | 100.0% | +0.0 pp [+0.0, +0.0] |
| Numerical Accuracy | 30.0% | 30.0% | +0.0 pp [+0.0, +0.0] |

## B. Same base model

| Metric | qwen3:8b Closed-book | V18 Agent | Agent − Qwen (95% CI) |
| --- | ---: | ---: | ---: |
| Goal Success | 37.5% | 25.0% | -12.5 pp [-33.3, +8.3] |
| Claim Coverage | 63.2% | 39.9% | -23.3 pp [-45.8, +0.0] |
| Hallucination-free | 54.2% | 100.0% | +45.8 pp [+25.0, +66.7] |
| Numerical Accuracy | 90.0% | 30.0% | -60.0 pp [-90.0, -30.0] |

## C. Reference

| System | Goal Success | Claim Coverage | Hallucination-free | Numerical Accuracy | Median latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| qwen3:8b (Closed-book) | 37.5% | 63.2% | 54.2% | 90.0% | 1.20s |
| Petroleum RAG Agent v17 | 25.0% | 39.9% | 100.0% | 30.0% | 23.26s |
| Petroleum RAG Agent v18 | 25.0% | 39.9% | 100.0% | 30.0% | 14.40s |
| GPT-5.4 mini (Closed-book reference) | 54.2% | 77.4% | 79.2% | 100.0% | 2.08s |
