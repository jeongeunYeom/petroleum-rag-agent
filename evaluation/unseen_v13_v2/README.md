# Independent unseen v2 for v13

Dataset frozen before first v13 invocation: YES.

This directory is an evaluation-only branch artifact. `benchmark.json` is 50 new questions and gold claims authored from the existing petroleum-engineering documents, not a v12 rerun. `dedup_preflight.json` records lexical/semantic comparison to prior frozen, development, and fixed-test questions. The frozen SHA256 is in `run_config.json`; `run_eval.py` refuses to invoke the product if the working dataset or committed dataset differs from that hash or if backend/frontend differs from the pinned product commit.

The first four frozen tasks (`SF01`–`SF04`) are the predetermined infrastructure smoke; they remain in the full denominator. Run order after the freeze commit: backend health and retrieval-mode probe; smoke; remaining Agent tasks; one fixed-snapshot OpenAI semantic review per task; deterministic scoring and report. Checkpoints in `raw/agent/` and `review/` are write-once. There is no product edit, reindex, web use, model fallback, or main merge.

The user wrote `gpt-5_4-mini-2026-03-17`; OpenAI's model lookup returned 404 for that spelling and 200 for the official snapshot `gpt-5.4-mini-2026-03-17`. The dotted snapshot is the sole configured reviewer. The preflight estimate is $0.705 for 50 requests at an 8k-input/1.8k-output envelope; the hard cap is $2.00. Token usage and estimated cost are recorded per saved response.
