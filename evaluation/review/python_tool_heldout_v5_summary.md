# Python Tool Heldout v5 — first paired Agent v6 baseline

The one frozen 12+12 A/B run completed without a selective rerun. The strongest result is negative: Python ON selected a calculation tool on all eight required tasks, but executed Python on **0/8**, produced no CALC record, and lowered externally adjudicated required-task numeric accuracy from **16/69 (23.2%) to 0/69**. Required Goal Success remained 0/8 in both conditions. The ON workflow, not an executed Python calculation, caused three paired coverage harms.

## Validity qualification

The frozen preflight reported PASS and zero GT conflicts, but post-freeze manual inspection found a real tie defect in `PT5-FE-D3`: `5.4/18` and `9.6/32` are both exactly 0.3, while binary floating point made the frozen reference rank C strictly above D by 5.55e-17. The frozen benchmark/GT/rubric were not changed, and no task was rerun. Treat the full-12/full-8 strict values below as auditable exploratory scores, **not a fully valid clean held-out benchmark**. The separately labelled 11-task/7-required sensitivity excluding the invalid task preserves the principal conclusion: required Goal Success 0/7 in both, numeric accuracy 8/61 (13.1%) OFF versus 0/61 ON. See `python_tool_heldout_v5_postfreeze_validity.json`.

The external source-completeness audit requires the frozen exact chunk and parser-visible fact/formula, not merely a semantically equivalent passage. Some retrieved alternative pages support the scientific relation. Therefore its 7 iteration-level `source_complete` false positives and source-retrieval failure labels are **exact-chunk audit discrepancies**, not all proven scientific-evidence absences. Qualitative citation QA considers the actual retrieved passages.

## Provenance and preflight (requested items 1–32)

| Item | Result |
|---|---|
| 1–3 Starting branch / product SHA / evaluation branch | `feature/python-tool-v6` / `8a720a02caa557a893c4d75245bed01df565b85f` / `feature/python-tool-heldout-v5` |
| 4 Freeze SHA | `a44e0e1627a5b071649151b09aad2724f38f6417` |
| 5 Final SHA | To be recorded after report commit |
| 6–8 Product files / previous heldouts changed / previous heldouts rerun | NO / NO / NO |
| 9–12 Tasks / need / strata / domains | 12; required 8, optional 2, not-needed 2; direct 4, recovery-challenge 2, end-to-end 2; reservoir 5, well test 4, formation evaluation 3 |
| 13–16 Preflight representability / targets | USERF 47/47, EFACT 7/7, formula 8/8; 84 canonical = 69 numeric + 15 typed, including 8 ranking |
| 17 GT conflicts | Frozen preflight said 0; **post-freeze mathematical tie conflict 1** (`PT5-FE-D3`) |
| 18–24 Frozen SHA-256 | Benchmark `aa588b115ab997ca5f1a3eb2b1c2eeda83233fd12673e477eb1fc3d8612e1c60`; rubric `17f9e89b5288bca9ba7eeab9470b300159f3ee7576ffcf26e5f5dae92fdac75a`; catalog `4b871bfbd7bfdedee08fcf8ec809483dab5b7944bde167bcda0e7471729fb97b`; calculator `bc79aa2afd302e9e218a1a126dc138c39cdc827dd23b9d79a6ce99bfb636f133`; reference outputs `91d41cb2005cf0d10d26c2c27396e559b6a44b72e655a24282f3311b4d1ac0cd`; preflight `38d77ea50c78ed15bc910298ae9c66b31a8dc0ef0f6e229242243d9435c4d8b3`; freeze SHA above |
| 25–30 Conditions | qwen3:8b; temperature 0; seed 42; `legacy` retrieval; internal top-k 5 / external top-k 5; web OFF; real 12-doc/18,976-chunk `petroleum_knowledge` at `D:\petroleum-rag-agent\data\vector_db` |
| 31–32 Complete A/B runs / partial reruns | 1 / 0; OFF all 12 then ON all 12 |

No old exact task/source or synthetic-smoke fixture was reused (all contamination checks 0). Preflight LLM, Agent, Planner, Binder, Contract and Retrieval calls were all 0. Raw run ID: `python-tool-v5-first-ab-20261006T082845Z`; raw hashes are in `python_tool_heldout_v5_run_provenance.json`.

## Primary Required 8 table

| Metric | Python OFF | Python ON |
|---|---:|---:|
| Goal Success | 0/8 | 0/8 |
| External criterion coverage | 41.7% | 29.2% |
| Numeric accuracy | 16/69 (23.2%) | 0/69 |
| Unit accuracy | 1/69 (1.4%) | 0/69 |
| Typed accuracy | 2/15 (13.3%) | 2/15 (13.3%) |
| Scenario completeness | 0/8 | 0/8 |
| Initial source complete, exact-chunk audit | N/A | 1/8 |
| Post-recovery source complete, exact-chunk audit | N/A | 1/8 |
| External contract complete | N/A | 0/8 |
| Product VALIDATED CALC | N/A | 0/8 |
| Externally valid CALC | N/A | 0/8 |
| GT-correct CALC | N/A | 0/8 |
| Grounded adoption | N/A | 0/8 |
| Strong Python Benefit | N/A | 0/8 |

For all 12, Goal Success was 3/12 OFF and 3/12 ON, coverage 52.8% versus 44.4%, numeric 17/71 (23.9%) versus 1/71 (1.4%), unit 2/71 (2.8%) versus 1/71 (1.4%), and citation correctness 3/12 versus 4/12. The one ON numeric target is the optional task's ordinary 0.72 arithmetic, not Python-derived.

| Stratum | n | Goal OFF/ON | Coverage OFF/ON | Numeric OFF/ON |
|---|---:|---:|---:|---:|
| Direct | 4 | 0/0 | 33.3% / 8.3% | 43.2% / 0% |
| Recovery challenge | 2 | 0/0 | 66.7% / 66.7% | 0% / 0% |
| End-to-end | 2 | 0/0 | 33.3% / 33.3% | 0% / 0% |
| Optional | 2 | 1/1 | 50% / 50% | 50% / 50% |
| Not needed | 2 | 2/2 | 100% / 100% | N/A |

## Engineering funnel (requested items 33–82)

Required ON: decision parsed 8/8, tool selected 8/8, plan present 8/8, requirement graph built 8/8; externally correct binding **8/46 variable slots**, with 0/8 task-complete. Initial binding completeness is observable for only three tasks (0/3); the product does not persist an initial pre-recovery graph on the five recovery-triggered tasks. Initial exact-chunk source complete 1/8. Recovery triggered 5/8, with 5 first rounds and 4 second rounds: **0/9 externally required gains**, 0/5 task recovery successes, post-recovery source complete still 1/8. Some apparent product-ready states are exact-chunk audit discrepancies rather than conclusively wrong engineering readiness.

Required expected formula sources 6: initial 1, post 1, runtime bound 1. Required EFACT inputs 7: initial 0, post 0, runtime bound 0. Required USERF 44: runtime registry 44, graph-bound 8. Binding missing variables 14, ambiguous 0, unit mismatch 0, cross-scenario mismatches/missing slots 34. Iteration-level exact-chunk source-complete discrepancies: false positive 7, false negative 4; they involve three and one tasks, respectively. The clear false-negative case is user-only descriptive arithmetic `PT5-WT-D4`, for which all authored user inputs existed but product demanded a KB formula.

RequiredOutputChecklist built 3/8; mean authored-target recall 15.6% (all eight), scenario coverage 0%, aggregate coverage 25%. CalculationContract snapshot generated 3/8; product complete 0/8 and external complete 0/8. Among the three snapshots, mean output recall 17.0%, precision 18.1%, unit accuracy 4.8%, scenario coverage 0%. The recurring blocker was `calculation_contract_output_sources_missing`; other tasks stopped at wrong/missing formula variables or evidence facts. Assumption guard passes 0, blocks 0, unsupported-physical-assumption false negatives 0: no code reached it, so this is **untested safety**, not a demonstrated success.

Execution boundary 0, code generated 0, sandbox passed 0, subprocess 0. CALC record created 0, Product VALIDATED 0, externally contract-complete 0, externally valid 0, GT-correct 0, grounded adoption 0. Direct GT-correct 0/4, recovery-challenge 0/2, end-to-end 0/2, required 0/8. CALC numeric/unit/typed/ranking/scenario accuracy and adoption coverage are N/A (no CALC outputs), not zero-quality produced CALCs. No CALC grounding failure can be observed downstream of the absent record. Final-response leakage regex found 0 internal-schema, 0 internal-instruction, 0 raw-output-ID leaks; no unsupported Python-execution claim or CALC overclaim was found. Safe missing-source handling was manually confirmed on 3 required ON and 3 required OFF responses, against 7/8 exact-chunk-incomplete required tasks each; this rate is sensitive to alternative-source equivalence.

| Required ON task | Furthest selected-tool stage* | Recovery rounds / gain | Immediate observed blocker |
|---|---:|---:|---|
| PT5-RE-D1 | 10 contract generated | 0 / 0 | Empty output source IDs in contract |
| PT5-WT-D2 | 4 graph | 2 / 0 | Wrong selected formula variable `t`, unbound to `tD/CD` inputs |
| PT5-FE-D3 | 4 graph | 2 / 0 | Wrong `FR` variable attribution; also frozen C/D tie defect |
| PT5-WT-D4 | 8 source audit only* | 2 / 0 | User-only arithmetic refused for lack of KB formula |
| PT5-RE-R1 | 10 contract generated | 0 / 0 | Empty output source IDs; no execution |
| PT5-RE-R2 | 4 graph | 2 / 0 | Formula present, example `Pf` fact missing |
| PT5-WT-E1 | 10 contract generated | 0 / 0 | Missing historical rates / empty output source IDs |
| PT5-FE-E2 | 4 graph | 1 / 0 | Wrong `Rt/Rxo` requirement, unsupported Sw examples |

\* Furthest-stage numbering in deterministic output uses maximum observed marker, not a sequential state machine. In particular stage 8 is an external source-audit marker and does not mean Python was executed. On optional/not-needed tasks, this stage is not meaningful unless tool selection occurred.

## Paired quality, harm and latency (requested items 83–115)

Manual QA corrected three numeric false matches and one missed true value, plus three typed false matches: shared-line case values had been misassigned to `F/H`, `B_Pc=475` was mistaken for the `Po` range, and a mere `A-D` mention was mistaken for leader A (in both conditions); a `D_Pc` mention was mistaken for final `Po` leader. Reviewer raw was never overwritten. Six C1/C3 reviewer decisions were corrected, including inconsistent decisions on identical OFF/ON answers. All 24 final answers were reviewed alongside cited evidence; for required ON 8, requirement graphs, recovery rounds, contract snapshots and the absence of code/CALC manifests were checked.

Required OFF→ON: Goal 0→0; coverage 41.7%→29.2%; numeric 23.2%→0%; unit 1.4%→0%. Direct, recovery and end-to-end values are above. Strong Python Benefit 0/8; weak/unattributed numeric improvement 0/8. Paired criterion coverage: benefit 0, neutral 5, harm 3. The harm is from the **ON workflow's refusals**, not from wrong Python arithmetic, since Python never executed. Optional tool selection/execution 0/2 and 0/2; not-needed selection/execution 0/2 and 0/2.

Distinct manually counted unsupported answer claims: OFF 13, ON 9; engineering contradictions 0/0; Python-unsupported claims 0/0; user-derived values attributed only to KB citations OFF 22, ON 8; CALC overclaims 0/0. Some numeric errors are also represented in target-level numeric accuracy, so these counts must not be added to it. Identical answer pairs 8/12 and identical cited-evidence mapping pairs 8/12.

| Latency | OFF | ON |
|---|---:|---:|
| All-12 mean / median / P95 | 238.2 / 237.8 / 377.1 s | 316.8 / 297.4 / 503.0 s |
| Required-8 mean / median / P95 | 253.8 / 250.2 / 377.1 s | 369.9 / 386.5 / 503.0 s |
| Required ON recovery-triggered mean | N/A | 413.3 s (5 tasks) |
| Required ON without recovery mean | N/A | 297.6 s (3 tasks) |

Paired bootstrap: 10,000 task-pair resamples, seed 42, 95% percentile CI; small-N exploratory only. All-12 ON−OFF: Goal 0 [0,0], Coverage −0.083 [−0.167,0], per-task Numeric −0.163 [−0.396,0]. Required-8: Goal 0 [0,0], Coverage −0.125 [−0.250,−0.0417], per-task Numeric −0.244 [−0.572,−0.00962], Unit −0.00962 [−0.0288,0]. Pipeline-6: Goal 0 [0,0], Coverage −0.167 [−0.278,−0.0556], Numeric −0.325 [−0.659,−0.0128]. Per-task bootstrap weighting differs from pooled target accuracy.

Single AI-assisted semantic reviewer: local `gemma4:latest`, blind shuffled packets without OFF/ON, tool, recovery, graph, contract or CALC state; 24/24 parsed. Deterministic numbers/units/GT and human evidence QA overrode reviewer where needed. Manual QA 24/24; reviewer criterion correction count 6. New evaluation tests 37 (24 preflight/GT plus 13 scoring/review); full backend pytest **692 passed, 6 warnings, xfail 0**. Local frontend `pnpm build` passed. OpenAI API NO; Gemini API NO. Commit/push/CI/clean-tree status is recorded after publication.

## Answer to the 17 engineering questions

1. Actual autonomous Python execution on unseen required tasks? **No, 0/8.**
2. Formula-variable binding? **8/46 correct slots, 0/8 task-complete.**
3. Initial exact-chunk source complete? **1/8.**
4. Did recovery fill a required missing input? **No, 0/9 rounds.**
5. Did post-recovery source completeness rise? **No, 1/8→1/8.**
6. Product source-complete false positives? **Seven iteration-level exact-chunk discrepancies in three tasks; alternative equivalent passages limit interpretation.**
7. Complete RequiredOutputChecklist? **No; built 3/8, mean target recall 15.6%.**
8. Externally complete CalculationContract? **No, 0/8.**
9. Unsupported physical constants entered Python? **No code execution; cannot test execution-time guard.**
10. Externally valid CALC? **0/8.**
11. GT-correct CALC? **0/8.**
12. Grounded adoption? **0/8.**
13. Numeric accuracy improvement ON vs OFF? **No; 0/69 vs 16/69.**
14. Strong Python-attributable benefit? **0/8.**
15. Goal Success improvement? **No; 0/8 in both.**
16. Harm? **Yes, three paired coverage harms and lower numeric accuracy from ON workflow; not an executed-Python harm.**
17. Dominant bottleneck? **Pre-execution evidence/formula/variable readiness and incomplete output contracts.** Secondary failures include fabricated Sw examples and final synthesis ignoring an explicit `Po=Pf+Pc` passage.

Interpretation: **No evidence was found that autonomous Python improved end-to-end performance in this exploratory held-out evaluation.** Since no CALC was produced, claims that v6 solved autonomous calculation, that recovery solved retrieval, or that v6 outperforms v5 are not supported. A future corrected held-out should fix the C/D tie in a new frozen version, preserve the v5 raw baseline, and test the pre-execution gates separately; product fixes belong on a separate branch.

## Artifact index

Raw OFF/ON JSON is under `D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v5\raw\first-ab-20261006T082839Z\`. The repo contains the frozen benchmark/manifest/rubric/source catalog/reference outputs, preflight and GT audit, deterministic score, binding/recovery/contract/CALC/funnel/iteration CSVs, one reviewer raw JSON plus blind ID mapping, manual QA JSON, strict adjudicated JSON/CSV, post-freeze validity notice and run provenance. Blind packets include source excerpts and are retained outside Git with raw evaluation data; they are not published in the repository.
