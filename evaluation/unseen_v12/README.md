# Frozen v12 unseen evaluation

The product under test is commit `2fd4af7d6b12c7d42292b6b7525b0aacf5f34739`. The benchmark was frozen in commit `a1a024bb2b9457e23c1d9848665a253f9c2ad4d1`. Do not edit its questions or answers after viewing results. The evaluation-only scripts may be repaired without changing the benchmark or product.

Run from repository root on the machine with the existing ChromaDB and local Ollama:

```powershell
$env:DATA_DIR = 'D:\petroleum-rag-agent\data'
$env:RETRIEVAL_MODE = 'hybrid'
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

In another shell, with `OPENAI_API_KEY` already set (never print it):

```powershell
cd D:\petroleum-rag-agent
python evaluation/unseen_v12/preflight.py
python evaluation/unseen_v12/run_eval.py cost-preflight
python evaluation/unseen_v12/run_eval.py agent --limit 5
python evaluation/unseen_v12/run_eval.py review --limit 5
python evaluation/unseen_v12/run_eval.py agent
python evaluation/unseen_v12/run_eval.py review
python evaluation/unseen_v12/score_eval.py
```

The agent uses the existing `from-message` API, local `qwen3:8b`, hybrid retrieval, and web OFF. The fixed OpenAI reviewer is `gpt-5.4-mini-2026-03-17`, temperature 0, reasoning effort `none`; no fallback. Each completed raw/review record is write-once and skipped on resume. The predeclared pricing/cap and rubric are in `run_config.json` and `EVALUATION_POLICY.md`. Per-task reviewer JSON and token usage are preserved, with aggregated usage in `usage.json`. Three malformed pilot reviewer outputs were discarded before scoring; see `api_error_history.json` for cost-accounting limits.
