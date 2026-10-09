# Final benchmark v1 — BLOCKED (not a performance result)

The benchmark was frozen before system outputs. The evaluated product remains `main` at
`fcd89e6e93fc866f4a237ee13c7910dcedac44c3`; the evaluation branch did not alter
product code or older evaluation records.

As of 2026-10-09 10:00:45 UTC, completed raw End-to-End responses are:

| System | Completed / frozen tasks | Status |
|---|---:|---|
| Petroleum-RAG-Agent, local qwen3:8b, hybrid KB | 50 / 50 | Raw capture complete |
| Qwen3:8b closed-book | 50 / 50 | Raw capture complete |
| OpenAI gpt-5.4-mini-2026-03-17 closed-book | 50 / 50 | Raw capture complete |
| Gemini gemini-2.5-flash closed-book | 20 / 50 | BLOCKED by HTTP 429 |

Gemini first returned HTTP 429 on L08, which succeeded after one cooldown retry. It
returned HTTP 429 again on L21; after a further cooldown, one retry also returned 429.
The original errors are preserved in `raw/gemini/error_history/`, and the latest L21
error is in `raw/gemini/L21.json`. No more Gemini generation calls were made after the
repeated L21 error. The cause may be a provider quota or rate window; this record does
not infer a reset time.

The frozen set has 50 items. L20 was identified as a near-duplicate of an earlier
heldout question before performance scoring and logged as INVALID, without altering
the frozen benchmark; expected valid denominator is 49.

Because the required four-system End-to-End comparison is incomplete, the prescribed
Same-Evidence, deterministic scoring, single-reviewer adjudication, bootstrap, CSV,
poster figures, and final report were **not run**. No performance ranking, success
rate, or citation/accuracy statistic should be inferred from these partial captures.

To resume after Gemini access is restored, preserve `raw/gemini/L21.json` as another
error-history record, then rerun `python evaluation/final_v1/run_experiment.py gemini`.
The runner skips all successful per-task files and spaces future Gemini calls by
10 seconds. Complete all 50 Gemini End-to-End responses before starting the three
Same-Evidence phases, then deterministic scoring, semantic review, bootstrap, and
report generation. Do not modify frozen questions, answers, or product code.

Secrets were not written to the evaluation files; a local scan found zero exact API
key values in 187 files scanned.
