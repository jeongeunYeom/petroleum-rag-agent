# Agent reliability v10 — development smoke

Development regression only. This is not an unseen final benchmark or a v1/v2 rerun.

Local model: qwen3:8b · Retrieval: hybrid · Existing Chroma chunks: 18,976

| Case | Pass | Status | Actions | Validated CALC | Seconds |
| --- | --- | --- | --- | ---: | ---: |
| direct | PASS | achieved | calculate → analyze → verify → synthesize → stop | 1 | 3.338 |
| ratio | PASS | achieved | calculate → verify → synthesize → stop | 1 | 2.704 |
| user_formula | PASS | achieved | calculate → verify → synthesize → stop | 1 | 3.082 |
| user_sweep | PASS | achieved | simulate → analyze → verify → synthesize → stop | 1 | 3.87 |
| kb_formula | PASS | achieved | retrieve → calculate → verify → synthesize → stop | 1 | 44.095 |
| literature | PASS | achieved | retrieve → verify → synthesize → stop | 0 | 38.12 |
| premise | PASS | achieved | retrieve → verify → synthesize → stop | 0 | 18.279 |
| unsupported | PASS | stopped | retrieve → stop | 0 | 11.228 |
| resume | PASS | achieved | calculate → verify → synthesize → stop | 1 | 3.579 |

## Development metrics

- direct_calculation_execution: True
- ordered_ratio_execution: True
- user_formula_execution: True
- user_formula_sweep_execution: True
- kb_formula_retrieval: True
- exact_formula_span_retrieval: True
- formula_to_calculate_transition: True
- calculation_provenance_complete: 6
- calculation_provenance_denominator: 6
- false_premise_correction: True
- same_run_resume: True
- nonempty_supported_final: 8
- repeated_or_no_progress_actions: 0

## Development rates (small synthetic denominators)

- formula_source_correctness: 1/1 (100.0%)
- calculation_provenance_completeness: 6/6 (100.0%)
- false_premise_handling: 1/1 (100.0%)
- python_simulation_execution_success: 6/6 (100.0%)
- correct_action_selection: 9/9 (100.0%)
- repeated_no_progress_action_rate: 0/37 (0.0%)
- same_run_resume_success: 1/1 (100.0%)

## Limits

Synthetic/local development cases only; no claim of final benchmark performance.
The KB-formula and premise checks each cover one live example, not every engineering domain.
Unsupported formula is a safe stop, not an achieved calculation.
No Chroma reindexing, PDF re-extraction, OpenAI/Gemini call, or frozen evaluation rerun was performed.
