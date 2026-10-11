# Scoring implementation audit

All 52 generation responses and 26 paired judge responses are preserved unchanged.
No model calls were repeated. Product, benchmark and scoring policy stayed frozen.

The reviewer emitted integer `1`/`0` for some binary fields (notably numeric
accuracy for P15 and P20), despite boolean examples in the prompt. The initial
aggregation used Python `is True`, which incorrectly rejected integer 1. The
final parser accepts only JSON booleans, binary integers, or null where applicable.
This is representation normalization, not re-adjudication or a rubric change.
A regression self-check covers the behavior. Only final corrected aggregates and
figures are deliverables; raw responses have not been edited.

Reviewer limitation: some judgments are stricter than ordinary engineering
interpretation. For example, an otherwise correct compressor discussion was
flagged for extra piping/pressure-loss details not spelled out in the reference.
Those judgments are retained, not selectively overturned. Reported hallucination
is therefore this single AI reviewer's assessment, not an independently established
factual error rate. High claim-coverage but unsuccessful answers can also reflect
the frozen all-required-claims rule. Human validation remains a limitation.
