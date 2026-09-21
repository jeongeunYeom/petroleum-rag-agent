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

- 일반 문서 질문: 내부 ChromaDB 검색
- 최신·현재 동향 질문: 외부 웹 검색
- 내부 자료와 최신 연구 비교: 내부 + 외부 통합 검색

외부 검색은 DDGS를 사용하며 별도 API 키가 필요하지 않습니다. 검색 결과와 순위는 공개 검색 서비스 상태에 따라 달라질 수 있습니다. 외부 결과는 답변 근거로만 사용하며 ChromaDB에 저장하지 않습니다.

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

## 안전 범위

- Agent 파일 접근은 `AGENT_WORKSPACE_DIR` 내부로 제한됩니다.
- 비밀 파일, 상위 경로, 임의 셸 명령과 패키지 설치를 차단합니다.
- 쓰기·수정·Python 실행은 계획을 보여준 뒤 승인을 요구합니다.
- 공개 다중 사용자 서비스로 배포하려면 별도 OS 사용자 또는 컨테이너 수준 격리를 추가해야 합니다.

라이선스가 필요한 재사용 코드 정보는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 있습니다.
