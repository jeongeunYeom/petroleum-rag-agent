# V21.2 final unseen evaluation policy

The evaluated product is the byte-identical application tree at `f5182b8ae2907452e1c53373055e66c5182c9b90`. The benchmark is authored after that product freeze and frozen by a separate commit before any evaluated model call. No question, gold answer, rubric, product code, or model setting may change after the benchmark freeze. One attempt per system/task; infrastructure polling may continue only the same run ID.

The primary denominator is 36 tasks. The four same-run resume probes are reported separately. Headline metrics are Goal Success, macro Claim Coverage, Hallucination-free, and Numerical Accuracy (16-task denominator). All semantic decisions use a single blinded call per task to `gpt-5.4-2026-03-05` at temperature zero. If that exact judge is unavailable, the evaluation is not finalized. Paired percentile bootstrap uses 10,000 resamples and seed 20261013.

Source candidates are selected before question writing, using seed 20261013, stratified by frozen KB document. The selection is 14 formula-like and 8 other eligible pages per document, uniformly sampled without replacement. Pages mechanically detected in prior V20.1/V21/V21.1/V21.2 development and observed regression artifacts are excluded. No old task text is displayed for question authoring.

Before tasks are finalized, novelty is measured against development and observed prompts using Unicode-normalized character 4-gram Jaccard similarity. A maximum similarity above 0.45 is rejected; any shorter prompt with eight or more consecutive identical normalized words is also rejected. This conservative lexical screen is supplemented by manual topic/family exclusion. It is not a guarantee of semantic novelty. Candidate rejection and the next predetermined source candidate are recorded before freeze.

Gold support requires a literal source span on the stated document/page. Numeric gold and units are independently calculated before freeze. After raw results exist, no invalid task replacement is allowed. Invalidity, if any, is recorded separately and denominators are transparently adjusted only under the frozen policy.
