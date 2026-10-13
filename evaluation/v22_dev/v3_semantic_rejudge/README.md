# V22 observed V3 same-protocol semantic comparison

This directory scores **only** the previously saved V22 answers in `../observed_v3_results.json`. It does not call the Agent, Qwen, retrieval, or ChromaDB. It is an observed development comparison, **not** a new unseen evaluation.

The original finalized V3 assets are read from commit `8af20278b1905be02fcd2a855471b749da094e38`. `prepare_v22_raw.py` verifies the original benchmark/rubric SHA256, the frozen V22 product SHA, the 36+4 saved run counts and task IDs, and absence of post-freeze product changes. It copies each saved answer and run state unchanged to `raw/v22_agent/`. `judge_v22_once.py` imports the original V3 JSON schema and prompt builder, extracts the original judge system instruction verbatim, and uses the original model/configuration (`gpt-5.4-2026-03-05`, temperature 0). It writes an exclusive reservation before each of 36 one-shot calls. An existing reservation or result is never called again. `score_v22_same_protocol.py` uses the original deterministic numeric, provenance, aggregation, and percentile helpers, plus the original finalized Qwen scored rows.

Order used (the original checkout path is provided explicitly):

```powershell
python evaluation/v22_dev/v3_semantic_rejudge/prepare_v22_raw.py --original D:/petroleum-rag-agent-v21-v3/evaluation/v21_2_final_unseen_v3
python evaluation/v22_dev/v3_semantic_rejudge/judge_v22_once.py --original D:/petroleum-rag-agent-v21-v3/evaluation/v21_2_final_unseen_v3
python evaluation/v22_dev/v3_semantic_rejudge/score_v22_same_protocol.py --original D:/petroleum-rag-agent-v21-v3/evaluation/v21_2_final_unseen_v3
```

The judge step has already completed all 36 calls. Do **not** rerun it; existing artifacts are intentionally skipped. The original Qwen answers and judgments were never regenerated. The comparison is paired by exact task ID (10,000 bootstrap resamples, seed 20261013; n=36 except n=16 for Numerical Accuracy).

`poster_metrics.md` is the concise poster-ready table; `SEMANTIC_REJUDGE_REPORT.md` records the protocol, paired intervals, diagnostics, and limitations. The per-task V22/Qwen rows are in `scored_rows.json`, with aggregate results in `metrics.json` and `comparison_qwen_v22.json`.
