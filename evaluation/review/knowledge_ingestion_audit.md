# v2 Knowledge ingestion vs Agent orchestration audit

## 판정

**원본 PDF 텍스트 추출은 이번 v2 표본의 주요 병목이 아니다.** 수식 13/13이 원본 PDF의 텍스트 레이어, 저장된 추출본, Chroma의 단일 chunk에서 동일 AST로 인식됐다. 반면 gold page retrieval은 18/39이고, 정확한 식 span이 Agent evidence에 들어간 것은 7/13뿐이었다. 식 span이 도달해도 계산으로 전환하거나 누락 입력을 물어보는 흐름이 실패했다.

- 범위: 원본 PDF 7권의 **40쪽**(frozen v2 catalog 28쪽 전수 + 실패 run의 비정답 상위 검색 페이지 12쪽), source record 28개(식 task 13개, Figure 4개), frozen Agent 60 run 중 실패 55건.
- 고정 상태: `b99d5ddf84a60086df08c08a2af546d8ae212852` 제품, `petroleum_knowledge` 12 documents / 18,976 chunks. SQLite SHA-256을 읽기 전후 비교했고 동일했다. benchmark 실행·재인덱싱·제품 코드는 건드리지 않았다.
- 분모: text/metadata는 40쪽, catalog anchor는 비그림 24개, equation은 식 task 13개(중복 source page 포함), figure link는 4개, retrieval은 gold source가 지정된 39 task, 1차 실패 원인 비율은 실패 55 task.

## 단계별 실측

| 지표 | 결과 | 판정 범위 |
|---|---:|---|
| PDF text-layer → extracted text 보존 | 100.0% (40/40) | 토큰 재현율 ≥95%; 시각 픽셀 OCR 정확도와 다름 |
| 숫자 토큰 보존 | 100.0% (39/39) | 원본 텍스트 레이어에 숫자가 있는 쪽만 분모; 그림 속 숫자는 별도 |
| 대표 단위 토큰 보존 | 100.0% (12/12) | psi/psia/ppg/stb/scf/ft/ohm/mD/cP/kWh/°C/°R가 텍스트 레이어에 있는 쪽 |
| Extracted text → Chroma 보존 | 100.0% (40/40) | 겹친 chunk를 합친 토큰 재현율; 저장 chunk와 Chroma 원문도 40/40 동일 |
| catalog 핵심 anchor 보존 | 100.0% (24/24) | catalog 요약의 핵심 영문 토큰 ≥70% |
| equation 보존 / parser 인식 | 100.0% / 100.0% (각 13/13) | 동일 AST가 단일 Chroma chunk의 실제 식 span에서 인식 |
| 식의 chunk-boundary 실패 | 0.0% (0/13) | 식 전체가 단일 chunk에 존재 |
| 문서·쪽 metadata 정확성 | 100.0% (40/40) | Chroma document, page, chunk ID와 PDF 물리 페이지 번호 대조 |
| Figure note↔문서/쪽/이미지 링크 | 100.0% (4/4) | note metadata와 이미지 존재; note 의미 정확도 전체 보증 아님 |
| v2 실행의 gold 문서 / 쪽 retrieval | 79.5% (31/39) / 46.2% (18/39) | 당시 Agent의 저장된 KB+FIG evidence 순위 기준 |
| KB 식 gold 쪽 / 실제 식 span retrieval | 8/13 / 7/13 | 같은 페이지의 다른 chunk는 식 span hit로 간주하지 않음 |
| Figure gold retrieval | 4/4 | 네 그림 모두 runtime evidence에 있음 |

원본 PDF 화면에서 RE242의 `P_o = P_f + P_c`와 RS335의 `Pc=Po-Pw`를 별도로 렌더링해 텍스트 레이어와 대조했고, 네 Figure 원본 이미지를 모두 육안 확인했다. 아래 100% 수치는 **선정된 페이지의 text layer 및 명시된 식**에 한정된다. 저장된 추출본은 끝 개행을 제거하거나 Figure note를 추가하므로 원본 텍스트와 전체 문자열이 완전히 같다는 뜻은 아니다. PDF의 모든 시각 요소, 수식의 첨자 모양, 그림 내부 작은 숫자까지 100% OCR됐다는 뜻도 아니다. RE242의 시각적 하첨자는 저장 텍스트에서 `Po/Pf/Pc`처럼 평탄화되지만 변수 식별과 AST는 보존된다. 40쪽에서 텍스트 레이어에 이미 있던 그리스 문자/Unicode 하첨자가 추출 과정에서 추가로 사라진 사례는 각각 0쪽이다. 이는 PDF 시각 레이어에만 있는 기호의 OCR 손실률을 뜻하지 않는다. 이번 13식에서 계산을 막는 식/상수/변수 손실은 발견되지 않았다.

## Formula audit — 원본 → 추출 → Chroma → parser → 실행 evidence

| Task | Gold source | 원본 식 | 추출 식 | Chroma 식/parser | 실제 식 span | 실패 1차 원인 |
|---|---|---|---|---|---|---|
| K01 | RE153 p153 | YES | YES | YES | NO | RETRIEVAL |
| K02 | RE242 p242 | YES | YES | YES | YES | ACTION_PLANNER |
| K03 | RE559 p559 | YES | YES | YES | YES | ACTION_PLANNER |
| K04 | DR431 p431 | YES | YES | YES | NO | RETRIEVAL |
| K05 | PTII21 p21 | YES | YES | YES | NO | RETRIEVAL |
| K06 | PTII23 p23 | YES | YES | YES | YES | CALCULATION_GATE |
| K07 | RS148 p148 | YES | YES | YES | YES | CALCULATION_GATE |
| K08 | RS335 p335 | YES | YES | YES | NO | RETRIEVAL |
| K09 | FE196 p196 | YES | YES | YES | YES | ACTION_PLANNER |
| K10 | RE349 p349 | YES | YES | YES | NO | RETRIEVAL |
| C01 | RE559 p559 | YES | YES | YES | YES | CALCULATION_GATE |
| C02 | RE153 p153 | YES | YES | YES | NO | RETRIEVAL |
| C03 | PTII165 p165 | YES | YES | YES | YES | ACTION_PLANNER |

13식 단계 분해: 원본 source missing **0**, extraction corrupted **0**, chunk-boundary **0**, 저장 chunk parser miss **0**, 당시 실행의 정확한 식 span retrieval miss **6**, 식 span 도달 후 planner/gate 실패 **7**. 단위는 원본 텍스트 레이어의 단위 토큰이 있던 12쪽 모두 보존됐고, 13식의 변수·상수는 AST 일치로 확인했다.

식 출처 인정에는 같은 문서나 인접 페이지가 아니라 **그 식 자체가 포함된 원문 chunk span**을 사용했다. `Po = Pf + Pc`(RE242)의 경우 원본·추출·Chroma 모두 식과 변수 Po/Pf/Pc가 확인되고 registry가 식 AST를 만들지만, K02 실행은 p242의 식을 실제로 받아서도 VERIFY/RETRIEVE 반복 후 계산 없이 종료했다. K05는 p21을 받았지만 식 `fm=64/Re`가 선택된 excerpt 안에 없어 페이지 recall만으로는 부족했다.

## Retrieval audit — 당시 저장된 실행 결과

| Task | 유형 | gold 문서 rank | gold 쪽 rank | 실제 식 span | 1차 실패 단계 |
|---|---|---:|---:|---|---|
| C01 | clarification | 1 | 1 | YES | CALCULATION_GATE |
| C02 | clarification | 1 | — | NO | RETRIEVAL |
| C03 | clarification | 1 | 3 | YES | ACTION_PLANNER |
| F01 | false_premise | 2 | 2 | n/a | INTENT_ROUTING |
| F02 | false_premise | 2 | 3 | n/a | SYNTHESIS |
| F03 | false_premise | 1 | 1 | n/a | SYNTHESIS |
| F04 | false_premise | 2 | 6 | n/a | SYNTHESIS |
| G01 | figure | 1 | 1 | n/a | SYNTHESIS |
| G02 | figure | 1 | 5 | n/a | SYNTHESIS |
| G03 | figure | 4 | 4 | n/a | PASS |
| G04 | figure | 1 | 4 | n/a | ACTION_PLANNER |
| K01 | kb_calculation | 5 | — | NO | RETRIEVAL |
| K02 | kb_calculation | 2 | 6 | YES | ACTION_PLANNER |
| K03 | kb_calculation | 1 | 1 | YES | ACTION_PLANNER |
| K04 | kb_calculation | 1 | — | NO | RETRIEVAL |
| K05 | kb_calculation | 3 | 3 | NO | RETRIEVAL |
| K06 | kb_calculation | 1 | 1 | YES | CALCULATION_GATE |
| K07 | kb_calculation | 1 | 2 | YES | CALCULATION_GATE |
| K08 | kb_calculation | 4 | — | NO | RETRIEVAL |
| K09 | kb_calculation | 1 | 3 | YES | ACTION_PLANNER |
| K10 | kb_calculation | 2 | — | NO | RETRIEVAL |
| L01 | literature | — | — | n/a | RETRIEVAL |
| L02 | literature | 5 | 5 | n/a | SYNTHESIS |
| L03 | literature | 1 | — | n/a | RETRIEVAL |
| L04 | literature | — | — | n/a | RETRIEVAL |
| L05 | literature | 3 | — | n/a | RETRIEVAL |
| L06 | literature | — | — | n/a | RETRIEVAL |
| L07 | literature | — | — | n/a | RETRIEVAL |
| L08 | literature | — | — | n/a | RETRIEVAL |
| L09 | literature | 1 | 1 | n/a | SYNTHESIS |
| L10 | literature | 1 | — | n/a | RETRIEVAL |
| L11 | literature | 1 | — | n/a | RETRIEVAL |
| L12 | literature | 1 | — | n/a | RETRIEVAL |
| L13 | literature | 1 | — | n/a | RETRIEVAL |
| L14 | literature | 1 | — | n/a | RETRIEVAL |
| L15 | literature | — | — | n/a | RETRIEVAL |
| L16 | literature | — | — | n/a | RETRIEVAL |
| L17 | literature | 5 | — | n/a | RETRIEVAL |
| L18 | literature | — | — | n/a | PASS |

gold source가 필요 없는 계산·사용자식 simulation·unsupported-formula 문항의 실패:

| Task | 유형 | 실제 action | 1차 실패 단계 |
|---|---|---|---|
| C04 | clarification | RETRIEVE → RETRIEVE | INTENT_ROUTING |
| D01 | direct_calculation | RETRIEVE → RETRIEVE → RETRIEVE | INTENT_ROUTING |
| D02 | direct_calculation | RETRIEVE → VERIFY → RETRIEVE → VERIFY → RETRIEVE → STOP | INTENT_ROUTING |
| D03 | direct_calculation | RETRIEVE → RETRIEVE → STOP | INTENT_ROUTING |
| D04 | direct_calculation | RETRIEVE → RETRIEVE → STOP | INTENT_ROUTING |
| D05 | direct_calculation | RETRIEVE → VERIFY → RETRIEVE → VERIFY → RETRIEVE → STOP | INTENT_ROUTING |
| D06 | direct_calculation | RETRIEVE → RETRIEVE → RETRIEVE | INTENT_ROUTING |
| D07 | direct_calculation | RETRIEVE → VERIFY → RETRIEVE → VERIFY → RETRIEVE → STOP | INTENT_ROUTING |
| D08 | direct_calculation | RETRIEVE → CALCULATE → RETRIEVE → VERIFY → RETRIEVE → VERIFY → STOP | CALCULATION_GATE |
| D09 | direct_calculation | RETRIEVE → VERIFY → RETRIEVE → STOP | INTENT_ROUTING |
| D10 | direct_calculation | RETRIEVE → VERIFY → RETRIEVE → VERIFY → RETRIEVE → STOP | INTENT_ROUTING |
| S01 | simulation | RETRIEVE → RETRIEVE | INTENT_ROUTING |
| S03 | simulation | RETRIEVE → RETRIEVE | INTENT_ROUTING |
| S04 | simulation | RETRIEVE → RETRIEVE | INTENT_ROUTING |
| U01 | unsupported_formula | RETRIEVE → VERIFY → RETRIEVE → STOP | SYNTHESIS |
| U02 | unsupported_formula | RETRIEVE → VERIFY → RETRIEVE → VERIFY → RETRIEVE → STOP | SYNTHESIS |
| U03 | unsupported_formula | RETRIEVE → RETRIEVE → RETRIEVE | SYNTHESIS |
| U04 | unsupported_formula | RETRIEVE → RETRIEVE → RETRIEVE | SYNTHESIS |

## 실패 원인 분리

55개 실패마다 첫 번째로 결과를 막은 단계를 1개씩 지정했다. 원인 중첩은 가능하므로 이는 **1차 원인**이지 각 구성요소의 독립적 에러율이 아니다. 상세한 action outcome, 근거 rank, formula span은 JSON의 `retrieval_audit`에 있다.

| 1차 원인 | 실패 수 / 55 | 비율 | 대표 증거 |
|---|---:|---:|---|
| INGESTION | 0/55 | 0.0% | 원본 텍스트가 저장본에서 사라짐 |
| CHUNKING | 0/55 | 0.0% | 식이 chunk 경계에서 분리 |
| RETRIEVAL | 21/55 | 38.2% | L01/L03, K01/K04/K05: gold 쪽/식 span 부재 |
| FORMULA_PARSER | 0/55 | 0.0% | 원문 식 span 도달 후 AST 인식 실패 |
| INTENT_ROUTING | 14/55 | 25.5% | D01·S01: 입력/사용자 식이 충분해도 RETRIEVE 반복 |
| ACTION_PLANNER | 5/55 | 9.1% | K02/K03: 정확한 식 도달 후 VERIFY/RETRIEVE 반복 |
| CALCULATION_GATE | 4/55 | 7.3% | K06/K07: 정확한 식 도달 후 calculation_source_missing |
| SYNTHESIS | 11/55 | 20.0% | F03: 반대 근거를 받고도 false premise를 그대로 답변 |

- 지식 파이프라인 중 **ingestion/chunking 1차 원인 0.0%**, retrieval 1차 원인 38.2%, Agent orchestration(식 parser·intent·planner·gate·synthesis) 61.8%. 별도로 gold-source task의 쪽 retrieval miss는 **21/39(53.8%)**이다.
- 가장 큰 세 원인은 **RETRIEVAL 21/55(38.2%)**, **INTENT_ROUTING 14/55(25.5%)**, **SYNTHESIS 11/55(20.0%)**다. 결과가 부족했던 PDF를 전체 재추출하는 것은 현재 근거로 정당화되지 않는다. 선택적 재추출도 이번 40쪽/13식에는 필요하지 않다. 다음 개발 우선순위는 (1) gold page/정확한 식 span retrieval, (2) 사용자 제공 값·식의 intent routing, (3) 도달한 식을 CALCULATE/clarification으로 연결하는 planner·readiness gate와 false-premise synthesis이다.

## 보존·판정 한계

- 이 진단은 frozen v2 질문이나 정답을 다시 실행하지 않았으며, 모델 출력 이후 코드를 수정하지 않았다. Retrieval rank는 그때 저장된 `internal_sources`와 `figures` 순서다. 내부 dense/BM25 후보 전체 순위는 raw 결과에 없어 분리 평가하지 않는다.
- 텍스트 보존 100%는 원본 PDF의 **추출 가능한 텍스트 레이어**를 기준으로 한다. 그림 안의 레이블·스캔 OCR 품질은 네 Figure의 링크/주요 제목을 육안 대조했지만 전체 12권에 대한 보증은 아니다.
- catalog gold span은 문장 요약일 수 있어, 비그림 텍스트는 어휘 anchor 70% 기준이다. 식은 이 느슨한 기준을 쓰지 않고 `FormulaSourceRegistry`의 literal span/AST로 검사했다.
- Figure 4/4 링크 및 runtime retrieval 성공은 실제 답변의 Figure 해석 성공과 별개다. G01/G02/G04 실패는 그림 누락보다는 출처 활용·합성 단계다.

## 표본 페이지 목록

| 문서 | 페이지 | 선정 이유 | PDF→추출 | 추출→Chroma | metadata |
|---|---:|---|---:|---:|---|
| Heriot-Watt University - Reservoir Engineering.pdf | 153 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt University - Reservoir Engineering.pdf | 183 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt University - Reservoir Engineering.pdf | 241 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt University - Reservoir Engineering.pdf | 242 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt University - Reservoir Engineering.pdf | 349 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt University - Reservoir Engineering.pdf | 503 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt University - Reservoir Engineering.pdf | 559 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt University - Reservoir Engineering.pdf | 571 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt University - Reservoir Engineering.pdf | 710 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Drilling_Engineering.pdf | 192 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Drilling_Engineering.pdf | 198 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Drilling_Engineering.pdf | 242 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Drilling_Engineering.pdf | 360 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Drilling_Engineering.pdf | 410 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Drilling_Engineering.pdf | 431 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Drilling_Engineering.pdf | 521 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Production_Technology_I.pdf | 21 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Production_Technology_I.pdf | 23 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Production_Technology_I.pdf | 88 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Production_Technology_II.pdf | 21 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Production_Technology_II.pdf | 23 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Production_Technology_II.pdf | 113 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Production_Technology_II.pdf | 165 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Production_Technology_II.pdf | 542 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Reservoir_Simulation.pdf | 144 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Reservoir_Simulation.pdf | 148 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Reservoir_Simulation.pdf | 207 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Reservoir_Simulation.pdf | 273 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Reservoir_Simulation.pdf | 335 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Well_Test_Analysis.pdf | 44 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Well_Test_Analysis.pdf | 65 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Well_Test_Analysis.pdf | 201 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Well_Test_Analysis.pdf | 213 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Well_Test_Analysis.pdf | 280 | failed_run_retrieval_distractor | 1.00 | 1.00 | OK |
| Heriot-Watt_University_-_Well_Test_Analysis.pdf | 499 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot_Watt_University_-_Formation_Evaluation.pdf | 103 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot_Watt_University_-_Formation_Evaluation.pdf | 120 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot_Watt_University_-_Formation_Evaluation.pdf | 133 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot_Watt_University_-_Formation_Evaluation.pdf | 171 | catalog_gold | 1.00 | 1.00 | OK |
| Heriot_Watt_University_-_Formation_Evaluation.pdf | 196 | catalog_gold | 1.00 | 1.00 | OK |
