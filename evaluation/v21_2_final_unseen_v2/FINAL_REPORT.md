# V21.2 final unseen evaluation — not finalized

**FINALIZED=false.** The 36-task primary evaluation cannot be scored as a complete paired benchmark. Qwen3:8b closed-book task `V212U-013` reached an HTTP read timeout at 1,200 seconds on its one permitted attempt. The frozen protocol prohibits another generation, question replacement, or a revised output limit. The raw error and all other raw attempts are preserved. The exact semantic judge was available but was not invoked with an invented or blank replacement answer; therefore Goal Success, Claim Coverage, Hallucination-free, Numerical Accuracy, and paired confidence intervals are **not reported**.

V21.2 was evaluated once on a newly authored benchmark that was frozen after the V21.2 product freeze and before any evaluated product run. The product was not modified after benchmark creation or after execution began.

## Freeze and design

- Evaluation branch: `eval/v21-2-final-unseen-v2`.
- Frozen product SHA: `f5182b8ae2907452e1c53373055e66c5182c9b90`.
- Benchmark freeze commit: `a48ef7f707c40e2cff7f92e4d3f929f2d63c78fa`.
- Working-file benchmark SHA256: `59224f5e6befd8d05fc832c1b950f0b9be60f1179e808d3c0cbccccc5365e2b9`. Committed Git blob SHA256: `35a73141f59c0c452c1146a46a958f178f0d664411277a9677b6603b7d04e570`. The difference is Windows CRLF checkout normalization; both hashes were frozen in the receipt before any model call.
- Rubric SHA256: `522531ca05f083c58dbdda761367fa7935eab335ac656e3f1ea402294fc573e5`.
- Exactly 36 primary questions: knowledge QA 8, multi-claim reasoning 6, direct calculation 6, user formula 4, KB formula 6, false premise 3, unanswerable 3. Six tasks have multiple required goals. Exactly 16 are numerical; exactly 12 are Korean requests grounded in English source passages. Four same-run resume probes are a separate diagnostic set.
- Candidate source pages were sampled before question authoring from the frozen production ChromaDB with seed `20261013`, stratified by document. Prior-used document/page pairs were extracted mechanically, without displaying old questions: 329 pairs were excluded, including 11 from the local V20.1 browser artifacts. The 23 gold source pages used by the primary tasks do not overlap that set. Literal supporting spans and all six formula spans were checked against the selected Chroma page text; numeric expressions and units were checked before freeze. The deterministic novelty screen compared 412 prior/development text entries without displaying them; the maximum new-question character-4-gram Jaccard similarity was 0.1508 under a predeclared 0.45 threshold. No candidates were rejected.
- The same frozen benchmark question was used for each system. Qwen closed-book received no KB, web, tool, or Python input. V21.2 used the normal unified agent API with hybrid retrieval, internal KB on, web off, local qwen3:8b, and unchanged eight-iteration product ceiling. The GPT reference used `gpt-5.4-mini-2026-03-17` closed-book with no tools. No product/backend/frontend application file changed.

## Execution and integrity

| System | Raw reservations | Completed responses | Error |
|---|---:|---:|---:|
| qwen3:8b closed-book | 36 | 35 | 1 timeout (`V212U-013`) |
| Frozen V21.2 Agent | 36 | 36 | 0 |
| GPT reference | 36 | 36 | 0 |

Every system/task has one unique attempt ID and `attempt_count=1`. There was no retry. The first preflight completed at `2026-10-13T08:01:20Z`, before the first raw reservation at `2026-10-13T08:07:33Z`; the saved `integrity_pre.json` is a later repeated check before Agent execution. The product application files, frozen benchmark and rubric, and all ChromaDB file hashes matched before and after execution. The KB remained `petroleum_knowledge`, 12 documents, 18,976 chunks. The formal post-run integrity gate first fails because the Qwen raw row is not `completed`; the missing judge rows are a downstream consequence. It correctly refuses to claim `FINALIZED=true`. No semantic judge rows exist. Single-reviewer AI-assisted semantic adjudication is not human review, and in this run it was not performed.

The 108-row `results.csv` is only an unscored raw-status/latency ledger. It is **not** a final performance table. The available unscored diagnostics are: Agent self-status `achieved` 7, `stopped` 24, `pending` 5; Python execution on 3/16 numerical tasks, validated calculation on 2/16; gold formula document/page retrieved on 3/6 KB-formula tasks, and RETRIEVE→CALCULATE on 0/6. These are execution observations, not Goal Success or Numeric Accuracy. Success-only latency median was 12.77 s for the 35 completed Qwen responses, 36.75 s for the 36 Agent responses, and 2.20 s for the 36 GPT reference responses. The timed-out Qwen request is excluded from that latency summary and is separately disclosed.

The four resume probes remain outside the 36-task denominator. Two first turns reached `waiting_for_user_input`; two stopped. The two resumed runs returned to `waiting_for_user_input`; none completed its final requested goal. These are raw state observations, not AI-judged success rates.

## Conclusion

No poster-safe V21.2-versus-Qwen superiority, numerical accuracy, hallucination, or confidence-interval claim can be made from this interrupted paired run. The benchmark and raw data remain frozen. Under the requested one-shot rule, this evaluation must remain not finalized rather than retrying or substituting the missing response.
