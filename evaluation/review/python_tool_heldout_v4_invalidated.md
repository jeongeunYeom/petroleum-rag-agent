# Python Tool Heldout v4 invalidated before a complete A/B run

Frozen product: `2646be1e5439cd689fdd236e064e2f9b64255274`
Freeze commit: `213231fd5c4f6bc29cefebd37f98fc9656c488cb`

The frozen P2 ground truth is contradictory: `expected_contract_outputs.lowest_cell=C5`, but `typed_targets.lowest_cell=C4`. Independent arithmetic gives C5 (141/660 = 0.213636...) below C4 (169/790 = 0.213924...). The preflight falsely passed because it validated numeric targets and typed-output counts, but not typed-output values against the independent calculation or the duplicate GT field.

The first A/B run was stopped rather than scoring against contradictory frozen GT. Two OFF responses were preserved; P3 was in progress when interrupted. ON was not started. No partial rerun occurred. Raw data: `D:\petroleum-rag-agent\data\evaluation\python_tool_heldout_v4\raw\first-ab-20261006T011627Z\python_off.json` (SHA256 `3ab3ff686e1db489c5d2b2d12c48705e926db00a08f0ea99d551874463b789b6`).

This is **not** a completed Python Tool Heldout v4 Baseline. No performance conclusion is drawn from the two responses. Frozen benchmark assets were not changed, and product v5 was not tuned. A corrected benchmark version would require a separate authorized freeze and first-run protocol.
