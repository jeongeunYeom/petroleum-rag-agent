# Python Tool Heldout v4 policy

This is a new exploratory 12-task benchmark of product SHA `2646be1e5439cd689fdd236e064e2f9b64255274` on branch `feature/python-tool-heldout-v4`. Product code and all earlier held-outs stay unchanged.

Pre-freeze audit is LLM-free and checks admissibility only: USERF/EFACT/formula recall, source locations and overlap, independent GT, supported units, and task balance. It does not call the planner, contract builder, retrieval query, code generator, or research model. Only PASS permits freeze and one full OFF 12 then ON 12 run.

OFF disables and disapproves Python. ON enables and approves it. Otherwise requests are identical: qwen3:8b, temperature 0, seed 42, internal KB only, default top-k 5, default legacy retrieval, max four iterations, no-progress patience two. No per-task reruns. Save an interrupted infrastructure run as incomplete. Treat product behavior failures as observed outcomes.

Frozen task wording, GT, source catalog, tolerances, criteria and rubric may not be changed after freeze. Evaluation code may be corrected transparently with raw outputs retained; no product tuning. Deterministic numeric/unit/CALC judgments override the one blind semantic reviewer. Manual QA covers all 24 answers and CALC traces. Report small-sample paired uncertainty and do not claim causal Python benefit without GT-correct grounded adoption.

A Git commit cannot contain its own SHA or its own full-file SHA256 as self-referential literal data. The frozen manifest records hashes of the other immutable assets; run provenance records the actual freeze commit SHA and manifest SHA256 externally. No main merge.
