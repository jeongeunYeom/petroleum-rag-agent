# V20.1 poster-candidate freeze

- Candidate product SHA: `c82ef66070695e6a13f7a6f3eb35f2714e4e5811` (`fix/v20-1-reliability-stabilization`). Validation commit follows this product commit and does not change product code.
- Browser result: B/C/D/E/F **5/5 required PASS**, A Monel also PASS; UI integration PASS. Exact V20 prompt strings were reused. Evidence: [browser report](../v20_1_browser_e2e/V20_1_BROWSER_E2E_REPORT.md) and [raw results](../v20_1_browser_e2e/results.json).
- Local development regression: 24 targeted v20.1 tests passed; full backend `python -m pytest -q`: **1,554 passed** (6 dependency deprecation warnings); frontend `pnpm test`: **23 passed**; `pnpm build`: **passed**.
- Production-style KB snapshot: existing `petroleum_knowledge`, **12 documents / 18,976 chunks**, `D:\petroleum-rag-agent\data\vector_db`; no reindex or ingest.
- Model/retrieval: local Ollama **qwen3:8b**, `RETRIEVAL_MODE=hybrid`; web off in the browser scenarios.
- Limitations: small selected scenario set, not a final unseen benchmark; Monel answer is extractive English; the UI spells resistivity as canonical `ohm-m` rather than typographic `Ω·m`; poster captures have blank viewport space. No broader reliability claim is implied.

**V20.1 POSTER CANDIDATE READY** under the requested B/C/D/E/F freeze criteria. Product development stops at the candidate SHA; no additional feature cycle is authorized by this validation.
