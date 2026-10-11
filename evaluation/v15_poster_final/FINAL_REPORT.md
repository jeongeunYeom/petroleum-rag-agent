# V15 final independent poster pilot

Status: **FINALIZED**

Product `6b8b0e7850a24b79b337882b1de3184cb7993d04`; freeze `279cebdea1724caeb8e4c00d03f5fac119209704`; benchmark SHA256 `13d3f8debfcebff350872a1fe0ce03d2458d10be3f6fb950a86df18527963496`. 24 frozen tasks, 10 numeric; no invalid tasks. Local qwen3:8b + hybrid, existing 12-document / 18,976-chunk KB; web OFF. Baseline `gpt-5.4-mini-2026-03-17`; judge `gpt-5.4-2026-03-05`. See POLICY.md for prespecified design and rubric.

## Primary results

| System | Goal Success | Claim Coverage | Hallucination-free | Numerical Accuracy | Median latency (s) |
|---|---|---|---|---|---|
| Petroleum RAG Agent | 20.83% | 30.90% | 37.50% | 20.00% | 20.65 |
| GPT-5.4 mini (Closed-book) | 79.17% | 93.06% | 87.50% | 100.00% | 2.36 |

| Category | Agent GS | GPT GS |
|---|---|---|
| Knowledge | 33.3% | 66.7% |
| Reasoning | 25.0% | 25.0% |
| Calculation | 10.0% | 100.0% |
| Safety | 25.0% | 100.0% |

## Statistical uncertainty

### Important interpretation of the judge-coded safety metric

The reported Hallucination-free score is the prespecified conservative conjunction of the judge's `hallucination_free` flag and an empty `material_errors` list. The judge sometimes marked the flag true while listing errors (for example P01 and P13); the aggregation did not silently discard those errors. Fourteen of the Agent's fifteen failed safety classifications involve an insufficiency/refusal statement or unnecessary request for inputs; P19 additionally includes an internal wrong-formula trace. P21 contains an over-strong engineering assertion in the answer. Consequently, **37.5% must not be presented as evidence that 62.5% of Agent answers fabricated engineering facts**. The reviewer treated some incorrect refusals as factual contradictions and did not consistently distinguish omissions from false assertions. These single-reviewer judgments and inconsistencies are preserved, not repaired or rerun after seeing results. The safety result is rubric-/reviewer-sensitive and needs expert review before being used as a standalone publication claim about factual hallucination.

Numerical Accuracy and Goal Success differ because the frozen claims also include use of the requested relation: P15 has a correct final scalar, but the judge gave partial credit for the method claim because the final answer omitted the relation/operands. For P11 the judge accepted units inherited from the question/trace even though the terse final answer omitted the word “minutes”. These are scoring limitations, not claims of independently human-verified accuracy.

This comparison is between complete systems with intentionally different information/tool access and hardware, not a controlled comparison of base model capabilities. The GPT baseline does not receive the gold excerpts or Agent evidence.

| Metric | Agent − baseline (pp) | Paired bootstrap 95% CI (pp) | N |
|---|---|---|---|
| goal_success | -58.33 | [-79.17, -33.33] | 24 |
| claim_coverage | -62.15 | [-77.78, -45.82] | 24 |
| hallucination_free | -50.00 | [-70.83, -25.00] | 24 |
| numeric_accuracy | -80.00 | [-100.00, -50.00] | 10 |

10,000 paired resamples, fixed seed. Small purposive pilot; correlated concepts and reviewer uncertainty are not fully captured by task bootstrap. Claims use a shared frozen rubric; tool/provenance/citation advantages are supplementary, not asymmetrical primary requirements.

## Agent citation support and execution

{
  "citation_semantic_support_percent": 72.72727272727273,
  "supported_links": 16,
  "total_links": 22,
  "citation_bearing_responses": 6,
  "responses": 24
}

{
  "status_counts": {
    "stopped": 12,
    "completed": 8,
    "waiting_for_user_input": 4
  },
  "internal_status_counts": {
    "stopped": 12,
    "achieved": 8,
    "pending": 4
  },
  "iterations_total": 45,
  "numeric": {
    "calculation_executed": {
      "true": 3,
      "denominator": 10
    },
    "validated_calculation": {
      "true": 2,
      "denominator": 10
    }
  },
  "numeric_judge": {
    "correct_routing": {
      "true": 7,
      "not_measured": 2,
      "denominator": 10
    },
    "operand_completeness": {
      "true": 4,
      "not_measured": 1,
      "denominator": 10
    },
    "formula_selected": {
      "true": 2,
      "not_measured": 1,
      "denominator": 10
    }
  },
  "relevant_evidence_but_goal_failed": [
    "P03",
    "P04",
    "P06",
    "P07",
    "P10",
    "P18",
    "P21",
    "P23",
    "P24"
  ],
  "unnecessary_refusal": [
    "P01",
    "P03",
    "P04",
    "P06",
    "P08",
    "P10",
    "P12",
    "P13",
    "P14",
    "P16",
    "P17",
    "P18",
    "P19",
    "P20",
    "P23",
    "P24"
  ],
  "extractive_fallback_used": [],
  "extractive_fallback_not_instrumented": [
    "P01",
    "P02",
    "P05",
    "P06",
    "P07",
    "P08",
    "P09",
    "P10",
    "P11",
    "P12",
    "P15",
    "P16",
    "P17",
    "P18",
    "P19",
    "P20",
    "P21",
    "P22",
    "P23",
    "P24"
  ]
}

Citation support denominator is audited citation-to-claim links, NOT all tasks. Uncited responses cannot earn link credit. Diagnostics derive from raw trace plus judge audit; missing instrumentation is not a measured zero. Retrieved-relevant-evidence-but-goal-failed IDs identify current synthesis/orchestration gaps, not a causal comparison to v14.

## Every task (failures retained)

| Task | Group | Agent GS | GPT GS | Agent status | Actions | Agent seconds |
|---|---|---|---|---|---|---|
| P01 | Knowledge | 0 | 1 | stopped | retrieve → verify → stop | 39.68 |
| P02 | Knowledge | 1 | 1 | completed | retrieve → verify → synthesize → stop | 22.04 |
| P03 | Knowledge | 0 | 1 | stopped | retrieve → verify → stop | 24.55 |
| P04 | Knowledge | 0 | 0 | stopped | retrieve → verify → stop | 20.76 |
| P05 | Knowledge | 1 | 1 | completed | retrieve → verify → synthesize → stop | 20.84 |
| P06 | Knowledge | 0 | 0 | stopped | retrieve → verify → stop | 25.92 |
| P07 | Reasoning | 0 | 1 | completed | retrieve → verify → synthesize → stop | 20.04 |
| P08 | Reasoning | 0 | 0 | stopped | retrieve → verify → stop | 40.43 |
| P09 | Reasoning | 1 | 0 | completed | retrieve → verify → synthesize → stop | 20.55 |
| P10 | Reasoning | 0 | 0 | stopped | retrieve → stop | 15.58 |
| P11 | Calculation | 1 | 1 | completed | calculate → verify → synthesize → stop | 6.15 |
| P12 | Calculation | 0 | 1 | waiting_for_user_input |  | 1.04 |
| P13 | Calculation | 0 | 1 | stopped | retrieve → verify → stop | 21.38 |
| P14 | Calculation | 0 | 1 | stopped | retrieve → verify → stop | 25.68 |
| P15 | Calculation | 0 | 1 | completed | calculate → verify → synthesize → stop | 6.15 |
| P16 | Calculation | 0 | 1 | waiting_for_user_input |  | 1.05 |
| P17 | Calculation | 0 | 1 | waiting_for_user_input |  | 1.06 |
| P18 | Calculation | 0 | 1 | waiting_for_user_input | retrieve | 20.08 |
| P19 | Calculation | 0 | 1 | stopped | calculate → stop | 30.33 |
| P20 | Calculation | 0 | 1 | stopped | calculate → stop | 19.31 |
| P21 | Safety | 0 | 1 | completed | retrieve → verify → synthesize → stop | 21.23 |
| P22 | Safety | 1 | 1 | completed | retrieve → verify → synthesize → stop | 36.38 |
| P23 | Safety | 0 | 1 | stopped | retrieve → verify → stop | 17.76 |
| P24 | Safety | 0 | 1 | stopped | retrieve → stop | 12.92 |

## Latency

Mean recorded stage times (seconds): retrieval 6.4800; LLM generation 9.3241; Python 0.9201; verification 9.5529; synthesis 3.2818. These timers overlap (verification contains generation/evaluation), so they MUST NOT be summed as disjoint elapsed time. Generation within verification is the largest observed cost, followed by retrieval.

Agent mean/median/p95 seconds: {'mean': 19.62170401252418, 'median': 20.652257200097665, 'p95': 39.18388291017617}. Baseline: {'mean': 2.3237347208390324, 'median': 2.3584785498678684, 'p95': 3.658052505250089}. Includes cold start and polling. Stage timings remain in scored_rows.json. No warm-up inference or successful/failed response rerun.

## API usage and cost

{
  "gpt-5.4-mini-2026-03-17": {
    "calls": 24,
    "input_tokens": 2797,
    "output_tokens": 4890,
    "cached_input_tokens": 0,
    "estimated_list_price_usd": 0.02410275
  },
  "gpt-5.4-2026-03-05": {
    "calls": 24,
    "input_tokens": 78320,
    "output_tokens": 10250,
    "cached_input_tokens": 0,
    "estimated_list_price_usd": 0.34955
  }
}

Estimated API list-price total: $0.373653; not an invoice, excludes local hardware/electricity. Pricing references in POLICY.md.

## Independence, limitations and integrity

The dedup corpus contains 3,635 unique candidate text strings from 2,232 historical Git blobs and 531 local files; these include question fields, test literals and some non-question strings. Dynamically assembled prompts and cross-language near-duplicates are not guaranteed to be fully recovered. This is an explicit limitation of the offline exact/lexical/LSA plus manual-neighbour screen, not a claim of proven universal novelty. No above-threshold or exact duplicate remained after prefreeze screening.

Only evaluation reporting adapters were adjusted after freeze: the actual trace key is `action_type`, and the CSV exporter serializes verified typed cells through the bundled spreadsheet runtime. No question, gold, rubric, request prompt, collection behaviour, model response, judge response, product file or retrieval setting was changed. Poster PNG and SVG charts were visually checked; CSV dimensions and typed values were verified.

Candidates preceded access to old task strings. Dedup covered Git-history and local evaluation/development material with exact/lexical/LSA checks and manual concept review. LSA is a limited semantic screen, not proof of no near-duplicate. Generic arithmetic operators and a few within-pilot topics recur. Gold text is the actual stored Chroma extraction; page metadata was not independently revalidated against rendered PDFs. Acoustic depth source relation is expressed verbally. Reasoning tasks may combine paragraphs within one chunk. All prompts are English, so this pilot does not establish Korean performance. No multi-turn resume or figure-viewer evaluation was included. Judge is one AI reviewer from the same provider family as the baseline; answer labels were randomized, but citation attachments can reveal system identity. No human adjudication is claimed. No frozen heldout or older benchmark was rerun or pooled. Product tests/CI were not rerun because no product files changed. Failure rationales and numeric extraction audit remain per-row.

Completion checks: {"agent_records": true, "baseline_records": true, "judge_reviews": true, "product_unchanged": true, "benchmark_unchanged": true, "chroma_counts_unchanged": true, "chroma_metadata_unchanged": true, "no_automatic_retries": true, "main_unchanged": true, "all_collections_usable": true}

## Poster-safe conclusions

The closed-book baseline was at least as strong on every primary metric in this independent pilot. Goal Success was 20.8% for Agent and 79.2% for the baseline. These results do not establish population superiority or a causal improvement over earlier, different pilot sets.

No post-result tuning was performed.
