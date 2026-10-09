"""Fresh local-qwen v8 development demos; never reads frozen held-out prompts."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.research_routes import cached_research_agent
from app.core.config import get_settings
from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.ollama import OllamaClient


class NoResearch:
    async def research(self, _request):
        raise RuntimeError("Unexpected retrieval in a complete user-input demo")


def criterion(*descriptions: str) -> list[GoalCriterion]:
    return [GoalCriterion(criterion_id=f"C{index}", description=description)
            for index, description in enumerate(descriptions, 1)]


COMMON = dict(execution_mode="autonomous_goal_execution", model="qwen3:8b",
              temperature=0, seed=42, use_internal=True, use_external=False)


CASES = {
    "A": dict(topic="Crude oil API gravity and oil heaviness",
              goal="Using the Heriot-Watt Reservoir Fluids Composition passage, explain the API gravity reference value for water and contrast light versus heavy crude oil.",
              success_criteria=criterion("State the source-supported API gravity reference for water",
                                         "Compare the source-supported API gravity of light and heavy crude with citations"),
              max_iterations=5, internal_top_k=6),
    "B": dict(topic="A_rate=187 stb/d, B_rate=234 stb/d, C_rate=163 stb/d.",
              goal="Calculate the mean rate, descending rank and top case.",
              success_criteria=criterion("Calculate the mean rate in stb/d",
                                         "Rank A, B, C descending and identify top case"),
              allow_python_execution=True, python_execution_approved=True, max_iterations=5),
    "C": dict(topic="SG=0.918.",
              goal="Retrieve the Heriot-Watt reservoir fluids specific gravity to API gravity equation and calculate API gravity in dimensionless for this sample using the cited equation.",
              success_criteria=criterion("Cite the KB equation converting specific gravity to API gravity",
                                         "Calculate API gravity from SG=0.918 in dimensionless using Python and cite the source"),
              allow_python_execution=True, python_execution_approved=True,
              max_iterations=6, internal_top_k=8),
    "D": dict(topic="SG=0.806.",
              goal="The conversion relation is missing from my input. Retrieve the Heriot-Watt reservoir fluids specific gravity to API gravity equation, then calculate API gravity in dimensionless using the cited equation.",
              success_criteria=criterion("Find the missing source-backed conversion equation",
                                         "Calculate API gravity from SG=0.806 in dimensionless using Python and cite the source"),
              allow_python_execution=True, python_execution_approved=True,
              max_iterations=6, internal_top_k=8),
    "E": dict(topic="Sweep porosity from 0.10 to 0.30 in steps of 0.02; model score = porosity * 50 + 10",
              goal="Simulate the parameter sweep, report all cases, identify the best score and mean.",
              success_criteria=criterion("Report all simulated cases",
                                         "Identify the best case and mean score"),
              allow_python_execution=True, python_execution_approved=True, max_iterations=6),
    "F": dict(topic="Sweep temperature from 15 to 35 in steps of 2; model response = temperature * 1.7 - 4",
              goal="Simulate all cases, then analyze the validated case outputs to report the best case and sensitivity range.",
              success_criteria=criterion("Report all simulated cases and best case",
                                         "Use the validated case outputs to report the response range"),
              allow_python_execution=True, python_execution_approved=True, max_iterations=6),
    "G": dict(topic="Xq=31 psi.",
              goal="Find a cited petroleum engineering equation for the fictional Kappa-Zeta coupling coefficient, then calculate Zeta in psi. Do not infer an equation if no source gives one.",
              success_criteria=criterion("Identify a source-backed Kappa-Zeta equation",
                                         "Calculate Zeta using that verified equation and Xq"),
              allow_python_execution=True, python_execution_approved=True,
              max_iterations=5, max_retrieval_actions=1, internal_top_k=5),
}


def check(case: str, result) -> tuple[bool, list[str]]:
    actions = [item["action_type"] for item in result.action_history]
    valid = [item for item in result.computations if item.validation_passed]
    problems = []
    if case == "G":
        if result.status.value == "achieved":
            problems.append("impossible goal was marked achieved")
        if result.stop_reason.value not in {"insufficient_evidence", "no_progress", "calculation_blocked"}:
            problems.append("missing safe stop reason")
        if valid or result.python_calls_total:
            problems.append("unsupported calculation ran")
        if not result.final_answer.strip():
            problems.append("safe limitation missing")
    else:
        if result.status.value != "achieved":
            problems.append("goal not achieved")
        if not result.validation.get("engineering_validation_passed"):
            problems.append("engineering validation failed")
        if result.validation.get("unsupported_engineering_claim_count", 0):
            problems.append("unsupported claim")
        if "verify" not in actions or "synthesize" not in actions:
            problems.append("verification or synthesis missing")
    if case == "A" and ("retrieve" not in actions or result.python_calls_total):
        problems.append("research-only path was not used")
    if case == "B" and (actions[:1] != ["calculate"] or "retrieve" in actions or not valid or not result.python_calls_total):
        problems.append("direct Python path failed")
    if case in {"C", "D"}:
        if "retrieve" not in actions or "calculate" not in actions or actions.index("retrieve") >= actions.index("calculate"):
            problems.append("retrieve-to-calculate switch missing")
        if not valid or not result.python_calls_total:
            problems.append("validated Python calculation missing")
        if not any(source.document == "Heriot-Watt University - Reservoir Engineering.pdf" and
                   source.page == 90 for source in result.internal_sources):
            problems.append("real KB formula page missing")
    if case in {"E", "F"}:
        if actions[:2] != ["simulate", "analyze"] or "retrieve" in actions:
            problems.append("simulation-analysis path failed")
        if not valid or sum(key.startswith("OUT_CASE_") for key in valid[0].output_manifest) < 10:
            problems.append("bounded multi-case output missing")
        if case == "F" and not any(item["action_type"] == "analyze" and
                                   item["details"].get("case_range") is not None and
                                   item["details"].get("derived_fact_ids_used")
                                   for item in result.action_history):
            problems.append("validated derived outputs were not reused")
    return not problems, problems


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--auto-python", action="store_true",
                        help="Omit client Python flags to exercise autonomous authorization")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[2] /
                        "evaluation" / "review" / "goal_execution_v8_development_smoke.json")
    args = parser.parse_args()
    if set(args.cases) - set(CASES):
        parser.error("unknown development demo")
    settings = get_settings()
    if not (settings.vector_db_dir / "chroma.sqlite3").is_file():
        raise RuntimeError("An existing Chroma DB must be connected; this smoke never creates one")
    if os.getenv("RETRIEVAL_MODE") not in {"legacy", "hybrid", "hybrid_rerank"}:
        raise RuntimeError("Set RETRIEVAL_MODE explicitly before running the smoke")
    ollama = OllamaClient(settings)
    reports = []
    for case in args.cases or list(CASES):
        case_input = dict(CASES[case])
        if args.auto_python:
            case_input.pop("allow_python_execution", None)
            case_input.pop("python_execution_approved", None)
        request = GoalResearchRequest(**COMMON, **case_input)
        research = NoResearch() if case in {"B", "E", "F"} else cached_research_agent()
        started = time.perf_counter()
        try:
            result = await GoalExecutionAgent(research, ollama).run(f"GR-V8-SMOKE-{case}", request)
            passed, problems = check(case, result)
            report = {
                "case": case, "passed": passed, "problems": problems,
                "execution_mode": request.execution_mode,
                "python_flags_supplied_by_client": not args.auto_python and "allow_python_execution" in case_input,
                "status": result.status.value, "stop_reason": result.stop_reason.value,
                "goal_coverage": result.goal_coverage, "elapsed_seconds": round(time.perf_counter() - started, 3),
                "actions": result.action_history, "state_history": result.state_history,
                "first_action": result.action_history[0]["action_type"] if result.action_history else None,
                "action_sequence": [item["action_type"] for item in result.action_history],
                "subprocess_reached": any(item.get("details", {}).get("subprocess_reached")
                                          for item in result.action_history),
                "python_calls": result.python_calls_total,
                "validated_calcs": sum(item.validation_passed for item in result.computations),
                "computations": [{"id": item.computation_id, "valid": item.validation_passed,
                                  "formula": item.formula, "manifest": item.output_manifest,
                                  "outputs": item.output_files, "sources": item.source_evidence_ids,
                                  "inputs": item.source_input_ids} for item in result.computations],
                "kb_sources": [{"id": item.evidence_id, "document": item.document, "page": item.page}
                               for item in result.internal_sources],
                "validation": result.validation, "answer": result.final_answer,
                "python_authorization_source": result.telemetry.get("python_authorization_source"),
                "unsupported_claims": result.validation.get("unsupported_engineering_claim_count", 0),
            }
        except Exception as exc:
            report = {"case": case, "passed": False, "problems": [type(exc).__name__],
                      "elapsed_seconds": round(time.perf_counter() - started, 3)}
        reports.append(report)
        summary = {"passed": sum(row["passed"] for row in reports), "total": len(reports),
                   "mandatory_passed": all(row["passed"] for row in reports if row["case"] in "BCDE"),
                   "retrieval_mode": os.getenv("RETRIEVAL_MODE"), "model": "qwen3:8b",
                   "openai_api_used": False, "gemini_api_used": False}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"cases": reports, "summary": summary},
                                         ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"case": case, "passed": report["passed"],
                          "status": report.get("status"), "problems": report["problems"],
                          "seconds": report["elapsed_seconds"]}, ensure_ascii=False), flush=True)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
