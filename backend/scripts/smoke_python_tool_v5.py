"""Four fresh synthetic end-to-end smokes using only local qwen3:8b."""

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
from app.services.ollama import OllamaClient


READINGS = [(31, 35), (42, 39), (57, 62), (48, 52), (63, 68), (27, 25),
            (74, 79), (36, 34), (51, 56), (69, 72), (44, 41), (58, 63)]
TOPIC_A = "(baseline psi, observed psi):\n" + "\n".join(
    f"T{index}=({baseline},{observed})" for index, (baseline, observed) in enumerate(READINGS, 1)
)
CASES = {
    "A": (TOPIC_A,
          "Calculate each of the 12 observed-minus-baseline differences in psi, mean absolute difference, RMS difference, maximum absolute difference, and all tied measurement IDs.",
          "This synthetic source describes repeated pressure measurements but gives no computed differences."),
    "B": ("q=735 stb/d, pr=3370 psi, pwf=2810 psi.",
          "Calculate the synthetic well productivity index PI in stb/d/psi using the cited equation.",
          "For this synthetic well, PI = q/(pr-pwf)."),
    "C": ("Use only the numerical measurements from the cited synthetic source.",
          "Calculate the synthetic pressure gradient in psi/ft from source values and the cited equation.",
          "Synthetic values: P_top=3580 psi, P_bottom=3100 psi, depth=96 ft. gradient = (P_top - P_bottom)/depth."),
    "D": ("q=812 stb/d, pr=3490 psi, pwf=2940 psi.",
          "Find the source equation for synthetic productivity index PI and calculate PI in stb/d/psi.",
          "This initial synthetic passage mentions productivity index but omits its equation."),
}


class SyntheticResearch:
    def __init__(self, case_id: str, initial: str):
        self.case_id = case_id
        self.initial = initial
        self.calls = 0

    async def research(self, request):
        self.calls += 1
        text = ("The synthetic source equation is PI = q/(pr-pwf)."
                if self.case_id == "D" and self.calls > 1 and request.use_internal and not request.use_external
                else self.initial)
        return ResearchResponse(
            query=request.query, answer="Synthetic passage.",
            internal_sources=[InternalEvidence(evidence_id="KB1", document="v5-synthetic.pdf",
                                               page=self.calls, chunk_id=f"v5-{self.case_id}-{self.calls}",
                                               score=1.0, excerpt=text)],
            web_sources=[], figures=[], provenance=[], model=request.model, inference_used=True,
            evidence_counts=EvidenceCounts(internal=1, external=0), routing_mode="internal_only",
            retrieval_mode="legacy", timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0),
            validation={},
        )


async def run_case(case_id: str, root: Path):
    topic, goal, source = CASES[case_id]
    settings = Settings(data_dir=root / case_id / "data", agent_workspace_dir=root / case_id / "workspace")
    ollama = OllamaClient(settings)
    research = SyntheticResearch(case_id, source)
    agent = GoalResearchAgent(research, ollama,
                              analysis_factory=lambda run_id: GoalPythonAnalysis(settings, ollama, run_id))
    request = GoalResearchRequest(
        topic=topic, goal=goal,
        success_criteria=[GoalCriterion(criterion_id="C1", description=goal)],
        model="qwen3:8b", max_iterations=1, temperature=0, seed=79,
        allow_python_execution=True, python_execution_approved=True,
        engineering_validation=False, use_external=False,
    )
    response = await agent.run(f"v5-local-smoke-{case_id}", request)
    trace = response.iterations[0].python_trace
    print(json.dumps({
        "case": case_id, "status": response.status.value, "selected": trace.tool_selected,
        "plan": trace.planner_plan_status, "contract": trace.contract_status,
        "contract_id": trace.calculation_contract_id, "required_outputs": trace.required_output_ids,
        "facts": trace.selected_fact_ids, "formula": trace.selected_formula_id,
        "recovery": trace.recovery_triggered, "recovery_queries": trace.recovery_query_count,
        "facts_verified": trace.facts_verified, "formula_verified": trace.formula_verified,
        "boundary": trace.call_boundary_reached, "subprocess": trace.subprocess_reached,
        "produced_outputs": trace.produced_output_ids, "missing_outputs": trace.missing_output_ids,
        "contract_complete": trace.contract_complete, "calc": trace.computation_id,
        "adoption": trace.calc_output_adoption_count, "grounding": trace.calc_grounding_validation_passed,
        "grounding_failures": trace.calc_grounding_failures, "blocked_stage": trace.blocked_stage,
        "verification_failures": trace.verification_failures,
        "attempt_errors": [attempt.get("error") for record in response.computations for attempt in record.attempt_records if attempt.get("error")],
        "final_answer": response.final_answer[:1600],
    }, ensure_ascii=False), flush=True)


async def main():
    with TemporaryDirectory(prefix="petroleum-v5-smoke-") as directory:
        for case_id in (sys.argv[1:] or list(CASES)):
            try:
                await run_case(case_id, Path(directory))
            except Exception as exc:
                print(json.dumps({"case": case_id, "error_type": type(exc).__name__,
                                  "error": str(exc)[:500]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
