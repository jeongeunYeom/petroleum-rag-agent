# Full KB re-ingestion v1 — staged audit

Decision: **STAGED_BLOCKED. Do not switch the production DB. Do not merge main.**
This is a knowledge-ingestion audit, not an Agent benchmark or evidence of improved answer accuracy.

## 1. Backup

- Branch at start: fix/agent-task-completion-v1; HEAD f44ff3e7eb5b849d56182767fdcff4a21be72a1f.
- Production data: D:\petroleum-rag-agent\data; Chroma: D:\petroleum-rag-agent\data\vector_db.
- Pre-run backup: D:\petroleum-rag-agent-kb-backup-before-full-reingest-20261017-175102\vector_db.
- Backup verified: 6 files, 286,119,838 bytes; chroma.sqlite3 199,065,600 bytes; SQLite integrity_check = ok. Both backup and untouched production collection petroleum_knowledge still contain 19,248 chunks from 12 documents.
- The replacement DB was built only at D:\petroleum-rag-agent-data-full-reingestion-v1\vector_db.

## 2. PDF inventory

Twelve raw PDFs, 8,089 pages and 346,188,246 bytes map 1:1 to the 12 production DB document IDs. There are no raw-only or DB-only IDs, duplicate hashes, same-name/different-digest PDFs, or filename/hash mismatches. Eleven old metadata records lack kb-ingestion-v9 provenance; only Formation Evaluation previously recorded kb-ingestion-v9 and figure_analysis_enabled=true. Full SHA256, path, size, pages and old per-document counts are in document_inventory.json.

## 3. Legacy ingestion audit

Twenty-four source pages in eight PDFs were compared across rendered PDF, PyMuPDF text, old extracted text and old Chroma chunks (body/equation/Figure samples per document). None of these 24 sampled pages had a structured equation or Figure chunk in the old DB.

- Well Test Analysis p75: the printed layered radial-flow fraction, indices and numerator/denominator collapse into isolated tokens in PDF text. p77 contains a drawn Figure that the embedded-image path does not capture.
- Drilling Engineering p75: P = 0.052 × MW × TVD and psi/ppg/ft remain literal text, but there was no old equation chunk.
- Handbook II p80: the membrane-efficiency equation survives as flattened text; subscripts and mathematical layout are lost.
- Handbook I p75 and Reservoir Simulation p75: matrix/tensor terms and layout are fragmented in the text layer.
- Reservoir Engineering p90: API = (141.5 / SG) - 131.5 remains literal text, without a structured old equation chunk.

See legacy_audit.json for all 24 page excerpts, metadata and page numbers.

## 4. Full re-ingestion

All 12 PDFs completed with the current DocumentProcessor.extract(..., analyze_figures=true) → semantic/text, equation and Figure processing → VectorStore.add_chunks path. They were copied and SHA-checked into the isolated staging data directory; the old DB was never cleared or ingested into. All staged records have ingestion_version=kb-ingestion-v9, figure_analysis_enabled=true and a matching Chroma chunk count. Completed per-document processing time sums to 9,207.08 seconds (2 h 33 min 27 s), excluding the aborted first attempt and the later read-only checks.

The first local Vision attempt reproduced Ollama HTTP 400 exceed_context_size_error: the image plus verification prompt exceeded num_ctx=4096. The generic image request context was raised to 8192, covered by a focused regression test, and the affected Formation PDF was reprocessed. Handbook VII, originally processed before the fix, was also reprocessed in staging. Across 3,915 final candidate JSON files there are zero occurrences of exceed_context_size_error. No paid/external model or OpenAI API was used; local qwen2.5vl:7b handled Vision, while BAAI/bge-m3 embeddings ran on the local RTX 3090.

Operational limits remain: candidate budgets leave many equations review_required; Drilling p446 has 1,571 tiny embedded elements that were rejected as decorations; some original JPX images could not be decoded; repeated identical Vision-input hashes occurred (35 groups in Production Technology II). These were recorded, not silently promoted to verified evidence.
Across all documents, equation candidates were 305 valid / 3,071 review_required / 62 failed; Figure candidates were 143 valid / 321 review_required / 9 failed / 7,347 ignored. The 143-vs-142 valid-Figure/indexed-Figure difference is diagnosed in section 7.

## 5. Before → after

Old category counts came from Chroma metadata; a larger chunk count alone is **not** a quality improvement.

| PDF | Old total | Old eq/fig | New total | New text | New verified eq | New fig | Overall sample |
|---|---:|---:|---:|---:|---:|---:|---|
| Well Test Analysis | 1,257 | 0/0 | 1,952 | 1,893 | 14 | 45 | FAIL: p75 equations unverified; Figure note axis error |
| Handbook II | 2,255 | 0/0 | 3,146 | 3,127 | 19 | 0 | PARTIAL: p80 formula flattened, no verified equation chunk |
| Production Technology I | 834 | 0/0 | 1,546 | 1,527 | 19 | 0 | PARTIAL: text/page retrieval works; Figure coverage unproven |
| Handbook III | 1,641 | 0/0 | 2,319 | 2,289 | 29 | 1 | PARTIAL: representative text found; JPX decode warnings |
| Reservoir Simulation | 978 | 0/0 | 1,718 | 1,686 | 23 | 9 | PARTIAL: p75 tensor equation remains layout-damaged/unverified |
| Handbook VII | 657 | 0/0 | 1,214 | 1,213 | 1 | 0 | PARTIAL: expected p110 misses retrieval top-5 |
| Handbook V | 4,767 | 0/0 | 6,521 | 6,499 | 22 | 0 | PARTIAL: page/text found; Figure candidates not validated |
| Production Technology II | 1,292 | 0/0 | 3,242 | 3,178 | 20 | 44 | PARTIAL: text/page found; repeated Vision inputs and Figure review load |
| Drilling Engineering | 1,044 | 0/0 | 1,556 | 1,499 | 50 | 7 | FAIL: p201 valid Figure note reverses axes |
| Handbook I | 2,268 | 0/0 | 3,122 | 3,091 | 29 | 2 | PARTIAL: matrix layout loss; p75 has verified and review-required candidates |
| Formation Evaluation | 739 | 46/14 | 759 | 679 | 53 | 27 | PARTIAL: required equation regression passes; Figure note adds unsupported acronym |
| Reservoir Engineering | 1,516 | 0/0 | 2,142 | 2,109 | 26 | 7 | PARTIAL: p90 API formula intact in text, not an equation chunk |
| **Total** | **19,248** | **46/14** | **29,237** | **28,790** | **305** | **142** | **Blocked for production** |

The sample status is a source-versus-index quality judgment, not a benchmark pass rate. Detailed valid/review_required/failed/ignored counts and warning categories appear in before_after.json and ingestion_progress.json.

## 6. Equation audit

- Formation p28: exact reviewed crop/source gives verified Q = k*A*DeltaP/(l*mu) — PASS.
- Formation p171: exact reviewed source gives verified S_w = sqrt(R_w/R_wa) — PASS. The adjacent R_wa = R_t/F relation is also present. All three manual_visual_audit equation chunks belong to Formation; the exact-PDF reviewed manifest was not applied to another document.
- Reservoir Engineering p90: API = (141.5 / SG) - 131.5 is preserved literally in the new page text and returned at rank 2 for its representative query; no verified equation chunk on p90 — PARTIAL.
- Drilling p75: P = 0.052 x MW x TVD and units P(psi), MW(ppg), TVD(ft) remain in text and the expected page is retrieved; no p75 equation chunk — PARTIAL.
- Handbook II p80: ΔP = Em(RT/V) ln(Ap/Am) remains text and p80 is retrieved, but subscript layout is flattened and no verified equation chunk exists — PARTIAL.
- Well Test p75: the crop visibly contains q_i = (2πk_i h_i)/(μ ln(r_e/r_w))(p_e-p_w). Local Vision transcribed the relation, but the PDF text layer lacks these symbols. Both candidates correctly remain review_required and no p75 verified equation chunk exists — FAIL for formula-source readiness.
- Reservoir Simulation p75: tensor Darcy symbols are damaged in PDF text; candidate verification does not recover a trusted p75 equation — PARTIAL.
- Handbook I p75: one candidate is verified and one remains review_required — PARTIAL.

Numerator/denominator, Greek symbols, sub/superscripts and units were judged against the rendered source on these examples. Presence of isolated term strings in a page is not equivalent to an executable verified equation. See equation_audit.json and candidate records.

## 7. Figure audit

Twenty-four Figure audit entries were sampled; every referenced image file exists and each note page matches its Chroma page metadata. This tests linkage only, **not semantic correctness**.

- Formation p172 Figure 4: correct document/page/crop/source caption (“Figure 4 Rwa Curve recorded on ISF/sonic log”), and the Figure chunk is found in top-5. However the valid note expands ISF to “Induction Sonic Formation” without visible source support — semantic PARTIAL.
- Drilling p201 “d Exponent Plot”: source image has horizontal d Exponent and vertical Depth, but a valid note says x=Depth and y=d Exponent and asserts a decline. This is a false-positive validity decision — FAIL.
- Well Test p261 log-log graph: source horizontal axis is Equivalent Time and vertical is Delta P; a valid note reverses them — FAIL.
- Well Test p75 Figure 65 is drawn/vector content and has no Figure chunk; its Figure-specific retrieval check fails — missing Figure coverage.
- Drilling p446 has 1,571 small embedded elements, rejected as decorations without Vision calls. No reviewed chapter-logo false positive was observed in the sampled crops, but that does not certify every candidate.
- Reservoir Simulation p361 has two valid image candidates serialized as equation notes inside one Figure section. The Figure-block splitter expects Figure Note Metadata, so the two notes are merged into one Figure chunk. This explains why its candidate valid count is 10 but indexed Figure count is 9; those equation-shaped Figure notes should not be treated as separately validated equation sources.

Figure notes must not be used as a source of numeric curve readings without separate visual validation. See figure_audit.json and the exact candidate JSON files in the staged data directory.

## 8. Formation Evaluation regression

New DB p28 has verified Q = k*A*DeltaP/(l*mu); p171 has verified S_w = sqrt(R_w/R_wa); p172 text chunks contain the Rw=0.08 ohm-m and Rwa=0.6 ohm-m example. Figure 4 page/caption/image linkage is intact. The exact-hash/crop reviewed manifest still applies only to Formation. This **content** regression passes, while p172 Figure-note semantics remain a production blocker.

## 9. Retrieval sanity

Hybrid BGE-M3 dense + BM25 retrieval returned the expected document in top-5 for 12/12 representative queries; expected page appeared in top-5 for 10/12. Well Test p75 and Handbook VII p110 missed the expected page. Additional Figure checks: Formation p172 and Drilling p201 Figure chunks were in top-5; Well Test p75 was not (2/3). Top ranks/pages, source-page text and indexed text excerpts are stored in retrieval_sanity.json. This is DB search sanity only; no Agent benchmark or final-answer accuracy test was run.

The staged backend returned HTTP 200 from /api/system/checklist with 12 documents, 29,237 chunks, local qwen3:8b and qwen2.5vl:7b available. The standard staged retrieval-health script exited successfully. Its temporary 127.0.0.1:8002 server was stopped afterward.

## 10. New KB baseline

Name: full-reingestion-v1, **staged only / STAGED_BLOCKED**. Chroma collection petroleum_knowledge at D:\petroleum-rag-agent-data-full-reingestion-v1\vector_db has 12 documents and 29,237 chunks: 28,790 text, 305 verified equation and 142 Figure chunks. All 12 records use kb-ingestion-v9 with analyze_figures=true; embedding model BAAI/bge-m3. Document hashes and counts are frozen in manifest.json. No production switch was performed. The old/backup DBs remain at 12 documents and 19,248 chunks.

The ingestion was started from the f44ff3e working tree with the one-line Vision context fix applied and later committed; some candidate generator_git_commit fields therefore show the startup HEAD. The committed equivalent code and audit scripts are recorded by the final branch SHA. This run-lineage nuance does not change the raw PDF hashes or stored chunk counts.

## 11. Remaining problems

1. Source text corruption plus strict symbol-grounding leaves important Well Test p75 and Reservoir Simulation p75 equations unverified. Manually verified image crops cannot simply be promoted without a safe provenance design.
2. Figure-note semantic validation accepts swapped graph axes (two sampled examples) and an unsupported acronym expansion. This is a correctness blocker even though page/image linkage passes.
3. Embedded-image-only extraction misses at least one vector Figure (Well Test p75). Other books with zero Figure chunks need broader visual coverage audit.
4. Some exact equation pages are preserved only as flattened text (Handbook II p80, Reservoir Engineering p90, Drilling p75). The Vision budget also leaves many candidates review_required.
5. Two representative page retrieval checks fail; repeated identical Vision inputs and malformed JPX assets cause avoidable time/coverage loss.
6. Mixed Figure/equation note metadata on Reservoir Simulation p361 merges distinct visual candidates into one chunk, weakening citation granularity.

## 12. Recommendation

**NO** — do not activate the staged DB, claim a production-ready unified KB baseline, or begin the next Agent task-completion revision against it yet. First fix/evaluate the generic source-aware equation verification and graph-axis/Figure semantic guardrails, then selectively reprocess affected documents and repeat this audit. Existing production ChromaDB is retained. No main merge, final benchmark, Agent logic change, or paid external-model evaluation was performed.

Verification: backend pytest 837 passed, 6 warnings; staged retrieval health PASS; staged backend health HTTP 200; production/backup/stage collection counts 19,248 / 19,248 / 29,237. Frontend was not changed.
