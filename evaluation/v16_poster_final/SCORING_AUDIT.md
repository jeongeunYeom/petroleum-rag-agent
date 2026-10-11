# Scoring audit

72 response records and 24 triple reviews. Full judge inputs, anonymous mappings and provider responses are retained. All claim-score lengths and domains were checked. Each external goal success additionally requires coverage=1, no fabricated fact, no wrong calculation and numeric correctness where applicable. Deterministic Goal Success overrides: [('V16-15', 'agent')].

Numeric values: extracted by single reviewer from final answers; deterministic absolute-tolerance/unit check across every required output. Numeric denominator=10, no missing tasks excluded. Fraction/percent normalization follows the frozen rubric. Hallucination-free = not(fabricated_fact or wrong_calculation); omission/refusal alone is not fabrication. Unnecessary refusal is answerable AND no substantive requested answer, not a stopped-status shortcut.

GPT token-length terminations: {'gpt_reference': ['V16-10']}. Raw local done_reason is retained. No response was rerun for incompleteness or failure. No judge response was repaired with another API call. No performance-driven scoring-policy changes.

Citation-link support and relevant-evidence judgements are supplementary and do not impose citation requirements on closed-book systems. The anonymous label mapping is saved outside each judge payload. Complete blinding is not possible because source lists and answer styles reveal augmentation.

Evaluation-only unit tests: 5 passed. CSV files are generated from typed Artifact Tool sheet values and independently round-trip checked. Main bootstrap uses paired tasks, 10,000 resamples, seed 16161012; Agent-minus-Qwen differences retain their signs.

No post-result tuning was performed.

## Mechanical citation audit

The judge supplied 14 evidence-to-gold links whose IDs were not cited in the actual answer. These were excluded under the frozen actual-citation denominator rule. Zero semantic scores were rewritten. Unreviewed actual citation IDs: 0. The retained links and rejected links are auditable in the companion JSON/CSV.

## Reviewer sensitivity, not score changes

V16-15 Agent reports the correct dimensionless numerical value but the reviewer rejects its omitted explicit dimensionless label. Numeric Accuracy therefore counts it as failure under the recorded units verdict. This is stricter than a value-only measure; three computations are executed/validated but only two outputs pass value-plus-unit scoring. V16-01 Qwen is marked fabricated partly for its nitrogen reference-gas example and current-based explanation. The source says carrier gas is usually air, not exclusively air, so the example alone does not establish fabrication. The reviewer verdict was retained unchanged; this illustrates possible over-strictness/false positives in the single-reviewer hallucination metric. These are not human-adjudicated labels and should not be used as precise safety guarantees. No rejudging was performed.
