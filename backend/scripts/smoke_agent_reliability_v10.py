"""Local development smoke only; synthetic prompts, never frozen evaluation tasks."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.research_routes import cached_research_agent
from app.core.config import get_settings
from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest, GoalRunStatus
from app.services.formula_source_registry import FormulaSourceRegistry, source_contains_equation
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.ollama import OllamaClient
from app.services.user_fact_registry import UserFactRegistry


CASES = {
    "direct": ("P=14 stb/d, Q=26 stb/d, R=20 stb/d. 평균과 내림차순 순위를 계산해줘.",
               "Calculate the mean and rank the three supplied rates"),
    "ratio": ("A=12, B=3. A를 B로 나눈 비율을 계산해줘.",
              "Calculate the explicitly ordered ratio of the supplied values"),
    "user_formula": ("u=4, v=9. index = u * v + 2. 이 식으로 index를 계산해줘.",
                     "Calculate index with the user-provided equation"),
    "user_sweep": ("Vary alpha from 0.2 to 0.6 in steps of 0.1. score = alpha * 4 + 3. "
                   "Simulate the sweep and find the best score.",
                   "Report the sweep cases and best result"),
    "kb_formula": ("SG=0.943인 원유야. 내부 문서의 비중–API gravity 관계식을 찾아 API도를 계산해줘.",
                   "Cite the actual KB equation span and calculate API gravity"),
    "literature": ("내부 자료를 근거로 상대투과도와 유체 포화도의 관계를 설명해줘.",
                   "Explain the source-supported relationship with a citation"),
    "premise": ("공극률이 작아지면 같은 벌크 부피에서 공극 부피가 늘어난다는 거 맞지?",
                "Check and, if necessary, correct the premise with a citation"),
    "unsupported": ("x=3. 내부 문서에서 임의의 Theta-Omega coupling law를 찾아 Omega를 계산해줘.",
                    "Do not calculate without an actual sourced relation"),
    "resume": ("x=5. value = x * y. 이 식으로 value를 계산해줘.",
               "Ask for missing y, then calculate from the same run"),
}


def summarize(case: str, result, elapsed: float) -> dict:
    actions = [row["action_type"] for row in result.action_history]
    validated = [row for row in result.computations if row.validation_passed]
    evidence = [{"evidence_id": row.evidence_id, "source_type": "knowledge_base",
                 "text": row.excerpt} for row in result.internal_sources]
    formula_span_correct = None
    if case == "kb_formula":
        records = FormulaSourceRegistry.from_evidence(evidence).records
        formula_span_correct = any(
            any(record.source_id == source_id and source_contains_equation(
                record, next(row["text"] for row in evidence if row["evidence_id"] == source_id),
                calc.source_formula or calc.formula)
                for record in records)
            for calc in validated for source_id in calc.formula_source_ids if source_id.startswith("KB"))
    full_evidence = evidence + UserFactRegistry.from_topic(result.topic).evidence()
    known = {str(row["evidence_id"]) for row in full_evidence}
    for calc in validated:
        for fact in calc.input_facts:
            source_id = str(fact.get("evidence_id") or "")
            if source_id and source_id not in known:
                full_evidence.append({"evidence_id": source_id, "source_type": "user_fact",
                                      "text": f"{fact.get('name')}={fact.get('value')} {fact.get('unit') or ''}"})
                known.add(source_id)
        for source_id in calc.formula_source_ids:
            if source_id.startswith("USERF"):
                if source_id not in known:
                    full_evidence.append({"evidence_id": source_id, "source_type": "user_fact",
                                          "text": calc.source_formula})
                    known.add(source_id)
                else:
                    source = next(row for row in full_evidence if row["evidence_id"] == source_id)
                    if calc.source_formula and calc.source_formula not in source["text"]:
                        source["text"] += "\n" + calc.source_formula
    provenance = [GoalExecutionAgent._provenance_complete(
        calc, full_evidence, result.topic + "\n" + (result.goal or "")) for calc in validated]
    row = {
        "case": case, "status": result.status.value, "run_status": result.run_status.value,
        "run_id": result.run_id, "actions": actions, "python_calls": result.python_calls_total,
        "action_history": result.action_history,
        "validated_calcs": len(validated), "formula_source_correct": formula_span_correct,
        "provenance_complete": all(provenance) if provenance else None,
        "premise_verdict": result.telemetry.get("premise_verdict"),
        "repeated_or_no_progress_actions": sum(row["reason_code"] in {
            "repeated_action_fingerprint", "retrieve_no_progress"} for row in result.action_history),
        "answer_nonempty": bool(result.final_answer.strip()),
        "answer": result.final_answer, "seconds": round(elapsed, 3),
        "evidence_count": len(result.internal_sources),
        "sources": [{"id": row.evidence_id, "document": row.document, "page": row.page,
                     "excerpt_prefix": row.excerpt[:300]} for row in result.internal_sources],
        "stop_reason": result.stop_reason.value if result.stop_reason else None,
        "validation": result.validation,
        "telemetry": result.telemetry,
    }
    expected_prefix = {
        "direct": ["calculate"], "ratio": ["calculate"],
        "user_formula": ["calculate"], "user_sweep": ["simulate", "analyze"],
        "kb_formula": ["retrieve", "calculate"], "literature": ["retrieve", "verify"],
        "premise": ["retrieve", "verify"], "unsupported": ["retrieve"],
        "resume": ["calculate"],
    }[case]
    row["action_selection_passed"] = actions[:len(expected_prefix)] == expected_prefix
    if case == "unsupported":
        row["passed"] = (result.status.value == "stopped" and not validated
                         and result.python_calls_total == 0 and row["answer_nonempty"])
    else:
        row["passed"] = result.status.value == "achieved" and row["answer_nonempty"]
    if case == "kb_formula":
        row["passed"] = row["passed"] and formula_span_correct is True and row["provenance_complete"] is True
    if case == "premise":
        row["passed"] = row["passed"] and row["premise_verdict"] == "contradicts" and \
            result.validation.get("citation_semantic_passed") is True
    row["passed"] = row["passed"] and row["action_selection_passed"]
    return row


def request(case: str) -> GoalResearchRequest:
    topic, criterion = CASES[case]
    return GoalResearchRequest(
        topic=topic, goal=topic,
        success_criteria=[] if case == "premise" else
        [GoalCriterion(criterion_id="C1", description=criterion)],
        execution_mode="autonomous_goal_execution", model="qwen3:8b", temperature=0, seed=42,
        use_internal=True, use_external=False, internal_top_k=8,
        max_iterations=7, max_retrieval_actions=2, max_python_calls=2,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*")
    args = parser.parse_args()
    if set(args.cases) - set(CASES):
        parser.error("unknown development case")
    settings = get_settings()
    if settings.retrieval_mode != "hybrid":
        raise RuntimeError("Development smoke requires hybrid retrieval")
    if not (settings.vector_db_dir / "chroma.sqlite3").is_file():
        raise RuntimeError("Existing Chroma DB is not connected")
    research = cached_research_agent()
    count = research.vector_store.count()
    if count != 18976:
        raise RuntimeError(f"Unexpected read-only Chroma count: {count}")
    agent = GoalExecutionAgent(research, OllamaClient(settings))
    reports = []
    for case in args.cases or CASES:
        req = request(case)
        started = time.perf_counter()
        try:
            result = await agent.run(f"DEV-V10-{case}", req)
            waiting = result.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT
            original_run_id = result.run_id
            if case == "resume" and result.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT:
                checkpoint = dict(result.resume_checkpoint)
                checkpoint["user_replies"] = ["y=4"]
                result = await agent.run(result.run_id, req, resume_state=checkpoint, resume_result=result)
            row = summarize(case, result, time.perf_counter() - started)
            if case == "resume":
                row["waited_for_input"] = waiting
                row["same_run_resumed"] = waiting and result.run_id == original_run_id
                row["passed"] = row["passed"] and row["same_run_resumed"]
        except Exception as exc:
            row = {"case": case, "error": type(exc).__name__, "seconds": round(time.perf_counter() - started, 3)}
        reports.append(row)
        print(json.dumps({key: value for key, value in row.items()
                          if key not in {"answer", "action_history", "sources", "telemetry"}},
                         ensure_ascii=True), flush=True)
    totals = {
        "label": "DEVELOPMENT SMOKE, NOT FINAL BENCHMARK",
        "model": "qwen3:8b", "retrieval_mode": settings.retrieval_mode,
        "chroma_chunks": count, "cases": len(reports),
        "achieved": sum(row.get("status") == "achieved" for row in reports),
        "passed": sum(row.get("passed") is True for row in reports),
        "validated_calcs": sum(row.get("validated_calcs", 0) for row in reports),
        "no_progress_actions": sum(row.get("repeated_or_no_progress_actions", 0) for row in reports),
    }
    by_case = {row["case"]: row for row in reports}
    validated_count = sum(row.get("validated_calcs", 0) for row in reports)
    totals["development_metrics"] = {
        "direct_calculation_execution": by_case.get("direct", {}).get("passed"),
        "ordered_ratio_execution": by_case.get("ratio", {}).get("passed"),
        "user_formula_execution": by_case.get("user_formula", {}).get("passed"),
        "user_formula_sweep_execution": by_case.get("user_sweep", {}).get("passed"),
        "kb_formula_retrieval": "retrieve" in by_case.get("kb_formula", {}).get("actions", []),
        "exact_formula_span_retrieval": by_case.get("kb_formula", {}).get("formula_source_correct"),
        "formula_to_calculate_transition": by_case.get("kb_formula", {}).get("actions", [])[:2]
        == ["retrieve", "calculate"],
        "calculation_provenance_complete": sum(row.get("validated_calcs", 0)
                                                for row in reports if row.get("provenance_complete") is True),
        "calculation_provenance_denominator": validated_count,
        "false_premise_correction": by_case.get("premise", {}).get("passed"),
        "same_run_resume": by_case.get("resume", {}).get("same_run_resumed"),
        "nonempty_supported_final": sum(row.get("status") == "achieved" and row.get("answer_nonempty")
                                         and row.get("validation", {}).get("citation_semantic_passed") is True
                                         for row in reports),
        "repeated_or_no_progress_actions": totals["no_progress_actions"],
    }
    def rate(numerator: int, denominator: int) -> dict:
        return {"numerator": numerator, "denominator": denominator,
                "percent": round(100 * numerator / denominator, 2) if denominator else None}

    execution_cases = [by_case.get(name, {}) for name in
                       ("direct", "ratio", "user_formula", "user_sweep", "kb_formula", "resume")
                       if name in by_case]
    total_actions = sum(len(row.get("actions", [])) for row in reports)
    totals["development_rates"] = {
        "formula_source_correctness": rate(int(by_case.get("kb_formula", {}).get("formula_source_correct") is True),
                                           int("kb_formula" in by_case)),
        "calculation_provenance_completeness": rate(
            totals["development_metrics"]["calculation_provenance_complete"], validated_count),
        "false_premise_handling": rate(int(by_case.get("premise", {}).get("passed") is True),
                                       int("premise" in by_case)),
        "python_simulation_execution_success": rate(
            sum(row.get("validated_calcs", 0) > 0 for row in execution_cases), len(execution_cases)),
        "correct_action_selection": rate(sum(row.get("action_selection_passed") is True for row in reports),
                                         len(reports)),
        "repeated_no_progress_action_rate": rate(totals["no_progress_actions"], total_actions),
        "same_run_resume_success": rate(int(by_case.get("resume", {}).get("same_run_resumed") is True),
                                        int("resume" in by_case)),
    }
    output = Path(__file__).resolve().parents[2] / "evaluation" / "review" / "agent_reliability_v10_dev_smoke.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"summary": totals, "cases": reports}, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    report = output.with_suffix(".md")
    lines = ["# Agent reliability v10 — development smoke", "",
             "Development regression only. This is not an unseen final benchmark or a v1/v2 rerun.", "",
             f"Local model: qwen3:8b · Retrieval: {settings.retrieval_mode} · "
             f"Existing Chroma chunks: {count:,}", "",
             "| Case | Pass | Status | Actions | Validated CALC | Seconds |",
             "| --- | --- | --- | --- | ---: | ---: |"]
    for row in reports:
        lines.append(f"| {row['case']} | {'PASS' if row.get('passed') else 'FAIL'} | "
                     f"{row.get('status', 'error')} | {' → '.join(row.get('actions', []))} | "
                     f"{row.get('validated_calcs', 0)} | {row['seconds']} |")
    lines += ["", "## Development metrics", ""]
    for key, value in totals["development_metrics"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## Development rates (small synthetic denominators)", ""]
    for key, value in totals["development_rates"].items():
        lines.append(f"- {key}: {value['numerator']}/{value['denominator']} "
                     f"({value['percent']}%)")
    lines += ["", "## Limits", "",
              "Synthetic/local development cases only; no claim of final benchmark performance.",
              "The KB-formula and premise checks each cover one live example, not every engineering domain.",
              "Unsupported formula is a safe stop, not an achieved calculation.",
              "No Chroma reindexing, PDF re-extraction, OpenAI/Gemini call, or frozen evaluation rerun was performed.", ""]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
