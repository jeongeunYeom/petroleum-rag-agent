# Agent task-completion v1 — development report

Date: 2026-10-17. Product base: `ade0d6ce133b57ef16b1892c09715643a04497d0`.
Branch: `fix/agent-task-completion-v1`. Evaluated product commit:
`b5b18cbc268f86bef5c683fe2867a30ab06b5643`. The benchmark source was the
previously seen `evaluation/final_ingestion_retrieval_v1` set. This is a
**development regression**, not a new unseen evaluation. No ChatGPT baseline was
run, and the frozen source records were not edited.

Environment: local `qwen3:8b`, `RETRIEVAL_MODE=hybrid`, existing production
ChromaDB at `D:\petroleum-rag-agent\data\vector_db` (12 documents, 19,248
chunks). No ingestion or Chroma rebuild was performed.

## 1. Root causes found

| Area | Trace-backed finding |
|---|---|
| Calculation | Formula and input facts could be present while readiness/action routing still chose retrieval or clarification. A validated one-output calculation could also be undermined by speculative LLM synthesis (FIR-010). |
| Over-refusal | Literal requested facts/equations and their citations were sometimes already present, but broad criteria or a generic `insufficient_evidence` decision blocked completion (p171/p172 earlier regression, FIR-004/025/026). |
| Figure | Repeated figure numbers required document/caption disambiguation. True spatial/photographic reading must not be answered with KB text alone. The correct figure can still lack a reliable local visual interpretation. |
| Retrieval | An explicit shortened title such as “Handbook II” was not a document constraint. Cross-document requests could search or cite only one named source. Preferred-page retrieval remains incomplete. |
| Synthesis | The answer writer can omit an explicit yes/no conclusion or requested numeric thresholds while the evaluator still marks criteria met (FIR-020, FIR-028). False-premise correction is also incomplete (FIR-023). |

## 2. Changes

- `calculation_requirements.py`, `calculation_contract.py`, `goal_research_agent.py`,
  `goal_action_planner.py`, and `goal_execution_agent.py`: deterministic formula
  readiness, bounded variable/unit checks, requested-output contracts, and
  compute transition; result synthesis can use a single validated sourced CALC
  only when its normalized equation matches a retrieved literal formula span.
- `goal_intent.py` and `goal_action_planner.py`: distinguish “find the equation
  used to calculate” from an instruction to actually calculate, including the
  duplicated topic/goal representation of from-message requests.
- `goal_claim_support.py`, `goal_execution_agent.py`: bind simple requested
  relation/value claims to evidence, permit grounded partial facts without
  fabricating dependent results, and record required claims, readiness,
  retrieval queries, coverage, actions, and stop reasons in telemetry.
- `document_constraint.py`, `research_agent.py`, `vector_store.py`: generic
  named-document scoping and fallback, numbered-volume shorthand, distinct
  retrieval for explicitly named multiple documents, and figure identity
  narrowing by document/context/caption.
- `research_agent.py` and `goal_execution_agent.py`: keep text-based Figure
  locator questions distinct from direct visual interpretation; a direct
  photograph/figure reading without a cited FIG result now refuses instead of
  presenting KB-only numeric text as image-grounded.
- Regression tests were added in `backend/tests/test_goal_execution_v8.py`,
  `test_goal_python_v7.py`, and `test_research_agent.py`. No frontend code was
  changed.

## 3. Verification

- Backend: `python -m pytest -q` — **836 passed**, 6 deprecation warnings.
- Frontend: Node component tests — **9 passed**; `pnpm build` — **passed**.
- GitHub Actions CI for product commit `b5b18cb` — **success**.
- Existing unsupported-formula behavior remained safe: FIR-024 stopped without
  Python or a fabricated number.

## 4. Before → after representative regressions

| Case | Earlier observed behavior | Product commit `b5b18cb` |
|---|---|---|
| Equation lookup (FIR-007) | Waited for `q` and `An` despite a formula-only request | `RETRIEVE → VERIFY → SYNTHESIZE → STOP`, achieved, Python 0; cited the field-unit equation from Handbook II p267. |
| Single sourced calculation (FIR-010) | Formula and validated CALC existed, but LLM caveat caused `insufficient_evidence` | `RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP`, achieved; formula from Handbook II p267, `vj = 240.645 ft/sec`, `CALC1` validated. |
| Shortened source title / two documents (FIR-020) | Only Drilling Engineering evidence was retrieved | Both Handbook II and Drilling Engineering were retrieved and cited. The answer still omitted an explicit yes/no conclusion; `achieved` is a false-positive completion. |
| Direct photograph reading (FIR-015) | KB-only numbers appeared in a stopped answer | Stopped with a Figure-evidence limitation; no unverified image-reading number was presented. |
| Figure 19 / Figure 7 visual questions (FIR-013/014) | Figure identity or visual support could be confused | Relevant Formation Evaluation figures were located at p88/p133, but local visual interpretation remained unresolved; safe stop. |
| Unsupported formula (FIR-024) | Safe refusal expected | Still safe: no Python, no invented equation or numeric result. |

The earlier p172 locator smoke again answered `Rw = 0.08 ohm-m` and `Rwa =
0.6 ohm-m` with page-172 KB evidence and `goal_achieved` on the final code.
However, a fresh p171 question explicitly asking for `S_w` in terms of
`R_w/R_wa` retrieved pages 235/196/166/194 rather than p171 and returned
another saturation relation. That **incorrect achieved answer** is a remaining
retrieval/relevance and stop-validation failure; the historical successful
p171 run does not cancel this finding.
Exact run IDs, answers, and retrieved pages are recorded in
`supplemental_smoke.json`.

## 5. Final 30-task development regression

All 30 tasks were executed on the same product commit. This descriptive audit
does **not** semantically adjudicate answer accuracy.

| Diagnostic | Count |
|---|---:|
| Agent goal status `achieved` | 17/30 |
| `stopped` | 12/30 |
| `pending` clarification | 1/30 |
| Python calls | 3 |
| Validated CALCs | 1 |
| Preferred document/page present in KB or FIG evidence | 23/30 |
| Figure-understanding tasks marked achieved | 0/3 |
| False-premise tasks marked achieved | 0/2 |
| Calculation tasks marked achieved | 1/3 |

The 17 `achieved` statuses are **not 17 correct answers**. FIR-020 omits the
required binary conclusion, and FIR-028 omits source-supported resin thresholds
and a concrete choice despite `achieved`. See `final/dev30_report.md` and
`final/dev30_diagnostic.json` for category counts and each task's action, page,
numeric-literal, and suspected-failure flags. Those flags can overlap and are
not independent semantic judgments.

## 6. Calculation execution and stop conditions

FIR-010 proves that a verified literal formula plus bound `q=450 gal/min` and
`An=0.60 in2` now causes Python execution and validated `CALC1`, with its
formula KB ID and user-fact IDs in the final answer. Readiness/missing variables
and iteration coverage are recorded in telemetry. The literal equation lookup
FIR-007 does not invoke Python or request irrelevant values.

This does not cover multi-output work. FIR-011 still asks for a formula even
though its preferred page is retrieved. FIR-012 runs Python once but produces
no validated CALC because variable binding is incomplete. FIR-029 repeats
`CALCULATE/RETRIEVE` for a three-case sweep, with one Python attempt and zero
validated CALCs. FIR-030 selects/binds an unrelated formula and cannot produce
the requested chained volume and density. These remain product defects, not
missing user authorization.

## 7. Figure, false-premise, and synthesis limits

Figure identity and safe refusal improved, but focused visual reading still
fails on all three Figure tasks. FIR-015's direct photograph request no longer
returns unsupported KB-only numbers. FIR-013/014 retrieved the intended figure
pages but the visual relationship could not be established.

FIR-023 is a blocker: a wrong premise about separator paraffin/cloud point was
repeated in the final answer with a KB citation while `engineering_validation_passed`
was true. The run stopped rather than achieving, but the user-facing claim was
still unsafe. FIR-020 and FIR-028 show that claim-level completion and synthesis
validation can still mark a vague or incomplete answer achieved. FIR-004/025/026
show continued over-refusal with preferred-page evidence present.

## 8. Recommendation

**NO — do not treat this branch as ready for a new final unseen evaluation or
main merge yet.** The next development pass should prioritize (1) false-premise
semantic contradiction checks, (2) mandatory claim/conclusion coverage before
`goal_achieved`, (3) multi-output formula binding and validated CALC adoption,
then (4) focused Figure reading and p171-style formula relevance. Reuse these 30
questions only as development diagnostics; any final generalization claim
requires a new independent frozen set.

Raw final run: `dev30_sha_b5b18cb_raw.jsonl`. ChromaDB and the original
evaluation branch were left unchanged. No main merge was performed.
