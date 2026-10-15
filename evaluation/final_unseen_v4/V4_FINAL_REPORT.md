# Final Unseen V4 — frozen V23 Agent

This is a one-shot final unseen measurement of the frozen product, not a development gate. Results are reported as observed; no item was dropped or changed after catalog sealing.

## Integrity and conditions

- Frozen product SHA: `62e5c36f3d66e25addc8a2c37b63af12e2636e78`. Evaluation branch: `eval/v23-final-unseen-v4`. Catalog/harness commit: `2de2ab847e30d245089ae57930e44cd3d014f5ff`; evaluation-only harness repair: `0c97f3ca4f91ad9509495d2709955c3927a950f5`; report-code commit: `6b354b339bcc2fc9a133151e2855e83da77b4280`.
- Sealed catalog SHA-256: `2bb620232232a2aaf02964de9d5b83f41f4df5f6386ab85724fd26c06f09a2aa`. Rubric SHA-256: `bf4d4aff0925d91b14f9505ce40bc51b287034601478f1a49b12760c406f09ca`.
- Existing read-only KB: `petroleum_knowledge`, 12 documents / 18,976 chunks; `chroma.sqlite3` precheck SHA-256 `1b389044d7efec1273a5d4d52a999d4831188e08a808d4a956a72ba816659fea`.
- Local model: `qwen3:8b` (Ollama digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`). Agent used hybrid KB retrieval and bounded tools; web was disabled. Qwen baseline was closed-book, with no KB, tools, or gold text.
- Product code, retrieval behavior and sealed catalog remained unchanged after V4 execution began. The initial harness-only Chroma settings incident is preserved separately in `HARNESS_INCIDENT.md`. Its 60 zero-time infrastructure rows were not model answers; the same immutable catalog was rerun after an evaluation-only settings fix. No task was silently excluded.
- Both conditions completed all 60 catalog rows. A post-run read-only KB check still found 12 documents / 18,976 chunks, and the SQLite SHA-256 matched the precheck hash above. The sealed catalog hash also matched exactly.
- After execution, a deterministic reporting flag was corrected to count repeated clarification only after a follow-up turn; the previous flag counted single-turn pending clarifications. This evaluation-only correction changed the count from 10 to 0; it did not change prompts, model outputs, rubric, or semantic task verdicts.

## Frozen Agent metrics

- Goal Success: **19/60 (31.7%)**
- Task Completion: **34/60 (56.7%)**
- Claim Coverage: **50/109 (45.9%)**
- Hallucination-Free: **56/60 (93.3%)**
- Numerical Accuracy: **18/40 (45.0%)**
- Citation Support Rate: **32/35 (91.4%)**; citation omissions recorded: 0.
- Uncertain semantic judgments: **0**; unresolved cases are not silently counted as successes.

## Agent category results

| Category | Goal Success | Task Completion |
|---|---:|---:|
| knowledge | 2/12 (16.7%) | 7/12 (58.3%) |
| direct | 2/8 (25.0%) | 3/8 (37.5%) |
| user_formula | 5/8 (62.5%) | 6/8 (75.0%) |
| kb_formula | 1/12 (8.3%) | 7/12 (58.3%) |
| multi_goal | 3/8 (37.5%) | 4/8 (50.0%) |
| false_premise | 2/4 (50.0%) | 3/4 (75.0%) |
| unanswerable | 2/4 (50.0%) | 2/4 (50.0%) |
| resume | 2/4 (50.0%) | 2/4 (50.0%) |

## Qwen3:8b closed-book vs frozen Agent

The conditions do **not** have equal information access: the Agent had its internal KB and tools, while Qwen answered from the same visible user turns without retrieval or tools.

| Metric | Qwen closed-book | Frozen Agent |
|---|---:|---:|
| Goal Success | 43/60 (71.7%) | 19/60 (31.7%) |
| Claim Coverage | 84/109 (77.1%) | 50/109 (45.9%) |
| Hallucination-Free | 43/60 (71.7%) | 56/60 (93.3%) |
| Numerical Accuracy | 32/40 (80.0%) | 18/40 (45.0%) |

## Agent reliability and latency

- Technical crashes: 0; blank responses: 0; raw error leaks: 0; invalid citation-ID rows: 0; repeated identical clarifications: 0; external-source rows: 0.

| Category | N | Median | P95 |
|---|---:|---:|---:|
| direct | 8 | 4.797 s | 50.750 s |
| user_formula | 8 | 5.000 s | 5.625 s |
| knowledge | 12 | 26.133 s | 95.750 s |
| kb_formula | 12 | 33.734 s | 55.563 s |
| multi_goal | 8 | 3.844 s | 15.813 s |
| resume | 4 | 28.985 s | 92.454 s |
| overall | 60 | 23.610 s | 82.407 s |

## All Agent Goal Success failures

| ID | Category | Failure class | Task-level rationale |
|---|---|---|---|
| V4-001 | knowledge | unnecessary_refusal | Agent stopped although the reservoir-fluid source explicitly says above-bubble oil is undersaturated and gas stays dissolved. |
| V4-002 | knowledge | incomplete_answer | The cited production text supports reduced hydrostatic head from lift gas; the answer never says lift is considered when reservoir pressure is insufficient. |
| V4-003 | knowledge | unnecessary_refusal | The answer stops instead of using the catalogued simulation source about cheaper option comparison and forecast uncertainty. |
| V4-006 | knowledge | unnecessary_refusal | The Agent gives no Sw pore-volume definition or hydrocarbon remainder despite an answerable source. |
| V4-007 | knowledge | incomplete_answer | KB5 supports post-breakthrough rising water cut; quoted fractional-flow definition does not state the curve's later-oil-production implication. |
| V4-008 | knowledge | incomplete_answer | Cited compaction-drive span supports pressure-loss compaction; the visible answer does not connect initial porosity to initial oil in place. |
| V4-009 | knowledge | retrieval_or_synthesis_failure | Cited chart headings do not provide either requested carbonate or Humble equation; Agent stops. |
| V4-010 | knowledge | incomplete_answer | The cited open-hole pressure-depth/RFT text is relevant, but probe penetration of mud cake is not answered. |
| V4-011 | knowledge | unnecessary_refusal | Agent stops without distinguishing tubing deposits from near-wellbore formation damage. |
| V4-012 | knowledge | incomplete_answer | The appraisal source supports large investment decisions amid uncertainty; the answer does not explain limited data/production history. |
| V4-013 | direct | arithmetic_error | Validated CALC is reported as 146 stb/d, not 136+211+73=420 stb/d; a validated flag cannot repair wrong binding. |
| V4-014 | direct | unnecessary_retrieval | Agent stops rather than subtracting the two explicit gauge pressures. |
| V4-016 | direct | unnecessary_clarification | Agent asks despite both old and new rates being present; no 15% answer is delivered. |
| V4-017 | direct | input_binding_failure | Agent asks for a generic validated item rather than using 3780 scf and 135 stb. |
| V4-019 | direct | unnecessary_clarification | Agent requests input instead of calculating the 160 psi rise relative to 1600 psi. |
| V4-020 | direct | input_binding_failure | Agent asks for a generic validated item even though both pressure readings are supplied. |
| V4-024 | user_formula | input_binding_failure | Agent remains in clarification instead of binding 145 stb/d and 6 days to V=q*t. |
| V4-026 | user_formula | wrong_unit | Agent computes scalar 20 but labels the requested percentage as dimensionless, not 20%. |
| V4-027 | user_formula | unnecessary_clarification | Agent waits despite the user-supplied m=7 and F=3*m+2 being complete. |
| V4-030 | kb_formula | formula_and_unit_omission | CALC1 uses the correct p90 source, but final text gives bare 16.51255 with no °API and does not state the equation. |
| V4-031 | kb_formula | unnecessary_refusal | Agent does not produce the carbonate F=1/phi² relation or 34.60 result. |
| V4-032 | kb_formula | unnecessary_refusal | Agent stops before the sourced carbonate relation and 12.76 result. |
| V4-033 | kb_formula | wrong_formula_selection | Agent selects the simpler sand 0.81/phi² source in place of the explicitly requested Humble 0.62/phi^2.15, yielding 15.31 instead of 14.61. |
| V4-034 | kb_formula | formula_not_shown | CALC1 correctly uses literal KB20 0.81/phi² and gives 11.11, but the user-facing answer does not display the requested textbook equation/span. |
| V4-035 | kb_formula | formula_not_shown | KB4 raw F=a/fm is safely normalized in CALC1 and 21.2046 is correct; final answer omits the requested sourced relation itself. |
| V4-036 | kb_formula | formula_not_shown | CALC1 uses the exact Rt=Ro/Sw² source and yields 17.78 ohm-m; final text provides only the result, not the requested relation. |
| V4-037 | kb_formula | unnecessary_clarification | Agent requests an unspecified additional input although Pf=2100 and Pc=125 are supplied. |
| V4-038 | kb_formula | unnecessary_clarification | Agent leaves a blank final answer in waiting state instead of rearranging Po=Pf+Pc. |
| V4-039 | kb_formula | formula_not_shown | CALC1 cites the literal separator GOR relation and gets 30 scf/stb, but the equation the user asked to find is absent from the final text. |
| V4-040 | kb_formula | unnecessary_clarification | Agent remains waiting with no Bo relation or 1.2 rb/stb answer despite Vres and L2 being present. |
| V4-041 | multi_goal | unnecessary_retrieval | Agent stops without summing user-only rates or identifying B as largest. |
| V4-042 | multi_goal | unnecessary_clarification | Agent waits although all three rates suffice for mean and ranking. |
| V4-043 | multi_goal | unnecessary_clarification | Agent waits instead of reporting both decline measures from 640 and 496 stb/d. |
| V4-045 | multi_goal | unnecessary_clarification | Agent waits rather than evaluating the supplied score formula for all three wells. |
| V4-047 | multi_goal | incomplete_answer | Agent reports 20% but omits the requested absolute 68 stb/d increase. |
| V4-050 | false_premise | incomplete_correction | Agent rejects FWL=OWC and cites capillary separation but does not state the zero-capillary-pressure FWL definition. |
| V4-051 | false_premise | contradictory_safe_stop | Agent quotes source for early storage unit slope and plateau onset, yet ends by saying the requested explicit correction remains unverified and stops. |
| V4-054 | unanswerable | incomplete_safe_stop | Agent remains waiting with no visible final explanation that the Lumen-Chi relation is absent. |
| V4-055 | unanswerable | irrelevant_citation | Agent returns an unrelated grid-refinement quote instead of explaining the missing Raven-Theta definition. |
| V4-058 | resume | retrieval_and_resume_failure | Agent stops before asking for missing porosity, so no same-run sourced F calculation occurs. |
| V4-060 | resume | false_stop_after_calculation | Agent asks for Q and validates R=7 in the same run, but final status is stopped with insufficient_evidence rather than completed. |

## Scoring method and limitations

Claim Coverage counts each required atomic claim and each requested numeric output as one item, following the pre-execution frozen rubric.
Automatic flags checked status, numeric tolerance/unit candidates, citation IDs, technical events and latency. One frozen rubric then guided **single-reviewer AI-assisted semantic adjudication** of every task, preserving task-level rationale in `semantic_scores.json`. A valid citation ID alone did not establish semantic support. Numeric heuristic matches were reviewed against target attribution and units. There was no human multi-reviewer consensus, no equal-information-access baseline, and only one catalog/model seed.

## Poster-safe conclusions

- On this sealed 60-task set, the frozen Agent achieved 19/60 goals versus 43/60 for the same local Qwen model closed-book. The result does **not** support a claim of superior Agent task completion. The conditions differ in KB/tool access, so this is not a pure model comparison.
- The Agent avoided materially false assertions on 56/60 tasks versus 43/60 for Qwen closed-book, but many of its safe/incomplete answers failed the requested goal. Safety and completion must be reported together, not conflated.
- Agent citation support was 32/35 reviewed cited claims. This narrow denominator cannot establish that all needed claims were surfaced or cited.
- Agent median/P95 latency was 23.610/82.407 s, compared with 1.413/5.297 s for the closed-book condition. The Agent's retrieval/verification path carries a substantial latency cost in this local setup.
- These are final results only for the frozen product SHA and this one catalog. Repairs after seeing V4 would require a new unseen V5 for another final claim.
