# Agent reliability v11.1 — retrieval analysis

This is a development-only analysis of the existing 12-document / 18,976-chunk Chroma collection. The database and hybrid dense+BM25+RRF implementation were not altered.

## Changes examined

`plan_query` uses bounded, fixed petroleum-domain vocabulary to infer one of six document families. It translates user-supplied Korean technical terms into English retrieval terms and generates a core concept query plus a relation/domain query (at most three lines). Premise polarity and generic instruction/criterion text are excluded; formula retrieval keeps its existing equation-oriented augmentation.

`rerank_sources` receives up to 20 hybrid candidates and applies concept/relation overlap, title/family match, a **soft** family prior, and per-document diversity. A strong cross-domain passage can still survive. LOW-confidence evidence triggers at most one refined query, then safe stop if still unsupported. Telemetry records candidate documents, scores, selected and dropped IDs, confidence, and refined recovery.

## Six live knowledge-QA cases

| Domain | Domain document in top 5 | Relevant chunk in top 5 | Relevant top 3 | Wrong-family top 5 | Supported answer, product check |
| --- | --- | --- | ---: | ---: | --- |
| Reservoir Engineering | Yes | Yes | 3/3 | 0 | Yes |
| Reservoir Simulation | Yes | Yes | 1/3 | 0 | Yes |
| Well Testing | Yes | Yes | 3/3 | 0 | Yes |
| Petrophysics | Yes | Yes | 3/3 | 0 | Yes |
| Drilling | Yes | Yes | 3/3 | 0 | Yes |
| Production | Yes | Yes | 3/3 | 0 | Yes |

Aggregate: domain-matched document recall@5 **100% (6/6)**; relevant chunk@5 **100% (6/6)**; top-3 relevant precision **88.9% (16/18)**; wrong-domain dominance **0% (0/6)**. The Reservoir Simulation case is the weakest top-3 ranking despite successful retrieval; it should remain a regression watch point. No LOW-confidence case occurred live, so refined-retrieval recovery is **N/A**, not 100%.

The separate six premise cases also had relevant-source retrieval **6/6**. One premise case had a single wrong-domain source among its top five but still had three relevant top-three excerpts. Exact document/page provenance for each case is preserved in the JSON record. These metrics use concept/family-level development gold, not frozen benchmark task IDs or pages.

## Remaining caveat

Source selection improved, but answer synthesis can still generate redundant or more specific prose than the directly retrieved relation. The smoke's supported-answer measure relies on the product's local-model-assisted citation validation and is **not independent semantic adjudication**. This is a separate verification risk, not evidence of a Chroma ingestion problem.
