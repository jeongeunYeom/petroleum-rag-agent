# v14 bounded development cycle

Base: `32de96cac75f6a96463e5ccebc24eab2eb061fe0`.

Development used only aggregate failure categories and fresh synthetic cases in
`backend/tests/test_agent_reliability_v14_dev.py`. Sealed v12/v13 questions,
answers, gold spans and raw responses were not inspected for these changes.

Changes: recognize percentage increase separately from decrease; preserve named
pressure operands and discard explicitly unrelated operands; admit explicitly
named dimensionless properties; bind a sole power and sole duration; pass the
complete retrieved excerpt and required goal to the existing citation validator;
name missing calculation targets instead of a generic failure where possible.
Existing Python sandbox, independent result checks and engineering validation stay.

Fresh development cases: 14 (direct 4, user formula 3, KB formula 2, knowledge 3,
premise 1, insufficient inputs 1). 28 parameterized checks include actual sandbox
calculation, provenance, route and source-transmission checks. These are development
tests, not unseen accuracy estimates. KB cases check routing, not live KB success.

Limits: this is not comprehensive language coverage; source text completeness does
not guarantee a correct local semantic judgment; unbound or ambiguous quantities
remain blocked. No retrieval tuning, frontend changes, Chroma changes or reindexing.
