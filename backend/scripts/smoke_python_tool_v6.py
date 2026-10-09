"""Seven fresh local-qwen development smokes; never loads frozen evaluations."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.config import Settings
from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest
from app.models.research_schemas import EvidenceCounts, InternalEvidence, ResearchResponse, ResearchTiming
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_research_agent import GoalResearchAgent
from app.services.final_response_guard import leaked_text
from app.services.ollama import OllamaClient


CASES = {
    "S1": (
        "case_A_x=4 m, case_A_y=7 m; case_B_x=6 m, case_B_y=9 m; case_C_x=8 m, case_C_y=5 m.",
        "Using the cited z equation, calculate z for each of the three cases.",
        ["The synthetic relation is z = x + y."],
    ),
    "S2": (
        "(baseline psi, observed psi):\nM1=(26,31)\nM2=(38,35)\nM3=(47,52)\nM4=(59,63)\nM5=(71,68)\nM6=(82,88)",
        "Calculate each observed-minus-baseline difference, mean absolute difference, RMS difference and maximum absolute difference.",
        ["These are synthetic paired pressure readings."],
    ),
    "S3": (
        "Use the numerical measurements in the cited synthetic passage to calculate z.",
        "Using the cited equation, calculate z in m from the source measurements.",
        ["Synthetic measurements: x is 7 m.\ny is 9 m.\nz = x + y."],
    ),
    "S4": (
        "x=12 m, y=5 m.",
        "Find the cited equation for z and calculate z in m.",
        ["The first synthetic passage discusses z but has no equation.", "The synthetic source equation is z = x + y."],
    ),
    "S5": (
        "x=14 m. Calculate z using the cited relation and the missing source measurement.",
        "Calculate z from the cited equation and source measurement in m.",
        ["The synthetic relation is z = x + y.", "The missing synthetic measurement y is 6 m."],
    ),
    "N1": (
        "x=19 m. Calculate z from the cited source relation.",
        "Calculate z in m from the cited equation; do not assume an unreported input.",
        ["The synthetic relation is z = x + y."],
    ),
    "N2": (
        "rate=7 m, flow_rate=8 m, x=2 m.",
        "Calculate z in m from the cited relation using the supplied flow-rate measurements.",
        ["The synthetic relation is z = q + x."],
    ),
}


class SyntheticResearch:
    def __init__(self, passages: list[str]):
        self.passages = passages
        self.calls = 0

    async def research(self, request):
        index = min(self.calls, len(self.passages) - 1)
        self.calls += 1
        return ResearchResponse(
            query=request.query, answer="Synthetic source passage",
            internal_sources=[InternalEvidence(evidence_id="KB1", document="v6-development.pdf",
                page=self.calls, chunk_id=f"development-{self.calls}", score=1.0,
                excerpt=self.passages[index])],
            web_sources=[], figures=[], provenance=[], model=request.model, inference_used=True,
            evidence_counts=EvidenceCounts(internal=1, external=0), routing_mode="internal_only",
            retrieval_mode="legacy", timing=ResearchTiming(retrieval_seconds=0,
                reasoning_seconds=0, elapsed_seconds=0), validation={},
        )


async def run_case(case_id: str, root: Path) -> dict:
    topic, goal, passages = CASES[case_id]
    settings = Settings(data_dir=root / case_id / "data", agent_workspace_dir=root / case_id / "workspace")
    ollama = OllamaClient(settings)
    research = SyntheticResearch(passages)
    agent = GoalResearchAgent(research, ollama,
        analysis_factory=lambda run_id: GoalPythonAnalysis(settings, ollama, run_id))
    request = GoalResearchRequest(topic=topic, goal=goal,
        success_criteria=[GoalCriterion(criterion_id="C1", description=goal)],
        model="qwen3:8b", max_iterations=1, temperature=0, seed=83,
        allow_python_execution=True, python_execution_approved=True,
        engineering_validation=False, use_external=False)
    response = await agent.run(f"v6-development-{case_id}", request)
    trace = response.iterations[0].python_trace
    report = {
        "case": case_id, "tool_selected": trace.tool_selected, "plan": trace.planner_plan_status,
        "requirement_graph": {"formula_id": (trace.requirement_graph or {}).get("formula_id"),
            "required_variables": trace.required_variable_count, "bound_variables": trace.bound_variable_count,
            "bindings": (trace.requirement_graph or {}).get("scenario_bindings"),
            "missing": trace.missing_variables, "ambiguous": trace.ambiguous_variables},
        "missing_before_recovery":
            trace.recovery_rounds[0]["missing_before"] if trace.recovery_rounds else trace.missing_variables,
        "recovery_rounds": trace.recovery_rounds, "binding_status":
            [item["status"] for item in (trace.requirement_graph or {}).get("formula_variables", [])],
        "source_complete": trace.source_complete, "contract": {
            "id": (trace.calculation_contract or {}).get("contract_id"),
            "scenarios": [item["scenario_id"] for item in (trace.calculation_contract or {}).get("scenarios", [])],
            "outputs": [item["name"] for item in (trace.calculation_contract or {}).get("required_outputs", [])]},
        "required_outputs": trace.required_output_checklist, "subprocess": trace.subprocess_reached,
        "validated_calc": any(item.validation_passed for item in response.computations),
        "grounding": trace.calc_grounding_validation_passed, "grounding_failures": trace.calc_grounding_failures,
        "assumption_guard": trace.assumption_guard_passed, "assumption_failures": trace.assumption_guard_failures,
        "instruction_leakage_detected": trace.final_response_leakage_detected,
        "instruction_leakage_stripped": trace.final_response_leakage_stripped,
        "final_instruction_leakage": leaked_text(response.final_answer),
        "blocked_stage": trace.blocked_stage, "research_calls": research.calls,
        "attempt_errors": [attempt.get("error") for item in response.computations
                           for attempt in item.attempt_records if attempt.get("error")],
        "final_answer": response.final_answer[:800],
    }
    print(json.dumps(report, ensure_ascii=True), flush=True)
    return report


async def main() -> None:
    with TemporaryDirectory(prefix="petroleum-v6-development-") as directory:
        reports = []
        for case_id in (sys.argv[1:] or list(CASES)):
            try:
                reports.append(await run_case(case_id, Path(directory)))
            except Exception as exc:
                failure = {"case": case_id, "error_type": type(exc).__name__, "error": str(exc)[:500]}
                reports.append(failure)
                print(json.dumps(failure, ensure_ascii=True), flush=True)
        positives = [item for item in reports if item["case"].startswith("S")]
        negatives = [item for item in reports if item["case"].startswith("N")]
        print(json.dumps({"summary": {
            "positive_source_complete": sum(item.get("source_complete", False) for item in positives),
            "positive_subprocess": sum(item.get("subprocess", False) for item in positives),
            "positive_validated_calc": sum(item.get("validated_calc", False) for item in positives),
            "positive_grounding": sum(item.get("grounding", False) is True for item in positives),
            "recovery_to_calc": sum(bool(item.get("recovery_rounds")) and item.get("validated_calc", False)
                                    and any(round_["required_gain"] for round_ in item["recovery_rounds"])
                                    for item in positives),
            "negative_subprocess": sum(item.get("subprocess", False) for item in negatives),
            "final_instruction_leakage": sum(item.get("final_instruction_leakage", False) for item in reports),
            "case_errors": [item["case"] for item in reports if "error_type" in item],
        }}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
