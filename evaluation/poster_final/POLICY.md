# Frozen final poster pilot evaluation

26 questions. This is a small, source-authored pilot, not a publication-scale or
independently human-authored benchmark. Product is pinned before question writing.
No model answer is obtained before benchmark freeze. No post-result tuning,
question/reference changes, reruns of completed calls, model fallback or main merge.

Identical question strings are sent to both systems. Agent: local qwen3:8b, hybrid,
12 documents / 18,976 chunks, web off, autonomous from-message API, default bounded
six iterations. Baseline: API `gpt-5.4-mini-2026-03-17`, closed book, no tools/web.
The label ChatGPT denotes this API baseline, not the consumer ChatGPT application.
One run per system/task. Waiting-for-input is scored on the displayed clarification;
no hidden follow-up answers. Timeout 300 seconds per Agent task, failures retained.

## Primary metrics (same rule for both systems)

- Goal Success: all required core expected claims, correct result and units where
  applicable, and no material error. This is answer-level task success, not the
  Agent's internal achieved flag, Python usage or citation availability.
- Claim Coverage: macro mean of each question's expected-claim scores (0/.5/1).
- Hallucination-free: fraction of responses without a material unsupported or
  false factual assertion. Refusal can be hallucination-free but still fail success.
- Numerical Accuracy: fraction of ten numeric tasks with correct value within
  the frozen absolute tolerance and correct/equivalent units. A deterministic
  final-answer numeric-token check is a backstop; semantic judge checks meaning.
- Citation Semantic Support: Agent-only supplement, denominator responses with
  KB/FIG/WEB citations. Also report citation-bearing response count. No citation
  is N/A rather than silently counted as a supported citation.

Judge: fixed `gpt-5.4-2026-03-05`, temperature 0, reasoning none, no tools/web,
one paired randomized-label review per question. This is **single-reviewer
AI-assisted semantic adjudication**, not human review. References, exact source
pages, candidate answers and Agent citation metadata are supplied to the judge.
Both models are in the same provider family; blinding does not remove all bias.

Deterministic calculations cross-check frozen gold values. Valid numeric answers
must contain the appropriate value, not just receive a judge pass. Source-based
questions use PDF page indices, not printed page numbers. Engineering code excerpts
are historical textbook material, not current design compliance advice.

Dedup: old development/test/heldout and v12/v13 benchmark questions are inspected
by a separate screening script only after the product commit. Jaccard >= .60 or
local qwen3-embedding:0.6b cosine >= .86 flags a candidate for replacement/review
before freeze. Automated screening is imperfect; topic/operation overlap can
remain. No old answers are used for product tuning.

Uncertainty: report n and paired task-bootstrap 95% intervals (seed 14026, 10,000
resamples) for primary metric differences. Category strata are small. No claims
of population-wide superiority or v13-to-v14 causal improvement are justified.
The sample is facilities-heavy; show that limitation rather than hiding it.

Cost: 26 baseline and 26 judge calls, zero automatic retries, result checkpointing.
Look up both snapshots before generation. Record actual API usage and list-price
cost estimates, distinguishing these from the provider's invoiced amount.
