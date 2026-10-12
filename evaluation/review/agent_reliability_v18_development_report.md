# Agent reliability v18 — development verification

This is a narrow reliability patch on `feature/agent-reliability-v18`, based on
`feature/agent-reliability-v17` at `3c5f0fd1da77ac46cb8447ed13f9b8ad9b30d7c3`.
It is **not** a final or unseen benchmark result.

## Changes and failure mechanisms

| Area | Failure mechanism | Patch |
| --- | --- | --- |
| Calculation routing | A formula or ordered operands could be parsed, yet readiness was not consistently checked before the action choice. | Check literal variable bindings and unit algebra before Python; record expected/bound/missing variables and deterministic route selection. Keep direct inputs off the retrieval path and source-required formulas on it. |
| Operand meaning | Equal-unit quantities can have distinct initial/final, inlet/outlet, recovered/injected roles. | Retain the literal value, unit and span; add a separate order-bearing role while preserving physical dimension. Accept unique role bindings, never a same-unit guess. |
| KB formula transition | A selected source relation could fall back to planning even with complete literal inputs; explicit prose definitions were not recognized. | Admit only narrowly structured ratio/minus definitions with exact source spans; maintain AST and source-span validation. Permit deterministic source-backed calculation when inputs are complete. |
| Final result | A validated compound-unit result could be rejected by the final claim checker because it read only the first unit atom; ranking-only results could stall at ANALYZE. | Match complete known compound units and allow a validated ranking manifest to satisfy ANALYZE. Preserve validated calculation text from later LLM rewriting. |
| Grounded QA | Semantic support could be established, then an additional synthesis/evaluation path could still refuse or delay the answer. | Once every required claim has an exact, engineering-validated span and no conflict, use a deterministic grounded answer and record VERIFY. Partial support remains partial, not achieved. |
| Clarification | A common explicit “from this information alone” underdetermination cue was misrouted as a calculation. | Route it to source answerability. Ask only for specifically missing inputs; English clarification renders variable/value/unit language in English. |

The source-quality policy, retrieval stack, model settings, sandbox, provenance gate,
EngineeringValidator, ChromaDB, and frontend product code were not changed.

## Synthetic development regression

`backend/tests/test_agent_reliability_v18_dev.py`: **29/29 passed**.

- Full-agent direct calculation: **8/8 achieved**, no KB retrieval or clarification.
- Full-agent user-equation calculation: **5/5 achieved**, 5/5 validated Python calculations and units.
- Full-agent KB-equation calculation: **5/5 achieved**, all retrieved before calculation; 5/5 exact source IDs and validated outputs.
- Fully supported grounded questions: **4/4 achieved** using exact source spans; unnecessary refusals **0/4**.
- Partial and conflicting evidence: **2/2 safely not achieved**; the partially supported answer retained its supported statement, with **0 generic refusals** in that case.
- Other guards: missing-variable readiness, ambiguous ratio order, exact prose-definition span, malformed compound unit, same-run clarification/resume, irrelevant-year and duplicate-unit distractors.

All tests use fresh synthetic text and in-memory sources. They do not estimate production accuracy.

## Local-model development smoke

The final run used the real local `qwen3:8b`, GoalExecutionAgent, and bounded Python
sandbox with synthetic in-memory retrieval only: **9/9 passed**. The cases were
2 grounded questions, 2 direct calculations, 2 user equations, 2 KB equations,
and 1 explicitly underdetermined question. Calculations were **6/6 validated**;
their deterministic finalizer was used **6/6**. The source-answerability fast
path was used in **3/3** applicable cases. Full grounded questions had **0/2
unnecessary refusals**. There was no generic refusal in the underdetermined case.

The first development run was 8/9 because the English “from this information
alone” cue requested inputs instead of checking source answerability. The cue
was corrected; the second and final confirmation runs were both 9/9. The raw
development-only files are:

- `evaluation/review/agent_reliability_v18_dev_smoke.json` (initial 8/9)
- `evaluation/review/agent_reliability_v18_dev_smoke_r2.json` (9/9)
- `evaluation/review/agent_reliability_v18_dev_smoke_r3.json` (final 9/9)

## Regression and limits

- Backend: `python -m pytest -q` → **1,441 passed**, 6 existing dependency deprecation warnings.
- Frontend: `node --test tests/*.test.mjs` → **9 passed**.
- Frontend: `pnpm build` → **success**.
- This patch was verified with synthetic evidence, not the production 12-document
  knowledge base. No v17 final evaluation was rerun and no v18 final benchmark
  was created. Broader terminology, OCR-damaged equations, and ambiguous
  natural-language definitions still require caution; they must not bypass
  source-span, unit, or provenance validation.
- Frozen evaluation contents read: **NO**. Sealed evaluation rerun: **NO**.
  ChromaDB modified or reindexed: **NO**. Main merged: **NO**.
