"""Two synthetic local-Ollama planning checks; never reads held-out cases or the KB."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest, PythonExecutionTrace
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_tool_planner import GoalToolPlanner
from app.services.ollama import OllamaClient
from app.services.user_fact_registry import UserFactRegistry


CASES = [
    {
        "name": "labeled_difference",
        "topic": "Layer A permeability = 73 mD\nLayer B permeability = 181 mD\nCalculate the difference and percent change.",
        "goal": "Calculate the difference and percent change in permeability using the supplied measurements.",
        "evidence": [],
    },
    {
        "name": "specialist_pi",
        "topic": "q=620 stb/d, pr=3150 psi, pwf=2710 psi. Calculate productivity index.",
        "goal": "Calculate productivity index using the supplied measurements and the cited formula.",
        "evidence": [{
            "evidence_id": "KB1", "source_type": "knowledge_base", "locator": "synthetic formula note",
            "text": "For this synthetic petroleum example, PI = q / (pr - pwf).",
        }],
    },
]


async def run() -> None:
    with tempfile.TemporaryDirectory(prefix="python-tool-v3-smoke-") as temp:
        settings = Settings(data_dir=Path(temp) / "data", agent_workspace_dir=Path(temp) / "workspace")
        ollama = OllamaClient(settings)
        planner = GoalToolPlanner(ollama)
        for index, case in enumerate(CASES, 1):
            request = GoalResearchRequest(
                topic=case["topic"], goal=case["goal"], model="qwen3:8b",
                success_criteria=[GoalCriterion(criterion_id="C1", description=case["goal"])],
                allow_python_execution=True, python_execution_approved=True,
            )
            registry = UserFactRegistry.from_topic(request.topic)
            evidence = [*case["evidence"], *registry.evidence()]
            decision = await planner.decide(request, request.success_criteria, evidence, None)
            trace = PythonExecutionTrace(
                tool_selected=decision.tool_needed, tool_type=decision.tool_type,
                plan_present=decision.plan is not None or decision.plan_parsed,
                planner_decision_attempts=decision.decision_attempts,
                planner_decision_status=decision.decision_status,
                planner_plan_attempts=decision.plan_attempts,
                planner_plan_status=decision.plan_status,
                available_user_fact_ids=[item.fact_id for item in registry.records],
                selected_user_fact_ids=decision.selected_user_fact_ids,
                verification_failures=decision.verification_failures,
            )
            record = None
            if decision.plan:
                analysis = GoalPythonAnalysis(settings, ollama, f"agentic-v3-local-smoke-{index}")
                record, _ = await analysis.execute(request, decision.plan, evidence, trace)
            print(json.dumps({
                "case": case["name"], "tool_selected": trace.tool_selected,
                "decision_attempts": trace.planner_decision_attempts,
                "decision_status": trace.planner_decision_status,
                "plan_attempts": trace.planner_plan_attempts,
                "plan_status": trace.planner_plan_status,
                "user_facts": trace.available_user_fact_ids,
                "selected_facts": trace.selected_user_fact_ids,
                "facts_verified": trace.facts_verified,
                "verification_failures": trace.verification_failures,
                "call_boundary": trace.call_boundary_reached,
                "subprocess": trace.subprocess_reached,
                "calc_valid": bool(record and record.validation_passed),
                "blocked_stage": trace.blocked_stage,
            }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(run())
