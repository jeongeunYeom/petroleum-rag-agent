# V21.2 final unseen V3 evaluation policy

This protocol is fixed before the benchmark freeze and before any evaluated model call. The evaluated product is commit `f5182b8ae2907452e1c53373055e66c5182c9b90`. The V2 evaluation is observed and is not a final unseen estimate; its question text may be processed only mechanically to exclude prior source pages and detect near duplicates.

## Scope and denominators

- Exactly 36 newly authored primary tasks: knowledge QA 8, multi-claim reasoning 6, direct calculation 6, user formula 4, KB formula 6, false premise 3, unanswerable 3.
- Exactly 16 numeric tasks (6 direct, 4 user-formula, 6 KB-formula), 12 Korean questions with English source material, 6 multi-goal tasks, and 4 independent two-turn resume probes outside the primary denominator.
- Source-dependent tasks use document/page pairs not present in the mechanically constructed prior-use exclusion set. The source pool is sampled with seed `20261013` before question authoring. Novelty threshold is maximum character-four-gram Jaccard similarity `0.45` against prior development and evaluation prompts; a separate multilingual BGE-M3 embedding screen rejects semantic cosine above `0.90`. Neither screen exposes prior question text to the author. Invalid candidates are rejected before freeze; replacement uses the next predetermined source candidate.
- Gold, rubric, and source spans are never passed to evaluated systems. Product code, benchmark, rubric, and Chroma files remain unchanged after freeze. Web is off; hybrid retrieval and the production 12-document, 18,976-chunk KB are required.

## One-shot generation and technical failures

Each system receives one generation attempt per task, with an attempt reservation written before generation. There are no generation retries, question replacements, timeout changes, output-limit changes, or score-based reruns. Polling an already-created Agent `run_id` is part of the same attempt and is allowed; creating a replacement run is not.

If the sole attempt ends in an HTTP/read timeout, process crash, transport/model-server error, or malformed empty transport response, preserve the raw error and write the deterministic answer record `response_status="technical_failure"`, `answer_text=""`, `technical_failure=true`. Continue with remaining tasks. The technical failure is the system's outcome on that task.

For a technical failure, Goal Success = 0; atomic Claim Coverage = 0; Numerical Accuracy = 0 if numeric; Citation Support = 0 where required. It is **not** an unnecessary refusal. Hallucination = false and Hallucination-free = true because no factual answer was produced. A semantic judge may receive `[NO RESPONSE — TECHNICAL FAILURE]`, but deterministic failure scoring overrides any semantic interpretation.

If **more than 20%** of primary tasks for any required system end in technical failure, set `FINALIZED=false` with reason `systemic evaluation infrastructure failure`; do not publish final performance claims. At or below 20%, retain the failures in the denominators and continue. Apply this rule symmetrically.

## Systems and scoring

- Required systems: `qwen3:8b` closed-book (no retrieval/tools/Python) and frozen V21.2 unified autonomous Agent (normal product settings, hybrid KB, web off). Optional GPT reference: exact `gpt-5.4-mini-2026-03-17`, closed-book, no tools.
- Semantic judge: exact `gpt-5.4-2026-03-05`, temperature 0. If unavailable, `FINALIZED=false`; no substitute. Blind each answer with an independently randomized anonymous label, omitting system/model/version. Judge completed answers once per system/task using question, atomic rubric, and allowed source evidence. Technical failures receive the deterministic score above.
- Goal Success requires every materially required goal. KB-formula tasks additionally require correct literal formula source, a validated calculation path, and correct numeric output. False-premise success requires rejection/correction plus support. Unanswerable success requires identifying the specific missing information without inventing a result.
- Atomic Claim Coverage: full 1, partial 0.5, absent/wrong 0; average within task, then across 36 tasks. Hallucination failure includes material fabrication, unsupported source assertion, wrong equation/calculation/unit, fabricated provenance, or unjustified certainty. Numerical Accuracy is all-or-nothing for every critical requested number and compatible unit, across exactly 16 tasks.
- Paired bootstrap Agent minus Qwen: 10,000 resamples, seed `20261013`, percentile 95% CI, n=36 for Goal Success/Claim Coverage/Hallucination-free and n=16 for Numerical Accuracy. If GPT reference is available, compute Agent minus GPT too. If CI contains zero, report `descriptive difference; superiority not established`.

## Finalization

`FINALIZED=true` only when frozen benchmark/rubric/product/KB are unchanged, exact judge available, all 36 task records exist for each required system with exactly one unique generation attempt each, technical failures are deterministically scored, no required system exceeds 20% technical failures, and all score rows are complete. If finalized, results are final regardless of their direction or magnitude. No product patch, benchmark replacement, rubric change, or rerun is permitted.
