# Petroleum Agent Held-out Policy

`petroleum_agent_heldout_v1` is the frozen final-performance benchmark for the
internal petroleum knowledge base. Its ground truth was checked against the
12-document, 18,976-chunk `petroleum_knowledge` collection without web search.

## Evaluation boundary

- Agent input contains only the question plus evidence retrieved from the internal
  text and figure indexes.
- Required/forbidden patterns, source locators, numeric tolerances, and manifest
  summaries are evaluator-only data and must not be added to an Agent prompt.
- Final held-out runs use `use_external=false`. A run that reports web search or web
  evidence is invalid for the internal-only comparison.

## Freeze rule

After the first full evaluation:

- Do not tune Agent, validator, retrieval, or generation rules to individual failed
  held-out questions.
- Correct only demonstrable evaluator false positives/negatives, recording the
  evidence and impact.
- Any ground-truth, wording, source, or scoring-rule change requires a new benchmark
  version instead of silently changing v1.
- Preserve the original result artifacts for every published comparison.

Dry-run/schema validation does not count as the first full evaluation.
