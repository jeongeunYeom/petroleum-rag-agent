# Petroleum Agent Frozen Semantic Baseline

## Evaluation setup

- 60 frozen held-out questions
- Run ID: `20261002T024117Z`
- Model: `qwen3:8b`
- Research mode with hybrid retrieval
- Engineering Validator ON
- Web OFF
- Temperature 0, seed 42
- Single-reviewer, model-neutral atomic semantic review

## Strict metrics

- Strict answer accuracy: 8/60 (13.33%)
- Hallucination rate recorded by the frozen strict evaluator: 2/60 (3.33%)
- Citation correctness recorded by the frozen strict evaluator: 41/60 (68.33%)

## Semantic metrics

- Semantic exact accuracy: 26/60 (43.33%)
- Semantic partial-or-better: 40/60 (66.67%)
- Mean claim coverage: 56.65%
- Hallucination rate: 9/60 (15.00%)
- Engineering contradiction rate: 8/60 (13.33%)
- Safe refusal rate: 11/60 (18.33%)
- False-premise recognition: 5/12 (41.67%)
- False-premise correction: 5/12 (41.67%)
- Numeric accuracy: 3/8 (37.50%)
- Figure semantic accuracy: 2/10 (20.00%)
- Citation accuracy for citation-required questions: 2/6 (33.33%)

## Domain breakdown

| Domain | Exact | Partial-or-better | Claim coverage | Hallucination | Safe refusal |
|---|---:|---:|---:|---:|---:|
| Well Test | 45.83% | 62.50% | 54.51% | 12.50% | 20.83% |
| Reservoir | 50.00% | 62.50% | 57.64% | 8.33% | 25.00% |
| Cross-domain | 25.00% | 83.33% | 56.94% | 33.33% | 0.00% |

## Task breakdown

| Task | Exact | Partial-or-better | Claim coverage |
|---|---:|---:|---:|
| Concept | 62.50% | 91.67% | 79.51% |
| False-premise | 25.00% | 41.67% | 33.33% |
| Figure | 20.00% | 60.00% | 41.67% |
| Numeric | 37.50% | 37.50% | 37.50% |
| Citation | 50.00% | 66.67% | 58.33% |

## Strict versus semantic

All 8 strict passes were semantic score 2. An additional 18 strict failures received semantic score 2:

`PH-WT-002`, `PH-WT-008`, `PH-WT-013`, `PH-WT-017`, `PH-WT-021`, `PH-WT-022`, `PH-RE-001`, `PH-RE-003`, `PH-RE-009`, `PH-RE-012`, `PH-RE-013`, `PH-RE-015`, `PH-RE-017`, `PH-RE-018`, `PH-RE-019`, `PH-RE-021`, `PH-XD-003`, `PH-XD-012`.

## Failure analysis

Failure attributions are non-exclusive. The review recorded 18 generation omissions, 14 partial answers, 11 safe refusals, 8 engineering errors, 8 figure failures, 5 numeric failures, 4 retrieval failures, and 3 citation failures.

## Limitation

This is a single-reviewer semantic evaluation. A second independent reviewer and adjudication pass should be added before publication. The frozen benchmark, rubric meaning, Agent, validator, retrieval system, and original strict result were not changed or rerun.
