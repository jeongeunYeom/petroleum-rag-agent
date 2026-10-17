# Agent task-completion development regression

This reuses the previously seen 30 tasks. It is **not** an unseen benchmark or semantic accuracy score.
`Before` is the prior run status; `After` is the current agent goal status. Neither alone measures answer correctness.

Rows: 30; agent achieved: 13; Python calls: 1; validated CALCs: 0.

| ID | Type | Before | After | Actions | Page hit | Suspected issues |
|---|---|---|---|---|---|---|
| FIR-001 | concept | completed | achieved | retrieve→verify→synthesize→stop | yes | — |
| FIR-002 | concept | completed | achieved | retrieve→verify→synthesize→stop | yes | — |
| FIR-003 | concept | completed | achieved | retrieve→verify→synthesize→stop | yes | — |
| FIR-004 | numeric_extraction | completed | stopped | retrieve→verify→stop | yes | grounded_completion_or_reasoning_unresolved |
| FIR-005 | numeric_extraction | stopped | achieved | retrieve→verify→synthesize→stop | yes | — |
| FIR-006 | numeric_extraction | completed | achieved | retrieve→verify→synthesize→stop | yes | — |
| FIR-007 | equation_retrieval | waiting_for_user_input | pending | retrieve→retrieve→retrieve | yes | required_numeric_value_missing, grounded_completion_or_reasoning_unresolved |
| FIR-008 | equation_retrieval | stopped | achieved | retrieve→verify→synthesize→stop | yes | — |
| FIR-009 | equation_retrieval | stopped | stopped | retrieve→verify→retrieve→verify→retrieve→stop | no | required_numeric_value_missing, grounded_completion_or_reasoning_unresolved, preferred_page_not_retrieved |
| FIR-010 | calculation | waiting_for_user_input | stopped | retrieve→calculate→retrieve→verify→retrieve→stop | yes | validated_calculation_missing, required_numeric_value_missing, grounded_completion_or_reasoning_unresolved |
| FIR-011 | calculation | stopped | pending | retrieve→retrieve→retrieve | yes | validated_calculation_missing, required_numeric_value_missing, grounded_completion_or_reasoning_unresolved |
| FIR-012 | calculation | waiting_for_user_input | stopped | calculate→retrieve→calculate→retrieve→verify→retrieve→stop | no | validated_calculation_missing, required_numeric_value_missing, grounded_completion_or_reasoning_unresolved, preferred_page_not_retrieved |
| FIR-013 | figure_understanding | completed | achieved | retrieve→verify→synthesize→stop | no | figure_evidence_missing, preferred_page_not_retrieved |
| FIR-014 | figure_understanding | stopped | stopped | retrieve→verify→retrieve→verify→retrieve→stop | yes | grounded_completion_or_reasoning_unresolved |
| FIR-015 | figure_understanding | waiting_for_user_input | pending | retrieve→retrieve | yes | required_numeric_value_missing, grounded_completion_or_reasoning_unresolved |
| FIR-016 | multi_evidence_synthesis | completed | achieved | retrieve→verify→synthesize→stop | yes | — |
| FIR-017 | multi_evidence_synthesis | stopped | achieved | retrieve→verify→synthesize→stop | yes | — |
| FIR-018 | multi_evidence_synthesis | completed | achieved | retrieve→verify→synthesize→stop | yes | — |
| FIR-019 | cross_document_reasoning | completed | achieved | retrieve→verify→retrieve→verify→synthesize→stop | no | preferred_page_not_retrieved |
| FIR-020 | cross_document_reasoning | stopped | achieved | retrieve→verify→retrieve→verify→synthesize→stop | no | preferred_page_not_retrieved |
| FIR-021 | cross_document_reasoning | waiting_for_user_input | pending | retrieve→retrieve | no | grounded_completion_or_reasoning_unresolved, preferred_page_not_retrieved |
| FIR-022 | false_premise | stopped | stopped | retrieve→verify→retrieve→verify→retrieve→stop | no | grounded_completion_or_reasoning_unresolved, preferred_page_not_retrieved |
| FIR-023 | false_premise | stopped | stopped | retrieve→verify→retrieve→stop | yes | grounded_completion_or_reasoning_unresolved |
| FIR-024 | unsupported_question | stopped | stopped | retrieve→retrieve→stop | no | — |
| FIR-025 | document_specific_fact | stopped | stopped | retrieve→verify→retrieve→verify→retrieve→stop | yes | grounded_completion_or_reasoning_unresolved |
| FIR-026 | document_specific_fact | stopped | stopped | retrieve→verify→retrieve→verify→retrieve→stop | yes | required_numeric_value_missing, grounded_completion_or_reasoning_unresolved |
| FIR-027 | document_specific_fact | waiting_for_user_input | pending | retrieve→retrieve | yes | grounded_completion_or_reasoning_unresolved |
| FIR-028 | goal_style_multi_step | completed | achieved | retrieve→verify→synthesize→stop | yes | required_numeric_value_missing |
| FIR-029 | goal_style_multi_step | stopped | stopped | calculate→retrieve→calculate→retrieve→verify→retrieve→stop | yes | validated_calculation_missing, required_numeric_value_missing, grounded_completion_or_reasoning_unresolved |
| FIR-030 | goal_style_multi_step | stopped | stopped | calculate→retrieve→calculate→retrieve→verify→retrieve→stop | yes | validated_calculation_missing, required_numeric_value_missing, grounded_completion_or_reasoning_unresolved |

These are triage labels only. A separate independent semantic review is required before any accuracy claim.

## Category diagnostic

| Category | Tasks | Achieved status | Validated CALCs | Preferred page retrieved |
|---|---:|---:|---:|---:|
| calculation | 3 | 0 | 0 | 2 |
| concept | 3 | 3 | 0 | 3 |
| cross_document_reasoning | 3 | 2 | 0 | 0 |
| document_specific_fact | 3 | 0 | 0 | 3 |
| equation_retrieval | 3 | 1 | 0 | 2 |
| false_premise | 2 | 0 | 0 | 1 |
| figure_understanding | 3 | 1 | 0 | 2 |
| goal_style_multi_step | 3 | 1 | 0 | 3 |
| multi_evidence_synthesis | 3 | 3 | 0 | 3 |
| numeric_extraction | 3 | 2 | 0 | 3 |
| unsupported_question | 1 | 0 | 0 | 0 |

## Suspected failure classes

These labels may overlap within a task; they are diagnostic flags, not independently adjudicated causes.

- grounded_completion_or_reasoning_unresolved: 16
- required_numeric_value_missing: 10
- preferred_page_not_retrieved: 7
- validated_calculation_missing: 5
- figure_evidence_missing: 1
