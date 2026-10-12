"""Run fresh in-memory v19 development smoke cases (never a final benchmark)."""

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_agent_reliability_v19_dev import (  # noqa: E402
    PassingEvaluator, SyntheticResearch, actions, execute, request, result_value,
)
from app.core.config import Settings  # noqa: E402
from app.models.goal_research_schemas import GoalRunStatus, GoalStatus  # noqa: E402
from app.services.goal_execution_agent import GoalExecutionAgent  # noqa: E402


def record(case_id, result, passed):
    return {"id": case_id, "passed": bool(passed), "run_id": result.run_id,
            "status": result.status.value, "actions": actions(result),
            "calculation_executed": result.python_calls_total > 0,
            "calculation_validated": any(c.validation_passed for c in result.computations),
            "formula_recovery_attempt_count": result.telemetry.get("formula_recovery_attempt_count", 0),
            "formula_recovery_success": result.telemetry.get("formula_recovery_success", False),
            "formula_local_expansion_success": result.telemetry.get("formula_local_expansion_success", False),
            "forced_calculate_transition": result.telemetry.get("forced_calculate_transition", False),
            "pre_stop_guard_checked": result.telemetry.get("pre_stop_guard_checked", False),
            "pre_stop_guard_prevented_refusal": result.telemetry.get("pre_stop_guard_prevented_refusal", False),
            "partial_grounded_answer_used": result.telemetry.get("partial_grounded_answer_used", False),
            "resume_readiness_recomputed": result.telemetry.get("resume_readiness_recomputed", False),
            "resume_block_cleared": result.telemetry.get("resume_block_cleared", False),
            "clarification_suppressed_existing_input": result.telemetry.get(
                "clarification_suppressed_existing_input", False)}


def main():
    cases = []
    with TemporaryDirectory(prefix="v19-development-") as temporary:
        root = Path(temporary)
        with MonkeyPatch.context() as patch:
            kb_cases = [
                ("KB-A", "Mass=5 kg; Speed=4 m/s. Find the internal Momentum equation and calculate Momentum.",
                 [[(21, "Momentum equation: Momentum=Mass*Speed. Mass (kg); Speed (m/s).")]], [], 20),
                ("KB-B", "Rise=10 m; Offset=2 m. Find the internal Span relation and calculate Span.",
                 [[(22, "Span is defined on the neighboring page of this guide.")]],
                 [(23, "Span relation: Span=Rise+Offset. Rise (m); Offset (m).")], 12),
                ("KB-C", "Pressure=8 psi; Area=3 ft2. Find the internal Thrust equation and calculate Thrust.",
                 [[(23, "Thrust depends on pressure and area; equation on the next section.")],
                  [(24, "Thrust equation: Thrust=Pressure*Area. Pressure (psi); Area (ft2).")]], [], 24),
            ]
            for case_id, text, pages, neighbors, expected in kb_cases:
                result, _, _ = execute(root / case_id, patch, text, pages, neighbors=neighbors)
                passed = (result.status == GoalStatus.ACHIEVED and result.computations and
                          result.computations[0].validation_passed and result_value(result) == expected)
                cases.append(record(case_id, result, passed))

            direct_cases = [
                ("DIRECT-A", "Readings 4, 10, 16 kg. Calculate their mean.", 10),
                ("DIRECT-B", "Estimate=Base*Multiplier. Base=6 kg; Multiplier=2 dimensionless. Calculate Estimate.", 12),
            ]
            for case_id, text, expected in direct_cases:
                result, research, _ = execute(root / case_id, patch, text)
                passed = (research.calls == 0 and result.status == GoalStatus.ACHIEVED and
                          result.computations and result.computations[0].validation_passed and
                          result_value(result) == expected)
                cases.append(record(case_id, result, passed))

            qa_cases = [
                ("QA-A", "Explain how a desander separates solids from a flowing stream.",
                 "A desander separates entrained solids from a flowing stream by centrifugal action."),
                ("QA-B", "What does a check valve prevent in a discharge line?",
                 "A check valve prevents reverse flow in a discharge line."),
            ]
            for case_id, text, source in qa_cases:
                result, _, _ = execute(root / case_id, patch, text, [[(30, source)]], qa=True,
                                       criterion=source)
                passed = (result.status == GoalStatus.ACHIEVED and "[KB1]" in result.final_answer and
                          not result.telemetry["refusal_generated"])
                cases.append(record(case_id, result, passed))

            resume_cases = [
                ("RESUME-A", "Budget=20 USD. Find the internal Margin equation and calculate Margin.",
                 "Margin equation: Margin=Budget-Cost. Budget (USD); Cost (USD).", "Cost=5 USD", 15),
                ("RESUME-B", "Flow=Rate*Duration. Rate=7 L/h. Calculate Flow.",
                 "", "Duration=3 h", 21),
            ]
            for case_id, text, source, reply, expected in resume_cases:
                patch.setattr("app.services.goal_execution_agent.get_settings",
                    lambda path=root / case_id: Settings(data_dir=path / "data",
                                                         agent_workspace_dir=path / "workspace"))
                agent = GoalExecutionAgent(SyntheticResearch([[(31, source)]] if source else []),
                                           object(), evaluator=PassingEvaluator())
                req = request(text)
                first = asyncio.run(agent.run(case_id, req))
                checkpoint = dict(first.resume_checkpoint)
                checkpoint["user_replies"] = [reply]
                resumed = asyncio.run(agent.run(case_id, req, resume_state=checkpoint, resume_result=first))
                passed = (first.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT and
                          resumed.run_id == first.run_id and resumed.status == GoalStatus.ACHIEVED and
                          resumed.clarification_question is None and resumed.computations and
                          resumed.computations[0].validation_passed and result_value(resumed) == expected and
                          resumed.telemetry["resume_readiness_recomputed"])
                row = record(case_id, resumed, passed)
                row["initial_status"] = first.run_status.value
                cases.append(row)

    summary = {"cases": len(cases), "passed": sum(row["passed"] for row in cases),
               "formula_recovery_attempts": sum(row["formula_recovery_attempt_count"] for row in cases),
               "formula_recovery_successes": sum(row["formula_recovery_success"] for row in cases),
               "local_expansion_successes": sum(row["formula_local_expansion_success"] for row in cases),
               "ready_forced_calculations": sum(row["forced_calculate_transition"] for row in cases),
               "calculations_executed": sum(row["calculation_executed"] for row in cases),
               "calculations_validated": sum(row["calculation_validated"] for row in cases),
               "guard_checks": sum(row["pre_stop_guard_checked"] for row in cases),
               "prevented_refusals": sum(row["pre_stop_guard_prevented_refusal"] for row in cases),
               "resume_recomputed": sum(row["resume_readiness_recomputed"] for row in cases),
               "resume_blocks_cleared": sum(row["resume_block_cleared"] for row in cases)}
    print(json.dumps({"summary": summary, "cases": cases}, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == summary["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
