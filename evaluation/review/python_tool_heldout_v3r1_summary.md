# Python-tool held-out v3r1: strict adjudication

Product: `f71896627cc77cd6df569bb3cd140289d3667fac` · freeze: `25f198b08c1e5125e4f82701fed097c2d350a359` · run: `python-tool-v3r1-first-ab-20261005T113542Z`

Prior v3 was invalidated before any Agent run; it has no performance score. This v3r1 run is independent.

## OFF vs ON

| Population | n | Goal OFF | Goal ON | Coverage OFF | Coverage ON | Numeric OFF | Numeric ON | Unit OFF | Unit ON |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| all_12 | 12 | 8.3% | 8.3% | 50.0% | 50.0% | 13.7% | 35.3% | 5.9% | 5.9% |
| required_8 | 8 | 0.0% | 0.0% | 25.0% | 25.0% | 8.3% | 31.2% | 0.0% | 0.0% |
| pipeline_6 | 6 | 0.0% | 0.0% | 27.8% | 33.3% | 10.0% | 37.5% | 0.0% | 0.0% |
| end_to_end_2 | 2 | 0.0% | 0.0% | 16.7% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |

## Required Python funnel (ON)

| Stage | Pipeline 6 | End-to-end 2 |
|---|---:|---:|
| decision_parsed | 6/6 | 2/2 |
| tool_selected | 6/6 | 2/2 |
| plan_parsed | 6/6 | 2/2 |
| plan_materialized | 1/6 | 2/2 |
| expected_user_available | 6/6 | 2/2 |
| expected_evidence_available | 5/6 | 0/2 |
| expected_formula_available | 4/6 | 0/2 |
| required_user_selected | 6/6 | 2/2 |
| required_evidence_selected | 5/6 | 0/2 |
| formula_selected | 3/6 | 0/2 |
| facts_verified | 1/6 | 2/2 |
| formula_verified | 1/6 | 2/2 |
| execution_boundary | 1/6 | 2/2 |
| code_generated | 1/6 | 2/2 |
| sandbox_passed | 1/6 | 2/2 |
| subprocess | 1/6 | 2/2 |
| result_validated | 1/6 | 1/2 |
| calc_created | 1/6 | 1/2 |
| calc_adopted | 0/6 | 0/2 |

## Paired task outcomes

| Task | OFF criteria | ON criteria | OFF numeric | ON numeric | ON CALC | ON attribution |
|---|---:|---:|---:|---:|---|---|
| PY3R1-RE-01 | 0/3 | 0/3 | 0/6 | 0/6 | no | materialization_failed |
| PY3R1-RE-02 | 1/3 | 1/3 | 0/6 | 0/6 | no | retrieval_source_missing |
| PY3R1-RE-03 | 1/3 | 1/3 | 0/6 | 0/6 | no | materialization_failed, planner_not_selected |
| PY3R1-WT-04 | 2/3 | 2/3 | 4/5 | 4/5 | no | materialization_failed |
| PY3R1-WT-05 | 0/3 | 0/3 | 0/5 | 0/5 | no | retrieval_source_missing |
| PY3R1-WT-06 | 1/3 | 2/3 | 0/12 | 11/12 | yes | materialization_failed |
| PY3R1-RE-07 | 0/3 | 0/3 | 0/5 | 0/5 | no | retrieval_source_missing |
| PY3R1-WT-08 | 1/3 | 0/3 | 0/3 | 0/3 | yes | retrieval_source_missing |
| PY3R1-RE-09 | 3/3 | 3/3 | 2/2 | 2/2 | no | planner_not_selected |
| PY3R1-WT-10 | 3/3 | 3/3 | 1/1 | 1/1 | no | materialization_failed |
| PY3R1-RE-11 | 3/3 | 3/3 | 0/0 | 0/0 | no | planner_not_selected |
| PY3R1-WT-12 | 3/3 | 3/3 | 0/0 | 0/0 | no | planner_not_selected |

Manual QA: 24/24. Blinded reviewer: gemma4:latest; disagreements with strict adjudication: 11.
Strong Python benefit: 0/8 required.
Paired confidence intervals use 10,000 bootstrap resamples (seed 42); the small sample is not a population-level performance guarantee.

## Interpretation

The pre-freeze, LLM-free input-contract audit passed: 81/81 required USERF, 7/7 EFACT, and 7/7 specialist formula anchors were representable. This says nothing about runtime retrieval or planner success. In the single full run, all 8 required ON tasks selected Python, but only 3 reached a subprocess and 2 produced validated CALC records (pipeline 1/6; end-to-end 1/2). The validated records matched **0/15** independent numeric targets and were adopted in **0/2** final answers. The 11 correct station values in WT-06 were generated in the final answer, while CALC1 contained only `difference=1`; its mean was wrong (1.8 versus 1.9 psi) and units were absent. Thus the pooled required numeric increase (8.3% to 31.2%) is not evidence of correct Python-derived computation. Goal Success stayed 0/8 required and 1/12 overall in both conditions.

Among required tasks, external coverage changed in one beneficial pair (WT-06), one harmful pair (WT-08), and six neutral pairs. Ten of twelve pairs had identical final-answer and citation-mapping hashes. The two not-needed ON tasks selected/executed Python 0/2; one optional task selected it but did not execute it. Runtime USERF availability/selection was 77/77, but required EFACT availability was 0/7 and formula availability 3/7. Exact held-out source retrieval failed in RE-02, WT-05, RE-07, and WT-08. Plan materialization failed in five ON tasks; RE-07 and WT-08 also show failed result validation after reaching a subprocess. These failure labels can overlap.

Strict QA found 12 unsupported claims, 1 engineering contradiction, and 4 USERF-as-KB attributions in OFF versus 16, 2, and 4 in ON. RE-09 and WT-10 satisfy their three literal criteria but fail strict Goal Success because USERF-derived arithmetic was cited as KB evidence. WT-12 likewise has three literal criteria but an overbroad MBH-correction claim. The sole strict success in each condition is RE-11. The blind reviewer disagreed with manual adjudication on 11 qualitative criterion decisions; its unmodified outputs are retained.

Mean end-to-end latency was 228.0 seconds OFF versus 250.8 seconds ON overall (required: 219.5 versus 249.0 seconds). The initial deterministic scoring snapshot is retained under `python_tool_heldout_v3r1_initial_scorer_audit/`; the corrected evaluator counts written-out numbers such as “three” and excludes CALC input values from result scoring. No Agent task was rerun, no frozen task/GT/source/tolerance/rubric was changed, and no product code was modified.

## Instrumentation limits

Per-stage decision/plan/materialization/verification/codegen/subprocess times are not exposed by frozen v4; only iteration python_seconds and end-to-end elapsed_seconds are measured.

Raw run and computation outputs are retained under `D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v3r1\first_full_ab` and the product workspace.
