# Agent reliability v9 — development smoke

This is a small development regression, **not** a final benchmark or an estimate of population-level accuracy. `evaluation/final_benchmark_v1.json` and its raw results were neither edited nor rerun. No final_benchmark_v2 was created or run.

Environment: local `qwen3:8b`, `RETRIEVAL_MODE=hybrid`, the existing Chroma collection (`petroleum_knowledge`, 12 documents, 18,976 chunks), autonomous from-message API, and the existing Python sandbox. No OpenAI or Gemini API was used.

| Development scenario | Run ID | Observed action path | Outcome |
| --- | --- | --- | --- |
| User-only mean and sum, X/Y/Z rates | `GR-20261010-094704-1F3345` | CALCULATE → VERIFY → SYNTHESIZE → STOP | Achieved; mean 18.0 and sum 54.0 stb/d; Python 1; no retrieval |
| User-only ratio and difference | `GR-20261010-100256-A83455` | CALCULATE → VERIFY → SYNTHESIZE → STOP | Achieved; A/B ratio 3.0 and A−B difference 8.0 stb/d; Python 1; no retrieval |
| KB SG–API equation, SG 0.91 | `GR-20261010-094801-BC4CE8` | RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP | Achieved; 23.99 °API; formula source is the p.90 chunk containing `API = (141.5 / SG) - 131.5` |
| User-equation parameter sweep | `GR-20261010-095432-97E5DE` | SIMULATE → ANALYZE → VERIFY → SYNTHESIZE → STOP | Achieved; 6 validated cases, best response 11.8; Python 1; no retrieval |
| Reversed kick-pressure premise | `GR-20261010-095358-3E32F5` | RETRIEVE → VERIFY → SYNTHESIZE → STOP | Achieved; explicitly rejected, corrected formation pressure > mud hydrostatic pressure, cited KB1 |
| Missing SG, then user provides 0.87 | `GR-20261010-095502-164AC4` | RETRIEVE → WAITING_FOR_USER_INPUT → CALCULATE → VERIFY → SYNTHESIZE → STOP | Same run resumed; Python 0 before reply, 1 after; achieved 31.14 °API |

Development checks (denominators apply only to the cases above and the 19 new synthetic tests):

| Check | Result |
| --- | --- |
| Formula source correctness | 1/1 real KB calculation at the equation-bearing page; 3/3 source-span paraphrase tests |
| Calculation provenance completeness | 5/5 validated live calculations have formula source IDs, input fact IDs, bound variables, normalized formula, units, code hash, and output |
| False-premise handling | 1/1 live kick prompt corrected with citation; 3/3 kick paraphrase tests reject agreement and require supporting evidence |
| Python/simulation execution success | 5/5 eligible live requests completed a validated calculation or sweep |
| Action selection | 6/6 live scenarios followed their expected initial branch (direct calculation, KB retrieval, simulation, premise retrieval, or clarification retrieval) |
| Repeated/no-progress CALCULATE actions | 0 observed in these six live scenarios; synthetic blocker test stops after unchanged retrieval |

Limits: these are deliberately small development checks, not unseen evaluation. Equation parsing is conservative; non-parseable OCR equations may cause a safe stop. The deterministic kick correction applies only when a passage explicitly states the pressure relation. Other premise categories still rely on their registered validators and source-grounded synthesis. The separate unseen final_benchmark_v2 remains to be designed and run later.
