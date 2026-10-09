# External model comparison summary

Semantic results were produced by a **single AI-assisted semantic reviewer** using the frozen rubric.
The Petroleum Agent was not re-run. Qwen ran locally on the RTX 3090; completed GPT/Gemini conditions used remote APIs.

| System | Condition | N | Exact | Partial+ | Coverage | Hallucination | Eng. error | Median s | P95 s | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| gemini-3.8-flash (gemini) | closed_book | 7 | 71.43% | 100.00% | 94.74% | 0.00% | 14.29% | 17.009289 | 51.237002 | partial_api_errors |
| gpt-6.1-sol (openai) | closed_book | 50 | 62.00% | 88.00% | 80.85% | 2.00% | 10.00% | 13.1938305 | 26.21281 | complete |
| gpt-6.1-sol (openai) | figure | 9 | 66.67% | 66.67% | 68.97% | 22.22% | 0.00% | 10.00711 | 15.139913 | complete_usable_subset |
| gpt-6.1-sol (openai) | same_evidence | 50 | 74.00% | 96.00% | 92.91% | 0.00% | 14.00% | 9.482716499999999 | 14.588641 | complete |
| qwen2.5vl:7b (qwen) | figure | 9 | 55.56% | 88.89% | 72.41% | 22.22% | 0.00% | 1.677871 | 6.698141 | complete_usable_subset |
| qwen3:8b (qwen) | closed_book | 50 | 32.00% | 76.00% | 60.99% | 34.00% | 20.00% | 2.2103625 | 4.647997 | complete |
| qwen3:8b (qwen) | same_evidence | 50 | 70.00% | 96.00% | 88.65% | 4.00% | 14.00% | 2.186213 | 3.377959 | complete |
| Petroleum Agent | petroleum_agent_text50 | 50 | 48.00% | 68.00% | 59.57% | 10.00% | 10.00% | 23.716312000000002 | 87.533628 | complete |
| Petroleum Agent | petroleum_agent_figure_usable | 9 | 22.22% | 66.67% | 48.28% | 44.44% | 33.33% | 58.594318 | 154.353609 | complete |
| gemini-3.8-flash (gemini) | same_evidence | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | not_run_rate_limit_or_quota |
| gemini-3.8-flash (gemini) | figure | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | not_run_rate_limit_or_quota |

## Key deltas

- Petroleum Agent minus qwen3:8b (qwen) closed-book exact: +16.00 percentage points
- qwen3:8b (qwen) same-evidence minus closed-book exact: +38.00 percentage points
- Petroleum Agent minus gpt-6.1-sol (openai) closed-book exact: -14.00 percentage points
- gpt-6.1-sol (openai) same-evidence minus closed-book exact: +12.00 percentage points
- Petroleum Agent minus gemini-3.8-flash (gemini) closed-book exact: -23.43 percentage points
- gemini-3.8-flash (gemini) same-evidence minus closed-book exact: N/A

## Interpretation limits

- Unavailable provider conditions: gemini/same_evidence, gemini/figure.
- Petroleum Agent is a system-level baseline with retrieval, validation, and repair; direct closed-book models use only their internal knowledge.
- Same-evidence results compare generation and reasoning with retrieval differences removed.
- Semantic grading used one AI-assisted reviewer, not a human panel.
- Petroleum Agent figure answers may include retrieved text and validator/repair context; the direct vision run used only question plus image.
- Latency compares local RTX 3090 execution with remote APIs only when cloud runs are available and is not pure inference latency.
- Configured API models are gpt-6.1-sol and gemini-3.8-flash; evaluation date is 2026-10-02.
