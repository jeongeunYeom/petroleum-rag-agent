# Final pilot results

Scoring caveat: Hallucination-free is the recorded single-judge conservative classification and includes incorrect refusals/insufficiency claims. It is not a fabrication-only rate; see SCORING_AUDIT.md before publication.

| System | Goal Success | Claim Coverage | Hallucination-free | Numerical Accuracy | Median latency (s) |
|---|---|---|---|---|---|
| Petroleum RAG Agent | 20.83% | 30.90% | 37.50% | 20.00% | 20.65 |
| GPT-5.4 mini (Closed-book) | 79.17% | 93.06% | 87.50% | 100.00% | 2.36 |

| Category | Agent GS | GPT GS |
|---|---|---|
| Knowledge | 33.3% | 66.7% |
| Reasoning | 25.0% | 25.0% |
| Calculation | 10.0% | 100.0% |
| Safety | 25.0% | 100.0% |

The closed-book baseline was at least as strong on every primary metric in this independent pilot. Goal Success was 20.8% for Agent and 79.2% for the baseline. These results do not establish population superiority or a causal improvement over earlier, different pilot sets.
