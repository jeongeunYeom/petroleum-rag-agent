# Agent v8 실제 사용자 E2E 재검증 R2 (2026-10-08)

## 범위와 판정

- 저장소 `D:\petroleum-rag-agent`, 브랜치 `feature/goal-execution-v8`, 검증한 제품 코드 `ccf881904005c8479bd39035c4f5ee5cc5459f2a` (`main` 병합 없음).
- 실제 로컬 Ollama `qwen3:8b`, `RETRIEVAL_MODE=hybrid`, 기존 ChromaDB **12문서/18,976청크**, backend `127.0.0.1:8000`, frontend `127.0.0.1:3000`. T1~T6는 `POST /api/research/goal-runs/from-message` 및 저장된 run 폴링, T7은 실제 in-app browser에서 채팅과 `/review` 이동을 확인했다.
- OpenAI/Gemini API 호출과 frozen heldout 수정·재실행은 하지 않았다. 기존 R1 보고서는 변경하지 않았다. PASS는 서버의 `achieved`만이 아니라 실제 계산값, 출처, 차단·재개 동작으로 판정했다.

## T1~T7 결과

| ID | 판정 | 실제 action sequence | 최종 상태 | Python / 검증 CALC | 핵심 결과·근거 | 전체 지연 |
|---|---|---|---|---|---|---:|
| T1 문헌·인용 | **PASS** | RETRIEVE → VERIFY → SYNTHESIZE → STOP | completed / achieved | 0 / 없음 | API–비중·밀도 관계는 Lake Vol. I p266 `[KB1]`와 Heriot-Watt p177 `[KB4]`을 함께 인용. FIG1은 *API–Watson factor* 관계 문장에만 붙었고 원유 무거움의 근거로 쓰이지 않았다. 지원되지 않은 생성 문장 1개 제거; 최종 citation semantic pass. | 15.546초 |
| T2 직접 계산 | **PASS** | CALCULATE → ANALYZE → VERIFY → SYNTHESIZE → STOP | completed / achieved | 1 / CALC1 | KB 검색 0. 평균 194.6666667 stb/d(≈194.67), B > A > C, 최고 B. USERF1~3과 validated CALC1 연결. | 18.302초 |
| T3 KB+계산 | **PASS** | RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP | completed / achieved | 1 / CALC1 | `API = (141.5 / SG) - 131.5`가 실제 있는 Heriot-Watt p90 `[KB2]`만 formula provenance. p89 `[KB1]`은 식 출처에서 제외. 원시값 22.6394335512, 답변 **22.64 °API**. | 24.519초 |
| T4 사용자 식 시뮬레이션 | **PASS** | SIMULATE → ANALYZE → VERIFY → SYNTHESIZE → STOP | completed / achieved | 1 / CALC1 | 검색 0. 11 cases, 최적 porosity 0.30 / score 25, 평균 20, 범위 10. 사용자 수식만 사용. | 3.584초 |
| T5 정보 부족·재개 | **PASS**¹ | RETRIEVE → RETRIEVE → **WAITING** → 동일 run에서 SIMULATE → ANALYZE → VERIFY → SYNTHESIZE → STOP | completed / achieved | 1 / CALC1 | 초기 6.654초에 모델/간격을 한 번에 질문. 사용자가 수식, 0.02 간격, bulk volume 1000 m³, CO₂ density 700 kg/m³를 제공한 후 11 cases 및 최대 210000을 검증. 같은 run ID와 KB evidence를 유지. | 13.724초(두 구간 누적) |
| T6 근거 없는 식 | **PASS**² | RETRIEVE → RETRIEVE → RETRIEVE → **WAITING** | waiting_for_user_input / pending | 0 / 없음 | Kappa-Zeta 식을 찾지 못해 사용자에게 출처 있는 식을 요청. Zeta 수치·식 창작 없음. 이전 2회 CALCULATE 재시도 제거. | 10.054초 |
| T7 Figure 접근 | **PASS**³ | 채팅 Figure 요청 → `Figure Review 열기` 링크 → `/review` | review 화면 진입 | 0 / 해당 없음 | 일반 사이드바에 Figure 메뉴 없음. 실제 브라우저에서 채팅 명령과 viewer 이동 성공. | 약 0.7초(UI) |

¹ T5의 현재 KB 검색에서는 해당 CO₂ 저장량 모델을 충분히 검증할 수 없었다. 따라서 계산은 **추가로 사용자가 직접 제공한 모델**에 한정된다. 계산 성공을 독립적으로 검증된 CO₂ 저장 용량 모델이라고 해석해서는 안 된다. 결과에 물리 단위가 표시되지 않는 점도 후속 개선 대상이다.

² 식이 끝내 제공되지 않은 T6는 종료 대신 안전하게 대기한다. 이 시점에 최종 답변·unsupported claim은 없다. 사용자가 모른다고 답하면 기존 bounded clarification 경로가 `insufficient_evidence`로 안전 종료한다.

³ `/review`의 후보·note·preview는 모두 0이었다. 채팅 접근 경로는 PASS이지만 실제 Figure 내용 열람은 확인할 데이터가 없어서 미검증이다.

실제 run ID: T1 `GR-20261008-095719-186F57`, T2 `GR-20261008-095735-4CE80F`, T3 `GR-20261008-095754-CC295A`, T4 `GR-20261008-095819-F0374B`, T5 `GR-20261008-095823-48CDB1`, T6 `GR-20261008-095837-630AFF`. 원본 실행 기록은 `D:\petroleum-rag-agent\data\agent_runs\goal-research\`에 있다.

### 추가 누락값 회귀: 식은 KB에 있고 입력만 없는 경우

`내부 교재의 SG-API 관계식을 찾아 API gravity를 계산해줘.`를 별도 실행했다. `GR-20261008-095624-671D11`에서 p90의 일반식 검색 후 **SG 값**을 질문하며 `WAITING_FOR_USER_INPUT`에 진입했다(10.458초). 문서의 `SG=0.744` 예제값을 사용자 원유의 값으로 사용하지 않았다. `SG는 0.918입니다.`에 같은 run이 `RETRIEVE → CALCULATE → VERIFY → SYNTHESIZE → STOP`으로 이어져 p90 `[KB4]`와 **22.64 °API**를 검증했다(누적 31.938초). 이는 T5의 “KB 식은 있지만 사용자 입력값이 부족한” 별도 분기도 실물 모델·DB에서 통과했음을 보인다.

## 시간과 R1 대비

| 구분 | R1 | R2 |
|---|---:|---:|
| T1~T7 PASS | 2/7 | **7/7** (T5는 사용자 추가 모델, T6는 안전 대기 기준) |
| T1~T6 평균 | 31.697초 | **14.288초** |
| T1~T6 중앙값 | 25.590초 | **14.635초** |
| 가장 긴 테스트 | T6 68.122초 | T3 24.519초 |

R2 여섯 API run의 최대 누적 병목은 **LLM generation 49.431초**, 그다음 verification 29.336초, retrieval 19.303초다. 단계 시간은 중첩되므로 합산해서 total로 간주하지 않는다. R1과 R2는 실패 경로·모델 워밍 상태가 달라 평균 시간 차이를 순수한 속도 향상률로 해석할 수 없다. 다만 T6의 반복 차단 CALCULATE가 2회→0회가 된 것은 action history로 확인된다.

## 제품 변경과 남은 한계

- 최종 문헌 claim을 실제 KB/WEB/FIG 문구와 대조하고 지원되지 않은 문장을 제거한다. 검증 후 남은 답변만 평가하므로 무근거 문장 하나 때문에 안전 거절로만 끝나지 않는다. FIG는 해당 figure note의 실제 변수·관계를 지지할 때만 인용한다.
- 한국어 유량·사용자 시뮬레이션 수식/범위/간격을 구조화하고, autonomous bounded Python 권한으로 직접 계산한다. CALC formula ID는 원본 KB 문서·페이지·chunk와 식 span에 다시 연결한다.
- 누락 입력은 KB 검색 후 묶어서 질문하고, resume 때 누적 사용자 사실을 하위 계산기로 전달한다. 교재 예제값은 사용자 물성값으로 대용하지 않는다. 같은 blocker에서 관련 식이나 사용자 입력이 바뀌지 않으면 CALCULATE를 반복하지 않는다.
- 제한: claim semantic 판정은 로컬 LLM의 보수적 판단에 의존하므로 모든 공학적 함의를 형식적으로 증명하지 않는다. T1의 역관계는 SG·밀도 정의와 API 식의 조합이며, FIG1의 Watson 문장은 질문의 핵심에는 부차적이다. T2의 API 응답에는 평균의 긴 원시 소수가 남지만 UI 표현 계층은 숫자를 짧게 표시한다. T5의 사용자 제공 모델은 과학적 적합성·효율계수 등이 별도 검증되지 않았다. Figure Review 내용은 현재 0개다.
- **main 병합 권고: YES (이번 T1~T7 수용 기준에 한정).** 위 Figure 데이터 가용성과 CO₂ 모델 검증은 별도 후속 과제다. 이 작업에서는 실제 병합하지 않았다.

## 테스트·CI

- Backend `python -m pytest -q`: **738 passed, 6 warnings** (41.19초). T1~T7별 원문+최소 2개 변형을 포함하며 frozen heldout 재실행은 하지 않았다.
- Frontend `node --test tests/*.test.mjs`: **9 passed**. `pnpm build`: **성공**.
- CI: 최종 push 후 GitHub Actions 실행 결과는 최종 전달에서 확인한다.
