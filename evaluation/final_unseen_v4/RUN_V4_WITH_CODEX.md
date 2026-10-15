# Run Final Unseen V4 with Codex

Use this instruction in the local Codex session that has access to the repository, Ollama and the existing ChromaDB.

---

You are executing the **final unseen V4 quantitative evaluation** for the frozen Petroleum Engineering RAG Agent.

Repository:
`jeongeunYeom/petroleum-rag-agent`

Evaluation branch:
`eval/v23-final-unseen-v4`

Frozen product SHA:
`62e5c36f3d66e25addc8a2c37b63af12e2636e78`

First read and follow exactly:

`evaluation/final_unseen_v4/V4_PROTOCOL.md`

## Critical integrity rules

- Do NOT modify product code.
- Do NOT modify retrieval behavior.
- Do NOT reindex or mutate ChromaDB.
- Do NOT create or inspect V4 prompts and then patch the product.
- Do NOT reuse exact V3/V22/V23/V23B/conference-stress prompts.
- Once the V4 catalog is sealed and any model execution starts, do NOT edit the catalog.
- If product code changes after V4 is revealed, stop: V4 is no longer final unseen and a new V5 would be required.
- No V4 output may be used to tune this frozen product.

## Phase 1 — verify freeze

Confirm:

1. product tree is byte-equivalent to product SHA
   `62e5c36f3d66e25addc8a2c37b63af12e2636e78`
   except evaluation-only files on this branch;
2. local `qwen3:8b` is available;
3. `RETRIEVAL_MODE=hybrid`;
4. web is off;
5. existing KB is read-only and exactly:
   - 12 documents
   - 18,976 chunks;
6. BGE-M3 embedding works;
7. direct-calc, retrieval and validated-calc health checks work using NON-V4 prompts.

Write:
`evaluation/final_unseen_v4/PRECHECK.md`

If any preflight item fails, STOP before generating V4.

## Phase 2 — generate and seal V4

Generate exactly **60 new tasks** using the category, language, domain and gold requirements in `V4_PROTOCOL.md`.

Important:
- source-dependent items must be demonstrably supported by the current KB;
- gold must include atomic claims and exact evidence locators/spans;
- numerical gold must include formula, bindings, expected value, tolerance and units;
- do not copy prior evaluation prompts.

Before any model run:
- validate the catalog structurally;
- audit KB support;
- ensure no exact normalized duplicate of prior evaluation prompts;
- write:
  `evaluation/final_unseen_v4/v4_catalog.json`
- hash it to:
  `evaluation/final_unseen_v4/v4_catalog.sha256`

After hashing:
**the catalog is immutable.**

## Phase 3 — execute one-shot Agent run

Run all 60 tasks against the frozen Agent with:

- qwen3:8b
- hybrid retrieval
- existing read-only KB
- web off

For resume tasks, preserve the intended two-turn interaction.

Write:
`evaluation/final_unseen_v4/agent_results.json`

Do not patch anything based on failures.

## Phase 4 — Qwen closed-book baseline

Run the exact same 60 user tasks against plain `qwen3:8b` with:

- no RAG
- no internal KB
- no tools
- no source/gold leakage

For resume tasks, provide the same follow-up turn.

Write:
`evaluation/final_unseen_v4/qwen_closed_book_results.json`

Clearly label this baseline as **closed-book**.

## Phase 5 — automatic scoring

Compute deterministic metrics per the protocol:

- Task Completion
- Numerical Accuracy
- citation/source validity
- unit correctness
- crash count
- blank answer count
- raw error leakage
- repeated clarification
- latency median/P95 by category

Write:
`evaluation/final_unseen_v4/automatic_scores.json`

## Phase 6 — semantic review packet

Create:
`evaluation/final_unseen_v4/semantic_review_packet.json`

For every task include:

- task ID/category/language
- user prompt(s)
- gold required goals
- gold atomic claims
- gold evidence spans
- Agent answer and citations
- baseline answer
- automatic flags

Then score using one frozen rubric for:

- Goal Success
- Claim Coverage
- Hallucination-Free
- Citation Support Rate

Preserve task-level verdict and rationale.

Do not use old development outcomes as judge examples.

Write:
`evaluation/final_unseen_v4/semantic_scores.json`

If semantic judgment is genuinely uncertain, mark it uncertain rather than silently passing it.

## Phase 7 — final report

Create:

`evaluation/final_unseen_v4/V4_FINAL_REPORT.md`

and

`evaluation/final_unseen_v4/V4_POSTER_NUMBERS.md`

The final report must contain:

### Frozen Agent
- Goal Success x/60 and %
- Task Completion x/60 and %
- Claim Coverage %
- Hallucination-Free x/60 and %
- Numerical Accuracy x/N and %
- Citation Support Rate %
- category-level results
- latency median/P95
- all failed task IDs with short failure classes

### Qwen closed-book vs Frozen Agent
Table:
- Goal Success
- Claim Coverage
- Hallucination-Free
- Numerical Accuracy

Explicitly note that Qwen is closed-book and Agent has the internal KB/tools.

### Integrity
Record:
- frozen product SHA
- evaluation branch/commit
- catalog SHA-256
- KB metadata
- model
- retrieval mode
- web-off state
- confirmation that no product code or benchmark item was modified after execution began

## Phase 8 — tests and commit

Evaluation-only code may be tested.

Do not modify product code to make evaluation pass.

Commit all final evaluation artifacts with:

`eval: record final unseen v4 results for frozen v23`

Do not merge to main automatically.

Do not start V5.

At the very end print exactly:

`V4 COMPLETE — FROZEN PRODUCT WAS NOT MODIFIED`

followed by a compact result table.
