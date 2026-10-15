# V23 product freeze — development gate

The V23.1 product candidate is frozen at **`62e5c36f3d66e25addc8a2c37b63af12e2636e78`** on `feature/conference-demo-v23`. This is a development-gate freeze, **not** a final unseen evaluation. No V4 benchmark was created or executed, and `main` was not merged.

## Gate evidence

| Requirement | Final-code development result | Gate |
|---|---:|---|
| Real-KB overall | 49/50 automatic; **48/50 (96%) conservative semantic review** | ≥90% |
| Knowledge | **9/10 conservative** (10/10 automatic) | ≥9/10 |
| Direct | 10/10 | 10/10 |
| User formula | 8/8 | 8/8 |
| KB formula | 10/10 | ≥9/10 |
| Multi-goal | 5/6 | ≥5/6 |
| False premise | 3/3 | 3/3 |
| Unanswerable | 3/3 | 3/3 |
| Same-run resume | 10/10 | ≥9/10 |
| 220-prompt stress | 220/220 automatic; **215/220 (97.7%) conservative semantic review** | ≥95% |
| Technical crash / blank / raw error / invented source ID / validator-confirmed unsupported numeric / repeated identical clarification | 0 / 0 / 0 / 0 / 0 / 0 | All zero |
| Unnecessary refusals, answerable petroleum tasks | 0/200 | ≤5% |
| Direct / user-formula median latency | 3.594 s / 4.985 s | ≤6 s / ≤8 s |

The conservative downgrades are one incomplete derivative-purpose explanation (`VB-K04`) and five equivalent stress phrasings (`VBST086`–`VBST090`). The sole automatic real-KB failure (`VB-M04`) is an ambiguous ratio-order request that produced a safe clarification, not an invented calculation. These development limitations are retained in the raw results and detailed in [V23B_REPAIR_REPORT.md](V23B_REPAIR_REPORT.md).

Targeted regressions: **455 passed**, including **184 newly added cases**. Full backend: **2,277 passed**. Frontend: **23 passed** and production build successful. The existing read-only `petroleum_knowledge` collection remained at **12 documents / 18,976 chunks**. Local `qwen3:8b`, hybrid retrieval, and the autonomous from-message API were used; web was off.

## Immutable evaluation reference

| File | SHA-256 |
|---|---|
| `real_kb_dev_v23b.json` | `4B58A2B2D6FB267D41436A471C867A1D3883EA5D10774A73B58E2E8878BE1099` |
| `conference_stress_v23b.json` | `CF1CB07B6FFAA2340B79770A2321100ED091D5BF4E715CE8FF2B9FFC7667AEC5` |
| `real_kb_dev_v23b_final_results.json` | `BBB2BB5A4756856742E802C50A2489154905FDDDEDD86EB7A24880D09111F7C1` |
| `conference_stress_v23b_final_results.json` | `3832C9C6ACA7DF564554D49F82125BB85CF5DA184B4F6ACD958665ECD9AA05E5` |

These prompts are observed development material from this point forward. Do not tune against them after this freeze or describe their results as unseen final performance. The V4 independent evaluation, if commissioned, must be created separately against the exact product SHA above. No further product change is included in this freeze record.
