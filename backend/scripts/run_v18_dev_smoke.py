"""Opt-in local qwen3:8b smoke with synthetic in-memory evidence only.

This is development verification, never a sealed/final benchmark. No Chroma client
or evaluation fixture is loaded.
"""

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from app.core.config import Settings
from app.models.goal_research_schemas import GoalCriterion
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_message_parser import GoalMessageRequest, parse_goal_message
from app.services.ollama import OllamaClient
from test_agent_reliability_v18_dev import SyntheticSources, RejectingEvaluator, unavailable


CASES = [
    ("grounded_gate", "Explain why the saffron gate stops backflow.",
     ["The saffron gate stops backflow because the hinged flap closes against reverse pressure."], None),
    ("grounded_screen", "Describe how the nickel screen filters coarse particles.",
     ["The nickel screen filters coarse particles by retaining grains larger than its mesh openings."], None),
    ("direct_mean", "U=11 psi; V=19 psi. Calculate the mean of U and V.", [], 15),
    ("direct_ratio", "inlet=64 kg; outlet=16 kg. Calculate inlet/outlet ratio.", [], 4),
    ("user_flux", "flux = volume / duration. volume=28 m3; duration=7 h. Calculate flux.", [], 4),
    ("user_rise", "rise = final - initial. initial=14 psi; final=39 psi. Calculate rise.", [], 25),
    ("kb_efficiency", "recovered=33 m3; injected=55 m3. Calculate efficiency using the internal source relation.",
     ["The synthetic manual states efficiency = recovered / injected."], .6),
    ("kb_delta", "high=71 psi; low=29 psi. Calculate delta using the internal source equation.",
     ["The synthetic test relation is delta = high - low."], 42),
    ("underdetermined", "From this information alone, determine the exact remaining service life.",
     ["Remaining service life requires the measured wear depth and calibrated wear rate."], None),
]


async def main(output: Path):
    if output.exists():
        raise SystemExit("Refusing to overwrite a previous development smoke")
    root = Path(tempfile.mkdtemp(prefix="petroleum-v18-dev-"))
    settings = Settings(data_dir=root / "data", agent_workspace_dir=root / "workspace")
    ollama = OllamaClient(settings)
    if "qwen3:8b" not in await ollama.list_models():
        raise SystemExit("Local qwen3:8b is unavailable")
    rows = []
    for name, message, passages, expected in CASES:
        request = parse_goal_message(GoalMessageRequest(message=message, model="qwen3:8b"))
        if name.startswith("grounded") or name == "underdetermined":
            request = request.model_copy(update={"success_criteria": [GoalCriterion(
                criterion_id="C1", description=message)]})
        sources = SyntheticSources(*passages)
        agent = GoalExecutionAgent(sources, ollama, evaluator=RejectingEvaluator(), synthesizer=unavailable)
        start = time.perf_counter()
        with patch("app.services.goal_execution_agent.get_settings", return_value=settings):
            result = await agent.run("GR-V18-DEV-" + name, request)
        valid_calcs = [calc for calc in result.computations if calc.validation_passed]
        values = [row.get("value") for calc in valid_calcs for row in calc.output_manifest.values()]
        passed = (result.status.value == "achieved" and not result.telemetry.get("refusal_generated")
                  and bool(result.final_answer))
        if expected is not None:
            passed = passed and any(isinstance(value, (int, float)) and abs(value - expected) < 1e-9
                                    for value in values)
            passed = passed and result.telemetry.get("deterministic_calc_finalizer_used")
        elif name.startswith("grounded"):
            passed = passed and result.telemetry.get("grounded_fast_path_used") and "[KB1]" in result.final_answer
        else:
            passed = passed and result.python_calls_total == 0 and "wear depth" in result.final_answer
        row = {"case": name, "passed": bool(passed), "status": result.status.value,
               "actions": [item["action_type"] for item in result.action_history],
               "seconds": round(time.perf_counter() - start, 3), "python_calls": result.python_calls_total,
               "validated_calc_count": len(valid_calcs), "answer": result.final_answer,
               "telemetry": {key: result.telemetry.get(key) for key in (
                   "intent_route", "route_forced_by_deterministic_readiness",
                   "deterministic_calc_finalizer_used", "grounded_fast_path_used",
                   "claim_support_checked", "refusal_generated", "clarification_generated")}}
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("case", "passed", "status", "seconds")}), flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"kind": "development_smoke_not_final_benchmark",
        "model": "qwen3:8b", "retrieval": "synthetic_in_memory_only", "chroma_opened": False,
        "frozen_evaluation_read": False, "passed": sum(row["passed"] for row in rows),
        "total": len(rows), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not all(row["passed"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
