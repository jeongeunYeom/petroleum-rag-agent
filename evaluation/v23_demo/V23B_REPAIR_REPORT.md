# V23.1 remaining failure-class repair — development gate

**Decision: V23 product candidate `62e5c36f3d66e25addc8a2c37b63af12e2636e78` meets the V23B development freeze gate.** These prompts were used during development and are **not** unseen final evaluation results. No V4 set was created or run.

| Item | Value |
|---|---|
| Branch / starting HEAD | `feature/conference-demo-v23` / `c322c20463ddff290cc57fa13b86ca21b487625d` |
| Earlier V23 candidate | `aa44faad60c21ec685c01e8bb1d5d74aa2f5b838` |
| Repaired product SHA | `62e5c36f3d66e25addc8a2c37b63af12e2636e78` |
| Runtime | local `qwen3:8b`, `RETRIEVAL_MODE=hybrid`, web off, autonomous from-message API |
| Existing KB | `petroleum_knowledge`, 12 documents / 18,976 chunks at `D:\petroleum-rag-agent\data\vector_db`; no ingest/reindex/write |
| Final development raw results | [`real_kb_dev_v23b_final_results.json`](real_kb_dev_v23b_final_results.json), [`conference_stress_v23b_final_results.json`](conference_stress_v23b_final_results.json) |

## Repairs and their general mechanisms

| Failure class | Repair | Safety constraint retained |
|---|---|---|
| Multi-output direct requests | Parse each requested operation and label extrema with the winning input; do not stop after only a total/average when ranking or extrema remain. | Direct arithmetic still uses bounded, validated Python and user facts. |
| Wrong KB formula / extra variables | Rank literal candidates by requested output, named material/model context, bound RHS variables, local heading and the penalty for unsupplied variables. Upgrade a pinned generic relation only when a separately verified, more specific source is present. | No coefficients are supplied from intent text; every selected formula must occur in an actual source span. |
| Requested variable not isolated | Isolate a target algebraically only when it occurs once in a verified equation and the transformation is exact. Retain the original literal equation and source ID as provenance; record the execution expression separately. | No Python `eval`; ambiguous or unbound equations still cannot execute. |
| Dimensionless resume and blocker leakage | Use source/canonical variable roles for dimensionless inputs; retain source and bound facts across clarification; show the actual missing value rather than contract identifiers. | Unknown units/variables are not guessed. |
| KB conceptual answerability | Bounded same-page/neighbor expansion, atomic requested claims, source-supported relation matching, and exclusion of instructional/learning-objective text masquerading as an answer. | Citation thresholds were not globally lowered; unsupported subclaims remain partial. |
| False-premise completion | Use literal source relations and narrowly provable monotonic implications; recognize natural confirmation cues, including “yes?”, and a pore/void/non-solid-volume divided-by-bulk definition only when the full numerator–denominator relation occurs in one source sentence. | No qualitative inference from an unknown sign, domain or absent relation. |
| Run-state write exception | Give each atomic run-state write a unique temporary file name before replacing the run JSON. | The run ID/checkpoint contract and existing data layout remain unchanged. |
| Development assessor false negative | Recognize ordinary Korean explicit rejection such as “맞지 않습니다.” | Assessment-only change; no product grounding rule was relaxed. |

Product changes: `backend/app/services/{calculation_request_ir,calculation_requirements,compound_units,formula_source_registry,goal_clarification,goal_execution_agent,goal_intent,goal_knowledge_retrieval,goal_research_service,goal_simulation,premise_grounding,source_answerability,user_fact_registry}.py` and `backend/tests/test_v23_conference_reliability.py`. Development-only changes: `evaluation/v23_demo/{generate_v23b,run_real_kb_dev,run_conference_stress}.py`, the two V23B catalogs, checkpointed raw results and these reports. There is no task-ID-dependent product branch.

## Previously observed V23 diagnostics (not unseen)

The original catalogs are observed development material. Latest recorded attempts gave Knowledge **10/10**, KB formula **9/10**, Multi-goal **6/6**, same-run Resume **10/10**, and stress **198/210 (94.3%)**. The recorded KB-formula miss `KF07` is a stale assessor false negative: its actual validated calculation cites Reservoir Engineering p.242 and that literal span contains `Po = Pf + Pc`; the raw recorded flag was not silently rewritten. The old stress remains below its own 95% gate and is not presented as an unseen result.

The intermediate V23B diagnostic [`conference_stress_v23b_r9_results.json`](conference_stress_v23b_r9_results.json) retained three mechanisms: one transient run-state temporary-file exception, one Korean-rejection regex miss, and five variants of a fixed-bulk-volume porosity implication that stopped after quoting a definition. These were repaired generically and the **entire** V23B stress was restarted into a new, empty result file. Checkpoint/probe outputs are development diagnostics, not additional independent trials.

## Final-code V23B real-KB development run

Catalog: [`real_kb_dev_v23b.json`](real_kb_dev_v23b.json) (50 tasks plus 10 new resume probes). The result file is the complete single pass on the product SHA above. Times include actual local API execution.

| Category | Automatic handled | Conservative semantic handled | Median | P95 |
|---|---:|---:|---:|---:|
| Knowledge | 10/10 | **9/10** | 22.578 s | 50.297 s |
| Direct | 10/10 | 10/10 | 4.296 s | 5.703 s |
| User formula | 8/8 | 8/8 | 5.000 s | 5.703 s |
| KB formula | 10/10 | 10/10 | 32.680 s | 53.578 s |
| Multi-goal | 5/6 | 5/6 | 5.078 s | 26.296 s |
| False premise | 3/3 | 3/3 | 28.234 s | 31.500 s |
| Unanswerable | 3/3 | 3/3 | 51.282 s | 52.797 s |
| **50-task total** | **49/50 (98%)** | **48/50 (96%)** | — | — |
| Same-run Resume | **10/10** | **10/10** | 5.766 s | 60.750 s |

The extra manual downgrade is `VB-K04`: the source supports why derivative type curves were added to improve an ambiguous pressure-only match, but the final answer quotes disconnected source fragments and does not clearly state that rationale. This is **partial synthesis**, not invented evidence. The catalog's `VB-M04` asks for “their ratio” of gas and oil inputs without specifying numerator/denominator, then assumes the numeric answer 32; it also asks which differently unit-labelled volume is larger. The Agent asked for ratio order instead of guessing. The automatic failure is preserved and classified as **ambiguous development expectation / safe clarification**, not an unsupported calculation.

## Final-code V23B 220-prompt conference stress

Catalog: [`conference_stress_v23b.json`](conference_stress_v23b.json). The final file contains **one clean full pass, 220 distinct IDs**. Its 50-task and stress catalogs are both development material and share some underlying topics; they are not independent unseen replications.

| Category | Automatic handled | Median | P95 |
|---|---:|---:|---:|
| Direct | 40/40 | **3.594 s** | 4.297 s |
| User formula | 30/30 | **4.985 s** | 16.266 s |
| Knowledge | 35/35 | 21.859 s | 39.922 s |
| KB formula | 30/30 | 30.601 s | 50.969 s |
| Multi-goal | 30/30 | 4.297 s | 5.000 s |
| False premise | 20/20 | 31.938 s | 44.953 s |
| Resume | 15/15 | 5.735 s | 59.812 s |
| Out of domain | 20/20 safely stopped | 27.000 s | 63.063 s |
| **Total** | **220/220 automatic** | 11.930 s | — |

Manual review downgrades `VBST086`–`VBST090` (five phrasings of the same derivative-purpose question) to partial explanations for the same reason as `VB-K04`. **Conservative full-task handled = 215/220 (97.7%)**, still above the 95% gate. This is an answer-completeness issue, not a fabricated citation. In the final stress: technical crashes **0**, blank replies **0**, raw exception leakage **0**, invented citation IDs **0**, validator-confirmed unsupported numeric results **0**, repeated identical clarification **0**, unnecessary refusals among the 200 answerable petroleum tasks **0/200**. All 20 out-of-domain tasks stopped with no cited/validated calculation. Ten out-of-domain rows have an internal `citation_semantic_passed=false` after unsuccessful retrieval; none issued a cited engineering answer. All 200 answerable task rows have `citation_semantic_passed=true`.

The direct median meets the ≤6 s target and user-formula median meets ≤8 s. Knowledge/KB-formula P95s and some 60+ s out-of-domain safe stops remain latency limitations; a safety-preserving route optimization was not introduced in this repair.

## Semantic and provenance safety audit

- **All final automatic failures:** the only one is `VB-M04`, manually inspected as a non-numeric, same-run clarification with no invented value. The five manually downgraded stress rows and `VB-K04` were read individually; each cites literal source text but omits a clear requested explanation.
- **Seeded passed sample (`Get-Random -SetSeed 231`):** real-KB Knowledge `VB-K02,K06,K01,K08,K07`, KB formula `VB-F02,F06,F01,F08,F07`, and all false-premise `VB-P02,P03,P01`; stress Knowledge `VBST078,081,072,100,071`, KB formula `VBST116,107,135,113,106`, false-premise `VBST178,173,176,166,167`, plus purposefully `VBST181`. The cited page and excerpt were compared with each claim, not merely checked for valid IDs. No fabricated source or unsupported engineering relation was found in this sample.
- **All 30 stress KB-formula calculations:** six unique formula/source/page groups, each appearing five times, were inspected: SG→API p.90, carbonate `F=1/φ²` p.165, source-layout `F=a/fm` interpreted as `a/φ^m` p.164 with local porosity/cementation context, GOR p.559, `Po=Pf+Pc` p.242, and `Rt=Ro/Sw²` p.167. Each has a validated CALC and an actual literal source span. This is stronger than citation-ID validity alone.
- **Units:** the sampled GOR is `scf/stb`, overburden pressure `psi`, resistivity `ohm-m`, API gravity `°API` where explicitly named. `VB-F01` produces a correct API numeric result but omits the `°API` display unit under the short output name `API`; no wrong unit was accepted, but missing display specificity remains a non-blocking limitation.
- **No weak-evidence completion:** absent formulas safely stopped in all 3 real-KB unanswerable tasks; the ambiguous ratio task asked instead of guessing. An isolated OOD request can still make two slow KB retrieval attempts before safe stopping.

## Tests, integrity and decision

- Targeted V23 suite: **455 passed**, up from 271 at the starting V23 candidate (**184 new targeted cases**).
- Full backend: **2,277 passed, 6 existing dependency warnings**.
- Frontend: **23 passed**; `pnpm build` **successful**. No frontend product file changed in V23.1.
- Real production Chroma collection read after the runs: **12 documents / 18,976 chunks**. The runners asserted 18,976 before and after. No ChromaDB, frozen heldout, sealed evaluation or V4 file was modified, generated or run.
- No `main` merge. The product SHA above is frozen for a separately commissioned final unseen V4 evaluation; no performance claim here should be called an independent final result.

**Development freeze gate: PASS, including conservative manual downgrades.** Remaining non-blocking issues are derivative-purpose answer clarity, occasional missing `°API` display, and long-tail retrieval latency on complex or out-of-domain requests.
