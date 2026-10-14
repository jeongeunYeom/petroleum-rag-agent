# V23 conference-demo development checks

These are development checks, not the later unseen V4 evaluation. Set `DATA_DIR`
to the parent of the existing `vector_db` and select `RETRIEVAL_MODE=hybrid` or
`hybrid_rerank`, then run `python evaluation/v23_demo/preflight.py` from the
repository root. The script fails if the existing ChromaDB is missing or its
count is not 18,976; it never ingests or reindexes documents. Calculation
artifacts go to the configured `AGENT_WORKSPACE_DIR`, not ChromaDB.
