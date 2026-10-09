# Petroleum Engineering AI Agent

석유공학 연구 목표를 **하나의 채팅 입력**으로 받는 로컬 우선 AI Agent입니다. 사용자가 자연어로 질문이나 목표를 적으면 Agent가 필요한 행동을 선택해 `RETRIEVE → CALCULATE → SIMULATE → ANALYZE → VERIFY` 중 해당 단계를 실행하고, 근거와 검증 결과를 포함해 답합니다. 모든 요청에 모든 단계가 실행되는 것은 아닙니다.

## 현재 제품 흐름

- 내부 Knowledge Base(PDF·텍스트·표·Figure Note를 포함한 ChromaDB)가 기본 근거입니다. 명시적으로 웹 자료나 최신 자료를 요청한 경우에만 외부 검색을 사용합니다.
- 좌측 Knowledge Base 사이드바에는 대화와 접힌 **지식베이스·문서 추가**, **고급 설정**이 있고, 우측은 채팅·하단 입력창과 실행 상태·결과를 보여줍니다. Plot·평가 화면·Figure Review는 일반 사용자 메뉴에 상시 표시하지 않습니다.
- `"추출된 그림 확인하고 싶어"`처럼 채팅에서 요청하면 Figure Review 뷰어로 이동할 수 있습니다. Figure 기능 자체는 유지됩니다.
- 답변의 `[KB1]` 같은 작은 인용 표시를 가리키거나 클릭하면 `run.internal_sources`의 해당 근거 ID에 연결된 실제 문서명, 페이지, 발췌문을 볼 수 있습니다. WEB/FIG 출처도 같은 근거 ID 체계를 사용합니다.
- 계산·시뮬레이션에 필요한 정보가 없으면 기존 입력과 근거를 확인하고 KB를 먼저 검색합니다. 그래도 부족한 값만 묶어서 질문하며, `WAITING_FOR_USER_INPUT` 상태에서 같은 `run_id`와 누적 근거를 유지한 채 답변 후 재개합니다. 값·단위·공식은 추측하지 않습니다.
- 업로드 문서를 삭제하면 원본, 메타데이터, Figure Note와 관련 ChromaDB 청크도 함께 삭제합니다.

## 구성

| 영역 | 기술 |
|---|---|
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python 3.11 |
| LLM / Vision | Ollama, Qwen3, Qwen2.5-VL |
| Retrieval | ChromaDB, sentence-transformers, DDGS 웹 검색 |
| Documents | PyMuPDF, pdfplumber, Pillow |
| Charts | Plotly, Matplotlib |

```text
backend/app/       API, 검색·검증, Goal Execution Agent
backend/tests/     백엔드 회귀 테스트
backend/scripts/   RAG 평가와 Well Test benchmark
frontend/app/      채팅 제품 UI와 별도 개발용 화면
evaluation/        과거 benchmark·검증 기록 (제품 기능과 별도)
scripts/e2e/       로컬·Docker E2E 테스트
workspace/         Agent가 접근할 수 있는 작업공간
```

업로드 문서와 ChromaDB는 Git에 저장하지 않고 `DATA_DIR`(기본 `./data`)에 유지됩니다. 저장소를 새로 받는 것만으로 검증에 사용한 12문서·18,976청크가 생기지는 않습니다.

## 빠른 시작

### 1. Ollama 준비

[Ollama](https://ollama.com/)를 설치하고 실행한 뒤 기본 모델을 받습니다.

```bash
ollama pull qwen3:8b
ollama pull qwen2.5vl:7b
```

임베딩 기본 모델은 `BAAI/bge-m3`입니다. `.env.example`은 Hugging Face/Transformers 오프라인 모드가 켜져 있으므로, 처음 설치할 때는 모델을 미리 캐시하거나 다운로드할 동안만 오프라인 설정을 해제해야 합니다. `hybrid_rerank` 사용 시 `BAAI/bge-reranker-base`도 필요합니다.

### 2. 환경 설정

```powershell
Copy-Item .env.example .env
```

저장소 루트에서 실행합니다(macOS/Linux는 `cp .env.example .env`). 백엔드는 루트 `.env`를 읽고 상대경로를 저장소 루트 기준으로 해석합니다. 주요 값은 다음과 같습니다.

```env
DATA_DIR=./data
AGENT_WORKSPACE_DIR=./workspace
OLLAMA_BASE_URL=http://127.0.0.1:11434
RETRIEVAL_MODE=legacy
```

기존 ChromaDB가 다른 곳에 있다면 `DATA_DIR`을 그 DB를 포함한 `data` 디렉터리의 절대경로로 지정합니다. 재인덱싱은 필요하지 않습니다. 검증 환경과 같은 검색 모드는 `RETRIEVAL_MODE=hybrid`이며 `.env.example`의 기본값은 `legacy`입니다. 프런트엔드 API 주소를 바꿔야 할 때는 `frontend/.env.local`에 `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api`처럼 지정합니다. 기본 주소는 코드에 설정되어 있습니다.

### 3. 실행

Docker(로컬 개발용):

```bash
docker compose up --build
```

직접 실행(저장소 루트에서 각각 별도 터미널):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

새 터미널:

```powershell
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

- 웹: <http://127.0.0.1:3000>
- API: <http://127.0.0.1:8000/api>
- API 문서: <http://127.0.0.1:8000/docs>

## 검색·검증 동작

채팅 기반 Goal Execution은 내부 ChromaDB를 기본으로 사용합니다. `웹에서`, `온라인에서`, `최근 논문`, `최신 연구`처럼 외부·최신 자료를 요청하면 웹 근거도 사용하며, `웹 없이` 같은 명시적 제외는 우선합니다. 단순히 내부 근거가 부족하다는 이유로 웹 검색 권한을 확대하지 않습니다. 별도의 Research API에는 자체 검색 옵션이 있으므로 모든 엔드포인트가 같은 문구 규칙을 따르는 것은 아닙니다.

외부 검색은 DDGS를 URL discovery에 사용한 뒤, 안전성 검사를 통과한 HTML/PDF를 직접 열어 본문을 추출하고 질문 관련 passage만 WEB 근거로 사용합니다. 페이지 fetch가 모두 실패한 경우에만 검색 snippet을 별도 fallback provenance로 표시합니다. 외부 결과는 요청 중에만 사용하며 ChromaDB에 저장하지 않습니다.

```text
DDGS discovery -> safe fetch -> content extraction -> passage ranking -> WEB evidence
```

fetch는 기본 5개 URL을 최대 3개씩 병렬 처리하며 URL당 최대 5 MB, 15초, 전체 Web Research 25초로 제한됩니다. BGE-M3와 lexical 점수를 결합해 관련도 `0.20` 미만 passage를 제외합니다. Web Research v2는 `DDGS discovery → safe concurrent fetch → extraction → relevance filtering → source/date metadata → quality + recency + primary-source ranking → WEB evidence` 순서로 동작합니다. 최신·역사·일반 기술·비교 질문을 구분하고, relevance가 비슷할 때 날짜가 명시된 최신 자료와 공식·1차 기술 자료를 우선합니다. Source authority는 순위 신호일 뿐, 내용이 참이라는 보증이 아닙니다. `.env`의 `WEB_FETCH_*`, `WEB_RESEARCH_TIMEOUT_SECONDS`, `WEB_MAX_FETCH_RESULTS`, `WEB_PASSAGE_*`로 조정할 수 있습니다.

내부 Retrieval은 `.env`의 `RETRIEVAL_MODE`로 선택합니다. 기존 ChromaDB를 그대로 읽으며 재인덱싱하지 않습니다.

| 값 | 내부 Retrieval |
|---|---|
| `legacy` | Dense + 기존 keyword + RRF |
| `hybrid` | BGE-M3 dense + BM25 + RRF |
| `hybrid_rerank` | BGE-M3 dense + BM25 + RRF + CrossEncoder |

`hybrid_rerank`는 `RERANKER_MODEL`을 최초 요청 때 지연 로딩합니다. 기본값은 `BAAI/bge-reranker-base`입니다.
오프라인 모드에서 사용하려면 해당 모델을 Hugging Face 캐시에 먼저 받아 두어야 합니다.

Research 답변은 retrieval mode와 무관하게 claim 단위 공학 검증을 통과해야 합니다. 질의에 따라 registry가 Well Test와 Reservoir validator를 하나 이상 선택하고, 각 validator의 이슈를 domain과 rule code가 보존된 상태로 합칩니다.

```text
Query -> Engineering Validator Registry
          |-- Well Test
          `-- Reservoir
```

Well Test validator는 wellbore storage의 unit-slope/pressure-derivative overlap, radial-flow derivative plateau, linear-flow `+1/2`, spherical-flow `-1/2`, late-time boundary/recharge의 조건부 unit-slope를 구분합니다. Reservoir validator는 porosity, permeability, saturation, Darcy-flow 방향, formation-volume factor, material balance와 대표 drive mechanism의 명백한 모순을 검사합니다. 질문에 잘못된 전제가 있으면 이를 명시적으로 반박해야 하며, citation의 공학적 의미가 claim과 일치하지 않거나 근거가 상충하는데 단정하면 해당 claim을 제거하고 최대 2회까지만 재작성합니다.

Validator는 답변의 사실 근거가 아니라 consistency/contradiction guard입니다. 최종 claim은 계속 KB, WEB 또는 FIG evidence로 뒷받침되어야 합니다. 향후 Drilling, Petrophysics, Production validator도 같은 registry에 추가할 수 있지만 현재 구현 범위에는 포함하지 않습니다.

## 채팅 기반 Autonomous Goal Execution

기본 UI는 목표·성공 조건·가설·Python 사용 여부를 각각 적는 폼이 아니라 **채팅 입력 한 칸**입니다. 메시지는 기존 `GoalResearchRequest`로 변환되고, 명시한 가설이 있을 때만 예상 결과로 기록됩니다. 성공 조건을 쓰지 않았다면 목표에서 생성합니다. 고급 설정과 구조화 API는 별도로 유지합니다.

```text
사용자 메시지 → 목표 해석 → RETRIEVE / CALCULATE / SIMULATE / ANALYZE / VERIFY
             → 근거·계산 결과 검증 → 인용 포함 답변 또는 추가 입력 대기
```

예를 들어 `"비중이 0.918인 원유의 API gravity를 내부 교재 식으로 계산해줘."`라고 보내면 KB에서 식을 찾고 실제 식 출처를 확인한 후 계산·검증해 약 `22.64 °API`와 인용을 답합니다. 입력값만으로 끝나는 평균·순위 계산은 불필요한 KB 검색 없이 계산할 수 있습니다. 명시적 범위와 식이 있는 요청은 시뮬레이션·분석으로 이어질 수 있습니다.

`"공극률 0.1~0.3에서 CO₂ 저장량 최적 조건 찾아줘."`처럼 모델이나 필수 변수가 빠진 요청은 우선 사용자 입력·누적 근거·기존 계산 결과·내부 KB를 확인합니다. 여전히 값이 없으면 `WAITING_FOR_USER_INPUT`(`run_status=waiting_for_user_input`)으로 일시 정지해 필요한 항목을 묻습니다. 사용자가 답하면 **새 run을 만들지 않고** 같은 `run_id`, 상태, 근거로 재개합니다. 출처 없는 식이나 수치를 만들어 계산하지 않습니다.

채팅에서 `보고서 만들어줘` 또는 `발표자료/PPT 만들어줘`라고 요청하면 완료된 연구 결과로 DOCX/PPTX 산출물을 만들 수 있습니다. 생성 여부는 연구 상태와 별도로 기록되며, 실패하거나 취소된 연구에서는 기본적으로 만들지 않습니다.

### Python 자동 실행과 안전 경계

채팅의 `autonomous_goal_execution`에서는 Agent가 계산·시뮬레이션 필요성을 판단해 **별도 사용자 승인 클릭 없이** 제한된 Python sandbox를 사용할 수 있습니다. 도구 허용 목록, 네트워크 차단, 실행 시간·호출 횟수·작업공간 제한, 입력값·공식의 provenance와 결과 검증은 유지됩니다. 검증을 통과한 계산만 `CALC*` 근거로 인용합니다. 사용자 수치는 문헌 근거를 대체하지 않으며 전문식에는 실제 KB/FIG/WEB 또는 사용자 제공 식이 필요합니다.

반면 기존 구조화 `POST /api/research/goal-runs`의 `legacy_goal_research` 경로는 Python 권한 플래그(`allow_python_execution`, `python_execution_approved`)를 별도로 요구합니다. 이 차이는 채팅 기반 자동 계산이 무제한 코드·파일 실행을 허용한다는 뜻이 아닙니다.

### Run API

실행은 백그라운드 run으로 저장됩니다. 일반 채팅은 첫 번째 엔드포인트를 사용하고 상태를 조회합니다. 추가 입력은 같은 run에 보냅니다.

```text
POST /api/research/goal-runs/from-message        자연어 메시지로 시작
GET  /api/research/goal-runs/{run_id}             상태·답변 조회
POST /api/research/goal-runs/{run_id}/resume      대기 중 사용자 답변 전달
POST /api/research/goal-runs/{run_id}/cancel      취소
POST /api/research/goal-runs                      구조화 요청(고급/기존 경로)
GET  /api/research/goal-runs/{run_id}/artifacts/{artifact_id}
```

Run 로그는 `DATA_DIR/agent_runs/goal-research/`에 저장됩니다. 검색 결과와 citation은 KB/WEB/FIG ID에, 검증된 계산은 CALC ID에 연결됩니다.

## 검증 기록과 현재 코드의 테스트

[Agent v8 최종 E2E R2 보고서](evaluation/review/goal_execution_v8_final_e2e_r2_report.md)는 2026-10-08 로컬 환경에서 `qwen3:8b`, `hybrid` 검색, 기존 ChromaDB **12문서·18,976청크**로 확인한 기록입니다. T1~T7은 **7/7 PASS**, 당시 백엔드 테스트 **738 passed**, 프런트엔드 테스트 **9 passed**, 빌드 성공, T1~T6 평균 응답시간은 **약 14.29초**였습니다. 이는 해당 데이터·모델·환경의 검증 결과이지 새 설치의 성능 보증은 아닙니다.

검증 범위도 구분해야 합니다. Figure Review는 채팅에서 뷰어로 들어가는 경로만 확인했으며 당시 후보·note·preview가 0개여서 **실제 Figure 내용 검증은 미완료**입니다. CO₂ 저장량 T5는 사용자가 추가로 제공한 모델·값을 바탕으로 재개한 사례로, 그 모델의 공학적 타당성이 KB에서 독립 검증된 것은 아닙니다. 과거 benchmark 및 frozen evaluation 기록은 `evaluation/`에 별도로 보존됩니다.

현재 코드의 백엔드 회귀 테스트, 프런트엔드 컴포넌트 테스트와 빌드는 다음과 같습니다(저장소 루트 기준).

```powershell
cd backend
python -m pytest -q

cd ../frontend
node --test tests/*.test.mjs
pnpm build
cd ..
```

로컬 또는 Docker E2E 도구(별도 실행 환경 필요):

```powershell
python scripts/e2e/run_local_e2e.py
python scripts/e2e/run_e2e.py --use-compose
```

### 연구용 Well Test benchmark

아래는 **제품 UI의 현재 검증 결과가 아니라 별도 연구 평가를 재현하는 명령**입니다. 질문 세트는 `evaluation/well_test_agent_benchmark.json`에 있습니다. frozen evaluation은 임의로 수정하거나 재실행하지 마세요.

```powershell
python backend/scripts/run_well_test_benchmark.py --dry-run
```

Retrieval mode별 비교는 백엔드를 각 모드로 다시 시작한 뒤 같은 조건으로 실행합니다. 첫 번째 터미널에서:

```powershell
$env:RETRIEVAL_MODE="legacy"       # hybrid, hybrid_rerank로 반복
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

두 번째 터미널의 저장소 루트에서:

```powershell
python backend/scripts/run_well_test_benchmark.py `
  --mode research `
  --retrieval-mode legacy `
  --model qwen3:8b `
  --temperature 0 `
  --seed 42
```

논문 benchmark는 기본적으로 Web Search를 비활성화하여 실시간 검색 변동성을 제거합니다. `--use-external`을 명시한 경우에만 웹 검색을 사용합니다. Engineering Validator ablation은 같은 조건에서 기본 ON 실행과 `--disable-engineering-validator` 실행을 비교합니다.

세 실행 결과를 한 표로 합칩니다.

```powershell
python backend/scripts/compare_benchmark_runs.py `
  data/evaluation/<legacy.json> `
  data/evaluation/<hybrid.json> `
  data/evaluation/<hybrid_rerank.json>
```

결과 JSON/CSV에는 retrieval mode, `use_external`, web evidence/search 여부, `engineering_validation_enabled`, 답변 정확도, hallucination rate, citation correctness, retrieval recall, engineering contradiction count, false-premise correction success, unsupported engineering claim count, 평균 retrieval/전체 시간이 기록됩니다.

## 사내망 배포 (planned / upcoming)

현재 저장소에는 사내망 운영 배포 절차가 아직 구현·검증되어 있지 않습니다. 별도 배포 구성이 완료되면 `docs/internal_deployment.md`에 설치·격리·운영 절차를 문서화하고 여기에서 링크합니다. 위 Docker 명령은 로컬 개발 실행 예시이며 사내망 배포 완료를 뜻하지 않습니다.

## 안전 범위

- Agent 파일 접근은 `AGENT_WORKSPACE_DIR` 내부로 제한됩니다.
- 비밀 파일, 상위 경로, 임의 셸 명령과 패키지 설치를 차단합니다.
- 채팅의 자율 계산·시뮬레이션은 제한된 sandbox와 provenance/결과 검증을 거치며, 임의의 파일 수정·셸 실행 권한으로 확대되지 않습니다.
- 공개 다중 사용자 서비스로 배포하려면 별도 OS 사용자 또는 컨테이너 수준 격리를 추가해야 합니다.

라이선스가 필요한 재사용 코드 정보는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 있습니다.
