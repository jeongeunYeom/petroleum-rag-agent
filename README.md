# Petroleum RAG Agent

석유공학 문서 RAG, 외부 웹 근거 검색, 로컬 LLM, 도구 실행 Agent를 하나의 채팅으로 결합한 로컬 우선 연구지원 애플리케이션입니다.

## 주요 기능

- PDF 업로드, 텍스트·표·그림 추출 및 ChromaDB 인덱싱
- 내부 문서, 최신 웹 자료 또는 두 근거를 자동으로 선택하는 Research Agent
- 답변별 문서·페이지·청크 및 클릭 가능한 웹 출처 표시
- 연구 목표에 맞춘 Agent 계획과 읽기 전용 도구 자동 실행
- 파일 생성·수정 및 Python 분석은 사용자 승인 후 실행
- 문서 삭제 시 원본, 메타데이터, Figure Note와 ChromaDB 청크 함께 삭제
- Figure Review, RAG 평가, Qwen3/Gemma4 비교 화면
- Ollama 기반 로컬 텍스트·비전 추론

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
backend/app/       API, RAG, Research Agent, 실행 Agent
backend/tests/     백엔드 회귀 테스트
backend/scripts/   RAG 평가와 Well Test benchmark
frontend/app/      통합 채팅, Figure Review, 평가 화면
evaluation/        Well Test benchmark 질문 세트
scripts/e2e/       로컬·Docker E2E 테스트
workspace/         Agent가 접근할 수 있는 작업공간
```

업로드 문서와 ChromaDB는 Git에 저장하지 않고 `data/`에 유지됩니다.

## 빠른 시작

### 1. Ollama 준비

[Ollama](https://ollama.com/)를 설치하고 실행한 뒤 기본 모델을 받습니다.

```bash
ollama pull qwen3:8b
ollama pull qwen2.5vl:7b
```

임베딩 모델은 기본값 `BAAI/bge-m3`를 처음 실행할 때 준비하거나, `.env`의 `EMBEDDING_MODEL`과 `EMBEDDING_MODEL_PATH`로 변경할 수 있습니다.

### 2. 환경 설정

```powershell
Copy-Item .env.example .env
```

macOS/Linux에서는 `cp .env.example .env`를 사용합니다. 주요 값은 다음과 같습니다.

```env
DATA_DIR=./data
AGENT_WORKSPACE_DIR=./workspace
OLLAMA_BASE_URL=http://127.0.0.1:11434
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api
```

### 3. 실행

Docker:

```bash
docker compose up --build
```

직접 실행:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

새 터미널:

```powershell
cd frontend
corepack enable pnpm
pnpm install --frozen-lockfile
pnpm dev
```

- 웹: <http://127.0.0.1:3000>
- API: <http://127.0.0.1:8000/api>
- API 문서: <http://127.0.0.1:8000/docs>

## 검색 동작

- 기본: 내부 ChromaDB만 검색
- `최신`, `최근`, `현재`, `동향`만으로는 웹 검색을 시작하지 않음
- `웹 검색`, `인터넷 검색`, `web sources`처럼 웹 자료를 명시적으로 요청할 때만 내부 + 외부 통합 검색
- `웹에서만`, `web only`처럼 명시하면 외부 웹만 검색

기본 정책은 **Internal knowledge is used by default. Web Research is only activated when the user explicitly requests web/online sources.** 입니다. 내부 근거가 없거나 검증에서 제거되더라도 자동으로 웹 검색으로 전환하지 않습니다.

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

## 테스트

```powershell
cd backend
pytest -q

cd ../frontend
pnpm build
```

로컬 또는 Docker 전체 흐름:

```powershell
python scripts/e2e/run_local_e2e.py
python scripts/e2e/run_e2e.py --use-compose
```

Well Test benchmark 질문은 `evaluation/well_test_agent_benchmark.json`에 있습니다.

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

## 안전 범위

- Agent 파일 접근은 `AGENT_WORKSPACE_DIR` 내부로 제한됩니다.
- 비밀 파일, 상위 경로, 임의 셸 명령과 패키지 설치를 차단합니다.
- 쓰기·수정·Python 실행은 계획을 보여준 뒤 승인을 요구합니다.
- 공개 다중 사용자 서비스로 배포하려면 별도 OS 사용자 또는 컨테이너 수준 격리를 추가해야 합니다.

라이선스가 필요한 재사용 코드 정보는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 있습니다.
