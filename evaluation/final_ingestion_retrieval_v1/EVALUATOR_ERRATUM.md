# Post-freeze evaluator erratum

The rubric, product commit, inference requests, raw answers, retrieval probe, and original `gemma4:latest` reviewer output remain frozen. After all 30×2 answers had been reviewed, an audit of the first-pass scorer found evaluation errors. This file documents the correction **before publication**, not a product change or a rerun.

The original scorer accepted several claims simply because the gold statement or retrieved evidence was present in the reviewer context. Examples: FIR-007, FIR-010, FIR-012, FIR-015 and FIR-021 were marked correct for the Agent despite an empty final answer; FIR-011 and FIR-029 were marked correct despite generic calculation refusals and no validated calculation. The reviewer also returned `citation_support` as strings/lists instead of booleans in some rows, omitted some required claim indices, and sometimes treated the closed-book baseline's deliberate lack of private evidence as factual hallucination. Therefore the first-pass answer metrics are **not valid for reporting**.

`aggregate_corrected.py` applies the frozen answer-vs-grounding distinction consistently to both systems:

1. Score the actual final answer, with empty and generic safe-stop answers failing answerable questions. An unanswerable question can pass with a non-fabricated refusal.
2. Require every rubric numeric result and unit judgment to be present/correct in the actual answer. A count of enumerated functions can be satisfied by the enumerated claims rather than a numeral. A source-specific decimal coefficient cannot be replaced by a nearby constant.
3. Treat missing applicable reviewer fields or claim indices as failures, not success. Require a validated Agent CALC where the rubric explicitly calls for one.
4. Normalize typed citation IDs only when they occur in the final answer and are returned source IDs; otherwise the semantic citation support is false.
5. Do not mistake a closed-book model's disclaimer that it cannot verify the private book for a refusal if it still gives every required substantive answer. Do not count its lack of private evidence as hallucination when the reviewer otherwise marked all gold claims correct. Grounded/retrieval metrics remain N/A for this comparator.
6. Preserve the single-reviewer outputs, and apply four narrowly documented factual QA corrections in `reviewer_quality_control.json`. These are visible row-by-row, not silent replacements or rubric edits.

This evaluation is still limited by one AI reviewer, a small heterogeneous 30-question sample, and the absence of an independent human adjudication panel. The corrected scores are descriptive, not confidence intervals or a claim of superiority. The verbatim-question retrieval probe is not the Agent planner's actual retrieval query. Neither the frozen product nor the benchmark questions were changed in response to these results.
