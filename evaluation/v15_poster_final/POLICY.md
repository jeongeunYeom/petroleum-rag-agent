# Frozen v15 final poster pilot policy

Product: `6b8b0e7850a24b79b337882b1de3184cb7993d04`. Evaluation-only branch `eval/v15-poster-final`. Main is not merged or modified. All new files are confined to this directory. Product, prompts, retrieval, embeddings and KB content remain fixed.

## Sampling and independence

24 newly authored tasks: Knowledge 6, Reasoning 4, direct calculation 4, user formula 3, KB formula 3, false premise 2, unanswerable 2. Numeric denominator: 10. Categories for reporting: Knowledge 6 / Reasoning 4 / Calculation 10 / Safety 4. This is a purposive small pilot, not a random sample of all petroleum questions.

Candidates were written from read-only existing Chroma passages and original arithmetic examples BEFORE inspecting old task strings. Old evaluation/development data were subsequently used only for duplicate screening. Exact normalized text, word/bigram and character TF-IDF cosine, and offline semantic LSA (192 dimensions) are compared across all Git refs and available local evaluation/test files. Review thresholds: lexical >=0.55 or LSA >=0.80; nearest neighbours are also manually reviewed for conceptual duplication even below thresholds. P14 was replaced before freeze to avoid a simple percentage-decrease template. Shared generic arithmetic operators are unavoidable; they do not establish copied tasks. LSA is not a neural multilingual semantic detector; independence cannot be guaranteed by a similarity score alone. No old answer/gold/raw was used as authoring material. Historical results are not pooled or used for causal v14-to-v15 improvement claims.

Gold documents, page metadata, exact stored chunk text, claims, formula relations, numeric outputs, units and absolute tolerances are frozen in benchmark.json. Acoustic depth has a literal verbal equation in the source. Reasoning tasks link at least two relationships/paragraphs; two do so within a single stored chunk. Evidence is not supplied to either tested system; only the judge sees gold. No task asks for new web access. All questions are English in this pilot.

## Freeze and collection

Freeze commit is created before the first inference. Its SHA is recorded afterward in a separate immutable freeze_receipt.json (avoids a self-referential commit hash); manifest records that receipt convention. Benchmark bytes are never edited after freeze. Single attempt per system/task, sequential Agent requests, no external harness retries or reruns. Existing bounded internal product repair is retained as production behaviour and is not an evaluation retry. Request attempt files are created exclusively before network submission; attempted rows are never resubmitted. Errors/timeouts remain in denominator. Agent deadline 600 seconds; cancellation and collection halt if completion is uncertain. GET polling is not model retry. A waiting clarification is scored as the actual first-turn answer; no invented user replies. No warm-up inference. Cold-start overhead remains in measured latency.

Agent: local `qwen3:8b`, `hybrid`, existing `petroleum_knowledge` Chroma (12 documents / 18,976 chunks), web OFF, autonomous `/api/research/goal-runs/from-message`, existing default max_iterations=6. Product source and KB metadata fingerprint verified before/after. Backend uses localhost port 8001. Production settings otherwise unchanged.

Closed-book baseline: `gpt-5.4-mini-2026-03-17`, temperature 0, reasoning_effort none, max_completion_tokens 2200, no tools/web/retrieval/files. Exact same question string; system instruction in run_evaluation.py. Judge: `gpt-5.4-2026-03-05`, temperature 0, reasoning_effort none, max_completion_tokens 6500, JSON response, no tools/web/fallback. Availability checked by API model listing before inference. One judge call per pair, random answer label order seed 15152026. Citation attachment may reveal RAG identity despite randomized labels; disclose this limitation. This is **single-reviewer AI-assisted semantic adjudication**, not human review.

## Common primary scoring

- Every frozen required claim: 0 missing/wrong, 0.5 partial, 1 fully satisfied. Claim Coverage is the mean per-task claim fraction, then macro mean across 24.
- Goal Success: every frozen claim scored 1, no material factual contradiction, and for numeric tasks ALL requested final outputs within frozen tolerance with correct/equivalent units. Judge success flag must also be true. Same rule for both systems. Primary scores do not require citations, Python or CALC from either system; these are separate Agent diagnostics.
- Hallucination-free: no material unsupported/false factual assertion. Correct general engineering elaboration is not unsupported merely because absent from the narrow gold passage. Specific invented case values, fabricated citations and false assertions fail. Refusals may be hallucination-free while failing goals. Empty/error responses score zero rather than receiving vacuous safety credit.
- Numerical Accuracy: all targets correct for a task, denominator exactly 10. Judge extracts clearly asserted final numeric values into the gold units and records the answer quote; deterministic tolerance comparison follows. Dimensionless answers do not require an explicit unit label. Equivalence conversion is allowed; copied inputs or gold without a final output are not accepted.
- No invalidation based on poor system performance. A demonstrable defective question may be logged INVALID without altering frozen bytes; any denominator change must be explicit.

## Supplementary and diagnostics

Agent Citation Semantic Support is supported citation-to-claim links / all audited citation-to-claim links, with numerator/denominator and citation-bearing responses /24 separately reported. Uncited answers are not in that link denominator. Nonexistent IDs fail. Do not put this metric in the two-system primary graph.

Save statuses, internal achieved, iterations, stage timings, action traces, actual Python calls, execution/validation/provenance records. Numeric diagnostics: appropriate routing, operand completeness, formula selection, execution, validated CALC; QA: relevant evidence retrieved, extractive fallback, unnecessary refusal, and relevant-evidence-but-goal-failure. Missing instrumentation is null/not measured, not false. No causal comparison with old pilot sets.

## Statistics, latency and cost

10,000 paired task bootstrap resamples, NumPy seed 15152026; two-sided percentile 95% CI for Agent minus baseline differences in percentage points. Resample all 24 aligned tasks for Goal Success, Claim Coverage, Hallucination-free; only 10 numeric tasks for Numerical Accuracy. Small-sample uncertainty and correlated topic families limit generalization. Mean/median/p95 single-request wall time includes infrastructure/cold-start; Agent stage timings are additionally retained.

Actual API usage is summed from response usage objects: input, output, cached-input tokens and calls per exact model. Estimated standard list price per million tokens: mini input $0.75 / cached $0.075 / output $4.50; judge input $2.50 / cached $0.25 / output $15. These are estimates, not provider invoices. Sources checked before calls: https://developers.openai.com/api/docs/models/gpt-5.4-mini and https://developers.openai.com/api/docs/models/gpt-5.4 . Local inference electricity/hardware cost is not estimated.

## Integrity and finalization

Require 24 usable Agent records, 24 baseline records, 24 judge reviews; no benchmark/product changes, identical KB counts and metadata fingerprint, one request attempt each, and main unchanged. Any mismatch => NOT FINALIZED. Preserve all raw requests/responses/errors. No product tests/heldout re-execution is needed for an evaluation-only change. All failures are reported. Results-only seal commit after charts/tables are verified. No post-result tuning.
