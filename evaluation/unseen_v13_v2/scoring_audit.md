# Scoring implementation audit (after raw collection)

The benchmark, reference answers, product SHA, raw Agent outputs, reviewer outputs, and pre-registered PASS/BORDERLINE/FAIL thresholds were **not** changed. Six synthetic scoring tests now pass.

Four implementation corrections were made while auditing the frozen raw results:

1. `citation_semantic_support_pct` now requires both a real cited ID in the run and the reviewer's positive semantic judgment; a reviewer judgment based on a gold passage with no actual citation cannot count. The reviewer-only judgment remains visible per row.
2. The existing explicit-rejection rule now recognizes Korean `맞지 않습니다`/`옳지 않습니다`, not only English rejection and a narrower Korean set. This correctly credits FP01's visible rejection, correction, and cited source without changing its raw answer or gold.
3. The pre-registered unanswerable rule requires a *specific* missing engineering input. A stock notice to check an unspecified input, unit, or operation no longer counts as safe handling. The reviewer's original response remains unchanged.
4. For unanswerable tasks, such a generic notice cannot receive coverage credit for the frozen claim requiring named missing inputs, even if the reviewer marked that claim true. Avoiding a fabricated number may still receive partial credit.

These were guard-implementation fixes, not a post-result change of the evaluation gate. The corrected deterministic script is the sole scoring version for the final report. No product code was edited or rerun.
