"""Three new synthetic, local-qwen development smokes (no held-out fixtures)."""

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


CASES = [
    (
        "A", "Core A porosity=14 %, Core B porosity=21 %",
        "Calculate the absolute difference and percentage change in porosity from Core A to Core B.",
        "The synthetic source discusses porosity measurements but reports no derived comparison.",
    ),
    (
        "B", "A=83 acres, h=26 ft, phi=0.22",
        "Calculate pore volume PV in barrels using the cited source equation and the supplied inputs.",
        "For this synthetic reservoir relation, PV = 7758 * A * h * phi.",
    ),
    (
        "C", "Calculate the pressure gradient from the measurements in the source.",
        "Calculate the pressure gradient from the three source measurements using the cited equation.",
        "P_top=3460 psi, P_bottom=3020 psi, depth=80 ft. gradient = (P_top - P_bottom)/depth.",
    ),
]


class SyntheticResearch:
    def __init__(self, text: str):
        self.text = text

    async def research(self, request):
        return ResearchResponse(
            query=request.query, answer="Synthetic source passage.",
            internal_sources=[InternalEvidence(
                evidence_id="KB1", document="v4-new-synthetic.pdf", page=4,
                chunk_id="v4-local-4", score=1.0, excerpt=self.text,
            )], web_sources=[], figures=[], provenance=[], model=request.model,
            inference_used=True, evidence_counts=EvidenceCounts(internal=1, external=0),
            routing_mode="internal_only", retrieval_mode="legacy",
            timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0),
            validation={},
        )


async def main() -> None:
    with TemporaryDirectory(prefix="petroleum-v4-smoke-") as directory:
        root = Path(directory)
        settings = Settings(data_dir=root / "data", agent_workspace_dir=root / "workspace")
        ollama = OllamaClient(settings)
        for case_id, topic, goal, source in CASES:
            if len(sys.argv) > 1 and case_id != sys.argv[1]:
                continue
            agent = GoalResearchAgent(
                SyntheticResearch(source), ollama,
                analysis_factory=lambda run_id: GoalPythonAnalysis(settings, ollama, run_id),
            )
            request = GoalResearchRequest(
                topic=topic, goal=goal, success_criteria=[GoalCriterion(
                    criterion_id="C1", description=goal,
                )], model="qwen3:8b", max_iterations=1, temperature=0, seed=42,
                allow_python_execution=True, python_execution_approved=True,
                engineering_validation=False,
            )
            try:
                result = await agent.run(f"v4-local-smoke-{case_id}", request)
                trace = result.iterations[0].python_trace if result.iterations else None
                print(json.dumps({
                    "case": case_id, "status": result.status.value,
                    "decision_status": trace.planner_decision_status if trace else None,
                    "selected": trace.tool_selected if trace else False,
                    "plan_status": trace.planner_plan_status if trace else None,
                    "plan_attempts": trace.planner_plan_attempts if trace else 0,
                    "selected_fact_ids": trace.selected_fact_ids if trace else [],
                    "selected_formula_id": trace.selected_formula_id if trace else None,
                    "facts_verified": trace.facts_verified if trace else False,
                    "formula_verified": trace.formula_verified if trace else False,
                    "boundary": trace.call_boundary_reached if trace else False,
                    "code_generated": trace.code_generated if trace else False,
                    "sandbox": trace.sandbox_validation_passed if trace else False,
                    "subprocess": trace.subprocess_reached if trace else False,
                    "validated": trace.result_validation_passed if trace else False,
                    "calc": trace.computation_id if trace else None,
                    "failure": trace.verification_failures if trace else [],
                    "blocked_stage": trace.blocked_stage if trace else None,
                    "plan_summary": trace.plan_summary if trace else None,
                    "attempt_errors": [item.get("error") for record in result.computations for item in record.attempt_records if item.get("error")],
                    "attempt_codes": [item.get("code", "")[:1200] for record in result.computations for item in record.attempt_records if item.get("error")],
                    "final_answer": result.final_answer[:1000],
                }, ensure_ascii=False), flush=True)
            except Exception as exc:
                print(json.dumps({"case": case_id, "error_type": type(exc).__name__, "error": str(exc)[:300]}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
