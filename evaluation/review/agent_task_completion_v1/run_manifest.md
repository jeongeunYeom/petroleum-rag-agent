# Development-run manifest

All rows here reuse already-seen evaluation questions for regression diagnosis;
none is a new unseen performance evaluation. The benchmark/rubric files in the
evaluation branch were read only. `qwen3:8b`, hybrid retrieval, and the existing
12-document/19,248-chunk ChromaDB were used for real API runs.

| File | Product state | Scope |
|---|---|---|
| `dev30_raw.jsonl` | `4ffb0cdc5cd6f4bf1f4d0b3dc7f9620d5bfc815a` | Preliminary full-30 diagnostic. |
| `pre_followup/` | same | Descriptive analysis of that run. |
| `dev30_final_raw.jsonl` | `8dd384594f5760b8fd1593bb5f8c4f02639f02a0` | Full-30 diagnostic before the sourced-calculation synthesis fix. |
| `pre_synthesis/` | same | Descriptive analysis of that run. |
| `targeted_final_raw.jsonl` | `f1cc17e7d204221114bcfaf402325393e2188be6` | Targeted calculation and two-document checks. |
| `dev30_pre_visual_guard_partial.jsonl` | `f1cc17e7d204221114bcfaf402325393e2188be6` | Interrupted at the Figure safety finding; incomplete, never scored. |
| `targeted_visual_guard_raw.jsonl` | transient working tree after `f1cc17e` | Reproduction of the photo-intent miss; not a committed product state. |
| `targeted_visual_guard_v2_raw.jsonl` | `8de7c0fd0fe3dd2ac9467ad36617bc408e599928` | Targeted safe photo-reading stop. |
| `dev30_pre_intent_guard_partial.jsonl` | `8de7c0fd0fe3dd2ac9467ad36617bc408e599928` | Interrupted at the formula-lookup misclassification; incomplete, never scored. |
| `targeted_formula_lookup_raw.jsonl` | transient working tree after `8de7c0f` | Reproduction of duplicated topic/goal intent bug; not a committed product state. |
| `targeted_formula_lookup_v2_raw.jsonl` | `b5b18cbc268f86bef5c683fe2867a30ab06b5643` | Targeted formula-only request: achieved, Python 0. |
| `dev30_sha_b5b18cb_raw.jsonl` | `b5b18cbc268f86bef5c683fe2867a30ab06b5643` | Final complete 30-task development regression. |
| `final/` | same | Final per-task descriptive diagnostic and summary. |

Partial and transient rows are preserved only for auditability. Do not aggregate
them with the final 30-task run or use any of these files as an independent
generalization score.
