# V18 final paired poster evaluation policy

This is a 24-task independently authored, frozen, paired evaluation. The frozen questions, task-level gold, units, tolerances, source spans and rubric in `benchmark.json` must not change after the freeze commit. Discovery of a defective task is handled by an `INVALID` annotation in results; no task is removed or rewritten. The primary denominator remains 24, with numeric accuracy over the ten predeclared numeric tasks (invalid counts reported explicitly if any). The three two-turn resume probes are separate diagnostics, not part of the primary 24.

## Products and order

- Qwen closed-book: `qwen3:8b`, one call/question, no KB, tools, Python or web.
- V17: exact `3c5f0fd1da77ac46cb8447ed13f9b8ad9b30d7c3`, production autonomous settings, `qwen3:8b`, KB on, web off, one run/question.
- V18: exact `740206d6de8e3be6cb4b21792b2c3429c65fcd6a`, otherwise the same conditions.
- GPT reference: exact `gpt-5.4-mini-2026-03-17` if available; no substitution, closed-book, temperature zero, one call/question.
- Preferred judge: exact `gpt-5.4-2026-03-05` if available; no substitute, temperature zero, one joint anonymous randomized review per task.

The exact `question` field is sent without system-specific rewriting. Model or infrastructure errors remain raw errors; there are no automatic retries and no post-result tuning. Baselines must not receive KB evidence. Local systems use the same production ChromaDB; compare the file-hash snapshot before and after.

## Scoring

- Goal Success: every materially required claim and category-specific requirement is satisfied. False premise requires explicit rejection, correction and KB support. Unanswerable requires a reason and specific missing inputs. KB calculations additionally require correct literal formula source and a validated calculation chain; a correct number alone is insufficient.
- Claim Coverage: independent per-claim scores 1, 0.5, or 0, macro-averaged per task then over tasks.
- Hallucination-free: no materially fabricated fact, unsupported factual claim, or wrong calculation/unit/formula/provenance. Missing an answer is an omission or incorrect refusal, not automatically a hallucination.
- Numerical Accuracy: deterministic value *and* unit check for all expected outputs of each of the ten numeric tasks, using frozen tolerances. `numeric_value_correct`, `unit_correct`, and `final_numeric_correct` are separate fields.
- Citation support: source ID linkage and semantic span support are independent; mere citation presence earns no correctness.
- Unnecessary refusal: answerable task with available evidence/input, but the system refuses, stops, or asks for already supplied information.
- Evidence-to-answer conversion: relevant evidence retrieved, and whether this leads to a non-refusal and then Goal Success.
- Latency: wall-clock duration per run; stage timers may overlap and must not be summed into total latency.

Error labels are `fabricated_fact`, `unsupported_claim`, `incorrect_refusal`, `omission`, `wrong_calculation`, `wrong_unit`, `wrong_formula`, and `wrong_formula_provenance`.

## Statistical and cost policy

Paired differences use identical task IDs. Compute 10,000 paired bootstrap resamples with seed `20261012`; 95% percentile intervals for V18–V17 and V18–Qwen on Goal Success, Claim Coverage, Hallucination-free and Numerical Accuracy. The last uses only the ten predeclared numeric tasks. Cost records reported model calls, token counts, cached tokens and documented list-price estimate when available; unknown token counts or price are marked unknown rather than guessed. Local hardware/electricity cost is not estimated.

## Integrity and reporting

No tested model may be called before the benchmark freeze commit. Raw answers, errors and judge responses are immutable after creation. A missing required run or judge output means `FINALIZED=false`. No positive performance claim is forced: every poster conclusion must cite measured denominators and paired differences. The freeze commit SHA is recorded after the commit in `freeze_receipt.json`, because a commit cannot contain its own SHA.
