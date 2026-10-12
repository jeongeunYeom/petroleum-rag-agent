# V20.1 browser reliability validation

## Scope and environment

- Product candidate: `c82ef66070695e6a13f7a6f3eb35f2714e4e5811` on `fix/v20-1-reliability-stabilization`, based on V20 product `9db8e190b143ac16720595c6b5393839e8b8d7db`.
- Real Microsoft Edge Chromium, headless, 1440×1000 CSS pixels at 1.5× scale; real frontend on `127.0.0.1:3000`, current-code backend on `127.0.0.1:8001`.
- Local Ollama `qwen3:8b`; `RETRIEVAL_MODE=hybrid`; existing `petroleum_knowledge` ChromaDB, **12 documents / 18,976 chunks**. No ingestion, reindexing, external model, or sealed benchmark was run.
- V20 browser A–F and clarification-reply strings were compared with the original validation harness and are **identical**. Only the result directory changed to `evaluation/v20_1_browser_e2e`.
- Frontend integration check passed: one chat input, no visible Goal Research drawer/button or iteration selector. All scenario-level browser-error arrays are empty; the separate global console log contains one unattributed resource 404, with no observed effect on the scenarios.

## Actual browser results

| Case | Run ID | Actual action sequence | Status | Result |
| --- | --- | --- | --- | --- |
| A Monel grounded QA | `GR-20261012-154923-60442F` | RETRIEVE → VERIFY → STOP | **PASS**, achieved | Direct Monel/nonmagnetic directional-survey support from Drilling Engineering pp.494/96 and Handbook vol.II p.284; no calculation. |
| B sourced API gravity | `GR-20261012-154942-46E93D` | RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP | **PASS**, achieved | Reservoir Engineering p.90 formula; validated 22.63943355 → **22.64 °API**. |
| C natural follow-up | `GR-20261012-155005-1FB617` | RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP | **PASS**, achieved | User context used, SG corrected to 0.85; validated **34.97 °API**. Assistant text was not evidence. |
| D chained Archie Rt | `GR-20261012-155033-EDC941` | RETRIEVE → CALCULATE F → CALCULATE Rt → VERIFY → SYNTHESIZE → STOP | **PASS**, achieved | Two validated calculations: F=20.661157 dimensionless; Rt=13.4930005 canonical `ohm-m`. Source and target provenance retained; no Rw clarification. |
| E missing TVD | `GR-20261012-155111-97E2AD` | RETRIEVE → RETRIEVE | **PASS**, waiting | Asked for TVD value/unit, not Pd; did not invent depth. |
| E same-run reply | `GR-20261012-155111-97E2AD` | RETRIEVE → RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP | **PASS**, achieved | Same run ID after `TVD는 8000 ft야.`; sourced Drilling Engineering p.360 relation, validated **P=4201.6 psi**. |
| F direct mean/rank | `GR-20261012-155142-672E99` | CALCULATE → ANALYZE → VERIFY → SYNTHESIZE → STOP | **PASS**, achieved | No retrieval; validated mean **194.6667 stb/d**, ranking **B > A > C**. No internal exception appeared to user. |

**Required B/C/D/E/F: 5/5 PASS.** Desired A also PASS; all six distinct tasks passed. E waiting and resume are separately recorded in [results.json](results.json) under one run ID. All scenario rows have empty browser-error arrays; see the global-console caveat above.

## Real-KB API smoke (before browser, reconfirmed at product SHA)

The same prompt strings were submitted to the autonomous `/from-message` API, with the TVD reply sent to `/resume`. The final confirmation was run after the product commit; compact traces are in [real_api_smoke.json](../v20_1_dev/real_api_smoke.json).

| Case | Final confirmation run | API outcome |
| --- | --- | --- |
| B | `GR-20261012-155258-361C05` | Achieved; 22.64 °API, sourced p.90. |
| C | `GR-20261012-155320-D40F5D` | Achieved; prior user context retained, 34.97 °API. |
| D | `GR-20261012-155347-5F860A` | Achieved; validated F then Rt≈13.493 `ohm-m`. |
| E / reply | `GR-20261012-155410-8C0A4A` | Asked only for TVD, then resumed the same run and validated P=4201.6 psi. |
| F | `GR-20261012-155440-805883` | Achieved; CALCULATE→ANALYZE→VERIFY, mean≈194.67 stb/d and B>A>C. |
| A | `GR-20261012-155445-16B6F3` | Achieved; retrieved direct Monel/directional-survey evidence. |

## Evidence and safeguards

- Monel answer used literal retrieved text, including “These collars are made from Monel and the Earths magnetic field is undisturbed by their presence” (KB1, Drilling Engineering p.494) and “isolate directional survey instruments from magnetic distortion due to the steel drillstring” (KB3, p.96). Query aliases improved recall; they did not become answer evidence.
- API gravity relation `API = (141.5 / SG) - 131.5` remained anchored to Reservoir Engineering p.90 (KB1). Both calculations were validated.
- Archie Rt was not marked achieved after intermediate F. The result retained two CALC records and target provenance; the supplied `Ω·m` was canonically represented internally as `ohm-m`.
- Hydrostatic source p.360 literally states `P = 0.052 x MW x TVD` and explicitly defines P in psi, MW in ppg, and TVD in ft. The exact source-anchored `x` layout was normalized for execution; the missing TVD was requested before calculation.

## Screenshots and poster candidates

Unmodified browser captures are in [screenshots](screenshots). The three selected copies are [Monel grounded QA](poster_candidates/poster_01_monel_grounded_qa.png), [sourced API gravity](poster_candidates/poster_02_api_gravity.png), and [Archie chain](poster_candidates/poster_03_archie_chain.png). The Archie image visibly shows internal search, F calculation, Rt calculation, and verification, followed by `Rt: 13.49 ohm-m` in the current canonical spelling.

## Known limitations

- The Archie UI displays canonical `ohm-m`, not the typographic `Ω·m` requested for the ideal poster caption. They are equivalent unit spellings; do not edit the screenshot or describe it as showing the Unicode symbol.
- The Monel answer is grounded but primarily reproduces English source excerpts rather than a fluent Korean synthesis. It supports the requested reason, but the screenshot should not be advertised as polished Korean prose.
- This is six selected real-product scenarios, not a general accuracy estimate or sealed final benchmark. Browser validation does not prove all engineering domains or unseen tasks.
- The screenshots have large blank viewport areas. Any later poster crop should retain the original text and must not imply an unobserved behavior.

Raw traces: [results.json](results.json), [real API smoke](../v20_1_dev/real_api_smoke.json), and [logs](logs). The earlier V20 validation artifacts on `validation/v20-browser-e2e` remain unchanged.
