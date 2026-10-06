# Python Tool Heldout v5 — Frozen Evaluation Policy

This is an unseen, exploratory evaluation of product SHA
`8a720a02caa557a893c4d75245bed01df565b85f`. It is not a v5/v6
version comparison. The 12 tasks contain 8 Python-required, 2 optional and 2
not-needed cases. Required cases split into 4 direct pipeline, 2
source-topology recovery challenges and 2 end-to-end cases.

Before freeze, deterministic preflight may inspect source chunks and run the
three registries and independent reference calculator. It must not run the
Agent, planner, product binder, checklist, contract, retrieval test or an LLM.
All user facts, required evidence facts and source formulas must be directly
representable, all source locators/hash values must match, old exact source
document/page and chunk overlap must be zero, and GT conflicts must be zero.
Failure blocks freeze and all Agent runs.

After freeze, task wording, criteria, canonical targets, tolerance, rubric,
source catalog and reference arithmetic are immutable. The manifest may be
filled with the freeze commit SHA without changing those frozen assets.
The runner verifies frozen hashes, GT consistency, product ancestry and
unchanged product files, and the real 18,976-chunk/12-document KB before task 1.

One complete paired run only: all 12 Python OFF, followed by all 12 Python ON,
with qwen3:8b, temperature 0, seed 42, internal KB only, no web, default
legacy retrieval, default top-k and goal loop. Only Python permission differs.
No failed-task or selective reruns. Preserve any partial output. Infrastructure
failure before task 1 permits a fresh start; infrastructure failure after any
task output invalidates the full baseline unless the failure can be scored as a
product behavior. Product failures are scored, not repaired.

Independent deterministic scoring is authoritative for numbers, units, typed
outputs, ranking, source completeness, binding, contracts and CALC correctness.
One blind gemma4:latest reviewer may assess qualitative claims only, without
condition or internal-tool state. Manual QA covers all 24 answers. Raw review
is immutable; adjudication is a separate artifact. Paired bootstrap uses
10,000 samples and seed 42. Strong Python Benefit requires an OFF criterion
failure, an ON GT-correct CALC grounded in the final answer, and the matching
ON criterion pass. Mere ON improvement is not attributed to Python.

Do not call OpenAI or Gemini APIs, merge main, alter product code, rerun old
heldouts or modify frozen results after inspecting the A/B outcome.
