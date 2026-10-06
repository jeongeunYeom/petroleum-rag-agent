# Python Tool Heldout v4r1 evaluation policy

Product is fixed at `2646be1e5439cd689fdd236e064e2f9b64255274`. This branch changes evaluation assets only. OpenAI and Gemini APIs are not used.

The prior `python_tool_heldout_v4` remains **INVALIDATED_DURING_FIRST_RUN** because of `GROUND_TRUTH_CONSISTENCY_CONFLICT`: `PT4-RE-P2` expected-contract and independent arithmetic said C5 while the typed target said C4. It produced two OFF responses, zero ON responses, zero complete A/B runs and **no valid performance result**. Do not edit or rerun it, compare performance with it, or reuse its scenarios, numbers or source pages.

## Freeze gate

Before freeze, both LLM-free phases must pass:

1. Input/source contract: every required USERF, EFACT and parseable FORMULA exists in v5's supported registries; the cited source chunk exists in the 18,976-chunk KB and has no excluded exact page/chunk overlap.
2. GT integrity: independent reference outputs match canonical targets, numeric/typed/ranking/contract projections, units, ties, extrema, scenarios and required-criterion references. All conflicts must be zero.

The reference calculator is independent of the Agent. No task is run through planner, contract builder, retrieval or any LLM during preflight. A failed gate forbids freeze and execution; GT consistency failures are ordinary test failures, never xfails.

After the PASS preflight, freeze benchmark, reference outputs/calculator, source catalog, tolerances, criteria and rubric. The runner verifies their hashes and repeats the GT audit read-only before task one. Runtime GT mismatch invalidates the whole run; no on-the-spot correction.

## One A/B run

One complete 12 OFF then 12 ON run, qwen3:8b temperature 0 seed 42, product-v5 default retrieval, internal KB only, web off. OFF denies Python; ON allows and approves Python. No selective reruns. Product failures are scored; infrastructure failure yields an incomplete run.

Use deterministic scoring for numeric, units, typed/ranking outputs, contracts, CALC and paired effects. Use one blind gemma4:latest reviewer only for qualitative criteria, then manual QA of all 24 final answers. Preserve raw reviewer and record corrections separately. A strong benefit requires OFF failure, ON GT-correct CALC, grounded final adoption, and the same criterion passing ON. Do not infer a Python benefit from a weaker numeric delta.
