# Petroleum RAG Agent v16 independent poster pilot

FINALIZED: True

Product SHA: `57af58c44816c3734ea3d5a7aa4e1f08407798ba`  
Freeze SHA: `fa4aeac138d1a2d515a7d5ffda62612ad39409b8`  
Benchmark SHA256: `e15d1c2cac2a5860a578127dd15572a1ea798d1d556b5ff55e889b0780ed5f07`  
24 frozen tasks, numeric denominator 10. Existing KB: 12 documents / 18,976 chunks. Nine source documents support the KB-grounded cases. Questions are Korean with technical English terminology.

## Primary comparison

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

Actual API-returned model IDs: `{"qwen_closed_book": ["qwen3:8b"], "gpt_reference": ["gpt-5.4-mini-2026-03-17"]}`. Judge: gpt-5.4-2026-03-05. Local Agent: qwen3:8b, unchanged hybrid retrieval, web off, autonomous production settings. This tests the complete RAG + orchestration product, not retrieval alone.

## Category Goal Success

| Category | N | Qwen | Agent | GPT reference |
|---|---:|---:|---:|---:|
| Knowledge | 6 | 16.7% | 16.7% | 33.3% |
| Reasoning | 4 | 0.0% | 0.0% | 75.0% |
| Calculation | 10 | 90.0% | 20.0% | 100.0% |
| Safety | 4 | 25.0% | 0.0% | 50.0% |

## Agent diagnostics

```json
{
  "status_counts": {
    "stopped": 12,
    "completed": 8,
    "waiting_for_user_input": 4
  },
  "internal_achieved": 8,
  "mean_iterations": 2.2083333333333335,
  "unnecessary_refusal_count": 15,
  "unnecessary_refusal_rate_answerable": 0.6818181818181818,
  "unnecessary_refusal_rate_all": 0.625,
  "relevant_evidence_but_failed": 6,
  "relevant_evidence_count": 7,
  "relevant_to_non_refusal_count": 3,
  "fallback_attempted": 13,
  "fallback_used": 0,
  "fallback_successful_finalization": 0,
  "citation_bearing_responses": 5,
  "citation_link_count": 19,
  "citation_semantic_support": 0.34210526315789475,
  "numeric_pipeline": {
    "correct_route": 3,
    "operand_validation_passed": 6,
    "formula_ready": 5,
    "calculation_ready": 6,
    "calculation_executed": 3,
    "calculation_validated": 3,
    "numeric_accuracy": 2
  },
  "numeric_pipeline_unknown": {
    "correct_route": 0,
    "operand_validation_passed": 0,
    "formula_ready": 0,
    "calculation_ready": 0,
    "calculation_executed": 0,
    "calculation_validated": 0
  },
  "timing_stage_mean_seconds": {
    "message_parsing_seconds": 0.00016511251063396534,
    "planning_seconds": 0.5273344583333334,
    "retrieval_seconds": 7.660958166666666,
    "llm_generation_seconds": 8.530983125,
    "python_seconds": 0.5431649166666667,
    "verification_seconds": 8.71599375,
    "evaluation_seconds": 4.777056166666667,
    "synthesis_seconds": 2.8505769583333334
  },
  "stage_times_overlap": true,
  "relevant_to_non_refusal_rate": 0.42857142857142855
}
```

Unnecessary refusals use 22 answerable tasks as denominator; overall /24 is separately provided. Relevant evidence is reviewer-assessed from actual retrieved spans, independent of the Agent's answerability flag. Telemetry unknowns are not silently converted to successful readiness. Internal achieved is not external success. Citation support applies only to actually cited links, not uncited answers.

## Per-task outcomes

| Task | Category | Qwen | Agent | GPT | Agent status | Actions | Refusal | Relevant evidence |
|---|---|---|---|---|---|---|---|---|
| V16-01 | knowledge | FAIL | FAIL | PASS | stopped | retrieve → verify → retrieve → stop | True | True |
| V16-02 | knowledge | FAIL | FAIL | FAIL | stopped | retrieve → verify → retrieve → stop | True | False |
| V16-03 | knowledge | FAIL | PASS | FAIL | completed | retrieve → verify → synthesize → stop | False | True |
| V16-04 | knowledge | FAIL | FAIL | PASS | completed | retrieve → verify → synthesize → stop | False | True |
| V16-05 | knowledge | PASS | FAIL | FAIL | stopped | retrieve → verify → retrieve → stop | True | True |
| V16-06 | knowledge | FAIL | FAIL | FAIL | completed | retrieve → verify → synthesize → stop | True | True |
| V16-07 | reasoning | FAIL | FAIL | FAIL | completed | retrieve → verify → synthesize → stop | False | False |
| V16-08 | reasoning | FAIL | FAIL | PASS | stopped | retrieve → verify → retrieve → stop | True | False |
| V16-09 | reasoning | FAIL | FAIL | PASS | stopped | retrieve → verify → retrieve → stop | True | False |
| V16-10 | reasoning | FAIL | FAIL | PASS | completed | retrieve → verify → synthesize → stop | False | True |
| V16-11 | direct_calculation | PASS | PASS | PASS | completed | calculate → verify → synthesize → stop | False | False |
| V16-12 | direct_calculation | PASS | PASS | PASS | completed | calculate → analyze → verify → synthesize → stop | False | False |
| V16-13 | direct_calculation | PASS | FAIL | PASS | waiting_for_user_input |  | True | False |
| V16-14 | direct_calculation | FAIL | FAIL | PASS | waiting_for_user_input |  | True | False |
| V16-15 | user_formula | PASS | FAIL | PASS | completed | calculate → verify → synthesize → stop | False | False |
| V16-16 | user_formula | PASS | FAIL | PASS | waiting_for_user_input |  | True | False |
| V16-17 | user_formula | PASS | FAIL | PASS | waiting_for_user_input |  | True | False |
| V16-18 | kb_formula | PASS | FAIL | PASS | stopped | calculate → stop | True | False |
| V16-19 | kb_formula | PASS | FAIL | PASS | stopped | calculate → stop | True | False |
| V16-20 | kb_formula | PASS | FAIL | PASS | stopped | calculate → stop | True | False |
| V16-21 | false_premise | FAIL | FAIL | FAIL | stopped | retrieve → verify → retrieve → stop | True | False |
| V16-22 | false_premise | FAIL | FAIL | FAIL | stopped | retrieve → stop | True | False |
| V16-23 | unanswerable | FAIL | FAIL | PASS | stopped | retrieve → verify → retrieve → stop | False | False |
| V16-24 | unanswerable | PASS | FAIL | PASS | stopped | retrieve → verify → retrieve → stop | False | True |

### Agent failure reasons

- V16-01: 답변이 실질 설명 없이 근거 부족을 이유로 거절했다. 제공된 근거에는 필라멘트 냉각·저항 변화와 reference cell/브리지 역할이 직접 있다.
- V16-02: 답변을 거절했고, 질문이 답변 가능함에도 중앙 플러그만 측정 대상이라는 점과 입구/출구 바깥 플러그의 구체 역할을 설명하지 않았다.
- V16-04: 첫 문장은 ES가 내부 염수/물상의 에멀전 강도·안정성을 감시한다는 점을 맞췄다. 그러나 지층수 유입 시에는 추가 물을 받아들일 만큼 안정해야 한다는 핵심 대신 침투 억제·수분 흡수 방지로 바꿔 답해 두 번째 필수 주장에 실패했다.
- V16-05: 제공된 근거에 정답이 직접 있는데도 검증 불가라고 답하며 실질적 답변을 거부했다.
- V16-06: 질문을 그대로 반복하고 인용표시만 했을 뿐, flash와 differential의 차이나 Rs가 달라지는 이유를 설명하지 않았다.
- V16-07: Very terse. States high salinity helps shale inhibition and mentions attapulgite cost, but does not explain Ca2+/Mg2+ reducing bentonite hydration/dispersion, and incorrectly adds shale-inhibition benefit for attapulgite instead of the required water-type-independent viscosity plus poor filtration control.
- V16-08: Refuses despite the task being answerable from available evidence and provides no substantive answer about constant enthalpy vs temperature or glycol preventing hydrate/ice formation.
- V16-09: 답변을 거부했고, 제공된 근거로 답할 수 있는 질문인데 체류시간 감소·에멀전 분리 시간 부족·가열/demulsifier 방안을 설명하지 않았다.
- V16-10: Reverses the key physics by saying P is less sensitive and S more useful/sensitive for gas or fluids. Mentions shale correction only vaguely.
- V16-13: Answer refuses despite all needed inputs being provided; gives no decrease or percentage.
- V16-14: 문제에 필요한 입력값이 모두 주어졌는데도 계산을 거부했고, 요청된 비율과 미회수 질량을 제시하지 않았다.
- V16-15: Numeric result is equivalent within tolerance, but it reports bracketed tags and no correct dimensionless unit despite the task specifying L is dimensionless.
- V16-16: Answer wrongly asks for missing a even though a=4.7 was provided, and gives no cost.
- V16-17: Incorrectly refuses despite k and v being provided; gives no calculation or answer.
- V16-18: Answer refuses and asks for missing input even though C and density were provided; gives no formula application or numeric result.
- V16-19: 주어진 값만으로 계산 가능한 답변인데 도구/추가값을 요구하며 계산을 제공하지 않았다.
- V16-20: 답변 가능한 문제인데 불필요하게 추가 입력을 요구하며 정의와 계산 결과를 제공하지 않았다.
- V16-21: 질문이 거짓 전제 과제인데 전제를 명시적으로 반박하지 않았고, 필요한 정정(원심분리법은 capillary end effect 문제를 겪고 displacing phase 상대투과도는 정량화 불가)을 제공하지 않았다.
- V16-22: 답변 가능 과제인데 전제를 반박하거나 올바른 설명을 하지 않고 근거 부족으로 거절했다.
- V16-23: Says it could not verify support from retrieved evidence instead of answering the unanswerable task properly. It does not clearly state exact remaining cycles cannot be determined from the given info, and it omits the specific needed inputs.
- V16-24: Gives only a generic inability-to-verify statement, without stating non-identifiability from TCD resistance change or naming the specific missing calibration/condition inputs.

## Latency and costs

| System | Mean seconds | Median seconds | P95 seconds |
|---|---:|---:|---:|
| qwen_closed_book | 2.75 | 2.34 | 5.16 |
| agent | 18.39 | 17.79 | 41.91 |
| gpt_reference | 3.69 | 2.77 | 7.31 |

Agent dependency startup is recorded in agent_startup.json. The first retrieval includes embedding load. Existing environment selected CPU for BGE-M3, while Ollama served the unchanged qwen3:8b. Agent and local closed-book runs were serial to avoid competing local generation. GPT ran separately in parallel with local work. Agent timing stages overlap and must not be summed.

```json
{
  "gpt_reference": {
    "calls": 24,
    "input_tokens": 1922,
    "output_tokens": 10198,
    "cached_tokens": 0,
    "estimated_usd": 0.0473325
  },
  "judge": {
    "calls": 24,
    "input_tokens": 112817,
    "output_tokens": 12486,
    "cached_tokens": 12544,
    "estimated_usd": 0.4411085
  },
  "local": "Local inference; hardware/electricity cost not estimated"
}
```

List-price estimates use actual API usage, not billed invoice totals. Sources: [GPT mini pricing](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [GPT-5.4 pricing](https://developers.openai.com/api/docs/models/gpt-5.4). Local inference; hardware/electricity cost not estimated.

## Scoring and limits

Single-reviewer AI-assisted semantic adjudication, NOT human review. Random anonymous labels, but writing style and presence of evidence can reveal the augmented system. The reviewer is from the same provider/family as the GPT reference. Gold and rubric were fixed before generation. Numeric outputs identified by the reviewer are checked deterministically against frozen tolerance and unit acceptance. Thus numeric extraction itself is not an independent human determination. Error, omission, incorrect refusal and wrong calculation remain separate.

This 24-task convenience pilot is small, source-grounded and partly clustered by concepts. Bootstrap intervals describe task resampling within this set, not new fields/documents. Duplicate screening used exact/lexical tests and bilingual semantic concept review, not an embedding-based semantic similarity score. Generic arithmetic operations necessarily overlap earlier supported operation families, but initial tasks were independently authored before historical access. No claim that every domain is equally represented. No real deployment safety guarantee. No post-result task rejection or denominator changes.

The single-turn unanswerable tests assess targeted clarification, not successful multi-turn resume. No simulation sweep was requested in this frozen 24-task composition. The use-case trace is selected from real successes, never synthesized as a fictional success.

## Integrity

```json
{
  "FINALIZED": true,
  "responses_complete": true,
  "judging_complete": true,
  "product_unchanged": true,
  "benchmark_unchanged": true,
  "policy_unchanged": true,
  "chroma_logical_unchanged": true,
  "chroma_files_unchanged": true,
  "no_automatic_retries": true,
  "exact_questions_identical": true,
  "no_post_result_tuning": true,
  "main_unchanged": true,
  "actual_citations_reviewed": true
}
```

No post-result tuning was performed. No main merge. Benchmark, prior evaluation records and product files were not edited after freeze. Evaluation aggregation/report code is separate from the fixed product.

## Poster-safe conclusions

1. On this pilot, Agent Goal Success is 12.5% versus 45.8% for the same qwen3:8b closed-book model (difference -33.3 percentage points). The result must be reported in this direction, not as an assumed RAG benefit.
2. Agent Hallucination-free is 87.5%, but 15/22 answerable tasks are unnecessary refusals and 6 failures have relevant retrieved evidence. Safety by withholding an answer is distinct from successful knowledge use.
3. Agent numeric accuracy is 20.0%; the observed execution/validation pipeline and latency above quantify the current reliability–latency trade-off. GPT reference results are shown separately and cannot isolate the effect of RAG.
