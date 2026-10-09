# Development-only Python execution diagnostic v1

This is an eight-case synthetic gate fixture, **not** an Agentic Baseline rerun, benchmark, or performance score. Plans are explicit fixture data; the real `GoalToolPlanner` model was not called. A deterministic fake code generator supplied D1/D4 code to the unchanged `GoalPythonAnalysis` and local `PythonTools` sandbox. Evaluation-only spies observed validation, permission, subprocess, and result-validation boundaries. No OpenAI, Gemini, or Ollama model call occurred.

| Case | Selected / plan | Facts verified | Request approval | Call boundary | Subprocess | Result / CALC | Stage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D1 evidence A=10 mD, B=20 mD | yes / yes | pass | yes | yes | yes, exit 0 | pass / CALC1 | CALC_VALIDATED |
| D2 numbers only in task, evidence has formula | yes / yes | fail | yes | no | no | no / no | EVIDENCE_ID_NOT_FOUND |
| D3 task numbers, sourced specialist formula | yes / yes | fail | yes | no | no | no / no | EVIDENCE_ID_NOT_FOUND |
| D4 evidence contains inputs and specialist formula | yes / yes | pass | yes | yes | yes, exit 0 | pass / CALC1 | CALC_VALIDATED |
| D5 10 mD evidence, 10 psi plan | yes / yes | fail | yes | no | no | no / no | UNIT_NOT_IN_EXCERPT |
| D6 sourced inputs, unsourced specialist formula | yes / yes | fail | yes | no | no | no / no | FORMULA_PROVENANCE_MISSING |
| D7 valid inputs, approval absent | yes / yes | pass | no | no | no | no / no | PERMISSION_NOT_APPROVED |
| D8 repeat D1 after success | yes / yes | pass | yes | no new call | no second run | cached pass / CALC1 | CACHE_HIT |

The explainer's first-failure result was cross-checked against the production `verified_facts()` boolean for all seven distinct plans. D8 reused D1's plan and cached computation. D1 and D4 are the only local subprocess executions. Synthetic task-only values are **not** admissible to the current provenance predicate unless copied into a cited evidence record with a matching ID, excerpt, value, and unit. This does not establish what the unrecorded frozen plans contained.

Output data: `D:\petroleum-rag-agent\data\evaluation\python_tool_execution_diagnostic_v1.json` (frozen post-hoc rows and all eight fixtures) and `D:\petroleum-rag-agent\data\evaluation\python_tool_execution_diagnostic_v1.csv` (eight fixture rows). Neither output contains API keys, environment values, full environment data, or `.env` contents.
