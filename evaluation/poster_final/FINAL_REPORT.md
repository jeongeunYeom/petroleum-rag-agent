# Final poster pilot evaluation — v14

Product: `dc706fe834d42a7ca44acd7b8914c36b7581b259`. Freeze: `975a11dc1b1ece3566f0f726ed826dfaa55c5ccd`.
Dataset SHA256: `60e7d8c49b318bd37dc79e43d5017a2bc2364f4c83d16a921c3913ca55bfc6b8`.

## Main comparison

| Metric | Petroleum RAG Agent | ChatGPT |
|---|---:|---:|
| Goal Success (%) | 7.69 | 65.38 |
| Claim Coverage (%) | 11.54 | 83.33 |
| Hallucination-free (%) | 84.62 | 88.46 |
| Numerical Accuracy (%) | 10.00 | 90.00 |

Goal Success is answer-level success under an identical rubric, not the Agent internal status. No citations or tool use are required of the closed-book baseline.

## Reproducibility and limitations

- 26 frozen/valid tasks; 0 invalid. Same exact question strings, web off, one generation per system.
- Agent: qwen3:8b, hybrid, 12 documents / 18,976 chunks; autonomous from-message API.
- ChatGPT label: gpt-5.4-mini-2026-03-17 API (not the consumer application).
- Judge: gpt-5.4-2026-03-05; single-reviewer AI-assisted semantic adjudication, not human review.
- Fixed temperature 0 and no tools for API calls. No fallback or automatic retry.
- Source-authored and facilities-heavy sample. Few questions per stratum; no population-wide or causal superiority claim.
- Development: 14 fresh cases / 28 checks; backend regression 1,159 passed. Tests are not held-out performance.
- Existing questions were used only for duplicate screening after product freeze (740 questions; zero flags at frozen thresholds). Automated screening cannot prove conceptual independence.
- Same provider family for baseline and judge may introduce bias. No independent human adjudication.
- Some reviewer judgments are over-strict about additional established details. Hallucination is the single reviewer's assessment, not a separately verified factual error rate. See [scoring audit](SCORING_AUDIT.md).
- Binary integer/boolean reviewer fields are normalized without changing raw judgments or making another API call.
- Correct refusal can be hallucination-free while failing an answerable task. Interpret safety together with success and coverage.
- No post-result product, benchmark or policy changes. No main merge.

## Supplementary citation support

Agent citation-bearing responses: 5/26. Semantic support among them: 40.0%. Internal achieved: 7/26.

## Latency

| System | Mean s | Median s | P95 s |
|---|---:|---:|---:|
| agent | 23.09 | 24.76 | 40.68 |
| chatgpt | 2.47 | 2.44 | 3.77 |

## Paired bootstrap 95% intervals

| Metric | Agent − ChatGPT, percentage points |
|---|---:|
| goal_success | -80.77 to -30.77 |
| claim_coverage | -86.54 to -55.45 |
| hallucination_free | -19.23 to 11.54 |
| numeric_accuracy | -100.00 to -50.00 |

10,000 paired task resamples, seed 14026; numerical subset n=10.

## Per-task adjudication

| ID | Category | Agent success | ChatGPT success | Agent finding |
|---|---|---:|---:|---|
| P01 | knowledge | 0 | 0 | A refuses to answer despite the provided source directly stating that slug catchers handle intermittent liquid slugs and that added volume reduces velocity and dissipates energy. It does not provide the requested service. |
| P02 | knowledge | 0 | 1 | Does not answer the question despite supplied evidence directly supporting it; cited support does not entail the refusal claim that sources did not directly support an answer. |
| P03 | knowledge | 0 | 1 | B refuses to answer despite supplied evidence that directly states pigs are used during hydrostatic testing to fill without entrapping air, with water pumped behind the pig to force air out ahead. The cited answer is therefore unsupported by its own provided source. |
| P04 | knowledge | 0 | 1 | A does not answer the question and misses both required claims, despite the supplied source directly supporting them. |
| P05 | knowledge | 0 | 0 | A does not answer the question and omits both required functions. Although a relevant source excerpt is present in metadata, the answer itself says the sources did not support an answer. |
| P06 | knowledge | 0 | 1 | B refuses to answer even though the supplied source directly states that open impellers are more sensitive to wear and their efficiency deteriorates rapidly in erosive service. Its cited support does not entail the refusal. |
| P07 | knowledge | 0 | 0 | A does not answer the question and omits all three required caliper criteria from the reference. |
| P08 | knowledge | 0 | 1 | B does not answer the question despite the supplied source directly supporting it. Its cited claim that the sources did not directly support an answer is contradicted by the provided reference source. |
| P09 | reasoning | 0 | 0 | B does not answer the question asked. It gives an unrelated quoted statement about hydrate inhibition around subsea wellheads from a different source passage and omits the key reference claims about methanol, high-flow-rate cost favoring line heaters, and use when line heaters are impractical. Its citation support is invalid for the quoted claim because the cited tag [KB3] is not the supplied source passage for this task. |
| P10 | reasoning | 0 | 0 | B correctly states that dilute dispersions need longer coalescence time because droplet contact is low. It does not answer the asked gravity-treatment footprint trade-off at all. Its citations also do not support the full answer given, and one cited source/page is outside the supplied source set. |
| P11 | reasoning | 1 | 0 | A states all three required claims: intercooling can save energy, lowers discharge temperature and reduces special-material needs, and the savings must be weighed against added capital and maintenance for cooling. Its citation matches the supplied source. |
| P12 | reasoning | 0 | 1 | B does not answer the separator-design question and instead gives an irrelevant statement about fluid entering a tank from a higher-pressure source. Its cited statement does not support the required claims about short-circuiting, inlet flow straightening, or gas/liquid sizing requirements. |
| P13 | direct | 0 | 1 | A gives 0.6%, but the correct median of 0.4%, 0.6%, 0.9%, 1.8%, 2.7% is 0.9%. This misses the required claim and gives a materially incorrect numeric result. |
| P14 | direct | 0 | 1 | Does not answer the question and provides no RMS computation or numeric result. |
| P15 | direct | 0 | 1 | Did not answer the inventory calculation; instead requested unrelated missing information. |
| P16 | direct | 0 | 1 | Does not answer the question and provides no valid calculation or percentage. |
| P17 | user_formula | 0 | 1 | Incorrectly refuses to answer despite the rate being provided in the question; does not give the required cost. |
| P18 | user_formula | 0 | 1 | Numeric value 2.0 is correct, but the stated unit is given as dimensionless^2/dimensionless instead of the requested dimensionless. |
| P19 | user_formula | 0 | 1 | Did not compute the requested value; refused despite sufficient provided information. |
| P20 | kb_formula | 0 | 1 | Does not answer the calculation despite the needed values being provided. It neither states PB = PH/e nor gives 60 hp. |
| P21 | kb_formula | 0 | 0 | Does not answer the calculable question and instead asks for missing information that was already provided. Its cited evidence includes the correct B31.4 formula on page 354, but the response does not use it to supply the required result. |
| P22 | kb_formula | 0 | 1 | Does not answer the calculation or provide the required formula/result; instead asks for missing information that was already provided. Its cited evidence does not support the requested plate-pack Reynolds relation/result. |
| P23 | false_premise | 0 | 0 | Incorrectly claims the evidence does not establish the premise, despite supplied source text explicitly stating lean glycol flows from the top, gas flows countercurrent upward, and the driest gas contacts the driest glycol. Its cited support does not entail the refusal claim. |
| P24 | false_premise | 1 | 0 | B explicitly rejects the premise and accurately states the handbook's claim that designing and maintaining an impressed-current system on a long offshore pipeline is very difficult. The citation directly supports the quoted claim. |
| P25 | unanswerable | 0 | 1 | Does not answer the question. It neither states that exact optimal dose cannot be determined from pressure alone nor requests the relevant fluid/emulsion, chemical, and flow/treatment data. |
| P26 | unanswerable | 0 | 1 | B does not answer the substance of the question: it neither states that exact remaining life cannot be determined from installation year alone nor requests the missing anode mass/inspection/current-consumption data. Its cited source actually supports a partial answer, so the citation does not entail the claim that the sources did not directly support an answer. |

## API usage and cost

Usage-based list-price estimate: **$0.266105 USD**. This is not a provider invoice.

```json
{
  "gpt-5.4-mini-2026-03-17": {
    "calls": 26,
    "input_tokens": 2255,
    "output_tokens": 4103,
    "cached_input_tokens": 0,
    "usage_based_list_price_usd": 0.02015475
  },
  "gpt-5.4-2026-03-05": {
    "calls": 26,
    "input_tokens": 75034,
    "output_tokens": 3891,
    "cached_input_tokens": 0,
    "usage_based_list_price_usd": 0.24595
  }
}
```

## Poster-safe conclusion

The closed-book ChatGPT API baseline achieved higher answer-level task success than the local petroleum RAG Agent in this small, facilities-heavy pilot; retrieval and tool orchestration did not ensure correct final answers.
