"""Local v11 development smoke; synthetic prompts, never frozen evaluation tasks."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.research_routes import cached_research_agent
from app.core.config import get_settings
from app.models.goal_research_schemas import GoalRunStatus
from app.services.formula_source_registry import FormulaSourceRegistry, source_contains_equation
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_message_parser import GoalMessageRequest, parse_goal_message
from app.services.ollama import OllamaClient


CASES = {
    "direct_median": ("A=5, B=11, C=14. Find the median of these three readings.", None),
    "direct_weighted": ("X=12, Y=18, X:Y=1:2. Compute the weighted average from these values only.", None),
    "user_formula": ("a=6, b=3. output=a*b+2. Calculate output with my equation.", None),
    "fixed_sweep": ("b=4. Sweep a from 1 to 3 step 1. score=2*a*b-a*a. Find the best case.", None),
    "kb_formula": ("An oil sample has SG=0.879. Locate the internal conversion equation and calculate its API gravity.", None),
    "premise": ("모세관 진입압은 저류층 밀봉 성능과 무관하다고 보면 되나? 내부 근거로 확인해줘.", None),
    "literature": ("저류층 시뮬레이션 교재에서 수치 격자의 역할을 내부 근거로 설명해줘.", None),
    "resume_formula": ("a=5. result=a*b. Compute the result using this equation.", "b is 7."),
    "resume_direct": ("X:Y=2:3. Calculate the weighted average of X and Y from my values only.", "X=12, Y=18."),
}


def summary_row(case: str, result, elapsed: float, *, waited: bool = False,
                same_run: bool = False) -> dict:
    actions = [row["action_type"] for row in result.action_history]
    calcs = [row for row in result.computations if row.validation_passed]
    outputs = {key: item.get("value") for calc in calcs for key, item in calc.output_manifest.items()}
    source_rows = [{"evidence_id": source.evidence_id, "source_type": "knowledge_base",
                    "text": source.excerpt} for source in result.internal_sources]
    known_ids = {row["evidence_id"] for row in source_rows}
    for calc in calcs:
        for fact in calc.input_facts:
            fact_id = str(fact.get("evidence_id") or "")
            if fact_id and fact_id not in known_ids:
                source_rows.append({"evidence_id": fact_id, "source_type": "user_fact",
                                    "text": f"{fact.get('name')}={fact.get('value')} {fact.get('unit') or ''}"})
                known_ids.add(fact_id)
        for source_id in calc.formula_source_ids:
            if source_id.startswith("USERF"):
                if source_id not in known_ids:
                    source_rows.append({"evidence_id": source_id, "source_type": "user_fact",
                                        "text": calc.source_formula or ""})
                    known_ids.add(source_id)
                else:
                    row = next(item for item in source_rows if item["evidence_id"] == source_id)
                    if calc.source_formula and calc.source_formula not in row["text"]:
                        row["text"] += "\n" + calc.source_formula
    provenance = [GoalExecutionAgent._provenance_complete(calc, source_rows,
                  result.topic + "\n" + (result.goal or "")) for calc in calcs]
    formula_correct = None
    if case == "kb_formula":
        records = FormulaSourceRegistry.from_evidence(source_rows).records
        formula_correct = any(
            any(record.source_id == source_id and source_contains_equation(
                record, next(row["text"] for row in source_rows if row["evidence_id"] == source_id),
                calc.source_formula or calc.formula) for record in records)
            for calc in calcs for source_id in calc.formula_source_ids if source_id.startswith("KB"))
    values = [float(row.get("value")) for calc in calcs for row in calc.output_manifest.values()
              if isinstance(row.get("value"), (int, float))]
    pass_conditions = {
        "direct_median": bool(calcs and math.isclose(values[0], 11) and actions[:1] == ["calculate"]),
        "direct_weighted": bool(calcs and any(math.isclose(value, 16) for value in values)
                                and actions[:1] == ["calculate"]),
        "user_formula": bool(calcs and any(math.isclose(value, 20) for value in values)
                             and actions[:1] == ["calculate"]),
        "fixed_sweep": bool(calcs and "simulate" in actions and "analyze" in actions
                             and math.isclose(outputs.get("OUT_BEST_RESULT", -1), 15)),
        "kb_formula": bool(calcs and formula_correct and "retrieve" in actions and "calculate" in actions
                            and any(math.isclose(value, 141.5 / .879 - 131.5, rel_tol=1e-8)
                                    for value in values)),
        "premise": bool(result.status.value == "achieved" and
                        result.telemetry.get("premise_verdict") == "contradicts" and
                        result.validation.get("citation_semantic_passed") is True),
        "literature": bool(result.status.value == "achieved" and
                           "retrieve" in actions and "verify" in actions and "simulate" not in actions
                           and result.validation.get("citation_semantic_passed") is True),
        "resume_formula": bool(waited and same_run and calcs and any(math.isclose(value, 35)
                                                                        for value in values)),
        "resume_direct": bool(waited and same_run and calcs and any(math.isclose(value, 15.6)
                                                                       for value in values)),
    }
    return {
        "case": case, "passed": pass_conditions[case], "run_id": result.run_id,
        "status": result.status.value, "run_status": result.run_status.value,
        "actions": actions, "validated_calcs": len(calcs), "python_calls": result.python_calls_total,
        "outputs": outputs, "formula_source_correct": formula_correct,
        "provenance_complete": all(provenance) if provenance else None,
        "waited_for_user": waited, "same_run_resumed": same_run,
        "premise_verdict": result.telemetry.get("premise_verdict"),
        "citation_semantic_passed": result.validation.get("citation_semantic_passed"),
        "repeated_no_progress": sum(row["reason_code"] in {"repeated_action_fingerprint", "retrieve_no_progress"}
                                    for row in result.action_history),
        "evidence": [{"id": source.evidence_id, "document": source.document, "page": source.page,
                      "excerpt_prefix": source.excerpt[:240]} for source in result.internal_sources],
        "telemetry": result.telemetry, "timing": result.timing,
        "answer": result.final_answer, "seconds": round(elapsed, 3),
        "stop_reason": result.stop_reason.value if result.stop_reason else None,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*")
    args = parser.parse_args()
    if set(args.cases) - set(CASES):
        parser.error("unknown synthetic development case")
    settings = get_settings()
    if settings.retrieval_mode != "hybrid":
        raise RuntimeError("v11 development smoke requires RETRIEVAL_MODE=hybrid")
    if not (settings.vector_db_dir / "chroma.sqlite3").is_file():
        raise RuntimeError("Existing Chroma DB is not connected")
    research = cached_research_agent()
    count = research.vector_store.count()
    if count != 18976:
        raise RuntimeError(f"Expected existing Chroma count 18976, got {count}")
    metadata = research.vector_store.collection.get(include=["metadatas"])["metadatas"]
    documents = {row.get("document") for row in metadata if row and row.get("document")}
    if len(documents) != 12:
        raise RuntimeError(f"Expected 12 existing documents, got {len(documents)}")
    agent = GoalExecutionAgent(research, OllamaClient(settings))
    rows = []
    for case in args.cases or CASES:
        message, reply = CASES[case]
        request = parse_goal_message(GoalMessageRequest(message=message, model="qwen3:8b"))
        request = request.model_copy(update={"use_external": False, "max_iterations": 8,
                                             "max_python_calls": 2, "max_retrieval_actions": 2,
                                             "temperature": 0, "seed": 42})
        start = time.perf_counter()
        try:
            result = await agent.run(f"GR-V11-SMOKE-{case.upper().replace('_', '-')}", request)
            waited = result.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT
            same_run = False
            if reply and waited:
                checkpoint = dict(result.resume_checkpoint)
                checkpoint["user_replies"] = [reply]
                prior_id = result.run_id
                result = await agent.run(prior_id, request, resume_state=checkpoint, resume_result=result)
                same_run = result.run_id == prior_id
            row = summary_row(case, result, time.perf_counter() - start,
                              waited=waited, same_run=same_run)
        except Exception as exc:
            row = {"case": case, "passed": False, "error": type(exc).__name__ + ": " + str(exc),
                   "seconds": round(time.perf_counter() - start, 3)}
        rows.append(row)
        print(json.dumps({key: value for key, value in row.items()
                          if key not in {"answer", "telemetry", "evidence"}}, ensure_ascii=True), flush=True)
    output = Path(__file__).resolve().parents[2] / "evaluation" / "review" / "agent_reliability_v11_dev_smoke.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "label": "DEVELOPMENT SMOKE ONLY — NOT FINAL BENCHMARK",
        "model": "qwen3:8b", "retrieval_mode": settings.retrieval_mode,
        "web": False, "chroma_documents": len(documents), "chroma_chunks": count,
        "synthetic_regression_cases": 51, "paraphrase_variants": 153,
        "live_passed": sum(row.get("passed") is True for row in rows),
        "live_total": len(rows), "cases": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
