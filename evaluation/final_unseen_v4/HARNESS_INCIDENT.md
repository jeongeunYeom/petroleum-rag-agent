# Evaluation harness incident before first V4 model call

After catalog sealing (SHA-256 `2bb620232232a2aaf02964de9d5b83f41f4df5f6386ab85724fd26c06f09a2aa`), the first Agent runner invocation on 2026-10-15 produced 60 immediate `harness_error` rows. Every row had `run_id=null`, zero or near-zero elapsed time, and the same exception: Chroma's in-process client had been opened with default telemetry settings in the evaluation preflight, while the frozen product opens that existing DB with telemetry disabled. The failure happened before a Goal Research run was created, so **no V4 task reached the model**.

The unmodified first output is preserved as `agent_harness_failure_results.json`. Only `run_conditions.py` was changed: its preflight and post-run count checks now open Chroma with the same telemetry setting as the product. The sealed catalog, rubric, gold, product files, retrieval behavior and KB were not changed. The runner was also given an app-initialization-only check so this issue can be tested without submitting a V4 task.

Under V4 Protocol rule 9, this technical harness failure permits rerunning the **same immutable catalog** after an evaluation-only harness repair. The replacement `agent_results.json` will be a new full pass. This incident is not counted as 60 Agent answer failures; it remains an explicit evaluation infrastructure event.
