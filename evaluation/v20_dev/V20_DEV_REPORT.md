# V20 development verification — Unified Autonomous Chat

## Scope and version

- Branch: `feature/unified-autonomous-chat-v20`
- Base: `feature/agent-reliability-v19` at `30fb66f9511be72107b23cfa8331ea15b0fdfd13`
- Implementation result SHA: `0d08beb5a50d44b403f41faee7e5468bee5fe302` (this report is a subsequent documentation commit)
- Product change: one normal chat entrypoint through `POST /api/research/goal-runs/from-message` and the existing `GoalExecutionAgent`. The separate Goal Research button, drawer, and user-facing iteration control are removed from the main UI. The internal eight-iteration ceiling remains a safety bound, not a target.
- No sealed final benchmark was opened or run. No ChromaDB reindexing, embedding/model replacement, or main merge was performed.

## Verification

| Check | Result |
| --- | --- |
| Backend targeted v20/regression tests | 55 passed |
| Backend full `python -m pytest -q` | 1,530 passed; 6 dependency deprecation warnings |
| Frontend `pnpm test` | 23 passed |
| Frontend `pnpm build` | Passed (Next.js production build and type check) |
| Retrieval health | `petroleum_knowledge`: 12 documents, 18,976 chunks; hybrid health PASS |

The frontend tests cover the single autonomous entrypoint, bounded chat context, same-run resume wiring, real-action process summary, citations/calculations, generated-file links, and absence of the visible Goal Research drawer. These are component/static-contract tests, not a browser-driven end-to-end test.

## Real production-KB smoke traces

These calls used the current product API on a temporary `127.0.0.1:8001` backend, local `qwen3:8b`, hybrid retrieval, and the existing 12-document ChromaDB. Each listed final trace is from an actual API run; no sealed benchmark item was used.

| Scenario | Run ID | Observed actions | Actual iterations / cap | Outcome |
| --- | --- | --- | --- | --- |
| Direct average/rank of A=187, B=234, C=163 stb/d | `GR-20261012-141947-CC7F01` | CALCULATE → ANALYZE → VERIFY → SYNTHESIZE → STOP | 4 / 8 | ACHIEVED; mean 194.666… stb/d, B > A > C |
| Sourced SG=0.918 → API gravity | `GR-20261012-142009-4044EB` | RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP | 4 / 8 | ACHIEVED; 22.64 °API; Heriot-Watt Reservoir Engineering p.90 formula evidence |
| Follow-up “그럼 0.85면?” | `GR-20261012-142320-EEA130` | RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP | 4 / 8 | ACHIEVED; prior user goal retained, SG corrected to 0.85, 34.97 °API; assistant text was not promoted to evidence |
| Monel drill-collar grounded QA | `GR-20261012-142404-CD0B2E` | RETRIEVE → VERIFY → STOP | 2 / 8 | ACHIEVED; cited Drilling Engineering p.494/p.15/p.495; no Python calculation |
| Missing SG, then user supplies `SG=0.918 dimensionless` | `GR-20261012-143612-CB6BD9` | RETRIEVE → RETRIEVE → WAITING; then CALCULATE → VERIFY → SYNTHESIZE → STOP | 5 / 8 total | Same run ID resumed and ACHIEVED; 22.64 °API; one clarification turn |
| User-provided relation missing multiplier, then `Multiplier=4 dimensionless` | `GR-20261012-142616-8B35D3` | WAITING; then CALCULATE → VERIFY → SYNTHESIZE → STOP | 3 / 8 total | Same run ID resumed and ACHIEVED; Gain=36 kg |
| Multi-formula Archie target Rt with explicit phi, a, m, n, Sw, Rw | `GR-20261012-143949-581C05` | RETRIEVE → CALCULATE F → CALCULATE Rt → VERIFY → SYNTHESIZE → STOP | 5 / 8 | ACHIEVED; validated F≈20.661157 and final Rt≈13.4930005 ohm-m |

The SG clarification initially exposed two false candidates in PDF-derived source text: a clipped prose definition (`SG = specific ...`) and a constant worked example. The source-aware filters now exclude those as executable dependency formulas while retaining literal equation provenance. A contextual follow-up initially failed the operand-source check; the final implementation validates the correction against the literal new user message and keeps the existing USERF identity. These were development fixes, not benchmark tuning.

## Adaptive stopping, policy, and limitations

- Observed successful runs stopped at 2, 3, 4, or 5 actual iterations, below the hidden ceiling of 8. Completion depends on verified target output/evidence, not a user-entered iteration count. An artifact failure is reported as `DELIVERABLE_FAILED` rather than a false overall achievement; an independently successful artifact remains downloadable.
- The missing-SG case waited for a user fact and resumed the same run. No formula or numeric input was invented. Follow-up context is limited to six messages and 2,400 characters; only prior user facts can become USERF records. Ambiguous bare numeric follow-ups request a named variable.
- Parser tests confirm explicit-web activation and web-negated local-only behavior. External web retrieval itself was not exercised in this local smoke.
- Real browser interaction, actual DOCX/PPTX generation, and the alternate `gemma4:latest` model were not smoke-tested here. Frontend behavior was verified by tests and production build; artifact-completion behavior has synthetic backend regression coverage.
