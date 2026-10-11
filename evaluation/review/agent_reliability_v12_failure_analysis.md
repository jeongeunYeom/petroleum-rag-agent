# Agent reliability v12 — development failure analysis

The final local smoke passed 29 of 30 cases. This file records the remaining failure without changing the prompt, accepting an unsupported answer, or weakening citation validation.

| Case | Observed sequence | Final state | Failure stage | Classification |
| --- | --- | --- | --- | --- |
| Q02 — permeability and fluid-flow explanation from internal material | RETRIEVE → VERIFY → STOP | `stopped`, `insufficient_evidence` | `finalization_or_citation` | Retrieved excerpts lacked sufficient semantic support for the proposed explanatory claim; safe-stop behavior, not a numeric/calculation fault. |

The final answer says direct supporting evidence was not confirmed. Validation recorded `unsupported_citation_claim_count=1`; the criterion remained unmet. The candidate evidence identified by the evaluator concerned measurement/statistical context rather than a directly supporting relationship. This should be investigated as KB retrieval/evidence-selection or answer-grounding coverage in a later development task. It must not be converted to a PASS by loosening semantic citation checks.

There were no calculation-path failures in this 30-case run. In particular, formula-ready/no-CALCULATE, validated-CALC/not-achieved, and stale-resume counters were each zero. The adversarial fact tests cover a separate failure mode—incorrect value–unit locality—without requiring any live prompt to produce a rejected fallback.

This is development diagnostic evidence only. It does not establish unseen benchmark performance, and the v4 frozen set was neither modified nor rerun.
