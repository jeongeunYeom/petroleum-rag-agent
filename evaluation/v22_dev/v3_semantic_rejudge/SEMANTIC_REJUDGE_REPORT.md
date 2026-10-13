# V22 observed V3 same-protocol semantic comparison

This is an **observed development benchmark**, not a V22 final unseen evaluation. V22 answers were **not regenerated**. The 36 saved primary answers and 4 saved resume probes came exclusively from `evaluation/v22_dev/observed_v3_results.json`; stopped/refused/clarification text was kept unchanged. Qwen answers, judgments, and finalized per-task scores were reused from the original V3 result commit, not regenerated.

## Frozen inputs and method

- Frozen V22 product SHA: `0bfffd45043c9a9f50e76dc6e57b7a44458da665`.
- Original V3 result commit: `8af20278b1905be02fcd2a855471b749da094e38`.
- Benchmark SHA256: `a720ff0282038fd89a11f94dc6ce435cfe8fcda39e16cffa1cef82d171cca6a5`.
- Rubric SHA256: `3e50b3faf93041a001b6741a05df57fb038d2e87e7bb158784b1fb76d65de4d2`.
- Saved V22 output SHA256: `a669ceff593e050497874ae722306dbfbea34b0160ae017d28fd1df1737a237b`.
- Exact semantic judge: `gpt-5.4-2026-03-05`, temperature 0, original V3 JSON schema and verbatim original system instruction. Blinded input included the frozen question, atomic rubric, allowed evidence, anonymous candidate label, and exact saved answer; it excluded system/version, action history, and previous proxy scores.
- Judge calls: **36/36 completed**, one reservation and one attempt per V22 answer; 0 judge failures, 0 technical failures in saved V22 primary runs. No judge result was substituted or retried.
- Deterministic scoring reused the original V3 numeric/unit, calculation and source-provenance, citation-ID, goal gate, aggregation, and percentile definitions. Original Qwen scored rows were checked against its finalized `metrics.json`.
- Paired bootstrap: 10,000 task-paired resamples, seed `20261013`; n=36 except n=16 for Numerical Accuracy.

## Headline comparison

| System | Goal Success | Claim Coverage | Hallucination-free | Numerical Accuracy | Technical failures | Median latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3:8b Closed-book | 12/36 (33.3%) | 66.0% | 21/36 (58.3%) | 11/16 (68.8%) | 0/36 | 1.52 s |
| Petroleum RAG Agent V22 | 4/36 (11.1%) | 25.0% | 30/36 (83.3%) | 3/16 (18.8%) | 0/36 | 17.56 s |

| V22 − Qwen metric | Difference | Paired bootstrap 95% CI | n |
| --- | ---: | ---: | ---: |
| Goal Success | −22.2 pp | [−36.1, −8.3] pp | 36 |
| Claim Coverage | −41.0 pp | [−55.6, −26.4] pp | 36 |
| Hallucination-free | +25.0 pp | [+5.6, +44.4] pp | 36 |
| Numerical Accuracy | −50.0 pp | [−75.0, −25.0] pp | 16 |

The intervals exclude zero **on this observed paired task set**. They do not estimate generalization to a new unseen task distribution.

## Category Goal Success

| Category | n | Qwen3:8b | V22 Agent |
| --- | ---: | ---: | ---: |
| knowledge_qa | 8 | 1/8 (12.5%) | 1/8 (12.5%) |
| multi_claim_reasoning | 6 | 0/6 (0.0%) | 0/6 (0.0%) |
| direct_calculation | 6 | 4/6 (66.7%) | 2/6 (33.3%) |
| user_formula | 4 | 4/4 (100.0%) | 1/4 (25.0%) |
| kb_formula | 6 | 0/6 (0.0%) | 0/6 (0.0%) |
| false_premise | 3 | 2/3 (66.7%) | 0/3 (0.0%) |
| unanswerable | 3 | 1/3 (33.3%) | 0/3 (0.0%) |

## Poster grouping (Goal Success)

Knowledge = `knowledge_qa`; Reasoning = `multi_claim_reasoning`; Calculation = `direct_calculation` + `user_formula` + `kb_formula`; Safety = `false_premise` + `unanswerable`.

| Group | n | Qwen3:8b | V22 Agent |
| --- | ---: | ---: | ---: |
| Knowledge | 8 | 12.5% | 12.5% |
| Reasoning | 6 | 0.0% | 0.0% |
| Calculation | 16 | 50.0% | 18.8% |
| Safety | 6 | 50.0% | 0.0% |

## V22 execution and provenance diagnostics

| Diagnostic | Result |
| --- | ---: |
| Calculation executed / validated / provenance complete | 8/16 · 6/16 · 6/16 |
| Numeric correct | 3/16 |
| Gold formula page / exact formula span retrieved | 5/6 · 5/6 |
| RETRIEVE before CALCULATE for KB formula | 2/6 |
| KB-formula numeric correct / formula provenance correct | 0/6 · 2/6 |
| Citation ID + semantic support among source-task rows | 3/26 |
| Judge-marked unnecessary refusals | 19 |
| Korean/cross-language Goal Success | 0/12 |
| Multi-goal Goal Success | 0/6 |
| Saved resume final completion | 0/4 |

The 4 resume probes are separate diagnostics, not part of the 36-task or 16-numeric denominators. In the saved replay, two probes completed turn 1 prematurely, one remained waiting after turn 2 and asked for another unit, and one stopped before clarification. No resume or answer was rerun.

## Interpretation and limits

The same-judge results show a completion–caution trade-off on this already observed corpus: V22 had higher hallucination-free scoring, but much lower Goal Success, claim coverage, and numeric accuracy than closed-book Qwen. Most saved V22 failures were judged unnecessary refusals; retrieved formula evidence often did not transition to validated calculation. The previous V22 lexical/deterministic proxy values are not interchangeable with these semantic scores.

The original frozen V3 Goal Success rule requires literal formula provenance for KB-formula tasks; a closed-book system cannot satisfy that structural gate, so the 0/6 Qwen KB-formula category should not be read as a pure answer-quality comparison. This is single-reviewer AI-assisted semantic adjudication, not human review, and the judge may err. The benchmark is observed development evidence; a new unseen V4 is required for final generalization claims. The product code, ChromaDB, benchmark, and rubric were not modified during this scoring task.

Poster-safe footnote: “V22는 개발 단계의 동일 36문항 벤치마크에서 평가되었으며, 의미 기반 평가는 동일한 AI judge와 고정된 채점 기준을 적용하였다.”
