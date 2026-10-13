# V21.2 development-smoke acceptance (declared before execution)

Use the unchanged 14 prompts in `backend/scripts/run_v21_dev_smoke.py`, the existing production KB, local `qwen3:8b`, and hybrid retrieval. Preserve earlier V21.1 results.

The 13 non-F3 cases pass only when their user-requested outputs are complete and grounded. F3 alone is an expected safe stop: no relative-permeability input means no mobility calculation or invented value.

C2 is a conceptual-plus-numeric request. It passes when the final answer explicitly includes a cited source-supported hydrostatic relation **and** a validated, provenance-linked ECD result, with both required goals MET and full goal achievement only after both. One calculation is sufficient; a second calculation is neither required nor rewarded. The unchanged historical runner's two-CALC `chain` flag will be reported separately, not rewritten or concealed.

If any non-F3 case fails this rule, do not freeze the product or run the observed old-24 regression.
