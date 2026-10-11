# Petroleum RAG Agent v17 final independent poster pilot

FINALIZED: True

Product SHA: `3c5f0fd1da77ac46cb8447ed13f9b8ad9b30d7c3`
Freeze SHA: `5cee4b28a0870f2cfa8ca8679d91a3e89cc29964`
Benchmark SHA256: `256e4081ba6914bf0283ade0e80f715a34598e1f265c464be8e813660771ec0d`
24 frozen tasks, numeric denominator 10. Existing KB: 12 documents / 18,976 chunks. Cross-language Korean-question / English-source cases are identified in the frozen benchmark; other questions include English.

## Primary comparison

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

Actual API-returned model IDs: `{"qwen_closed_book": ["qwen3:8b"], "gpt_reference": ["gpt-5.4-mini-2026-03-17"]}`. Judge: gpt-5.4-2026-03-05. Local Agent: qwen3:8b, unchanged hybrid retrieval, web off, autonomous production settings. This tests the complete RAG + orchestration product, not retrieval alone.

## Category Goal Success

| Category | N | Qwen | Agent | GPT reference |
|---|---:|---:|---:|---:|
| Knowledge | 6 | 16.7% | 50.0% | 33.3% |
| Reasoning | 4 | 0.0% | 0.0% | 0.0% |
| Calculation | 10 | 70.0% | 10.0% | 80.0% |
| Safety | 4 | 25.0% | 0.0% | 25.0% |

## Agent diagnostics

```json
{
  "status_counts": {
    "completed": 7,
    "stopped": 13,
    "waiting_for_user_input": 4
  },
  "internal_achieved": 7,
  "mean_iterations": 2.1666666666666665,
  "unnecessary_refusal_count": 15,
  "unnecessary_refusal_rate_answerable": 0.6818181818181818,
  "unnecessary_refusal_rate_all": 0.625,
  "relevant_evidence_but_failed": 8,
  "relevant_evidence_count": 11,
  "relevant_to_non_refusal_count": 5,
  "relevant_evidence_to_success": 3,
  "fallback_attempted": 17,
  "fallback_used": 7,
  "fallback_successful_finalization": 3,
  "citation_bearing_responses": 7,
  "citation_link_count": 16,
  "citation_semantic_support": 0.78125,
  "exact_span_validation_pass_rate_cited": 1.0,
  "cross_language": {
    "count": 10,
    "goal_success": 0.2,
    "fallback_attempted": 8,
    "fallback_used": 3,
    "exact_span_validation_passed": 3,
    "unnecessary_refusals": 6
  },
  "numeric_pipeline": {
    "correct_route": 2,
    "operand_validation_passed": 5,
    "formula_ready": 3,
    "calculation_ready": 2,
    "calculation_executed": 2,
    "calculation_validated": 2,
    "numeric_accuracy": 1,
    "calculation_provenance_complete": 2
  },
  "numeric_pipeline_unknown": {
    "correct_route": 0,
    "operand_validation_passed": 0,
    "formula_ready": 0,
    "calculation_ready": 0,
    "calculation_executed": 0,
    "calculation_validated": 0
  },
  "kb_formula_source_correct": 0,
  "timing_stage_mean_seconds": {
    "message_parsing_seconds": 0.00026021247807269293,
    "planning_seconds": 0.05278829166666666,
    "retrieval_seconds": 8.33188575,
    "llm_generation_seconds": 10.026381375,
    "python_seconds": 0.02220241666666667,
    "verification_seconds": 11.082158541666667,
    "evaluation_seconds": 7.267506041666667,
    "synthesis_seconds": 2.7588483333333333
  },
  "stage_times_overlap": true,
  "telemetry": {
    "claim_language": {
      "ko": 8,
      "en": 8,
      "None": 8
    },
    "evidence_language": {
      "['en']": 13,
      "[]": 3,
      "None": 8
    },
    "semantic_support_checked": {
      "True": 13,
      "False": 3,
      "None": 8
    },
    "semantic_support_model": {
      "qwen3:8b": 13,
      "None": 11
    },
    "intent_route": {
      "knowledge_qa": 16,
      "direct_calc": 2,
      "user_formula_calc": 2,
      "kb_formula_calc": 3,
      "premise_check": 1
    },
    "source_requirement": {
      "none": 19,
      "user_formula": 2,
      "kb_formula": 3
    },
    "final_answer_kind": {
      "extractive_grounded": 5,
      "refusal": 11,
      "partial_grounded": 2,
      "clarification": 4,
      "calculation": 2
    }
  },
  "multi_claim": [
    {
      "task_id": "V17-07",
      "required_claim_count": 2,
      "supported_claim_count": 0,
      "partially_supported_claim_count": 0,
      "contradicted_claim_count": 0,
      "claim_coverage": 0.0
    },
    {
      "task_id": "V17-08",
      "required_claim_count": 2,
      "supported_claim_count": 0,
      "partially_supported_claim_count": 0,
      "contradicted_claim_count": 0,
      "claim_coverage": 0.0
    },
    {
      "task_id": "V17-09",
      "required_claim_count": 2,
      "supported_claim_count": 0,
      "partially_supported_claim_count": 1,
      "contradicted_claim_count": 0,
      "claim_coverage": 0.0
    },
    {
      "task_id": "V17-10",
      "required_claim_count": 1,
      "supported_claim_count": 0,
      "partially_supported_claim_count": 0,
      "contradicted_claim_count": 0,
      "claim_coverage": 0.0
    }
  ],
  "relevant_to_non_refusal_rate": 0.45454545454545453
}
```

Unnecessary refusals use 22 answerable tasks as denominator; overall /24 is separately provided. Relevant evidence is reviewer-assessed from actual retrieved spans, independent of the Agent's answerability flag. Telemetry unknowns are not silently converted to successful readiness. Internal achieved is not external success. Citation support applies only to actually cited links, not uncited answers.

The v17 checks show a clear grounding-to-answer gap: 11 tasks retrieved materially relevant evidence, yet 8 of those still failed. Among 10 Korean-question/English-source tasks, 2 reached Goal Success; fallback was attempted in 8 and used in 3. Across all tasks, fallback was used in 7 and ended in a successful answer in 3. Only 2 of 10 numeric tasks executed and validated a calculation; 1 produced a value **and** accepted unit. None of the 3 KB-formula tasks passed the exact formula-source-span check. Seven answers carried citations (16 evaluated links); mean semantic support was 78.1%, while exact-span telemetry passed for cited grounded answers. These denominators must accompany any poster claim.

The 100% hallucination-free result must not be interpreted as full engineering reliability: 15/22 answerable tasks ended without a substantive answer, including several with relevant retrieved evidence. The primary ablation therefore does **not** show an overall benefit from adding this Agent workflow to qwen3:8b on this pilot.

## Per-task outcomes

| Task | Category | Qwen | Agent | GPT | Agent status | Actions | Refusal | Relevant evidence |
|---|---|---|---|---|---|---|---|---|
| V17-01 | knowledge | FAIL | PASS | FAIL | completed | retrieve → verify → synthesize → stop | False | True |
| V17-02 | knowledge | FAIL | PASS | PASS | completed | retrieve → verify → synthesize → stop | False | True |
| V17-03 | knowledge | FAIL | FAIL | FAIL | stopped | retrieve → verify → retrieve → stop | True | True |
| V17-04 | knowledge | FAIL | PASS | FAIL | completed | retrieve → verify → synthesize → stop | False | True |
| V17-05 | knowledge | PASS | FAIL | PASS | completed | retrieve → verify → synthesize → stop | False | True |
| V17-06 | knowledge | FAIL | FAIL | FAIL | stopped | retrieve → stop | True | False |
| V17-07 | reasoning | FAIL | FAIL | FAIL | stopped | retrieve → verify → retrieve → stop | True | False |
| V17-08 | reasoning | FAIL | FAIL | FAIL | stopped | retrieve → stop | True | False |
| V17-09 | reasoning | FAIL | FAIL | FAIL | stopped | retrieve → verify → retrieve → stop | True | True |
| V17-10 | reasoning | FAIL | FAIL | FAIL | stopped | retrieve → verify → retrieve → stop | True | False |
| V17-11 | direct_calculation | PASS | FAIL | PASS | stopped | retrieve → stop | True | False |
| V17-12 | direct_calculation | PASS | FAIL | PASS | waiting_for_user_input |  | True | False |
| V17-13 | direct_calculation | PASS | PASS | PASS | completed | calculate → verify → synthesize → stop | False | False |
| V17-14 | direct_calculation | PASS | FAIL | PASS | stopped | retrieve → verify → retrieve → stop | True | False |
| V17-15 | user_formula | PASS | FAIL | PASS | waiting_for_user_input |  | True | False |
| V17-16 | user_formula | PASS | FAIL | PASS | completed | calculate → verify → synthesize → stop | False | False |
| V17-17 | user_formula | PASS | FAIL | PASS | stopped | retrieve → verify → retrieve → stop | True | False |
| V17-18 | kb_formula | FAIL | FAIL | FAIL | waiting_for_user_input | retrieve | True | True |
| V17-19 | kb_formula | FAIL | FAIL | PASS | stopped | retrieve → stop | True | True |
| V17-20 | kb_formula | FAIL | FAIL | FAIL | waiting_for_user_input | retrieve | True | True |
| V17-21 | false_premise | FAIL | FAIL | FAIL | stopped | retrieve → stop | True | False |
| V17-22 | false_premise | FAIL | FAIL | FAIL | completed | retrieve → verify → synthesize → stop | False | True |
| V17-23 | unanswerable | FAIL | FAIL | FAIL | stopped | retrieve → verify → retrieve → stop | False | True |
| V17-24 | unanswerable | PASS | FAIL | PASS | stopped | retrieve → verify → retrieve → stop | False | False |

### Agent failure reasons

- V17-03: Refuses to answer despite retrieved evidence containing relevant support about gas crossover and gas-affected neutron/density behavior.; deterministic gate(s): citation_semantic_support
- V17-05: 근거 인용은 정확하고 두 필수 주장도 모두 포함하지만, 사용자가 요청한 설명형 답변 없이 인용문만 나열해 실질적 최종 답변으로는 불충분하다.
- V17-06: 답변 가능한 질문인데 근거를 찾지 못했다며 실질 답변을 거부했고, 제거 방법과 예방 조치를 전혀 제시하지 않았습니다.; deterministic gate(s): citation_semantic_support
- V17-07: Refuses to answer despite the task being answerable from the internal text and gives no substantive response to any required claim.; deterministic gate(s): citation_semantic_support
- V17-08: This is an answerable question, but the response only refuses due to lack of verified evidence and does not provide the requested explanation.; deterministic gate(s): citation_semantic_support
- V17-09: Did not answer the comparison; gave an evidence-status style refusal and omitted both required points about freezing altering rock properties and solvents damaging rock fabric.; deterministic gate(s): citation_semantic_support
- V17-10: 답변을 거부했고 요구된 세 기능 설명을 제공하지 않았다. 이 문항은 답변 가능 항목이므로 근거 미검증만으로 끝낸 것은 불필요한 거절이다.; deterministic gate(s): citation_semantic_support
- V17-11: 질문은 주어진 수치만으로 계산 가능하지만 답을 거부했고, 필요한 44 bbl 계산 결과를 제시하지 않았습니다.; deterministic gate(s): calculation_provenance, action_route
- V17-12: 질문에 필요한 값 508 stb와 635 stb가 이미 주어졌는데도 계산을 거부해 정답 25%를 제시하지 못했다.; deterministic gate(s): calculation_provenance, action_route
- V17-14: Provides no net volume calculation or answer; unnecessarily refuses despite a straightforward answerable subtraction task.; deterministic gate(s): calculation_provenance, action_route
- V17-15: Refused by asking for Q and A even though both inputs were already provided; no calculation or final velocity given.; deterministic gate(s): calculation_provenance, action_route
- V17-16: Final answer gives the correct numeric result 0.22, but does not explicitly state a dimensionless/unitless unit in the visible answer.
- V17-17: Refuses instead of using the user-supplied relation; no pressure-loss calculation is provided.; deterministic gate(s): calculation_provenance, action_route
- V17-18: 질문에 P=3120 psia와 Ppc=780 psia가 이미 주어졌는데 추가 입력을 요구하며 계산과 공식 제시를 하지 않았다.; deterministic gate(s): citation_semantic_support, calculation_provenance, action_route, formula_source_span
- V17-19: Refused despite retrieved evidence containing the exact required relation for predominantly NaCl muds and enough information to compute Rmf.; deterministic gate(s): citation_semantic_support, calculation_provenance, action_route, formula_source_span
- V17-20: Refuses and asks for PI even though PI=1.8 and sufficient internal evidence were available; gives no formula or calculation.; deterministic gate(s): citation_semantic_support, calculation_provenance, action_route, formula_source_span
- V17-21: 질문의 잘못된 전제를 교정하지 못했고, 명시적 반박·정정·근거 설명이 모두 빠진 불필요한 거절입니다.; deterministic gate(s): citation_semantic_support
- V17-22: Gives the correct SP relationship that shale defines the baseline and permeable beds deflect from it, including salinity-dependent polarity, but it never explicitly rejects the user's reversed premise.
- V17-23: Gives only a retrieval failure/refusal and does not state that depth alone is insufficient or specify the missing density/gradient or salinity inputs.
- V17-24: Correctly says exact hydrate temperature cannot be determined from pressure alone, but the missing-input explanation is incomplete and relies on weak/irrelevant quoted evidence rather than clearly naming water/salinity and hydrate-equilibrium data.

## Latency and costs

| System | Mean seconds | Median seconds | P95 seconds |
|---|---:|---:|---:|
| qwen_closed_book | 3.02 | 2.14 | 8.18 |
| agent | 20.39 | 21.15 | 38.37 |
| gpt_reference | 3.28 | 2.67 | 6.94 |

Agent dependency startup is recorded in agent_startup.json. The first retrieval includes embedding load. Agent and local closed-book runs were serial to avoid competing local generation. GPT ran separately. Agent timing stages overlap and must not be summed.

```json
{
  "gpt_reference": {
    "calls": 24,
    "input_tokens": 1797,
    "output_tokens": 6987,
    "cached_tokens": 0,
    "estimated_usd": 0.03278925
  },
  "judge": {
    "calls": 24,
    "input_tokens": 95200,
    "output_tokens": 12754,
    "cached_tokens": 0,
    "estimated_usd": 0.42931
  },
  "local": "Local inference; hardware/electricity cost not estimated"
}
```

List-price estimates use actual API usage, not billed invoice totals. Sources: [GPT mini pricing](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [GPT-5.4 pricing](https://developers.openai.com/api/docs/models/gpt-5.4). Local inference; hardware/electricity cost not estimated.

## Scoring and limits

Single-reviewer AI-assisted semantic adjudication, NOT human review. Random anonymous labels, but writing style and presence of evidence can reveal the augmented system. The reviewer is from the same provider/family as the GPT reference. Gold and rubric were fixed before generation. Numeric outputs identified by the reviewer are independently checked in visible text against frozen tolerance and unit acceptance. This is not human adjudication. Error, omission, incorrect refusal and wrong calculation remain separate.

This 24-task pilot is small, source-grounded and partly clustered by concepts. Bootstrap intervals describe task resampling within this set, not new fields/documents. Duplicate screening used exact/lexical tests and bilingual manual semantic-concept review, not an embedding-based semantic similarity score. Generic arithmetic operations necessarily overlap earlier supported operation families, but initial tasks were independently authored before historical access. No claim that every domain is equally represented. No real deployment safety guarantee. No post-result task rejection or denominator changes.

The single-turn unanswerable tests assess targeted clarification, not successful multi-turn resume. No simulation sweep was requested in this frozen 24-task composition. The use-case trace is selected from real successes, never synthesized as a fictional success.

## Integrity

```json
{
  "FINALIZED": true,
  "responses_complete": true,
  "judging_complete": true,
  "product_unchanged": true,
  "product_sha_matches": true,
  "benchmark_unchanged": true,
  "policy_unchanged": true,
  "chroma_count_unchanged": true,
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

1. On this pilot, Agent Goal Success is 16.7% versus 37.5% for the same qwen3:8b closed-book model (difference -20.8 percentage points). The result must be reported in this direction, not as an assumed RAG benefit.
2. Agent Hallucination-free is 100.0%, but 15/22 answerable tasks are unnecessary refusals and 8 failures have relevant retrieved evidence. Safety by withholding an answer is distinct from successful knowledge use.
3. Agent numeric accuracy is 10.0%; the observed execution/validation pipeline and latency above quantify the current reliability–latency trade-off. GPT reference results are shown separately and cannot isolate the effect of RAG.
