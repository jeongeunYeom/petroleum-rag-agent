"""Evaluation-only diagnosis of the frozen agentic run and eight synthetic gates.

This does not invoke GoalResearchAgent or rerun a held-out task. Only D1 and D4
execute the existing local Python sandbox with deterministic, fixture-bound code.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.permission_manager import PermissionManager
from app.agents.result_validator import AgentResultValidator
from app.core.config import Settings
from app.models.goal_research_schemas import GoalResearchRequest
from app.services.goal_python_analysis import (
    FRACTION_RE, NUMBER_RE, GoalPythonAnalysis, _basic_arithmetic_formula,
)
from app.services.goal_tool_planner import PythonAnalysisPlan, ToolDecision
from app.tools.python_tools import PythonTools


REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "evaluation/dev/python_tool_execution_diagnostic_v1.json"
PROVENANCE = REPO / "evaluation/review/agentic_heldout_v1_run_provenance.json"
FROZEN = Path(r"D:\petroleum-rag-agent\data\evaluation\agentic\agentic-v1-20261004T075903Z")
OUTPUT = Path(r"D:\petroleum-rag-agent\data\evaluation")
UNKNOWN = "unknown"


def explain_verified_facts(plan: PythonAnalysisPlan, evidence: list[dict]) -> str | None:
    """Name the first gate, in the same order as the frozen production predicate."""
    by_id = {str(item["evidence_id"]): str(item["text"]) for item in evidence if item.get("source_type") != "calculation"}
    if not plan.input_facts:
        return "INPUT_FACTS_EMPTY"
    if re.search(r"difference|change|compare|comparison|ratio|chart|graph|차이|변화율|비교|그래프", plan.purpose, re.I) and len(plan.input_facts) < 2:
        return "INPUT_FACT_COUNT_TOO_LOW"
    if len({fact.name for fact in plan.input_facts}) != len(plan.input_facts):
        return "DUPLICATE_INPUT_NAME"
    for fact in plan.input_facts:
        source = by_id.get(fact.evidence_id, "")
        excerpt = fact.source_excerpt.strip()
        if not source:
            return "EVIDENCE_ID_NOT_FOUND"
        if not excerpt:
            return "SOURCE_EXCERPT_EMPTY"
        if excerpt not in source:
            return "SOURCE_EXCERPT_NOT_IN_EVIDENCE"
        if not math.isfinite(fact.value):
            return "VALUE_NOT_FINITE"
        if fact.unit and fact.unit.casefold() not in excerpt.casefold():
            return "UNIT_NOT_IN_EXCERPT"
        numbers = [float(match.group().replace(",", "")) for match in NUMBER_RE.finditer(excerpt)]
        numbers.extend(int(match.group(1)) / int(match.group(2)) for match in FRACTION_RE.finditer(excerpt) if int(match.group(2)))
        if not any(math.isclose(value, fact.value, rel_tol=1e-9, abs_tol=1e-12) for value in numbers):
            return "VALUE_NOT_IN_EXCERPT"
    basic = bool(plan.formula and _basic_arithmetic_formula(plan.formula, {fact.name for fact in plan.input_facts}))
    if plan.formula and not basic:
        if not plan.supporting_evidence_ids:
            return "FORMULA_PROVENANCE_MISSING"
        normalized = re.sub(r"[^a-z0-9]", "", plan.formula.casefold())
        if not any(normalized in re.sub(r"[^a-z0-9]", "", by_id.get(value, "").casefold()) for value in plan.supporting_evidence_ids):
            return "FORMULA_NOT_FOUND_IN_SOURCE"
    if any(value not in by_id for value in plan.supporting_evidence_ids):
        return "SUPPORTING_EVIDENCE_ID_NOT_FOUND"
    return None


def decision_stage(decision: ToolDecision, approved: bool) -> str | None:
    if not decision.tool_needed:
        return "PLANNER_NOT_SELECTED"
    if decision.plan is None:
        return "PLANNER_SELECTED_NO_PLAN"
    if not approved:
        return "PERMISSION_NOT_APPROVED"
    return None


class FixtureCodeGenerator:
    """A deterministic fake model; never contacts an external model or API."""

    def __init__(self):
        self.calls = 0

    async def chat_structured(self, messages, *_args, **_kwargs):
        self.calls += 1
        supplied = json.loads(messages[-1]["content"])
        facts = {fact["name"]: fact["value"] for fact in supplied["input_facts"]}
        if set(facts) == {"A", "B"}:
            result = {"difference": facts["B"] - facts["A"], "percent_change": (facts["B"] - facts["A"]) / facts["A"] * 100}
        else:
            result = {"k_eff": (facts["k1"] * facts["h1"] + facts["k2"] * facts["h2"]) / (facts["h1"] + facts["h2"])}
        payload = {"inputs": facts, "result": result, "summary": "Fixture calculation validated."}
        code = "import json\nwith open(" + repr(supplied["output_json"]) + ", 'w', encoding='utf-8') as handle:\n    json.dump(" + repr(payload) + ", handle)\n"
        return json.dumps({"code": code})


async def run_dev_cases(fixture: dict) -> list[dict]:
    cases = {item["id"]: item for item in fixture["cases"]}
    rows = []
    with tempfile.TemporaryDirectory(prefix="python-tool-diagnostic-") as temp:
        settings = Settings(data_dir=Path(temp) / "data", agent_workspace_dir=Path(temp) / "workspace")
        d1_analysis = None
        original_validate = PythonTools.validate
        original_run = PythonTools.run_python
        original_permission = PermissionManager.require_tool_level
        original_result = AgentResultValidator.validate_action
        for item in fixture["cases"]:
            case = cases[item.get("reuse_case", item["id"])]
            plan = PythonAnalysisPlan.model_validate(case["plan"])
            evidence = case["evidence"]
            approved = item.get("python_execution_approved", case.get("python_execution_approved", True))
            request = GoalResearchRequest(topic=case["topic"], allow_python_execution=True, python_execution_approved=approved)
            decision = ToolDecision(tool_needed=True, tool_type="python_calculation", reason="Fixture-selected", plan=plan)
            fake = FixtureCodeGenerator()
            analysis = d1_analysis if item["id"] == "D8" else GoalPythonAnalysis(settings, fake, f"GR-DIAG-{item['id']}")
            if item["id"] == "D1":
                d1_analysis = analysis
            predicted = explain_verified_facts(plan, evidence)
            actual = GoalPythonAnalysis.verified_facts(plan, evidence)
            if (predicted is None) != actual:
                raise AssertionError(f"Diagnostic explainer diverged from production predicate: {item['id']}")
            before = analysis.calls
            with (
                patch.object(PythonTools, "validate", autospec=True, side_effect=original_validate) as validate_spy,
                patch.object(PythonTools, "run_python", autospec=True, side_effect=original_run) as run_spy,
                patch.object(PermissionManager, "require_tool_level", autospec=True, side_effect=original_permission) as permission_spy,
                patch.object(AgentResultValidator, "validate_action", autospec=True, side_effect=original_result) as result_spy,
            ):
                record, executed = await analysis.execute(request, plan, evidence)
            if not approved:
                stage = "PERMISSION_NOT_APPROVED"
            elif predicted:
                stage = predicted
            elif record is not None and not executed and record.validation_passed:
                stage = "CACHE_HIT"
            elif analysis.calls == before:
                stage = "PYTHON_BUDGET_EXHAUSTED" if analysis.last_error == "Python call budget exhausted." else "PRE_CALL_UNKNOWN"
            elif record is not None and record.validation_passed:
                stage = "CALC_VALIDATED"
            elif fake.calls == 0:
                stage = "CODEGEN_FAILED"
            elif not run_spy.called:
                stage = "SANDBOX_VALIDATION_FAILED"
            elif not result_spy.called:
                stage = "PYTHON_EXECUTION_FAILED"
            else:
                stage = "RESULT_VALIDATION_FAILED"
            row = {
                "task_id": item["id"], "description": item["description"], "tool_selected": decision.tool_needed,
                "plan_present": decision.plan is not None, "input_fact_count": len(plan.input_facts),
                "supporting_evidence_ids": plan.supporting_evidence_ids,
                "permission_request_enabled": request.allow_python_execution,
                "permission_approved": request.python_execution_approved,
                "verified_facts_passed": actual, "python_call_counter_before": before,
                "python_call_counter_after": analysis.calls, "call_boundary_reached": analysis.calls > before,
                "code_generated": fake.calls > 0 if item["id"] != "D8" else False,
                "sandbox_validation_passed": validate_spy.called and stage == "CALC_VALIDATED",
                "permission_manager_passed": permission_spy.called and stage == "CALC_VALIDATED",
                "subprocess_reached": run_spy.called, "result_validation_passed": bool(record and record.validation_passed),
                "calc_created": bool(record and record.validation_passed), "blocked_stage": stage,
                "expected_stage": item["expected_stage"], "attempts": analysis.attempts,
                "subprocess_exit_code": record.attempt_records[-1].get("exit_code") if record and record.attempt_records else None,
                "code_generator": "deterministic fixture, no model call",
            }
            if stage != item["expected_stage"]:
                raise AssertionError(f"{item['id']}: expected {item['expected_stage']}, got {stage}: {analysis.last_error}")
            rows.append(row)
    return rows


def frozen_posthoc(raw: dict) -> tuple[list[dict], dict]:
    selected = []
    for task in raw["results"]:
        response = task["response"]
        available = []
        prior = None
        for iteration in response["iterations"]:
            available.extend(iteration["evidence_added"])
            if iteration["python_requested"]:
                run_id_valid = bool(re.fullmatch(r"GR-[A-Z0-9-]+", response["run_id"]))
                selected.append({
                    "task_id": task["task_id"], "iteration": iteration["iteration"],
                    "python_requested": True, "python_decision_reason": iteration["python_decision_reason"],
                    "tool_type": UNKNOWN, "plan_present": True,
                    "plan_present_basis": "GoalToolPlanner.decide returns tool_needed=true only with a non-null plan",
                    "input_fact_count": UNKNOWN, "supporting_evidence_ids": UNKNOWN,
                    "permission_request_enabled": task["request"]["allow_python_execution"],
                    "permission_approved": task["request"]["python_execution_approved"],
                    "verified_facts_passed": UNKNOWN,
                    "python_executed": iteration["python_executed"], "python_calls": iteration["python_calls"],
                    "python_attempts_task_total": response["python_attempts_total"],
                    "python_failures_task_total": response["python_failures"],
                    "computation_ids": iteration["computation_ids"],
                    "evidence_ids_available_at_decision": list(dict.fromkeys(available)),
                    "goal_criteria": response["frozen_criteria"],
                    "prior_criteria": prior["criteria"] if prior else [],
                    "current_gaps_from_prior_iteration": prior["gap_analysis"] if prior else [],
                    "run_id_matches_analysis_constructor": run_id_valid,
                    "final_validation_error_observed": response["validation"].get("python_analysis_error") == "Invalid goal research run ID",
                    "blocked_stage": "RUN_ID_REJECTED" if not run_id_valid else UNKNOWN,
                    "call_boundary_reached": iteration["python_calls"] > 0,
                    "subprocess_reached": False if response["python_attempts_total"] == 0 else UNKNOWN,
                    "calc_created": bool(iteration["computation_ids"]),
                })
            prior = iteration
    stats = {
        "full_agent_tasks": len(raw["results"]),
        "python_selected_tasks": len({row["task_id"] for row in selected}),
        "python_selected_iterations": len(selected),
        "actual_python_calls": sum(task["response"]["python_calls_total"] for task in raw["results"]),
        "validated_calcs": sum(bool(c.get("validation_passed")) for task in raw["results"] for c in task["response"]["computations"]),
        "run_id_rejected_iterations_by_deterministic_code_path": sum(row["blocked_stage"] == "RUN_ID_REJECTED" for row in selected),
        "run_id_error_directly_visible_in_final_task_validation": sum(bool(task["response"]["validation"].get("python_analysis_error") == "Invalid goal research run ID") for task in raw["results"]),
        "unknown_blocked_stage_iterations": sum(row["blocked_stage"] == UNKNOWN for row in selected),
    }
    return selected, stats


def write_results(path: Path, payload: dict) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "python_tool_execution_diagnostic_v1.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = payload["dev_cases"]
    with (path / "python_tool_execution_diagnostic_v1.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frozen-dir", type=Path, default=FROZEN)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    hashes = {}
    for name, expected in provenance["raw_artifact_sha256"].items():
        digest = hashlib.sha256((args.frozen_dir / name).read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(f"Frozen artifact hash mismatch: {name}")
        hashes[name] = digest
    raw = json.loads((args.frozen_dir / "full_agent.json").read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    selected, stats = frozen_posthoc(raw)
    dev = asyncio.run(run_dev_cases(fixture))
    payload = {"run_id": provenance["run_id"], "scope": "post-hoc frozen artifact plus synthetic development fixtures; no held-out rerun", "frozen_artifact_sha256": hashes, "frozen_stats": stats, "frozen_selected_iterations": selected, "dev_cases": dev}
    write_results(args.output_dir, payload)
    print(json.dumps({"frozen_stats": stats, "dev_stages": {row["task_id"]: row["blocked_stage"] for row in dev}}, indent=2))


if __name__ == "__main__":
    main()
