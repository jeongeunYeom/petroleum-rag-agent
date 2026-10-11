# Agent reliability v11.1 — premise grounding analysis

## Source-first path

`PREMISE_CHECK` remains separate from truth assessment. After premise-specific retrieval, the assessor may combine up to three literal supporting spans from one or more retrieved KB sources. The local model selects **indexed spans supplied by the server**, rather than inventing quote text. Invalid IDs or nonliteral legacy quotes are rejected. It returns `supports`, `contradicts`, or `insufficient`, a corrected relation, support IDs/spans, relation type, method, confidence, and structured failure reason. The final correction explicitly rejects the premise, states the source-supported relation, and carries the source citation; the existing engineering and claim-level citation checks still run.

If the first assessment is insufficient, the agent reads at most four indexed neighbors from the same document (same page chunk ±1, then adjacent page ±1), records `premise_context_expansion`, and reassesses. It does not write to Chroma. A subsequent refined retrieval is bounded; if the relation remains unsupported, the agent safely stops.

The deterministic equation helper corrects only simple literal two-variable relations with named variables and necessary sign/fixed-variable conditions. Unknown signs, missing variable meaning, or unsupported physical assumptions leave the verdict insufficient. The fixed-bulk-volume porosity ratio correction remains source-dependent.

## Six live false-premise cases

| Domain | Verdict | Evidence locator(s) | Explicit rejection + citation | Result |
| --- | --- | --- | --- | --- |
| Reservoir Engineering | Contradicts | Reservoir Engineering p713; Handbook V p1130 | Yes | PASS |
| Reservoir Simulation | Contradicts | Reservoir Simulation p85, p12 | Yes | PASS |
| Well Testing | Contradicts | Handbook V p1024; Well Test Analysis p111 | Yes | PASS |
| Petrophysics | Contradicts | Formation Evaluation p164; Handbook V p153 | Yes | PASS |
| Drilling | Contradicts | Drilling Engineering p360 | Yes | PASS |
| Production | Contradicts | Production Technology II p452 | Yes | PASS |

Intent, relevant-source hit, explicit correction, and retained citation all occurred in **6/6** cases. The product's local-model semantic validation also passed **6/6** retained answers. This is a small development smoke, not an unseen estimate.

## Failure diagnosis during implementation

- `PREMISE_GROUNDING`: Long OCR chunks prompted conservative `insufficient` even when a direct relation or equation was present. Bounded literal excerpts and indexed selection resolved this in the final six-case run.
- `PREMISE_CONTEXT`: An initial insufficient verdict sometimes caused neighbor reads. The final run found direct spans before expansion, so the live correctness of the adjacent-context path remains unmeasured; the read-only ±1-page/maximum-four policy is unit-tested.
- `PREMISE_SYNTHESIS`: PDF line wraps caused one quote to be split into many apparent claims by line-level citation validation. Raw supporting spans remain byte-for-byte source substrings; only answer display whitespace is normalized. The final six answers passed without weakening the citation validator.

The final run has no failed premise case. The supporting excerpts can still be long or include ancillary context; a later independent reviewer may judge a more concise citation presentation preferable. No unsupported correction is allowed when the source relation or necessary assumptions are absent.
