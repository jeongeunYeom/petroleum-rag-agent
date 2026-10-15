# Final Unseen V4 Evaluation Protocol

## Purpose

This protocol defines the **final unseen quantitative evaluation** for the frozen Petroleum Engineering RAG Agent.

- Frozen product SHA: `62e5c36f3d66e25addc8a2c37b63af12e2636e78`
- Product branch at freeze: `feature/conference-demo-v23`
- Evaluation branch: `eval/v23-final-unseen-v4`
- Runtime target: local `qwen3:8b`
- Retrieval default: `hybrid`
- Web: off
- Existing KB: `petroleum_knowledge`, 12 documents / 18,976 chunks

The V23/V23B prompts are **observed development material**. They must not be reported as final unseen performance.

---

## Non-negotiable integrity rules

1. **Do not change product code after the frozen SHA.**
2. Create the V4 benchmark only after confirming the product freeze.
3. Do not tune, patch, add task-specific rules, change retrieval behavior, or reindex the KB after seeing V4 outputs.
4. If a product change is made after any V4 item/output is observed, V4 immediately becomes an observed development set and a completely new V5 is required.
5. Evaluation-only scripts and reports may be added on the evaluation branch, but product files must remain byte-equivalent to the frozen product SHA.
6. V4 items must not copy exact prompts from V3, V22/V23 development catalogs, V23B, conference stress, or prior held-out sets.
7. Do not cherry-pick or delete difficult items after generation.
8. The final catalog is generated once, hashed, then treated as immutable.
9. A technical harness crash may justify rerunning the **same immutable catalog** after fixing the evaluation harness only. It does not justify editing items or product behavior.
10. No V4 result may be called “unseen” after item-level tuning.

---

## Preflight

Before generating V4:

- verify current product tree against frozen SHA;
- verify no product file differs from `62e5c36f3d66e25addc8a2c37b63af12e2636e78`;
- verify local Ollama and `qwen3:8b`;
- verify BGE-M3 embedding path;
- verify `RETRIEVAL_MODE=hybrid`;
- verify web is disabled;
- verify KB collection is exactly 12 documents / 18,976 chunks;
- run one non-benchmark health check for:
  - direct calculation,
  - KB retrieval,
  - validated calculation path;
- do not use a V4 prompt as preflight.

Record the preflight result before creating the benchmark.

---

## V4 catalog size and composition

Create **60 new tasks**.

| Category | Count |
|---|---:|
| Knowledge / explanation | 12 |
| Direct deterministic calculation | 8 |
| User-supplied formula calculation | 8 |
| KB-formula retrieval + calculation | 12 |
| Multi-goal / compositional task | 8 |
| False-premise correction | 4 |
| Unanswerable / insufficient-evidence | 4 |
| Resume / missing-input two-turn task | 4 |
| **Total** | **60** |

The categories above are mutually assigned for reporting, even when a task has secondary characteristics.

### Language distribution

Across the full catalog:

- Korean: 24
- English: 24
- Mixed Korean/English: 12

At least 12 tasks should contain natural visitor-style variation such as:
- casual phrasing,
- harmless typo,
- abbreviated notation,
- reordered clauses,
- short follow-up wording.

Do not intentionally make wording nonsensical.

### Domain coverage

Use only topics actually supportable by the current internal KB. Spread tasks across available petroleum-engineering areas such as:

- reservoir engineering,
- petrophysics,
- well testing,
- production,
- drilling,
- reservoir fluids / PVT,
- stimulation or other supported topics.

Do not manufacture a task merely to satisfy a topic quota when the KB does not contain the needed evidence.

---

## Gold construction

Every task must contain machine-readable gold metadata.

### Knowledge-dependent tasks

Record:

- required atomic claims;
- supporting source document;
- page or locator;
- literal supporting span(s);
- whether each claim is explicit or a narrowly valid mathematical implication;
- forbidden unsupported implications where useful.

### Numerical tasks

Record:

- target quantity;
- expected formula or allowed equivalent form;
- input bindings;
- expected numerical value;
- tolerance;
- expected unit/dimension;
- whether the source formula is required.

### False-premise tasks

Record:

- premise;
- correct relation;
- source support;
- what constitutes an adequate correction.

### Unanswerable tasks

Record:

- why the available evidence is insufficient;
- what the system must not invent;
- what a successful safe limitation should say at minimum.

### Resume tasks

Record:

- first-turn missing variable;
- expected clarification target;
- second-turn user reply;
- expected final result;
- retained source/formula requirements.

---

## Benchmark generation isolation

Generate V4 programmatically after freeze.

The generation process may inspect the KB/source text to create valid gold evidence, but it must not alter product code.

After generating the 60-task catalog:

1. verify exact task count and category/language distributions;
2. check normalized prompts for exact duplicates against prior evaluation catalogs;
3. run a source-support audit of all KB-dependent gold items;
4. write the final catalog;
5. compute SHA-256;
6. from that point onward, do not edit the catalog.

If a gold item is discovered to be objectively invalid **before any model execution**, replace it before sealing and document the reason.  
After model execution begins, no item may be replaced or edited.

---

## Execution conditions

Run two conditions on the exact same user-task catalog.

### Condition A — Frozen Agent

- exact frozen product code;
- local `qwen3:8b`;
- existing read-only KB;
- hybrid retrieval;
- normal Agent search/calculation/verification behavior;
- web off.

### Condition B — Qwen closed-book baseline

- same `qwen3:8b`;
- same user-facing task wording;
- no KB retrieval;
- no Agent tools;
- no hidden gold/source text;
- direct model answer only.

This baseline is explicitly **closed-book** and must be labeled that way in reports. It is not evidence that the two conditions have equal information access.

For resume tasks, the baseline receives the same two-turn conversation.

---

## Metrics

Report the following separately for Agent and, where meaningful, Qwen closed-book.

### 1. Goal Success (GS)

Task-level binary score.

Pass only when all required user goals are completed correctly.

For:
- unanswerable tasks: a correct evidence-limited refusal/limitation counts as success;
- resume tasks: the system must ask for the correct missing input and then complete after the reply;
- ambiguous tasks intentionally requiring clarification: the correct specific clarification counts as success only if that is the gold behavior.

### 2. Claim Coverage (CC)

For tasks with requested factual/engineering claims:

```
supported requested atomic claims delivered
/
total requested atomic claims
```

Do not give credit for generic filler.

### 3. Hallucination-Free rate (HF)

Task-level binary score.

Pass only if the response contains:
- no fabricated source;
- no fabricated formula;
- no unsupported engineering relation;
- no unsupported numerical result;
- no materially wrong citation attribution.

A cautious partial answer may be HF even when GS fails.

### 4. Numerical Accuracy (NA)

Evaluate only tasks requiring a final numerical result.

A task passes when:
- every required numerical output is within the task tolerance;
- units/dimensions are correct;
- no requested numerical output is missing.

Report numerator and denominator.

### 5. Task Completion (TC)

Report the proportion of tasks that end in the correct final interaction state:

- completed answer when answerable;
- correct targeted clarification when intentionally incomplete;
- correct safe limitation when unanswerable.

TC is an interaction-state metric; GS is stricter semantic goal fulfillment.

### 6. Citation Support Rate (CSR)

For Agent KB-dependent answers only:

```
supported cited atomic claims
/
all cited atomic claims
```

### 7. Reliability / UX

Report:

- technical crashes;
- blank visible responses;
- raw exception leakage;
- repeated identical clarification;
- unnecessary refusal on answerable petroleum tasks.

### 8. Latency

Report median and P95 for Agent:

- Direct
- User formula
- Knowledge
- KB formula
- Multi-goal
- Resume
- overall

Do not hide slow successful cases.

---

## Scoring procedure

### Objective automatic scoring

Use deterministic scoring where possible for:

- exact task counts;
- final status;
- numeric values/tolerances;
- unit/dimension checks;
- source/citation IDs;
- crash/blank/error events;
- clarification repetition;
- latency.

### Semantic scoring

For GS, CC, HF, and CSR where semantic judgment is needed:

1. create a review packet containing:
   - task;
   - gold atomic claims;
   - gold evidence spans;
   - Agent answer;
   - cited evidence;
   - baseline answer;
2. score against a frozen rubric;
3. do not expose prior development task outcomes as examples in the judge prompt;
4. preserve every task-level judgment and rationale.

The final report must distinguish:
- automatic score;
- semantic-reviewed score;
- any unresolved reviewer uncertainty.

Do not silently upgrade an automatic failure.

---

## Recommended final tables

### Agent final unseen V4

| Metric | Score |
|---|---:|
| Goal Success | x/60 (%) |
| Task Completion | x/60 (%) |
| Claim Coverage | % |
| Hallucination-Free | x/60 (%) |
| Numerical Accuracy | x/N (%) |
| Citation Support Rate | % |

Also report category-level GS/TC.

### Agent vs Qwen closed-book

| Metric | Qwen closed-book | Frozen Agent |
|---|---:|---:|
| Goal Success | % | % |
| Claim Coverage | % | % |
| Hallucination-Free | % | % |
| Numerical Accuracy | % | % |

Clearly state that Qwen is closed-book while the Agent has access to the internal KB and tools.

---

## Acceptance / interpretation

V4 is **not** a development gate. It is the final measurement.

Do not change product code because a score is disappointing.

If performance is lower than expected:
- report it honestly;
- analyze failure classes;
- treat any subsequent fix as the beginning of a new product version;
- any post-V4 modified product requires a new unseen V5 for a new final claim.

Aspirational targets, not guaranteed outcomes:

- Goal Success ≥ 80%
- Task Completion ≥ 90%
- Hallucination-Free ≥ 90%
- Numerical Accuracy ≥ 90%

These targets must never be substituted for observed scores.

---

## Required artifacts

Create under `evaluation/final_unseen_v4/`:

- `PRECHECK.md`
- `v4_catalog.json`
- `v4_catalog.sha256`
- `agent_results.json`
- `qwen_closed_book_results.json`
- `automatic_scores.json`
- `semantic_review_packet.json`
- `semantic_scores.json`
- `V4_FINAL_REPORT.md`
- `V4_POSTER_NUMBERS.md`

The report must record:

- exact frozen product SHA;
- evaluation-code commit SHA;
- KB count/hash metadata;
- catalog hash;
- runtime/model;
- retrieval mode;
- all denominators;
- all failures by ID and category;
- latency;
- integrity statement that no product changes occurred after V4 was revealed.

---

## Final stop rule

Once V4 execution begins:

**No product modification. No benchmark modification. No retuning.**

After the report is produced, stop and preserve the results exactly as observed.
