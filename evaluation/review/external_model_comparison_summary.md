# External model comparison summary

Semantic results were produced by a **single AI-assisted semantic reviewer** using the frozen rubric.
The Petroleum Agent was not re-run. Qwen ran locally on the RTX 3090; GPT/Gemini API runs are unavailable because keys were absent.

| System | Condition | N | Exact | Partial+ | Coverage | Hallucination | Eng. error | Median s | P95 s | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| qwen2.5vl:7b (qwen) | figure | 9 | 55.56% | 88.89% | 72.41% | 22.22% | 0.00% | 1.677871 | 6.698141 | complete |
| qwen3:8b (qwen) | closed_book | 50 | 32.00% | 76.00% | 60.99% | 34.00% | 20.00% | 2.2103625 | 4.647997 | complete |
| qwen3:8b (qwen) | same_evidence | 50 | 70.00% | 96.00% | 88.65% | 4.00% | 14.00% | 2.186213 | 3.377959 | complete |
| Petroleum Agent | petroleum_agent_text50 | 50 | 48.00% | 68.00% | 59.57% | 10.00% | 10.00% | 23.716312000000002 | 87.533628 | complete |
| Petroleum Agent | petroleum_agent_figure_usable | 9 | 22.22% | 66.67% | 48.28% | 44.44% | 33.33% | 58.594318 | 154.353609 | complete |
| gpt-6-sol (openai) | closed_book | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | not_run_missing_api_key |
| gpt-6-sol (openai) | same_evidence | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | not_run_missing_api_key |
| gpt-6-sol (openai) | figure | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | not_run_missing_api_key |
| gemini-3.8-flash (gemini) | closed_book | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | not_run_missing_api_key |
| gemini-3.8-flash (gemini) | same_evidence | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | not_run_missing_api_key |
| gemini-3.8-flash (gemini) | figure | 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | not_run_missing_api_key |

## Interpretation limits

- OpenAI and Gemini were not executed because their API-key environment variables were absent.
- Semantic grading used one AI-assisted reviewer, not a human panel.
- Petroleum Agent figure answers may include retrieved text and validator/repair context; the direct vision run used only question plus image.
- Latency compares local RTX 3090 execution with remote APIs only when cloud runs are available and is not pure inference latency.
