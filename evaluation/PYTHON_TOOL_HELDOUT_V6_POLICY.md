# Python Tool Heldout v6 — Frozen Evaluation Policy

This is an unseen exploratory evaluation of product SHA
`ec987f074648a6eb442b911044dff4808bc87d84`, not a product-version
comparison. The twelve tasks comprise eight Python-required, two optional,
and two not-needed cases. Required strata are two generic-direct, three
specialist-direct, one recovery-challenge, and two end-to-end cases. Domains
are reservoir engineering 5, well test 4, and formation evaluation 3.

Before freeze, deterministic preflight may inspect exact existing KB chunks,
run UserFactRegistry, EvidenceFactRegistry, FormulaSourceRegistry, and the
independent reference calculator. It must not call an Agent, planner, product
IR/checklist/resolver/binder/contract, retrieval query, or LLM. All required
facts and formulas must be representable, source locators and hashes must
match, old exact document/page and chunk overlap must be zero, and independent
GT conflicts must be zero. Any failure blocks freeze and all Agent runs.

After freeze, the task wording, criteria, rubric, source catalog/exclusions,
reference calculator, targets and tolerances are immutable. The manifest may
be filled with the freeze commit SHA without changing any frozen asset.
The runner verifies hashes against the freeze commit, product ancestry,
unchanged application files, and the real 18,976-chunk, 12-document KB before
task one.

Only one complete pair is allowed: all twelve Python OFF, followed by all
twelve Python ON, with qwen3:8b, temperature 0, seed 42, internal KB only,
no web, legacy retrieval, and default top-k/goal-loop settings. Only Python
permission differs. No selective reruns or post-outcome edits. Preserve partial
output and invalidate the baseline after a post-task infrastructure failure;
product failures are scored.

Independent deterministic scoring is authoritative for numeric values,
units, typed/ranking outputs, source completeness, binding, contracts and
CALC correctness. One blind gemma4:latest reviewer judges qualitative claims
only, without condition or tool-state labels. Manual QA covers all 24
answers. Raw review is immutable and adjudication is a separate artifact.
Paired bootstrap uses 10,000 samples and seed 42. Strong Python Benefit
requires an OFF criterion failure, an ON GT-correct CALC grounded in the
final answer, and matching ON criterion pass. Mere improvement is not
attributed to Python.

Do not call OpenAI or Gemini APIs, merge main, alter product code, rerun old
heldouts, create or reindex the KB, or modify frozen results after inspection.
