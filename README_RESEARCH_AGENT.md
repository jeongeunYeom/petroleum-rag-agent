# Codex Petroleum Research Agent

This branch adds an evidence-only research path without changing document
ingestion or writing external results to ChromaDB.

## Architecture

```text
question -> route query -> BGE-M3/Chroma dense search --+
                  |       collection keyword search ----+-> RRF
                  |                                      |
                  +-----> DDGS web search ---------------+-> normalized evidence
                                                         -> conflict checks
                                                         -> Ollama JSON claims
                                                         -> claim/evidence validation
                                                         -> deterministic answer
```

Routing modes are `internal_only`, `external_only`, and `hybrid_research`.
Internal hits receive `KB*` IDs, web hits receive `WEB*` IDs, and Figure Note
hits receive `FIG*` IDs. The model is instructed to use only these evidence
blocks. Unknown citations are removed, empty evidence causes a deterministic
refusal, and detected KB/web conflicts receive a mandatory neutral disclosure.

The internal retriever independently combines the existing BGE-M3/Chroma dense
index with the collection's keyword search using Reciprocal Rank Fusion. It
uses the existing collection read-only; no re-embedding or second knowledge
base is created. Dense-only candidates below a conservative similarity floor
and sparse candidates without enough literal query overlap are rejected before
fusion. DDGS results are normalized and deduplicated in memory only.

Ollama is constrained to a small JSON schema containing independent claims and
their evidence IDs. The application, not the model, renders the five answer
sections and final source list. Before rendering, it rejects unknown IDs,
KB/WEB citations placed in the wrong section, numbers or units absent from the
cited text, equations that do not match the source rendering, and claims whose
BGE-M3 similarity to their cited evidence is below the conservative threshold.
This intentionally favors precision over recall when PDF extraction makes a
formula ambiguous. A single bounded repair pass is attempted after rejected or
malformed claims; failure keeps the already validated first result.

## API

`POST /api/research/evidence`

```json
{
  "query": "내 교재의 residual trapping과 최근 연구를 비교해줘",
  "internal_top_k": 5,
  "external_top_k": 5,
  "use_internal": true,
  "use_external": true,
  "model": "qwen3:8b"
}
```

The response includes the required answer, sources, figures, provenance,
model, inference flag, and evidence counts. It also includes routing mode,
retrieval/reasoning/total timing, conflict signals, citation validation, and an
unsupported-claim count and per-check rejection counts. Structured run logs are written under
`data/agent_runs/research/`; private chain-of-thought is never requested or
stored.

## Run and test

```powershell
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest -q tests/test_research_agent.py
```

DDGS is the only new package and does not require a paid API key.

## Fair comparison

Use the same benchmark, model, `top_k`, ChromaDB, temperature, and machine for
both runs. The internal-only comparison below avoids giving either agent live
web evidence:

```powershell
python backend/scripts/run_well_test_benchmark.py --mode rag --model qwen3:8b --top-k 5 --condition existing-agent
python backend/scripts/run_well_test_benchmark.py --mode research --model qwen3:8b --top-k 5 --condition codex-research-agent
python backend/scripts/compare_benchmark_runs.py data/evaluation/<existing.json> data/evaluation/<codex.json>
```

Add `--use-external` only when the comparison target also receives the same
number of live search results. Research benchmark rows record answer, total,
retrieval and reasoning time, internal/external counts, document/page, web
URLs, citation validation, unsupported claims, and hallucination evaluation.

## Known limits

- RRF uses the current collection keyword scan; very large collections may
  need a dedicated sparse index after profiling demonstrates the need.
- Conflict detection is a conservative directional-term pre-screen. The
  final prompt still compares all supplied evidence.
- DDGS availability and ranking depend on public search backends, so exact web
  results are not reproducible unless captured by the benchmark harness.
- Semantic validation uses the existing BGE-M3 model. If that model is
  unavailable, the response explicitly records that the semantic check was
  skipped while deterministic citation, number, unit, and equation checks still
  apply.
- Citation precision and recall require a human-labeled evidence relevance set
  for publication-quality scoring.
