# Agent reliability v11.1 — development smoke

This is a **development regression**, not an unseen final benchmark. No v3 task was rerun or rescored, and no v4 benchmark was created. The product branch started from v11 SHA `aaa5a6999e7f46a287cb8b0560fe876adc9ff93c`.

## Method and environment

- Autonomous natural-language message parser and goal-execution agent, called in-process; local `qwen3:8b`, `hybrid` retrieval, web disabled.
- Existing read-only `petroleum_knowledge` Chroma collection: **12 documents, 18,976 chunks**. No indexing or PDF extraction.
- Six false-premise and six knowledge-QA prompts newly written for this development check, one per domain in each group. The exact prompts, source IDs/pages, answer, validation, actions, rerank telemetry, and wall-clock time are in [the JSON record](agent_reliability_v11_1_dev_smoke.json).
- Pass is the smoke script's conjunction of domain-document hit, relevant-chunk hit, and either explicit source-cited correction (premise) or an achieved answer with retained citation (QA). Citation semantic support here means the product's **local-model-assisted** validator accepted the retained answer; it is not independent human adjudication.

## Synthetic checks

| Development set | Cases | Wording variants | Result |
| --- | ---: | ---: | ---: |
| False-premise semantics across six domains | 12 | 36 | 36/36 route, correct source-grounded verdict and cited correction |
| Knowledge retrieval across six domains | 18 | 54 | 54/54 domain plan and relevant-source reranking |
| Additional guards | — | — | Literal indexed spans, fabricated-span rejection, multiline PDF rendering, bounded read-only context, conditional equation inference, cross-domain soft prior, LOW-confidence path |

These are synthetic development fixtures, not 90 independent end-to-end model runs. Their representative Python tests are in `backend/tests/test_agent_reliability_v11_1.py`.

## Live result

**12/12 PASS**, mean **23.35 s**, median **21.49 s**. Every case used the real local model and unchanged Chroma data. All six premise cases reached `PREMISE_CHECK`, retrieved a relevant chunk, rejected the false premise explicitly, and cited a source in a retained answer. All six knowledge cases reached `KNOWLEDGE_QA` and returned an internally validated, cited answer.

| Case | Domain | Result | Final action path | Relevant in top 3 | Time |
| --- | --- | --- | --- | ---: | ---: |
| P-RES | Reservoir Engineering | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 3/3 | 24.94 s |
| P-SIM | Reservoir Simulation | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 3/3 | 16.29 s |
| P-WELL | Well Testing | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 3/3 | 18.12 s |
| P-PETRO | Petrophysics | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 3/3 | 20.15 s |
| P-DRILL | Drilling | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 3/3 | 19.90 s |
| P-PROD | Production | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 3/3 | 19.33 s |
| K-RES | Reservoir Engineering | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 3/3 | 33.97 s |
| K-SIM | Reservoir Simulation | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 1/3 | 22.20 s |
| K-WELL | Well Testing | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 3/3 | 24.72 s |
| K-PETRO | Petrophysics | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 3/3 | 25.37 s |
| K-DRILL | Drilling | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 3/3 | 34.49 s |
| K-PROD | Production | PASS | RETRIEVE → VERIFY → SYNTHESIZE → STOP | 3/3 | 20.78 s |

## Development gate readout

| Metric | Observed | Target |
| --- | ---: | ---: |
| Premise intent routing | 6/6 = 100% | ≥95% |
| Premise relevant-source retrieval | 6/6 = 100% | ≥85% |
| Explicit false-premise correction | 6/6 = 100% | ≥85% |
| Premise citation semantic support, product validator | 6/6 = 100% | ≥85% |
| QA domain-matched document recall@5 | 6/6 = 100% | ≥85% |
| QA relevant chunk@5 | 6/6 = 100% | ≥80% |
| QA top-3 relevant precision | 16/18 = 88.9% | ≥65% |
| QA wrong-domain dominance (≥3 of top 5) | 0/6 = 0% | ≤15% |
| QA supported-answer success, product validator | 6/6 = 100% | ≥80% |
| Refined-retrieval recovery | Not exercised: 0 LOW-confidence live cases | N/A |

The final run has **no failed case** to assign a failure code. During development, the observed failures were classified as `PREMISE_GROUNDING` (an overly conservative verdict despite direct relation), `PREMISE_SYNTHESIS` (OCR line breaks split one quote into many claims), and `SOURCE_RELEVANCE` (a relevant domain document present but weak span selection). See the [premise analysis](agent_reliability_v11_1_premise_analysis.md) and [retrieval analysis](agent_reliability_v11_1_retrieval_analysis.md).

## v11 regression and limits

The existing v11 nine-case development smoke was rerun into a **temporary path**, leaving its tracked report intact: **9/9 PASS**, seven validated Python calculations, two same-run resumes, correct KB formula source, and zero repeated/no-progress actions. The original v11 smoke result was 7/9; this comparison is development-only, not a final performance claim. The v11 synthetic fact/unit/intent/calculation/resume tests also pass in the full backend suite.

Live tests exercised source-grounded premise correction, but **did not trigger adjacent-context expansion or LOW-confidence refined retrieval**; these paths have bounded synthetic tests. The local-model semantic validator is not an independent reviewer, and some QA prose remains verbose or broader than the smallest directly quoted source relation. This work does not establish unseen accuracy or remove the need for later independent evaluation.
