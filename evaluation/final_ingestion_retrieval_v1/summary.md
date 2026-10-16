# Final ingestion/retrieval evaluation v1

## 1. Frozen version and environment

- Evaluated product: `fix/equation-retrieval-answering-v1` at `ade0d6ce133b57ef16b1892c09715643a04497d0`. Evaluation branch: `evaluation/final-ingestion-retrieval-v1`. No product code, prompt, threshold, index, or retrieval-parameter change was made during this evaluation; `main` was not merged.
- Evaluation date: 2026-10-16 (Asia/Seoul); Python 3.11.9. Backend 792 passed before unseen execution; frontend production build passed afterward.
- Agent: local `qwen3:8b`, hybrid retrieval, `BAAI/bge-m3`, web off, normal autonomous `POST /api/research/goal-runs/from-message`, default top 5 and maximum 6 iterations. No Agent seed or temperature was explicitly fixed by the product.
- Closed-book comparator: `gpt-6.1-sol` via OpenAI Responses, same question text, no KB, web, tools, Python, or figure images. Reviewer: local `gemma4:latest`, temperature 0, seed 17, applied to both systems.
- Existing `petroleum_knowledge` ChromaDB: 12 documents / 19,248 chunks, comprising 739 Formation Evaluation chunks and 18,509 other chunks. Formation Evaluation metadata records `kb-ingestion-v9` and figure analysis enabled; legacy document ingestion/figure settings were not recorded. The ChromaDB was neither rebuilt nor modified.
- Dataset `final_ingestion_retrieval_v1` was locked before unseen inference: freeze commit `f38d4ed877e774119906c8d72c4c039788423827`, rubric SHA256 `5e9978f4a43edf2c080fa4eef9cf83e6c9e475c43ba64b6490ed3e2cf0ffb19a`. The seven known regressions are wholly excluded from all unseen denominators.

## 2. Known development regressions — separate from unseen

| Case | Historical failure | Current strict result | Observation |
|---|---|---|---|
| PH-RE-024 | Safe refusal | **PASS** | Formation Evaluation p171/p172 retrieved; final Rw = 0.08 and Rwa = 0.6 ohm-m cited to p172. |
| Darcy p28 | Equation not answered from requested source | **FAIL** | A plausible relation was given, but it cited Handbook I p70 rather than Formation Evaluation p28; requested page absent from selected top five. |
| Sw square root p171 | Radical lost by text extraction | **FAIL as full task; partial content recovery** | Final text gave `Sw = sqrt(Rw/Rwa)` with p171 citation, but run stopped as insufficient evidence. This confirms the symbol can surface; it does not demonstrate goal completion. |
| Figure 4 text locator | Unnecessary visual-evidence gate | **FAIL as full task; partial content recovery** | Both p172 values were stated with citation, but run stopped as insufficient evidence. |
| True Figure 4 visual query | Figure must be read visually | **FAIL** | Wrong Figure pages selected; no visual trend fabricated. The prompt's Figure 4 locator is ambiguous across chapters. |
| Unsupported fictional relation | Unrelated equation insertion risk | **PASS** | No invented formula or numerical value. |
| Source-backed API calculation | Historical success path | **PASS** | Reservoir Engineering p90 literal equation, validated CALC1, 22.64 °API. |

Strict regression result: **3/7 pass, 4/7 fail**. These are previously seen engineering case studies, not independent performance estimates. Their raw runs and explicit judgments are in `regression_raw.jsonl` and `regression_results.json`.

## 3. Final unseen dataset

Thirty locked questions: 3 each in concept, numeric extraction, equation retrieval, calculation, figure understanding, multi-evidence synthesis, cross-document reasoning, document-specific fact, and goal-style multi-step; 2 false-premise and 1 unsupported question. Difficulty: 7 easy, 14 medium, 9 hard. Gold locators cover 18 distinct document/page pairs across 8 documents. Original PDF page text, existing Chroma page metadata, and three source figure images were audited before freeze. A scan of 437 distinct historical questions, including earlier evaluation branches, removed close matches; maximum retained character n-gram TF-IDF similarity was 0.2997. This does not prove absence of every semantic or cross-language overlap. See `rubric.json`, `source_audit.json`, `dedup_audit.json`, and `manifest.json`.

## 4–6. Agent, closed-book baseline, and comparison

**Scoring integrity:** the first-pass single reviewer mistook retrieved/gold information for actual final-answer content in several cases and emitted inconsistent citation types. Its raw output is preserved. Published metrics below use the transparent, post-freeze evaluator correction in `EVALUATOR_ERRATUM.md` and `aggregate_corrected.py`, including four documented reviewer QA corrections. Neither rubric nor model outputs were changed. This remains *single-reviewer AI-assisted semantic adjudication with deterministic answer gates and documented QA*, not a human-panel score.

| Metric | Petroleum Agent | ChatGPT closed-book | Interpretation |
|---|---:|---:|---|
| Overall answer accuracy | **10/30 (33.3%)** | **21/30 (70.0%)** | −36.7 percentage points for this fixed but unmatched-model comparison |
| Grounded answer rate | **7/29 answerable (24.1%)** | N/A | Baseline received no private evidence; do not impute zero |
| Required-claim coverage | 50.0% | 84.4% | Reviewer claims gated by actual answer presence |
| Agent evidence coverage | 65.0% | N/A | Presence of supporting evidence, independently of final use |
| Numeric accuracy | 3/13 (23.1%) | 8/13 (61.5%) | Applicable questions; required values and units or enumerated fact count |
| Equation accuracy | 3/8 (37.5%) | 6/8 (75.0%) | Includes strict source-specific decimal coefficients |
| Figure-answer accuracy | 0/3 | 0/3 | Baseline was not given images; not a matched visual test |
| Calculation accuracy | 0/5 | 4/5 (80.0%) | Formula, inputs, result; Agent also required validated CALC |
| Correct refusal | 1/1 | 1/1 | One unanswerable item only; not a stable rate estimate |
| Agent over-refusal | 15/29 answerable (51.7%) | N/A | Includes empty waiting/final answers and generic safe stops |
| Material unsupported/false claim | 3/30 (10.0%) | 0/30 detected | The single reviewer may miss additional errors |
| Goal-style completion | 0/3 | 2/3 | Baseline measures final-answer task completion, not Agent actions |
| Mean / median latency | 34.56 / 23.36 s | 9.78 / 8.19 s | Different local/API models and hardware paths |
| Agent p95 latency | 79.20 s | 21.31 s | Small-sample descriptive percentile |

All 30 Agent and 30 baseline requests completed without transport errors. Agent run states: 10 `completed`, 14 `stopped`, 6 `waiting_for_user_input`. None of the 30 Agent runs recorded a Python call or validated CALC. The Agent averaged 3.5 iterations and self-reported mean/median goal coverage of 36.1%/0%; self-status was not used as an answer correctness label. On 18 answers with citation IDs, every cited ID existed in the returned record; this **100% ID validity is not semantic support**. Across all Agent claims, the corrected citation semantic support average was 40.0%.

### Category breakdown

Rates are descriptive; most cells have only 2–3 items. `Hit@5` is the strict all-gold-page **question-only diagnostic probe**, not the Agent's unexposed planner query.

| Category | N | Agent answer | Agent grounded | Baseline answer | Hit@5 | Agent refusals/waiting |
|---|---:|---:|---:|---:|---:|---:|
| Calculation | 3 | 0% | 0% | 67% | 100% | 3 |
| Concept | 3 | 67% | 67% | 100% | 100% | 0 |
| Cross-document reasoning | 3 | 33% | 33% | 100% | 0% | 2 |
| Document-specific fact | 3 | 33% | 33% | 67% | 100% | 1 |
| Equation retrieval | 3 | 33% | 0% | 67% | 33% | 2 |
| False premise | 2 | 0% | 0% | 100% | 50% | 1 |
| Figure understanding | 3 | 0% | 0% | 0% | 0% | 3 |
| Goal-style multi-step | 3 | 0% | 0% | 67% | 100% | 2 |
| Multi-evidence synthesis | 3 | 67% | 67% | 100% | 100% | 0 |
| Numeric extraction | 3 | 67% | 33% | 33% | 33% | 1 |
| Unsupported question | 1 | 100% safe refusal | N/A | 100% safe refusal | N/A | 0 |

## 7. Retrieval, separate from answer quality

For the 28 questions with specified gold document/page pairs (excluding direct user-only calculation and the unsupported question), the frozen top-10 hybrid probe sent the **verbatim question**, with no web, to `/api/research/evidence`. Strict all-required-page **Hit@1 = 10/28 (35.7%)**, **Hit@3 = 16/28 (57.1%)**, **Hit@5 = 17/28 (60.7%)**, **Hit@10 = 18/28 (64.3%)**, and strict MRR = **0.4595**. Multi-source questions require all gold pages by K. This probe cannot be described as the actual autonomous planner query: the frozen product response does not expose that string. Actual selected top-five evidence is preserved separately in `agent_results.json` and `agent_raw.jsonl`; the probe's ranks and chunks are in `retrieval_metrics.json`.

## 8. Failure analysis and next work (not performed during this evaluation)

The 20 failed Agent questions were classified by observable *primary* cause, with the terminal symptom also retained per ID in `failure_analysis.json`:

| Primary cause | Count | Share of 20 failures |
|---|---:|---:|
| Calculation readiness/execution failure | 5 | 25.0% |
| Over-refusal despite selected evidence | 4 | 20.0% |
| Figure grounding failure | 3 | 15.0% |
| Retrieval miss in question-only probe | 3 | 15.0% |
| Synthesis failure | 2 | 10.0% |
| Material hallucination/contradiction | 3 | 15.0% |

No ingestion failure is established by this experiment: each selected gold page had at least one existing Chroma chunk, but a full equation-preservation or ingestion-causality audit was not conducted. Nor can a missing page in the **question-only** probe prove the Agent's internal retrieval query failed. The strongest observed orchestration issue is zero validated Agent calculations even when the probe found the correct source (calculation and goal-style Hit@5 were 100%). Figure retrieval and cross-document source combination are separate weaknesses. Future versions should investigate readiness transitions, source selection, figure matching, and stopping criteria; no such tuning was done here.

## 9. Poster-ready table

| Fixed 30-question evaluation | Petroleum Agent | ChatGPT closed-book |
|---|---:|---:|
| Answer accuracy | 33.3% | 70.0% |
| Numeric accuracy (13 applicable) | 23.1% | 61.5% |
| Equation accuracy (8 applicable) | 37.5% | 75.0% |
| Calculation accuracy (5 applicable) | 0% | 80.0% |
| Median latency | 23.36 s | 8.19 s |

Agent-only: grounded answer rate **24.1% of 29 answerable questions**; strict diagnostic retrieval Hit@5 **60.7% of 28 source-locator questions**. Do not present grounded or retrieval rates as a baseline comparison; do not describe the comparison as a controlled RAG ablation.

## 10. Paper-ready interpretation (Korean)

본 평가에서는 제품 커밋과 30문항 정답 기준을 추론 전에 고정하고, 개발 과정에서 이미 사용한 7개 회귀 사례를 별도로 분리하였다. 새 평가 문항의 원본 PDF와 기존 ChromaDB를 대조한 결과, 지정한 근거 페이지에는 모두 하나 이상의 저장 청크가 존재했다. 이는 평가 범위 내에서 원문 페이지가 전부 누락된 상태는 아니라는 뜻이지만, 수식·그림의 정보 보존율이나 이전 ingestion 버전 대비 개선 폭을 입증하지는 않는다. 질문 원문으로 수행한 독립 검색 진단의 엄격한 Hit@5는 60.7%였으며, 실제 자율 Agent의 검색어는 응답에 기록되지 않아 해당 수치를 내부 planner 검색 성능으로 치환할 수 없다.

동일 질문에 대한 최종 답변 정확도는 Petroleum Agent 33.3%(10/30), 내부 문서·도구·그림 없이 답한 ChatGPT 비교 모델 70.0%(21/30)였다. Agent의 근거와 답변이 함께 충족된 비율은 답변 가능한 29문항 중 7문항(24.1%)이다. 특히 계산이 필요한 5문항에서 검증된 계산 실행은 0회였고, 그림 해석 3문항도 모두 완료하지 못했다. 반면 문헌 개념과 다중 근거 요약 일부에서는 정답을 생성했고, 허구 수치를 요구한 1문항은 두 시스템 모두 안전하게 거절했다. 검색 진단에서 계산 근거가 상위 5개에 있었는데도 계산을 실행하지 못한 점은 검색 이후의 준비 상태 판정과 행동 연결이 중요한 병목임을 시사한다.

이 차이를 곧바로 검색증강의 부정적 인과 효과로 해석해서는 안 된다. Agent와 비교 모델의 기반 모델, 실행 환경, 내부 문서·그림 접근권한, 도구 사용 조건이 일치하지 않으며, 한 범주에 2–3문항뿐이다. 단일 AI 심사자의 원시 판정에는 빈 답변을 정답으로 인정하는 오류가 있어 사전 고정된 정답 기준에 따라 실제 답변 존재·필수 수치·검증된 계산을 확인하는 보정 채점을 공개적으로 적용하였다. 독립 인간 심사나 동일 모델 기반 ablation이 없는 만큼 본 수치는 작은 고정 평가셋의 기술적 결과로만 제시한다. 동일 문항·동일 환경의 이전 버전 평가가 없으므로 전체 성능 향상이라는 주장은 하지 않는다.

## 11. Merge recommendation, limitations, reproducibility

**Recommendation: NO** for `main` merge on the basis of this final evaluation. The safe-source changes recover some known cases (notably PH-RE-024 and p90 API calculation), but four of seven known regressions do not meet strict completion criteria, unseen answer accuracy is 10/30, and all unseen calculation/figure tasks fail. The product has not been modified to address these issues.

Limits: a closed-book `gpt-6.1-sol` baseline is not model-matched to local `qwen3:8b`; it had no figure images, so figure rows are capability-as-tested only. Three figure questions, one unanswerable question, and two false premises are too small for stable category claims. No paired confidence interval or causal uplift estimate is claimed. The single reviewer and documented QA may still miss semantic errors; the raw answers should remain available for independent review. The 437-question string dedup audit does not guarantee semantic novelty. Stage timings may overlap and must not be summed into total latency. The product does not expose actual planner retrieval queries or token/cost traces, so those are recorded as unavailable rather than invented.

Reproduction: use the frozen product SHA, existing original ChromaDB snapshot, local `qwen3:8b`, the frozen `rubric.json` and `SCORING_POLICY.md`, and scripts `run_product.py`, `run_baseline.py`, `run_retrieval_probe.py`, `adjudicate.py`. Existing 30×2 raw model results and 60 raw reviewer outputs are saved, so no paid re-run is required to regenerate scores: run `python evaluation/final_ingestion_retrieval_v1/aggregate_corrected.py`. Run `python -m pytest -q evaluation/final_ingestion_retrieval_v1/test_aggregate_corrected.py` for synthetic scoring checks. Original `aggregate.py` is retained for provenance but its initial answer metrics must not be quoted. Raw runs include run IDs, selected evidence IDs/chunks, answers, and timings; concise `agent_results.json` and `baseline_results.json` are supplied. Configuration, freeze hashes, and source audits are in the adjacent JSON files. No ChromaDB content is committed.
