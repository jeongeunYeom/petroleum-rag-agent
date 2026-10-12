# Frozen policy reference

The byte-identical `POLICY.md` and `benchmark.json` in this directory come from
`eval/v18-poster-final` at `e59c2959231c7997c2ab883a66708e91c14962e3`.
Their SHA-256 hashes are checked before every product or judge call. The policy's
historical V17/V18 wording is retained as frozen reference material; V20.1 is
an added paired product row, not a new unseen benchmark.

The helper `frozen_score_results.py` is the unchanged V18 `score_results.py`.
`score_reeval.py` uses its numeric matcher, agent diagnostics, percentile and
paired bootstrap without changing their scoring rules. Previously scored Qwen,
V18 and GPT rows are read from the fixed V18 evaluation commit, never rerun.
