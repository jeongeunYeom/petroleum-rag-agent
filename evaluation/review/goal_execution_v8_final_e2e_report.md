# Agent v8 실제 사용자 E2E 검증 (2026-10-08)

## 범위와 판정

- 저장소/브랜치/제품 SHA: `D:\petroleum-rag-agent`, `feature/goal-execution-v8`, `6703ef8522d5a6f2c0bed672aff051d5d00058d6`.
- 실제 실행: frontend `127.0.0.1:3000`, backend `127.0.0.1:8000`, 로컬 Ollama `qwen3:8b`, `hybrid` retrieval, 기존 `D:\petroleum-rag-agent\data\vector_db`의 **12문서/18,976청크**. 자연어 `POST /api/research/goal-runs/from-message`로 autonomous goal execution 실행. 외부 웹 권한은 사용하지 않았고 OpenAI/Gemini API도 호출하지 않았다. frozen heldout은 수정·재실행하지 않았다.
- T1/T7 및 UI는 실제 in-app browser로 검증했다. T2~T6는 실제 backend API와 지속 저장된 run을 검증했으며 **브라우저 E2E가 아닌 API E2E**다. 제품 코드 수정 없이 결과를 기록했다.
- PASS는 API의 `achieved` 표시뿐 아니라 요청한 결과와 실제 citation/formula provenance가 맞는 경우에만 부여했다. T7은 명시된 *채팅에서 viewer 접근* 기준으로 PASS이나 viewer 내용은 비어 있다.

## 시나리오 결과

| ID | 판정 | 실제 action sequence | 최종 상태 | Python / 검증 CALC | 핵심 결과 | KB/FIG provenance | 보고된 unsupported claim | 전체 지연 | 문제점 |
|---|---|---|---|---|---|---|---:|---:|---|
| T1 | **FAIL** | RETRIEVE → VERIFY → SYNTHESIZE → STOP | `completed / achieved` | 0 / 없음 | API도가 낮으면 원유가 무겁다는 답변 | `[KB2]` Lake Vol. I p266, `[FIG1]` 같은 책 p271 | 0 | 25.408초 | KB2 발췌는 API도와 비중의 관련성만 말하며 반비례를 직접 입증하지 않음. FIG1은 Watson Characterization Factor 그래프인데 원유 무거움 그래프로 인용. `achieved`와 수동 근거 판정 불일치. |
| T2 | **FAIL** | RETRIEVE → RETRIEVE → STOP | `stopped / no_progress` | 0 / 없음 | 계산 없음. 기대: 평균 194.67 stb/d, B(234) > A(187) > C(163) | 없음 | 미기록 | 9.062초 | 사용자 값만으로 가능한 계산을 KB 검색으로 보냄. 요청에 `allow_python_execution=false`; CALCULATE 없음. |
| T3 | **FAIL** | RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP | `completed / achieved` | 1 / `CALC1=true` | 수치는 22.6394335512로 맞음. 답변은 `dimensionless` | 실제 식은 Heriot-Watt Reservoir Engineering `[KB2]` p90; CALC의 `formula_evidence_ids=[KB1]` p89 | 0 | 25.772초 | p89는 연습문제일 뿐 관계식 없음. 식 출처가 잘못 연결되어 provenance 검증 실패; °API 단위 표시도 실패. |
| T4 | **FAIL** | RETRIEVE → RETRIEVE | `waiting_for_user_input / pending` | 0 / 없음 | 시뮬레이션 없음. 기대: 11 cases, 최적 porosity 0.30, score 25, mean 20, range 10 | Lake Vol. V의 관련 없는 5개 KB hit | 미기록 | 약 7.884초(클라이언트) | 사용자 제공 `score=porosity*50+10`을 인식하지 않고 모델/식을 다시 요구. `simulation_spec=null`, `allow_python_execution=false`. API `total_seconds=0.000109`는 실제 지연과 불일치. |
| T5 | **FAIL** | RETRIEVE → CALCULATE → RETRIEVE → CALCULATE → RETRIEVE → VERIFY → STOP | `stopped / insufficient_evidence` | 0 / 없음 | 저장량 수치를 추측하지는 않음 | `[KB1]` Reservoir Simulation p303, `[KB2]` Lake Vol. I p236, `[KB3]` Reservoir Engineering p515 | 0 | 53.934초 | 두 CALCULATE가 `calculation_contract_unit_missing`으로 차단. 필요한 입력을 묻고 같은 run을 대기시키지 않고 최종 종료. |
| T6 | **PASS** | CALCULATE → RETRIEVE → CALCULATE → RETRIEVE → VERIFY → RETRIEVE → STOP | `stopped / insufficient_evidence` | 0 / 없음 | Kappa-Zeta 식 미발견, Zeta 계산·수치 창작 없음 | 검색은 했으나 식을 뒷받침하는 근거 없음 | 0 | 68.122초 | 안전 종료는 맞지만 차단된 CALCULATE 2회와 긴 지연이 남음. |
| T7 | **PASS**¹ | CHAT_FIGURE_INTENT → FIGURE_REVIEW_LINK → OPEN_REVIEW_VIEWER | `/review` 열림 | 0 / 해당 없음 | 상시 Figure 메뉴 없이 채팅 요청으로 viewer 링크가 즉시 나타남 | viewer에 후보/노트/preview 모두 0 | 해당 없음 | 약 0.74초(브라우저 명령+이동) | 접근은 성공했지만 현재 viewer에서 실제 그림을 볼 수 없음. |

¹ T7 PASS는 사용자 요구의 명시적 접근 경로 기준이다. 그림 내용 확인까지 필수로 해석하면 T7은 미완료다.

실제 run ID: T1 `GR-20261008-083054-67E731`, T2 `GR-20261008-083237-CD69EC`, T3 `GR-20261008-083333-3C580C`, T4 `GR-20261008-083445-F61D0F`, T5 `GR-20261008-083522-A2FC19`, T6 `GR-20261008-083654-C01B9D`. 실행 기록은 `D:\petroleum-rag-agent\data\agent_runs\goal-research\` 아래에 있다.

## 단계별 응답시간 (초)

| ID | Parse | Planning | Retrieval | LLM generation | Python/계산 경로 | Verification | Evaluation | Synthesis | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| T1 | 0.00008 | 0.007 | 10.708 | 14.569 | 0 | 14.575 | 4.966 | 9.603 | 25.408 |
| T2 | 0.00011 | 2.017 | 6.978 | 0 | 0 | 0 | 0 | 0 | 9.062 |
| T3 | 0.00009 | 0.001 | 4.082 | 15.868 | 5.687 | 4.512 | 4.485 | 0.013 | 25.772 |
| T4 | 0.00011 | 2.498 | 3.850 | 0 | 0 | 0 | 0 | 0 | **약 7.884**² |
| T5 | 0.00009 | 2.104 | 7.080 | 37.007 | 7.579 | 14.566 | 10.401 | 4.158 | 53.934 |
| T6 | 0.00009 | 2.340 | 10.821 | 46.440 | 8.356 | 12.888 | 5.448 | 7.434 | 68.122 |
| T7 | 해당 없음 | 해당 없음 | 해당 없음 | 해당 없음 | 해당 없음 | 해당 없음 | 해당 없음 | 해당 없음 | 약 0.74 (UI) |

² T4 대기 상태의 API `total_seconds`는 0.000109초로 잘못 기록되었다. 표에는 클라이언트 측 약 7.884초 관측을 썼다. 단계별 카운터는 서로 겹치므로 합이 Total과 같지 않다. `python_seconds`에도 실제 Python 호출 0건인 T5/T6의 차단·준비 경로 시간이 들어가며, 이를 Python subprocess 실행으로 해석하면 안 된다.

## 실제 UI 확인

- 953px viewport에서 문서 사이드바 340px, CSS의 xl 폭 370px. 긴 PDF 파일명은 2줄 제한이고 `title` 속성에 확장자 포함 전체 이름이 있다. KB 목록은 12문서로 표시됐다.
- 스크롤바의 계산된 `scrollbar-width`는 `none`; 실제 문서 목록의 `scrollTop`이 휠 스크롤 후 **0→538**로 바뀌었다. in-app Chromium에서 검증했고 Edge/Firefox/모바일은 별도로 실행하지 않았다.
- `[KB2]` 칩 10px, 주변 본문 14px. 클릭과 hover 시 표시되는 툴팁의 문서명·페이지 266·발췌문은 해당 T1 run의 `internal_sources.KB2`와 일치했다. **UI의 ID 매핑은 정확하지만 인용 문장의 의미 적합성은 별개이며 T1에서 실패했다.**
- 채팅 중심 레이아웃과 하단 입력창, `연구 진행 중`→`답변 작성 중` 표시를 확인했다. 상시 메뉴에 Plot, 평가 결과, Figure Review가 없었다. `/evaluation` 개발 route는 빌드에 존재하지만 일반 메뉴에서 비노출이다.
- T7 채팅 응답의 `Figure Review 열기` 링크로 `/review`를 열었다. 대시보드가 후보 0·note 0·preview 0을 표시해 실제 그림 검수까지 확인할 수는 없었다.

## 종합

- **PASS 2/7, FAIL 5/7. 필수 기능 실패 있음.** T1/T3의 서버 상태 `achieved`는 출처 의미 검증 성공을 보장하지 않았다.
- T1~T6 평균 **31.697초**, 중앙값 **25.590초**(UI-only T7 제외). 최장 T6 **68.122초**. 가장 큰 계측 병목은 LLM generation(T6 46.440초, T5 37.007초)이며, 실패 재시도도 이를 늘렸다.
- **Blocking:** T2 직접 계산 미진입, T4 명시된 시뮬레이션 식 미인식, T5 누락값 clarification 대신 종료, T1/T3 근거·계산식 provenance 오귀속.
- **Non-blocking / 별도 확인:** T7 viewer는 열리지만 빈 상태, T3 °API 단위 미표시, T4 대기 시간 계측 오류, T6 68초 지연, Edge/Firefox·모바일 미실행. T7의 실제 그림 확인이 병합 필수라면 빈 viewer도 blocking으로 승격해야 한다.
- **main 병합 권고: NO.** 이 검증에서는 결함을 제품 코드에서 고치지 않았고, 보고서만 추가했다.

## 테스트·CI

- Backend `python -m pytest -q`: **713 passed, 6 warnings (40.56s)**.
- Frontend `node --test tests/*.test.mjs`: **9 passed, 0 failed**. `pnpm build`: **성공**.
- 제품 기준 SHA `6703ef8522d5a6f2c0bed672aff051d5d00058d6`의 [GitHub Actions CI run 37744734143](https://github.com/jeongeunYeom/petroleum-rag-agent/actions/runs/37744734143): **success**. 보고서만 추가한 커밋의 CI 상태는 최종 전달 시 별도 확인한다.
