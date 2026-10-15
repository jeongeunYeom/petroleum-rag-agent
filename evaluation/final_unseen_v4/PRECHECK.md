# Final Unseen V4 precheck — before catalog generation

Date: 2026-10-15 (Asia/Seoul). Evaluation branch: `eval/v23-final-unseen-v4`, initial branch HEAD `4dd522cf4e447ec03dba5d84249e3d345151e882`.

Frozen product SHA: `62e5c36f3d66e25addc8a2c37b63af12e2636e78`. `git diff --name-status` from that SHA to the evaluation branch showed only `RUN_V4_WITH_CODEX.md` and `V4_PROTOCOL.md`; `git diff --exit-code` on `backend/` and `frontend/` was empty. The evaluation-only `precheck_calc.py` was added after branch checkout. No product file was changed.

| Preflight item | Observed result |
|---|---|
| Existing KB | `D:\petroleum-rag-agent\data\vector_db`; collection `petroleum_knowledge`, **12 documents / 18,976 chunks** before and after both checks |
| SQLite metadata | `chroma.sqlite3`, 197,062,656 bytes, SHA-256 `1b389044d7efec1273a5d4d52a999d4831188e08a808d4a956a72ba816659fea` (Python read-only byte stream) |
| Local model | Ollama `qwen3:8b`, digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`; generation completed |
| Retrieval | `RETRIEVAL_MODE=hybrid`; a non-V4 wellbore-storage query returned five locatable KB sources |
| Embedding | `BAAI/bge-m3` loaded on CPU; 1,024-dimensional non-empty vector |
| Web | All evaluation runs set `WEB_FETCH_ENABLED=0`; from-message tasks do not request external sources |
| Direct calculation | Non-V4 `A=17 psi, B=8 psi` sum produced validated 25 |
| Retrieved and validated KB calculation | Known pre-V4 SG→API path completed `retrieve → calculate → verify → synthesize → stop`; validated 22.64 °API and literal formula source at *Heriot-Watt University - Reservoir Engineering.pdf*, p.90 |

The checks used `evaluation/v23_demo/preflight.py` and `evaluation/final_unseen_v4/precheck_calc.py`. Their prompts are known historical/non-V4 health checks. Neither script performed ingest, reindexing, or Chroma writes. The final catalog did **not** exist when this precheck was written.
