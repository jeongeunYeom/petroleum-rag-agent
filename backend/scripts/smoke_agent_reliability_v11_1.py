"""Frozen-in-script v11.1 development smoke: six premise and six knowledge cases."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.research_routes import cached_research_agent
from app.core.config import get_settings
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_knowledge_retrieval import _document_domain
from app.services.goal_message_parser import GoalMessageRequest, parse_goal_message
from app.services.ollama import OllamaClient


# Development concepts and document families only: no frozen task IDs, pages, answers or source spans.
CASES = [
    ("P-RES", "premise", "reservoir_engineering",
     "대수층 물 유입은 저류층 압력 유지와 무관하지? 내부 자료로 전제를 검증해줘.",
     (("aquifer", "water influx"), ("pressure", "support"))),
    ("P-SIM", "premise", "reservoir_simulation",
     "저류층 시뮬레이션에서 격자 크기는 수치 해상도에 아무 영향이 없지? 근거로 확인해줘.",
     (("grid", "cell"), ("size", "resolution", "accuracy"))),
    ("P-WELL", "premise", "well_testing",
     "유정 압력 상승 시험은 shut-in 이후 압력을 기록할 필요가 없지? 내부 근거로 점검해줘.",
     (("buildup", "shut-in"), ("pressure", "record"))),
    ("P-PETRO", "premise", "petrophysics",
     "저항도 검층 결과는 물 포화도와 무관하다고 보면 되나? 자료로 검증해줘.",
     (("resistivity", "electrical"), ("saturation", "water"))),
    ("P-DRILL", "premise", "drilling",
     "시추 이수 밀도가 증가해도 정수압은 변하지 않는 거지? 교재 근거로 확인해줘.",
     (("mud", "fluid"), ("hydrostatic", "pressure"))),
    ("P-PROD", "premise", "production",
     "생산 분리기의 압력은 가스 분리 거동과 무관하지? 내부 자료로 검토해줘.",
     (("separator", "separation"), ("gas", "pressure"))),
    ("K-RES", "knowledge", "reservoir_engineering",
     "저류층 물질수지 해석에서 대수층 물 유입 항은 어떤 역할을 하나? 내부 자료로 설명해줘.",
     (("aquifer", "water influx"), ("material balance", "pressure"))),
    ("K-SIM", "knowledge", "reservoir_simulation",
     "저류층 시뮬레이터에서 셀 간 transmissibility가 투과도와 어떻게 연결되는지 설명해줘.",
     (("transmissibility", "transmission"), ("permeability", "grid"))),
    ("K-WELL", "knowledge", "well_testing",
     "유정 pressure buildup 시험에서 shut-in 뒤 압력 기록을 사용하는 목적을 설명해줘.",
     (("buildup", "shut-in"), ("pressure", "transient"))),
    ("K-PETRO", "knowledge", "petrophysics",
     "저항도 검층과 물 포화도 추정의 관계를 내부 교재에서 설명해줘.",
     (("resistivity", "electrical"), ("saturation", "water"))),
    ("K-DRILL", "knowledge", "drilling",
     "시추 이수 밀도가 정수압 관리에 어떤 영향을 주는지 교재 근거로 설명해줘.",
     (("mud", "fluid"), ("hydrostatic", "pressure"))),
    ("K-PROD", "knowledge", "production",
     "생산 분리기 압력과 가스 분리 과정의 관계를 내부 자료로 설명해줘.",
     (("separator", "separation"), ("gas", "pressure"))),
]


def _relevant(text: str, groups: tuple[tuple[str, ...], ...]) -> bool:
    lower = text.casefold()
    return all(any(term.casefold() in lower for term in alternatives) for alternatives in groups)


async def main() -> None:
    settings = get_settings()
    if settings.retrieval_mode != "hybrid" or not (settings.vector_db_dir / "chroma.sqlite3").is_file():
        raise RuntimeError("Connect the existing Chroma DB with RETRIEVAL_MODE=hybrid")
    research = cached_research_agent()
    if research.vector_store.count() != 18976:
        raise RuntimeError("Existing 18,976-chunk Chroma collection required")
    metadata = research.vector_store.collection.get(include=["metadatas"])["metadatas"]
    documents = {row.get("document") for row in metadata if row and row.get("document")}
    if len(documents) != 12:
        raise RuntimeError("Existing 12-document knowledge base required")
    agent = GoalExecutionAgent(research, OllamaClient(settings))
    rows = []
    for case_id, kind, family, prompt, concepts in CASES:
        request = parse_goal_message(GoalMessageRequest(message=prompt, model="qwen3:8b"))
        request = request.model_copy(update={"use_external": False, "internal_top_k": 5,
                                             "max_retrieval_actions": 2, "max_iterations": 7,
                                             "temperature": 0, "seed": 42})
        started = time.perf_counter()
        try:
            result = await agent.run(f"DEV-V11-1-{case_id}", request)
            sources = result.internal_sources
            matched = [item for item in sources if _document_domain(item.document) == family]
            relevant = [item for item in sources if _relevant(item.excerpt, concepts)]
            top3 = sum(_relevant(item.excerpt, concepts) for item in sources[:3])
            wrong = sum(_document_domain(item.document) not in {None, family} for item in sources[:5])
            cited = bool(re.search(r"\[(?:KB|FIG|WEB)\d+\]", result.final_answer))
            # Rejected draft claims have already been removed; score the retained answer.
            semantic = bool(result.validation.get("citation_semantic_passed") and cited)
            rejection = bool(re.search(r"전제.{0,12}(?:맞지|잘못|틀)|premise.{0,25}(?:incorrect|contradict)",
                                       result.final_answer, re.I))
            corrected = bool(kind == "premise" and rejection and semantic and
                             result.telemetry.get("premise_verdict") == "contradicts" and
                             result.status.value == "achieved")
            supported = bool(kind == "knowledge" and semantic and result.status.value == "achieved")
            pass_case = bool(matched and relevant and (corrected if kind == "premise" else supported))
            history = result.telemetry.get("retrieval_rerank_history") or []
            row = {"id": case_id, "kind": kind, "domain": family, "passed": pass_case,
                   "intent": result.telemetry.get("intent_route"), "status": result.status.value,
                   "actions": [item["action_type"] for item in result.action_history],
                   "premise_verdict": result.telemetry.get("premise_verdict"),
                   "premise_method": result.telemetry.get("premise_grounding_method"),
                   "premise_failure_reason": result.telemetry.get("premise_grounding_failure_reason"),
                   "premise_supporting_source_ids": result.telemetry.get("premise_supporting_source_ids"),
                   "context_expansion": result.telemetry.get("premise_context_expansion") or [],
                   "domain_document_hit": bool(matched), "relevant_chunk_hit": bool(relevant),
                   "top3_relevant": top3, "wrong_domain_top5": wrong,
                   "citation_semantic_support": semantic, "explicit_correction": corrected,
                   "supported_answer": supported,
                   "refined_attempted": any("refined_retrieval" in item for item in history),
                   "refined_recovered": any(item.get("refined_recovery") for item in history),
                   "sources": [{"id": item.evidence_id, "document": item.document,
                                "page": item.page, "chunk_id": item.chunk_id,
                                "excerpt_prefix": item.excerpt[:280]} for item in sources],
                   "retrieval_rerank": history, "answer": result.final_answer,
                   "validation": result.validation, "seconds": round(time.perf_counter() - started, 3)}
        except Exception as exc:
            row = {"id": case_id, "kind": kind, "domain": family, "passed": False,
                   "error": type(exc).__name__ + ": " + str(exc),
                   "seconds": round(time.perf_counter() - started, 3)}
        rows.append(row)
        print(json.dumps({key: value for key, value in row.items()
                          if key not in {"sources", "retrieval_rerank", "answer", "validation"}},
                         ensure_ascii=True), flush=True)
    output = Path(__file__).resolve().parents[2] / "evaluation" / "review" / "agent_reliability_v11_1_dev_smoke.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"label": "DEVELOPMENT ONLY — NOT FINAL BENCHMARK",
                                  "model": "qwen3:8b", "retrieval_mode": "hybrid", "web": False,
                                  "documents": 12, "chunks": 18976, "cases": rows},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
