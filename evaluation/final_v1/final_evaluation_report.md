# Final Petroleum-RAG-Agent evaluation, frozen v1

## Provenance and design

- Evaluated product: merged `main` at `fcd89e6e93fc866f4a237ee13c7910dcedac44c3`; evaluation branch only, product code unchanged.
- Frozen benchmark SHA-256: `03ea4db7b7aa91a886ee454e2c7ed45c22d31bff84b9e4bb447e030ab376c89f`; freeze commit `a88fdc4a8e57e46c9f4775e8a3e07fcbb5360f2c`.
- Frozen tasks: 50; invalid: 1; valid: 49. Invalid records are preserved in `invalid_tasks.json`, not silently revised.
- Actual main models: Agent and local closed-book `qwen3:8b`; OpenAI `gpt-5.4-mini-2026-03-17`; semantic reviewer `gpt-5.4-2026-03-05`.
- Agent used autonomous `POST /api/research/goal-runs/from-message`, local Qwen3:8b, `hybrid` retrieval, 12-document/18,976-chunk ChromaDB, web disabled, Python as product policy allows. Four clarification tasks had one prewritten reply and same-run resume attempted.
- All baselines were one-shot, no tools or web. Track A closed-book models saw only the question. Track B received the *Agent's captured KB/FIG text evidence* for each identical question; this does not independently evaluate their retrieval. Figure pixels were not supplied to the text baselines, only retrieved figure notes.
- Temperature was zero where accepted; Qwen additionally used seed 42. Runs were sequential by system, not randomized in time. No output-driven product or benchmark tuning.
- Scoring combines deterministic numeric/unit/action/provenance checks, structured expected claims, and **single-reviewer AI-assisted semantic adjudication** (`gpt-5.4-2026-03-05`, prompt `final-v1-reviewer-1`). This is not human review. The reviewer saw anonymized system labels and source spans; all raw reviews are retained.

## Track A — End-to-End Product Comparison

| System | N | Goal success | Exact | Claim coverage | Hallucination | Numeric | Citation ID | Median s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| agent | 49 | 8.2% | 16.3% | 36.2% | 34.7% | 22.2% | 78.0% | 25.29 |
| qwen_closed_book | 49 | 22.4% | 22.4% | 52.5% | 57.1% | 33.3% | N/A | 1.09 |
| openai_closed_book | 49 | 57.1% | 57.1% | 84.1% | 24.5% | 55.6% | N/A | 2.62 |

These are *not equal-information conditions*: only the Agent had retrieval and tools. Closed-book citation/retrieval metrics are N/A, not zero.

## Track B — Same-Evidence Comparison

| System | N | Goal success | Exact | Claim coverage | Hallucination | Numeric | Citation ID | Median s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| agent | 49 | 8.2% | 16.3% | 36.2% | 34.7% | 22.2% | 78.0% | 25.29 |
| qwen_same_evidence | 49 | 36.7% | 36.7% | 71.8% | 46.9% | 44.4% | 71.8% | 1.77 |
| openai_same_evidence | 49 | 73.5% | 75.5% | 94.3% | 6.1% | 66.7% | 97.7% | 2.00 |

The Agent row is the identical product output from Track A, not a second Agent run. The supplied evidence is whatever the Agent actually retrieved, including retrieval misses.

## Supplementary Gemini evaluation — incomplete due to provider rate limiting

- Status: `EXTERNAL_PROVIDER_BLOCKED`; model ID: `gemini-2.5-flash`.
- Attempted unique tasks: 42/50; completed unique tasks: 41/50.
- The earlier blocked snapshot had 20 completed tasks; 21 additional tasks were captured before the next 429. All 41 successful files remain untouched.
- HTTP 429 observed: True. Earlier successful raw responses and error history are preserved.
- Gemini is excluded from the 49-task main denominator, all performance tables, bootstrap comparisons, and ranking. No Gemini performance rate is calculated.

## Secondary quality and latency measures

| System | Unsupported claims | Contradictions | Safe refusal | False premise | Unit | Formula | Citation semantic | Mean s | p95 s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| agent | 36.7% | 20.4% | 100.0% | 0.0% | 40.0% | 71.4% | 50.4% | 34.39 | 80.96 |
| qwen_closed_book | 59.2% | 42.9% | 100.0% | 33.3% | 66.7% | 71.4% | N/A | 1.36 | 3.03 |
| openai_closed_book | 32.7% | 4.1% | 100.0% | 100.0% | 80.0% | 94.1% | N/A | 2.80 | 5.16 |
| qwen_same_evidence | 46.9% | 26.5% | 100.0% | 33.3% | 80.0% | 80.0% | 60.5% | 2.11 | 2.67 |
| openai_same_evidence | 8.2% | 4.1% | 100.0% | 100.0% | 86.7% | 94.1% | 82.3% | 2.26 | 3.71 |

## Agent engineering and workflow diagnostics

- Document Recall@K: 82.9% (N=38); Page Recall@K: 61.8% (N=38).
- Figure retrieval accuracy: 75.0% (N=4); formula source correctness: 0.0%.
- Correct action selection: 57.1%; clarification trigger: 50.0%; same-run resume: 50.0%.
- Validated Python/simulation execution: 11.8%; validated CALC adoption: 11.8%; repeated/no-progress action fraction: 17.4%.
- Safe-refusal accuracy: 100.0%; false-premise handling: 0.0%; citation semantic support: 50.4%.
- Agent latency: mean 34.39 s, median 25.29 s, p95 80.96 s. Mean retrieval 8.03 s; LLM generation 19.80 s; calculate/simulate 4.57 s; verification 18.74 s.

## Category performance (Agent)

| Category | N | Goal success | Exact | Mean latency s |
|---|---:|---:|---:|---:|
| clarification | 4 | 0.0% | 0.0% | 42.82 |
| cross_domain | 3 | 0.0% | 0.0% | 25.96 |
| direct_calculation | 7 | 0.0% | 28.6% | 33.01 |
| drilling | 3 | 0.0% | 0.0% | 28.96 |
| false_premise | 3 | 0.0% | 0.0% | 59.72 |
| figure | 4 | 0.0% | 25.0% | 22.02 |
| kb_calculation | 4 | 0.0% | 0.0% | 50.57 |
| petrophysics | 6 | 33.3% | 50.0% | 29.45 |
| reservoir_engineering | 6 | 0.0% | 0.0% | 40.71 |
| reservoir_simulation | 2 | 0.0% | 0.0% | 7.87 |
| simulation | 2 | 0.0% | 0.0% | 43.62 |
| unsupported_formula | 2 | 50.0% | 50.0% | 10.89 |
| well_testing | 3 | 33.3% | 33.3% | 34.19 |

## Final Agent acceptance, independent of earlier T1–T7

| Function | Example task | Actual action sequence | Goal success |
|---|---|---|---:|
| petrophysics | L01 | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 0.0% |
| direct_calculation | N01 | RETRIEVE → CALCULATE → RETRIEVE → VERIFY → RETRIEVE → VERIFY → STOP | 0.0% |
| kb_calculation | N07 | RETRIEVE → CALCULATE → RETRIEVE → VERIFY → STOP | 0.0% |
| simulation | S01 | CALCULATE → RETRIEVE → VERIFY → RETRIEVE → VERIFY → RETRIEVE → STOP | 0.0% |
| clarification | C01 | CALCULATE → RETRIEVE → CALCULATE → RETRIEVE → VERIFY → STOP | 0.0% |
| unsupported_formula | U01 | RETRIEVE → RETRIEVE → RETRIEVE | 0.0% |
| figure | G01 | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 0.0% |

Example tasks are the first frozen-order item in each category, not selected successes.

## Statistical analysis

Task-paired, nonparametric bootstrap percentile 95% intervals use 4000 resamples and seed 20261009. Full differences and denominators are in `statistical_analysis.json`. With about 49 valid tasks, category subsets and rare behaviors (especially four clarifications and four figures) are too small for strong significance claims. Intervals are exploratory uncertainty summaries, not independent repeated-system measurements.

| Comparison (Agent minus baseline) | Metric | Paired N | Difference | Bootstrap 95% CI |
|---|---|---:|---:|---:|
| qwen_closed_book | goal_success | 49 | -14.3 pp | [-26.5 pp, -2.0 pp] |
| qwen_closed_book | exact_accuracy | 49 | -6.1 pp | [-18.4 pp, 6.1 pp] |
| qwen_closed_book | claim_coverage | 49 | -16.3 pp | [-31.1 pp, -1.6 pp] |
| qwen_closed_book | hallucination | 49 | -22.4 pp | [-36.7 pp, -8.2 pp] |
| qwen_closed_book | numeric_accuracy | 18 | -11.1 pp | [-44.4 pp, 22.2 pp] |
| openai_closed_book | goal_success | 49 | -49.0 pp | [-63.3 pp, -32.7 pp] |
| openai_closed_book | exact_accuracy | 49 | -40.8 pp | [-57.1 pp, -24.5 pp] |
| openai_closed_book | claim_coverage | 49 | -47.9 pp | [-60.9 pp, -34.5 pp] |
| openai_closed_book | hallucination | 49 | 10.2 pp | [-6.1 pp, 26.5 pp] |
| openai_closed_book | numeric_accuracy | 18 | -33.3 pp | [-61.1 pp, 0.0 pp] |
| qwen_same_evidence | goal_success | 49 | -28.6 pp | [-42.9 pp, -14.3 pp] |
| qwen_same_evidence | exact_accuracy | 49 | -20.4 pp | [-34.7 pp, -8.2 pp] |
| qwen_same_evidence | claim_coverage | 49 | -35.6 pp | [-47.5 pp, -23.5 pp] |
| qwen_same_evidence | hallucination | 49 | -12.2 pp | [-28.6 pp, 2.0 pp] |
| qwen_same_evidence | numeric_accuracy | 18 | -22.2 pp | [-44.4 pp, 5.6 pp] |
| openai_same_evidence | goal_success | 49 | -65.3 pp | [-77.6 pp, -51.0 pp] |
| openai_same_evidence | exact_accuracy | 49 | -59.2 pp | [-73.5 pp, -44.9 pp] |
| openai_same_evidence | claim_coverage | 49 | -58.1 pp | [-68.8 pp, -47.4 pp] |
| openai_same_evidence | hallucination | 49 | 28.6 pp | [14.3 pp, 42.9 pp] |
| openai_same_evidence | numeric_accuracy | 18 | -44.4 pp | [-66.7 pp, -22.2 pp] |

## Invalid tasks and limitations

L20: Near-duplicate of petroleum_agent_heldout_v1_questions.json item 52 on interference testing and inter-well reservoir continuity; violates the new-item policy.

- The source catalog consists of KB text spans and selected figure notes. Four figure items cannot establish full visual-understanding capability; figure-note quality is a further limitation.
- Direct-calculation inputs overlap answer values in some tasks; numeric scoring therefore requires both deterministic tolerance matching and reviewer verification of output/value association.
- The same-evidence track fixes evidence to the Agent's retrieval output and inherits its omissions. It cannot isolate generation from a perfect-retrieval counterfactual.
- One AI reviewer is not an independent panel or blinded human assessment. Structured raw responses permit later human audit.
- Baseline models differ in size, training, cost and provider; comparisons do not control those factors. API service and local hardware can affect latency.
- Missing or blocked outputs are reported separately, never converted into success.

## Poster-safe conclusions

1. Agent goal success was 8.2% on valid tasks, below openai_closed_book at 57.1%. This unequal-information end-to-end comparison does not establish a retrieval benefit.
2. With the Agent's retrieved text evidence supplied to both systems, Agent goal success remained 8.2% versus 73.5% for OpenAI. This is a generation/orchestration gap conditional on the captured evidence, not a causal isolation of either component.
3. Agent median response time was 25.29 s. Local-versus-remote latency is not a controlled hardware comparison; the 49-task, single-reviewer results need independent replication.

All per-task grades are in `final_results.csv`; raw responses, traces, source IDs, citations, calculations, latency, and reviews are under `raw/`, `same_evidence/`, and `review/`.
