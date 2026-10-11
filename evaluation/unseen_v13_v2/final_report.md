# v13 independent unseen evaluation v2

Tested product commit: 32de96cac75f6a96463e5ccebc24eab2eb061fe0
Product modified during evaluation: NO
Dataset frozen before execution: YES
Prior unseen questions used for tuning: NO
OpenAI reviewer: gpt-5.4-mini-2026-03-17
main merge: NO

Dataset: 50 tasks, SHA256 `3ad693ca1cd4a365f78801ad5a6a15784e36e046767e7b94ef6a0d7d3c9fee8c`, freeze commit `501a5a8eb47656c2e8faf8354e8bddc722dc0b8e`.
Local Agent: qwen3:8b; hybrid; existing Chroma 12 documents/18,976 chunks; web OFF.
The requested underscore reviewer ID was unavailable (HTTP 404); the official dotted snapshot with the same date was fixed for the whole run.
Single-reviewer AI-assisted semantic adjudication; no human review claim.
Pre-registered decision: **FAIL**.

## Overall metrics

| Metric | Value |
|---|---:|
| n | 50 |
| source_answerable_n | 36 |
| calculation_n | 15 |
| false_premise_n | 4 |
| unanswerable_n | 4 |
| goal_success_pct | 16.0 |
| exact_accuracy_pct | 16.0 |
| partial_or_better_pct | 34.0 |
| claim_coverage_pct | 29.55 |
| hallucination_pct | 14.0 |
| unsupported_claims_total | 27 |
| document_recall_at_k_pct | 76.39 |
| page_recall_at_k_pct | 33.33 |
| citation_id_correctness_pct | 36.11 |
| citation_semantic_support_pct | 30.56 |
| numeric_accuracy_pct | 20.0 |
| unit_accuracy_pct | 20.0 |
| validated_calc_pct | 20.0 |
| operand_binding_pct | 20.0 |
| kb_formula_source_correctness_pct | 0.0 |
| false_premise_handling_pct | 25.0 |
| unanswerable_safe_handling_pct | 0.0 |
| mean_latency_seconds | 21.164 |
| median_latency_seconds | 20.262 |
| review_cost_usd | 0.0992 |

## Reviewer API usage and cost

- Fixed Responses calls: 50; no-cost model lookups: 2; total OpenAI HTTP requests: 52.
- Input tokens: 96,105; output tokens: 6,022; estimated on-demand cost: $0.0992 versus $2.00 hard cap.
- Cost is computed from returned usage and [official GPT-5.4 Mini pricing](https://developers.openai.com/api/docs/models/gpt-5.4-mini), not independently reconciled to a billing invoice.


## Category and difficulty

| Slice | n | Strict success % | Exact accuracy % | Hallucination % |
|---|---:|---:|---:|---:|
| category:cause_effect | 4 | 0.0 | 0.0 | 0.0 |
| category:comparison | 4 | 25.0 | 25.0 | 0.0 |
| category:conditional_reasoning | 4 | 0.0 | 0.0 | 50.0 |
| category:direct_calculation | 5 | 0.0 | 0.0 | 0.0 |
| category:false_premise | 4 | 25.0 | 25.0 | 50.0 |
| category:kb_formula_calculation | 5 | 0.0 | 0.0 | 0.0 |
| category:multi_source | 4 | 25.0 | 25.0 | 25.0 |
| category:single_fact | 8 | 12.5 | 12.5 | 0.0 |
| category:terminology_confusion | 3 | 66.67 | 66.67 | 33.33 |
| category:unanswerable | 4 | 0.0 | 0.0 | 0.0 |
| category:user_formula_calculation | 5 | 40.0 | 40.0 | 20.0 |
| difficulty:easy | 8 | 12.5 | 12.5 | 0.0 |
| difficulty:hard | 16 | 18.75 | 18.75 | 18.75 |
| difficulty:medium | 26 | 15.38 | 15.38 | 15.38 |

## Failure patterns (non-exclusive labels)

- Retrieval was marked in 19 failed tasks. Document recall was 76.39%, but exact-page recall was only 33.33%; this is a source-location gap, not proof that original PDFs lost content.
- Citation grounding was marked in 25 failures. Only 36.11% of source-dependent answerable tasks used valid citation IDs, and 30.56% met both ID and semantic-support checks.
- Calculation: direct 0/5, user-formula 2/5, KB-formula 0/5. Validated CALC was 20.0% across 15 calculation tasks. Routing/binding and formula selection were marked in 10/12/5 failed tasks, respectively.
- False-premise correction succeeded in 1/4; specific safe handling succeeded in 0/4.
- 27 unsupported claims and 7 material-hallucination/contradiction task flags were recorded. The 36 verification labels overlap other failure types and are not a separate root-cause count.


## Failed tasks and pre-registered failure types

| ID | Category | Failure types | Reviewer observation |
|---|---|---|---|
| SF01 | single_fact | citation_grounding, retrieval, verification |  |
| SF02 | single_fact | citation_grounding, retrieval, unsupported_extra_claim, verification | The visible answer is a safe refusal stating that no direct supporting evidence was found. However, the gold passage explicitly defines lost circulation/lost returns as the loss of whole mud to a formation due to caverns, fractures, or highly permeable beds, so the refusal is unnecessary and the claim is unsupported by the answer. |
| SF04 | single_fact | citation_grounding, retrieval, unsupported_extra_claim, verification | The visible answer is a safe refusal stating it could not find direct support. However, the gold passage does support the claim that cement channeling is the irregular displacement of mud by cement, leaving voids in the cement sheath. The answer therefore fails to use available support, but it does not fabricate a contradictory claim. |
| SF05 | single_fact | citation_grounding, retrieval, unsupported_extra_claim, verification | The visible answer says the retrieved sources did not directly support an answer, but the cited formation-evaluation excerpt explicitly states that the Gamma Ray log is primarily used to differentiate between shales and other formation types. The expected claim is supported, so the answer is unsupported/refusal-like rather than correct. |
| SF06 | single_fact | citation_grounding, retrieval, verification | The visible answer is a safe refusal stating no direct supporting evidence was found. It does not assert the two expected claims, so neither claim is supported by the answer. |
| SF07 | single_fact | citation_grounding, retrieval, unsupported_extra_claim, verification | The visible answer refuses to answer, but the cited gold excerpt directly supports both claims: numerical dispersion is due to both spatial (Δx) and time (Δt) discretisation/truncation error. Therefore neither claim is supported by the visible answer. |
| SF08 | single_fact | citation_grounding, verification |  |
| MS01 | multi_source | citation_grounding, retrieval, verification | The visible answer is a refusal stating the sources did not directly support an answer, so it does not support either frozen claim. No fabrication or contradiction is present. |
| MS02 | multi_source | citation_grounding, retrieval, verification | Visible answer is a refusal stating no direct supporting evidence was found, so it does not support either expected claim. The response is safe but unhelpful; it does not answer the question or use the provided sources. |
| MS04 | multi_source | unsupported_extra_claim, verification | Claim 1 is supported by KB1. Claim 2 is not supported as written: the cited sources support that lower mobility ratio improves water/oil displacement recovery efficiency, but the visible answer instead discusses stability when M<1 and adds unsupported/general statements about waterflood sweep and mobility ratio calculation. It also contains an engineering contradiction by implying M<1 means stable displacement, which is supported by KB5, but the answer does not connect this to improved recovery efficiency as required. |
| CE01 | cause_effect | citation_grounding, verification | The visible answer refuses to answer and does not state the two frozen claims; however the cited source KB4 directly supports both claims: overbalance forces mud filtrate into permeable formation, and mud solids deposit on the borehole wall forming mudcake. |
| CE02 | cause_effect | citation_grounding, retrieval, verification | Visible answer is a safe refusal stating no direct supporting evidence was found. It does not assert either frozen claim, so both claim_supported booleans are false. |
| CE03 | cause_effect | citation_grounding, retrieval, unsupported_extra_claim, verification | The visible answer refuses to answer and does not support either frozen claim. The cited source excerpt S20 directly supports both that depletion/skin reduces well production rate and that this reduces the critical water cut at which natural flow ceases, but the answer does not state these claims. |
| CE04 | cause_effect | citation_grounding, retrieval, verification | Visible answer is a safe refusal asking for an unrelated missing value (L) and does not address either claim. No substantive claim is supported. |
| CO01 | comparison | citation_grounding, verification |  |
| CO02 | comparison | citation_grounding, verification |  |
| CO04 | comparison | citation_grounding, retrieval, verification | The visible answer is a refusal stating the sources did not directly support an answer, so it does not support either frozen claim. |
| DC01 | direct_calculation | extraction_binding, routing, unsupported_extra_claim, verification | The visible answer refuses to answer and does not state the combined injected volume. The cited sources are irrelevant to the arithmetic question, so the expected claim is unsupported. |
| DC02 | direct_calculation | extraction_binding, routing, unsupported_extra_claim, verification | The visible answer does not support the expected claim that pressure fell by 315 psi; it instead asks for missing input despite the question already providing start and end pressures. No calculation is performed. |
| DC03 | direct_calculation | extraction_binding, routing, verification | The visible answer is a safe refusal stating that the sources did not establish the equation or inputs and that no numerical result was calculated. It does not support the expected claim that oil rate increased by 25% relative to 760 stb/d, but it is not a hallucination. |
| DC04 | direct_calculation | calculation_execution, extraction_binding, verification | The visible answer is a safe refusal and does not state the median 27 MMscf/d, so the single expected claim is not supported. |
| DC05 | direct_calculation | extraction_binding, routing, unsupported_extra_claim, verification | The visible answer does not provide the requested water-minus-oil difference; it asks for missing input instead. This is a safe refusal, but the task was answerable from the prompt because the order is specified as water-minus-oil. |
| UF01 | user_formula_calculation | extraction_binding, routing, unsupported_extra_claim, verification | The visible answer does not support the expected claim. It asks for missing area input instead of using the provided operands (area=2,400,000 m², thickness=14 m, porosity=0.17) to compute E = 5,712,000 m³. |
| UF04 | user_formula_calculation | extraction_binding, routing, verification | Visible answer is a safe refusal asking for missing variable name, but the task already specifies the variable sweep (φ) and all needed inputs. It does not support any of the three expected calculation claims. |
| UF05 | user_formula_calculation | unsupported_extra_claim, verification | The answer supports the 600 psi difference via 3500-2900=600 and the numeric result 2.4, but it incorrectly labels C as psi instead of dimensionless. |
| KF01 | kb_formula_calculation | calculation_execution, citation_grounding, extraction_binding, formula_selection, retrieval, verification | The visible answer is a safe refusal and does not state either expected claim. It also does not cite the page or provide the calculation. |
| KF02 | kb_formula_calculation | citation_grounding, extraction_binding, formula_selection, retrieval, routing, verification | The visible answer is a safe refusal asking for Ro, but the task already supplies Ro=7.2 ohm-m and Sw=0.40. It does not answer the two frozen claims, so both are unsupported by the visible answer. |
| KF03 | kb_formula_calculation | citation_grounding, extraction_binding, formula_selection, routing, unsupported_extra_claim, verification | The visible answer refuses to calculate, so it does not support either frozen claim. The cited source does support that shrinkage factor is the reciprocal of Bo, and with Bo=1.25 the implied value would be 0.8 STB/reservoir bbl, but that calculation is absent from the answer. |
| KF04 | kb_formula_calculation | citation_grounding, extraction_binding, formula_selection, retrieval, routing, verification | The visible answer is a safe request for missing information and does not state either frozen claim. It does not provide the defining span or the computed value, so neither claim is supported. |
| KF05 | kb_formula_calculation | citation_grounding, extraction_binding, formula_selection, routing, verification |  |
| CR01 | conditional_reasoning | unsupported_extra_claim, verification | First claim is supported by the cited passage describing mud filtrate forced into the permeable formation under mud-column overpressure. Second frozen claim is not stated in the visible answer, which mentions only filtrate invasion and omits mudcake deposition. |
| CR02 | conditional_reasoning | citation_grounding, retrieval, unsupported_extra_claim, verification | Visible answer cites an unrelated/unsupported excerpt about dissolved gas drive and gas cap formation (KB3) rather than the needed claim that below bubble point solution gas drive can occur with rising GOR and that water drive plus solution gas drive can form combination drive. The answer does not explicitly support either frozen claim. |
| CR03 | conditional_reasoning | citation_grounding, unsupported_extra_claim, verification | The visible answer refuses to answer and does not state the two frozen claims. The cited sources do support both underlying claims, but the answer itself does not. |
| CR04 | conditional_reasoning | unsupported_extra_claim, verification | First claim is supported: the cited source says exceeding the critical oil production rate forms a water cone. Second claim is not supported and is partly contradicted: the source offers coning suppression perforations with an inverted ESP injecting water into an injection zone, not downhole hydrocyclone separation into a disposal zone as stated in the visible answer. |
| TC01 | terminology_confusion | citation_grounding, unsupported_extra_claim, verification | The visible answer does not address the frozen claim about shrinkage factor vs Bo; it instead quotes an unrelated statement about gas release and formation volume factor. The cited source excerpt KB3 does support that the reciprocal of Bo is the shrinkage factor, but the answer did not make that claim. |
| FP02 | false_premise | false_premise, retrieval, unsupported_extra_claim | The answer correctly rejects the premise and defines lost circulation as mud loss to the formation, but it also adds an unsupported/incorrect framing about 'formation fluid entering the borehole because mud pressure is too low,' which is not supported by the cited sources. |
| FP03 | false_premise | citation_grounding, false_premise, retrieval, verification | The visible answer only says it could not find direct support, so it does not support either expected claim. |
| FP04 | false_premise | false_premise, retrieval, unsupported_extra_claim | The answer correctly rejects the identical-mechanism premise and distinguishes gas lift gas injection/reduced hydrostatic head from pump-supplied mechanical energy. However, it adds unsupported specifics about an ESP and an electric motor that are not needed for the frozen claims. |
| UA01 | unanswerable | unanswerable_handling |  |
| UA02 | unanswerable | unanswerable_handling | The visible answer safely refuses to compute and notes missing source support, but it does not explicitly identify the missing annulus geometry and cemented length required by the second frozen claim. |
| UA03 | unanswerable | unanswerable_handling |  |
| UA04 | unanswerable | unanswerable_handling |  |

## Interpretation

Calculations require the right final number and unit, validated contract-complete CALC, and correct operand binding; KB formula tasks additionally require formula-source provenance on the gold page.
A source citation counts only if its ID exists in the run and the fixed reviewer finds semantic support in the cited excerpt.
One AI reviewer can make semantic mistakes. The sealed benchmark and raw outputs are retained for later independent human inspection, not post-hoc retuning.
For example, the FP04 reviewer flagged the cited electric-submersible-pump detail as unsupported even though its quoted excerpt mentions that detail; this possible reviewer false positive was not post-hoc overridden.
This dataset differs from v12 unseen; no paired score-improvement claim is made.

## Next step

Preserve this sealed result and start a separate development cycle; do not hotfix against these questions.
