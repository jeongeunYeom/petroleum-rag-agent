# v13 unseen v2 failure analysis

Counts are non-exclusive and calculated only over failed strict-goal tasks.

- verification: 36
- citation_grounding: 25
- retrieval: 19
- unsupported_extra_claim: 19
- extraction_binding: 12
- routing: 10
- formula_selection: 5
- unanswerable_handling: 4
- false_premise: 3
- calculation_execution: 2

## Representative observed patterns

- SF01: a source-based definition ended in generic evidence refusal rather than a grounded answer.
- DC02: both pressure operands were supplied, but the Agent requested their order and no validated CALC was produced.
- KF03: the KB relationship was not adopted, so no validated formula-source chain or final numeric claim was produced.
- UF05: validated user-formula result 2.4 was printed with psi even though the supplied index was dimensionless.
- UA04: a generic input/unit/operation notice did not name the flow or geometry data needed for breakthrough time.
- FP04: a possible reviewer false positive about cited ESP detail is retained unchanged for independent audit.

No source reindex, benchmark rewrite, product hotfix, or v12 score comparison was performed.
