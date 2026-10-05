# Python Tool Heldout v2 freeze policy

- This is one exploratory, paired Python OFF/ON evaluation of product SHA `f48287799ca9a780c46c1285f95d01baadc92de5`.
- Freeze the 12 tasks, input values, formula/source locators, tolerances, reference calculator, rubric, manifest, and evaluation code before the first full run. Keep the freeze commit and asset hashes.
- Run A all 12, then B all 12, once. No failed-task partial reruns. Product's own bounded retries are allowed.
- Do not modify product runtime code, tune retrieval or the tool-selection policy, or edit ground truth after seeing results.
- Preserve raw model responses, reviewer responses, deterministic scores, and any strict manual adjudication separately. Never silently overwrite an earlier layer.
- A planner parse failure, missing canonical fact, provenance rejection, or sandbox rejection is a product result, not an infrastructure failure.
- If Ollama, Chroma, the runner, or storage fails externally, preserve the incomplete run and abort. Do not resume it after a fix; a future evaluation requires a new version.
- Previously frozen `petroleum_agent_heldout_v1`, `agentic_heldout_v1`, `python_tool_heldout_v1`, and strict adjudication v1.1 remain untouched and are never rerun here.
- Do not use any held-out task for preflight smoke. Use a separate trivial synthetic fixture to test condition flags, trace persistence, and scorer parsing.
- The resulting complete first A/B run is the **Python Tool Heldout v2 Baseline**. Its sample size (12 total, 8 required) supports exploratory conclusions only.
