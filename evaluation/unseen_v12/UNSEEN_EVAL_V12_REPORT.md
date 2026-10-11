# v12 independent unseen evaluation

Tested version: v12  
Dataset: new `unseen_eval_v12.json` (50 frozen tasks)  
OpenAI model: `gpt-5.4-mini-2026-03-17`  
v12 modification during evaluation: NO  
main merge: NO

- Frozen product: `2fd4af7d6b12c7d42292b6b7525b0aacf5f34739`; benchmark SHA256: `780fe62c79adb836e73db33416d6a2de0eb9e36a7aac863fd73df09cc2c08d72`
- Evaluation: 50 new tasks; local `qwen3:8b` + hybrid Chroma (12 documents / 18,976 chunks), web off.
- Reviewer: `gpt-5.4-mini-2026-03-17`; single-reviewer AI-assisted semantic adjudication. No human review claim.
- Verdict: **FAIL** under pre-registered thresholds in `EVALUATION_POLICY.md`.

## 요약

- 엄격한 목표 달성 22.0%, 계산 정확도 0.0%, 잘못된 전제 교정 0.0%로 사전 정의한 기준에 미달했다.
- 문서/페이지 검색 재현율은 80.26% / 57.89%였지만, 인용 의미 지지는 50.0%였다. 검색 이후의 실행·판단 실패를 분리해서 보아야 한다.
- 답변 불가 5문항 중 구체적으로 필요한 입력을 설명한 비율은 20.0%였다. 막연한 안전 거절은 성공으로 처리하지 않았다.

## Overall

| Metric | Value |
|---|---:|
| n | 50 |
| invalid_tasks | 0 |
| infrastructure_errors | 0 |
| goal_success_pct | 22.0 |
| run_status_counts | {'completed': 21, 'stopped': 22, 'waiting_for_user_input': 7} |
| exact_accuracy_pct | 22.0 |
| partial_or_better_pct | 46.0 |
| claim_coverage_pct | 35.42 |
| hallucination_pct | 20.0 |
| unsupported_claims_total | 30 |
| engineering_contradictions_total | 6 |
| numeric_accuracy_pct | 0.0 |
| unit_accuracy_pct | 10.0 |
| validated_calc_pct | 0.0 |
| safe_refusal_pct | 20.0 |
| false_premise_handling_pct | 0.0 |
| adjudication_guard_counts | {'generic_abstention_not_claim_support': 20, 'explicit_premise_rejection_absent': 1, 'missing_input_explanation_absent': 4} |
| citation_id_correctness_pct | 52.63 |
| citation_semantic_support_pct | 50.0 |
| document_recall_at_k_pct | 80.26 |
| page_recall_at_k_pct | 57.89 |
| mean_latency_seconds | 23.666 |
| median_latency_seconds | 23.306 |
| p95_latency_seconds | 43.502 |
| average_retrieval_seconds | 6.473 |
| average_llm_generation_seconds | 12.619 |
| average_python_seconds | 0.104 |
| average_verification_seconds | 13.525 |
| average_synthesis_seconds | 3.909 |
| review_cost_usd | 0.1058 |

## Decision basis

Pre-registered PASS thresholds: goal success ≥70%, material hallucination ≤10%, citation semantic support ≥80%, safe handling of unanswerables ≥80%. Observed: 22.0%, 20.0%, 50.0%, 20.0%, respectively.
Most frequent failure labels: claim_coverage (32), goal_not_achieved (25), citation_missing_or_semantically_unsupported (23), unsupported_claim (18), relevant_evidence_but_answer_incomplete (13).


## Category / difficulty / answerability

| Slice | n | Goal success % | Claim coverage % | Hallucination % | Median s |
|---|---:|---:|---:|---:|---:|
| answerability:False | 5 | 20.0 | 60.0 | 0.0 | 21.364 |
| answerability:True | 45 | 22.22 | 32.56 | 22.22 | 23.341 |
| category:calculation | 10 | 0.0 | 0.0 | 0.0 | 2.062 |
| category:cause_effect | 5 | 40.0 | 40.0 | 0.0 | 27.316 |
| category:comparison | 5 | 40.0 | 80.0 | 40.0 | 27.138 |
| category:conditional_reasoning | 5 | 20.0 | 20.0 | 20.0 | 25.31 |
| category:false_premise | 4 | 0.0 | 25.0 | 50.0 | 22.329 |
| category:multi_source | 5 | 20.0 | 40.0 | 60.0 | 23.207 |
| category:single_fact | 6 | 33.33 | 50.0 | 33.33 | 22.391 |
| category:terminology_confusion | 5 | 40.0 | 40.0 | 0.0 | 21.309 |
| category:unanswerable | 5 | 20.0 | 60.0 | 0.0 | 21.364 |
| difficulty:easy | 12 | 25.0 | 40.0 | 25.0 | 21.317 |
| difficulty:hard | 12 | 33.33 | 50.0 | 25.0 | 23.25 |
| difficulty:medium | 26 | 15.38 | 26.92 | 15.38 | 25.291 |

## Failure cases

| ID | Category | Cause labels | Agent status | Reviewer observation |
|---|---|---|---|---|
| SF02 | single_fact | retrieval_document_miss, citation_missing_or_semantically_unsupported, claim_coverage, unnecessary_refusal_or_clarification, goal_not_achieved | stopped | The answer refused despite the provided source excerpt directly stating the pocket is off-centre with ports into the annulus. |
| SF03 | single_fact | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, goal_not_achieved | stopped | The cited excerpt states that a VDL provides the wavetrain of the received signal. |
| SF04 | single_fact | hallucination_or_engineering_contradiction, unsupported_claim | achieved | The answer adds unsupported claims about magnetic declination being irrelevant and about explicit protocol evidence. |
| SF06 | single_fact | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, hallucination_or_engineering_contradiction, unsupported_claim | achieved | The answer incorrectly states MW is lbm/gal instead of ppg and does not support the psi claim from the cited excerpts. |
| MS01 | multi_source | retrieval_page_miss, claim_coverage, hallucination_or_engineering_contradiction, unsupported_claim, multi_hop_synthesis_failure | achieved | The answer correctly names the water-drive labels but misstates the drive energy source, which the cited material says is aquifer-water expansion, not pressure difference. |
| MS02 | multi_source | retrieval_document_miss, citation_missing_or_semantically_unsupported, claim_coverage, unnecessary_refusal_or_clarification, goal_not_achieved, unsupported_claim, multi_hop_synthesis_failure | pending | No agent answer or cited excerpts were provided to support either claim. |
| MS03 | multi_source | retrieval_page_miss, citation_missing_or_semantically_unsupported, claim_coverage, hallucination_or_engineering_contradiction, unsupported_claim, multi_hop_synthesis_failure | achieved | The answer misstates VDL as Vertical Depletion Log and cites reservoir pressure/fluid distribution instead of cement-bond evidence across casing, cement, and formation. |
| MS05 | multi_source | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, hallucination_or_engineering_contradiction, unsupported_claim, multi_hop_synthesis_failure | achieved | The answer only cites placeholders and does not state the required reasons, so neither claim is supported by the cited excerpts. |
| CE01 | cause_effect | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, goal_not_achieved | stopped | The answer correctly refused to answer despite cited excerpts supporting the claims. |
| CE02 | cause_effect | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, goal_not_achieved | stopped | The answer refused to answer, but the cited excerpt directly supports both expected claims. |
| CE05 | cause_effect | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, goal_not_achieved | stopped | The answer refused despite a cited passage directly supporting the reclaimer/distillation point, but it did not address the first claim. |
| CP03 | comparison | hallucination_or_engineering_contradiction, unsupported_claim | achieved | The answer correctly supports both CBL and VDL bond interpretations, but it adds unsupported claims about wave velocity, attenuation, mechanical properties, and fluid-filled zones. |
| CP04 | comparison | hallucination_or_engineering_contradiction, unsupported_claim | achieved | The answer adds unsupported extra description about edge-water drive being upper/side and about structural distribution. |
| CP05 | comparison | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, goal_not_achieved | stopped | The answer refused despite cited excerpts that do support both skin-factor interpretations. |
| NU01 | calculation | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, goal_not_achieved | stopped | The refusal was appropriate, but the cited source excerpt does support the formula and the numeric result was not provided. |
| NU02 | calculation | retrieval_document_miss, citation_missing_or_semantically_unsupported, claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, unnecessary_refusal_or_clarification, goal_not_achieved, unsupported_claim | pending | No agent answer or cited excerpts were provided to support the two claims. |
| NU03 | calculation | retrieval_document_miss, citation_missing_or_semantically_unsupported, claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, goal_not_achieved, unsupported_claim | stopped | The answer refused to compute despite all needed inputs being present in the prompt and source. |
| NU04 | calculation | claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, goal_not_achieved | stopped | The answer refused to compute the slope despite the problem providing all needed values. |
| NU05 | calculation | claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, unnecessary_refusal_or_clarification, goal_not_achieved, unsupported_claim | pending | No answer was provided, so neither the weighting method nor the 117 stb/d result was supported. |
| NU06 | calculation | claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, unnecessary_refusal_or_clarification, goal_not_achieved, unsupported_claim | pending | No agent answer was provided, so neither claim is supported. |
| NU07 | calculation | claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, unnecessary_refusal_or_clarification, goal_not_achieved, unsupported_claim | pending | No answer was provided, so neither expected claim is supported. |
| NU08 | calculation | claim_coverage, missing_validated_CALC, wrong_numeric_result, goal_not_achieved | stopped | The answer refused to compute despite the question being answerable, but the cited excerpts do not support the refusal. |
| NU09 | calculation | claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, unnecessary_refusal_or_clarification, goal_not_achieved, unsupported_claim | pending | No answer was provided, so neither claim is supported. |
| NU10 | calculation | claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, unnecessary_refusal_or_clarification, goal_not_achieved, unsupported_claim | stopped | The answer refused despite the problem being fully specified and did not compute the 350 psi drop or 0.10 fraction. |
| CR01 | conditional_reasoning | retrieval_page_miss, citation_missing_or_semantically_unsupported, claim_coverage, goal_not_achieved | stopped | The answer refused to answer despite the cited source excerpt directly supporting both pressure-constraint claims. |
| CR02 | conditional_reasoning | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, goal_not_achieved | stopped | The answer refused to answer despite the cited passage directly supporting the conditional correction rule. |
| CR03 | conditional_reasoning | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, goal_not_achieved | stopped | The answer refused to use the cited passage even though it directly supports IPO for casing/injection pressure and TPO for tubing pressure. |
| CR05 | conditional_reasoning | retrieval_page_miss, citation_missing_or_semantically_unsupported, claim_coverage, hallucination_or_engineering_contradiction, unsupported_claim | achieved | The answer cites unsupported complementary logs and does not use the cited deep-resistivity passage. |
| TC01 | terminology_confusion | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, goal_not_achieved, terminology_confusion | stopped | The answer refused despite cited passages that do support both claims about positive skin and the unaltered formation. |
| TC02 | terminology_confusion | retrieval_document_miss, citation_missing_or_semantically_unsupported, claim_coverage, goal_not_achieved, terminology_confusion | stopped | The answer refused to provide support, but the cited passage does support both claims about the side-pocket mandrel and the gas-lift valve. |
| TC05 | terminology_confusion | retrieval_document_miss, citation_missing_or_semantically_unsupported, claim_coverage, unnecessary_refusal_or_clarification, goal_not_achieved, terminology_confusion | pending | The agent refused due to missing inputs, but the task was answerable from the provided source and no exact answer was given. |
| FP01 | false_premise | retrieval_page_miss, citation_missing_or_semantically_unsupported, claim_coverage, goal_not_achieved, false_premise_not_explicitly_corrected | stopped | The answer refused to give the supported correction despite cited excerpts stating mud must exceed pore pressure and not exceed fracture pressure. |
| FP02 | false_premise | citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, false_premise_not_explicitly_corrected, hallucination_or_engineering_contradiction, unsupported_claim | achieved | The answer incorrectly says negative skin reflects damage-related permeability reduction, while the cited sources say positive skin indicates damage and negative skin indicates permeability enhancement. |
| FP03 | false_premise | relevant_evidence_but_answer_incomplete, claim_coverage, false_premise_not_explicitly_corrected, hallucination_or_engineering_contradiction, unsupported_claim | achieved | The answer swaps IPO and TPO pressure control, contradicting the cited material. |
| FP04 | false_premise | retrieval_document_miss, citation_missing_or_semantically_unsupported, claim_coverage, goal_not_achieved, false_premise_not_explicitly_corrected | stopped | The answer refused to provide the requested interpretation, and the cited excerpts do not support the refusal or the VDL bonding explanation. |
| UA01 | unanswerable | unanswerable_fabrication_or_no_safe_response | stopped | The answer correctly refuses to invent permeability and asks for more data. |
| UA03 | unanswerable | unanswerable_fabrication_or_no_safe_response | stopped | The answer correctly refused an exact density and the cited excerpts support needing pressure, temperature, composition, and property data. |
| UA04 | unanswerable | unanswerable_fabrication_or_no_safe_response | stopped | The answer appropriately refused to invent an exact influx value and the cited excerpts support that aquifer influx depends on missing reservoir/aquifer inputs and a model. |
| UA05 | unanswerable | unanswerable_fabrication_or_no_safe_response | stopped | The answer correctly refused to invent a valve depth and the cited sources support that missing design data are needed. |

## Interpretation / limitations

- Retrieval recall is computed against pre-frozen gold document/page metadata, not mere citation existence.
- Stage timings come from product telemetry and can overlap; do not sum them to estimate end-to-end latency.
- Strict goal success requires product achieved status, claim correctness, citation semantic support, and validated CALC for calculation tasks.
- One AI reviewer can misjudge semantics; selected failures merit expert audit before external claims.
- The reviewer occasionally credited gold passages even when the product showed only a generic abstention. Deterministic guard rules enforce the pre-registered requirement that the answer itself contain claims and name missing inputs. Original reviewer outputs are retained unchanged.
- This unseen set differs from prior versions and must not be represented as a paired v11/v12 gain.
- Source selection and hand-authored reference claims can carry errors; post-freeze corrections are prohibited and any errors should be marked INVALID.

## Recommended next step

Have a domain expert inspect the listed failures and gold spans, then design a separate future development set. Do not change this frozen run or merge v12 to main from this evaluation.
