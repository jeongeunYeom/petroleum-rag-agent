# Python Tool Heldout v4r1 — strict first-run baseline

Product `2646be1e5439cd689fdd236e064e2f9b64255274` · run `python-tool-v4r1-first-ab-20261006T025631Z` · manual QA 24/24

| Stratum | n | Goal OFF | Goal ON | Coverage OFF | Coverage ON | Numeric OFF | Numeric ON | Unit OFF | Unit ON |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all_12 | 12 | 0.0% | 0.0% | 20.8% | 20.8% | 0.0% | 0.0% | 0.0% | 0.0% |
| required_8 | 8 | 0.0% | 0.0% | 25.0% | 25.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| pipeline_6 | 6 | 0.0% | 0.0% | 33.3% | 33.3% | 0.0% | 0.0% | 0.0% | 0.0% |
| end_to_end_2 | 2 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

## ON funnel

| Stage | Required 8 | Pipeline 6 | End-to-end 2 |
|---|---:|---:|---:|
| decision_parsed | 8/8 | 6/6 | 2/2 |
| tool_selected | 8/8 | 6/6 | 2/2 |
| plan_parsed | 8/8 | 6/6 | 2/2 |
| plan_materialized | 3/8 | 1/6 | 2/2 |
| contract_generated | 3/8 | 1/6 | 2/2 |
| contract_complete | 2/8 | 1/6 | 1/2 |
| facts_verified | 3/8 | 1/6 | 2/2 |
| formula_verified | 3/8 | 1/6 | 2/2 |
| recovery_triggered | 6/8 | 5/6 | 1/2 |
| recovery_success | 0/8 | 0/6 | 0/2 |
| execution_boundary | 3/8 | 1/6 | 2/2 |
| code_generated | 3/8 | 1/6 | 2/2 |
| sandbox_passed | 3/8 | 1/6 | 2/2 |
| subprocess | 3/8 | 1/6 | 2/2 |
| result_schema_valid | 2/8 | 1/6 | 1/2 |
| validated_calc | 2/8 | 1/6 | 1/2 |
| contract_complete_calc | 0/8 | 0/6 | 0/2 |
| gt_correct_calc | 0/8 | 0/6 | 0/2 |
| grounded_adoption | 0/8 | 0/6 | 0/2 |

Strong Python benefit: 0/8; weak/unattributed numeric improvement: 0/8.
Bootstrap: 10,000 paired resamples, seed 42; exploratory small-sample intervals only.
No product tuning or selective reruns. The first completed A/B run is the frozen baseline.
Full pre-execution contract names and units are not persisted by product v5; contract semantic metrics are observable lower bounds after result creation.

## Integrity and setup

- Evaluation branch: `feature/python-tool-heldout-v4r1`, forked from the unchanged product v5 SHA shown above. Freeze commit: `4a05deb18f95e01623da7117423ea4825fcf5c51`.
- New tasks: 12 (8 required: 6 pipeline + 2 end-to-end; 2 optional; 2 not-needed). Reservoir engineering 6, well test 4, formation evaluation 2. Canonical targets 68 (60 numeric, 8 typed, including 1 ranking); 66 required outputs.
- LLM-free preflight: USERF 80/80, EFACT 7/7, FORMULA 10/10. Independent reference, canonical and expected-contract targets all 68/68. Numeric, unit, typed, ranking, tie, argmin/argmax, scenario, duplicate, orphan and missing-target GT conflicts: **0**. Previous exact source overlap: 0. Both preflight phases passed before freeze.
- One complete first A/B: OFF 12 then ON 12, no selective reruns or product exceptions. `qwen3:8b`, temperature 0, seed 42; product-default `legacy` retrieval against the existing 18,976-chunk/12-document DB; web off. OpenAI/Gemini APIs not used.
- The prior `python_tool_heldout_v4` remains `INVALIDATED_DURING_FIRST_RUN` (two OFF responses, zero ON, no valid performance result). No performance comparison to v4 is made.

## Strict outcome

| Metric | Required OFF | Required ON | Pipeline OFF | Pipeline ON |
|---|---:|---:|---:|---:|
| Goal success | 0/8 | 0/8 | 0/6 | 0/6 |
| External criterion coverage | 25.0% | 25.0% | 33.3% | 33.3% |
| Numeric target accuracy | 0/58 | 0/58 | 0/44 | 0/44 |
| Unit target accuracy | 0/58 | 0/58 | 0/44 | 0/44 |
| Typed target accuracy | 1/8 | 1/8 | 1/6 | 1/6 |
| Scenario completeness | 0/8 | 0/8 | 0/6 | 0/6 |
| Internally complete contract trace | N/A | 2/8 | N/A | 1/6 |
| Externally complete contract | N/A | 0/8 | N/A | 0/6 |
| Subprocess reached | N/A | 3/8 | N/A | 1/6 |
| Validated CALC | N/A | 2/8 | N/A | 1/6 |
| Contract-complete CALC | N/A | 0/8 | N/A | 0/6 |
| GT-correct CALC | N/A | 0/8 | N/A | 0/6 |
| Grounded adoption | N/A | 0/8 | N/A | 0/6 |
| Mean latency | 242.0 s | 313.4 s | 265.4 s | 307.1 s |

The two end-to-end tasks also had 0/2 goal success, 0/2 GT-correct CALC and 0/2 grounded adoption; mean latency rose from 172.1 to 332.3 seconds. ON selected Python in all 8 required tasks, but only 3 reached a subprocess. Across all 12 tasks, ON selected 9 and executed 4. The optional pair had one unnecessary selection/execution; the two not-needed tasks had none.

Runtime target-fact availability in ON was USERF **80/80**, EFACT **0/7**, and FORMULA **4/10**, versus 100% for each in source-only preflight. Required recovery triggered in 6/8, succeeded in 0/8; recovered source candidates did not produce the missing target facts or a complete calculation. The two validated CALCs were both GT-wrong. Post-result semantic contract matching was observable for those two manifests only: 2/14 expected outputs (14.3% recall), 2/9 produced outputs (22.2% precision), zero scenario coverage; unit accuracy was not estimable because no numeric output matched its semantic target. This does **not** reveal complete pre-execution contracts.

## Task-level failure attribution (ON)

| Task | Primary observation |
|---|---|
| RE-P1 | Formula-variable materialization failed; recovery ineffective; no Python call or required values. |
| RE-P2 | Same formula-variable failure; no transmissibilities or ranking. |
| WT-P3 | Target formula page retrieved, but variable materialization failed; no forecast values. |
| WT-P4 | Materialization failed; final log-log slopes remained wrong; no Python call. |
| RE-P5 | Thickness/formula pages absent. Python used invented `dx=1`; internally validated CALC was GT-wrong and not adopted. |
| WT-P6 | Repeated formula-variable/fact-ID failures; no Python call. Final response leaked internal response instructions. |
| RE-E1 | Target table/formula pages absent. Python attempt hit `null` NameError, then failed result validation. |
| FE-E2 | Packing endpoint page absent. Python calculated a log-to-log ratio, not requested endpoint normalization; incomplete GT outputs. |
| RE-O1 | Correct no-tool choice, but omitted the simple final sum. |
| WT-O2 | Unnecessary Python execution; wrong planned formula and two `null` NameErrors; final answer regressed to refusal. |
| RE-N1 / FE-N2 | Correct no-tool choices, but incomplete or unsupported source-grounded conceptual explanations. |

Retrieval-source absence affected 7/12 tasks in each condition. The dominant required-task bottleneck was **retrieval of exact source facts**, followed by **planner/formula materialization** (5/8 failed there). For the tasks reaching execution, contract completeness and independent CALC correctness were still unmet. No grounded Python benefit can be claimed. A complete product-internal contract trace (2/8) is not equivalent to a benchmark-complete contract (0/8).

## QA, uncertainty, and provenance

- Blind single-reviewer `gemma4:latest` results were retained. Manual QA examined 24/24 final answers and corrected 8 qualitative criterion disagreements and 13 numeric/typed target-level false matches. In particular, the deterministic scorer had attached two wrong slope values to different segments and treated mere label mentions as argmin/tie answers. The frozen GT and tolerance were not changed.
- Strict unsupported claim counts were 13 OFF and 12 ON; engineering contradictions 0 OFF and 1 ON; provenance/CALC-overclaim counts 2 OFF and 3 ON. These are manual counts, not product self-reported hallucination rates. Three answer pairs had identical hashes; five citation-map hashes matched.
- Required paired bootstrap (10,000 resamples, seed 42) yielded delta 0 for goal success, numeric accuracy and unit accuracy, each with 95% percentile CI [0, 0]. External coverage delta 0 had CI [-0.1875, 0.1875]. Small n and a single execution prohibit broad generalization.
- Full backend tests: 660 passed, 6 warnings, 0 xfail (28 v4r1-specific tests). Frontend production build succeeded. Product files and earlier heldouts were unchanged; no prior heldout was rerun.

The first completed A/B run is the frozen **Python Tool Heldout v4r1 Baseline**. It does not establish a positive Python benefit. The next product investigation should prioritize exact-source retrieval and formula-variable binding, then enforce source-complete input contracts before code generation and detect unsupported assumptions such as `dx=1`. Those are recommendations only; no product tuning was applied during this evaluation.

Raw run files and the blind packets with full KB excerpts remain on the local evaluation host. The branch records hashes, scores, reviewer outputs, adjudication and aggregate CSVs without publishing bulk source passages from the 12-document knowledge base.
