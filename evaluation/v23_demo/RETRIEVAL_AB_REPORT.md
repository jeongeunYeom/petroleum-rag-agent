# V23 development retrieval A/B (not the final V4 benchmark)

Both modes ran the same 40 new, read-only questions against the existing `petroleum_knowledge` collection (12 documents; 18,976 chunks), top-5, no web. The gold document/page and 17 literal formula markers were checked against stored chunks. Two capillary-pressure cases initially pointed to the wrong page (69 instead of the actual `Po = Pf + Pc` span on page 242); their labels were corrected before this summary was calculated. The retrieved outputs themselves were not rerun or changed.

| Mode | Target document @5 | Target page @5 | Literal formula span @5 | Gold-page MRR | Median | P95 | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| hybrid | 97.5% | 80.0% | 70.6% (12/17) | 0.627 | 4.019 s | 16.799 s | 0 |
| hybrid_rerank | 97.5% | 85.0% | 64.7% (11/17) | 0.665 | 11.993 s | 37.795 s | 0 |

Conference default: **hybrid**. Reranking gains two target-page hits but loses one exact formula-span hit and approximately triples median latency on this CPU-hosted retrieval setup. For a live demo, formula recovery and responsive retrieval outweigh that small page-recall gain. This is a development choice, not a claim that hybrid is universally more accurate.

The page/span labels are conservative exact-locator checks. Gold-page MRR measures rank of a known relevant page, **not** independent semantic relevance of every top-k hit. A fully adjudicated top-k semantic relevance rate has not yet been measured. These runs also overlapped other local tests, so latencies are indicative rather than controlled hardware benchmarks. Raw rows and the label-aware summary are in `retrieval_ab_hybrid.json`, `retrieval_ab_hybrid_rerank.json`, and `retrieval_ab_summary.json`.
