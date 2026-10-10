"""Bounded parameter sweep through the existing approved Python sandbox."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import keyword
import math
import re
from dataclasses import replace
from pathlib import Path

from app.agents.permission_manager import PermissionManager
from app.agents.result_validator import AgentResultValidator
from app.core.config import Settings
from app.models.agent_schemas import AgentAction, AgentPermissionLevel, AgentToolName
from app.models.goal_research_schemas import ComputationRecord, GoalResearchRequest
from app.services.goal_execution_state import SimulationSpec
from app.services.formula_source_registry import normalize_formula
from app.tools.python_tools import PythonTools


def validate_expression(spec: SimulationSpec) -> None:
    if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,40}", spec.parameter.name) or
            keyword.iskeyword(spec.parameter.name)):
        raise ValueError("invalid simulation parameter name")
    if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,40}", spec.output_name) or
            keyword.iskeyword(spec.output_name)):
        raise ValueError("invalid simulation output name")
    if len(spec.expression) > 200 or any(abs(value) > 1e9 for value in (
        spec.parameter.start, spec.parameter.stop, spec.parameter.step
    )):
        raise ValueError("simulation expression or range exceeds safe bounds")
    try:
        tree = ast.parse(spec.expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("invalid simulation expression") from exc
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Constant,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Load)
    if sum(1 for _ in ast.walk(tree)) > 40:
        raise ValueError("simulation expression exceeds safe bounds")
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError("simulation expression contains unsupported operations")
        if isinstance(node, ast.Name) and node.id != spec.parameter.name:
            raise ValueError("simulation expression references an unknown parameter")
        if isinstance(node, ast.Constant) and (isinstance(node.value, bool) or
                                               not isinstance(node.value, (int, float)) or
                                               not math.isfinite(node.value) or abs(node.value) > 1e9):
            raise ValueError("simulation expression contains an invalid constant")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow) and (
            not isinstance(node.right, ast.Constant) or not isinstance(node.right.value, (int, float))
            or abs(node.right.value) > 8
        ):
            raise ValueError("simulation exponent exceeds safe bounds")


async def run_parameter_sweep(settings: Settings, request: GoalResearchRequest, run_id: str,
                              spec: SimulationSpec, calc_id: str, source_id: str = "USERF1") -> ComputationRecord:
    if not (request.allow_python_execution and request.python_execution_approved):
        raise PermissionError("Python simulation requires explicit approval")
    validate_expression(spec)
    count = math.floor((spec.parameter.stop - spec.parameter.start) / spec.parameter.step + 1e-10) + 1
    if count > min(spec.max_cases, 100):
        raise ValueError("simulation case budget exceeded")
    workspace = settings.agent_workspace_dir.resolve()
    analysis_dir = (workspace / "results" / "goal-research" / run_id / "analysis").resolve()
    analysis_dir.relative_to(workspace)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    scoped = replace(settings, agent_workspace_dir=analysis_dir)
    permissions = PermissionManager(scoped)
    permissions.require_tool_level(AgentPermissionLevel.APPROVED_EXECUTION, AgentToolName.RUN_PYTHON)
    python = PythonTools(scoped, permissions)
    json_name, csv_name = "simulation.json", "simulation.csv"
    code = (
        "import csv\nimport json\nimport math\n"
        f"cases = []\nfor i in range({count}):\n"
        f"    {spec.parameter.name} = round({spec.parameter.start!r} + i * {spec.parameter.step!r}, 12)\n"
        f"    value = {spec.expression}\n"
        "    if not math.isfinite(value):\n        raise ValueError('non-finite simulation value')\n"
        f"    cases.append({{'parameter': {spec.parameter.name}, 'value': value}})\n"
        f"best = {'max' if spec.objective == 'max' else 'min'}(cases, key=lambda row: row['value'])\n"
        f"worst = {'min' if spec.objective == 'max' else 'max'}(cases, key=lambda row: row['value'])\n"
        "result = {'cases': cases, 'best': best, 'worst': worst, "
        "'mean': sum(row['value'] for row in cases) / len(cases), "
        "'range': max(row['value'] for row in cases) - min(row['value'] for row in cases)}\n"
        f"with open({json_name!r}, 'w', encoding='utf-8') as handle:\n"
        "    json.dump(result, handle, allow_nan=False)\n"
        f"with open({csv_name!r}, 'w', newline='', encoding='utf-8') as handle:\n"
        "    writer = csv.DictWriter(handle, fieldnames=['parameter', 'value'])\n"
        "    writer.writeheader()\n    writer.writerows(cases)\n"
    )
    python.validate(code)
    execution = await asyncio.to_thread(
        python.run_python, code, task_id=f"goal-research/{run_id}/simulation/{calc_id}"
    )
    action = AgentAction(action_id=f"{calc_id}-simulation", tool=AgentToolName.RUN_PYTHON,
                         description="Bounded parameter sweep", arguments={"expected_outputs": [json_name, csv_name]})
    checked = AgentResultValidator(scoped, permissions).validate_action(action, execution)
    if not checked or not checked["passed"]:
        raise ValueError("simulation output validation failed: " + "; ".join((checked or {}).get("errors", [])))
    for name in (json_name, csv_name):
        if (analysis_dir / name).stat().st_size > settings.agent_max_file_bytes:
            raise ValueError("simulation output exceeds file size limit")
    data = json.loads((analysis_dir / json_name).read_text(encoding="utf-8"),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) != count or any(
        not isinstance(row, dict) or not all(isinstance(row.get(key), (int, float)) and
                                              math.isfinite(row[key]) for key in ("parameter", "value"))
        for row in cases
    ):
        raise ValueError("simulation result cases are incomplete or non-finite")
    best, worst = data["best"], data["worst"]
    selected = max if spec.objective == "max" else min
    if best != selected(cases, key=lambda row: row["value"]) or worst != (
        min if spec.objective == "max" else max
    )(cases, key=lambda row: row["value"]):
        raise ValueError("simulation extrema failed independent validation")
    if not math.isclose(data["range"], max(row["value"] for row in cases) -
                        min(row["value"] for row in cases), rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError("simulation range failed independent validation")
    manifest = {}
    for index, row in enumerate(cases, 1):
        manifest[f"OUT_PARAMETER_{index:03d}"] = {
            "name": f"case_{index}_{spec.parameter.name}", "value": row["parameter"],
            "unit": spec.parameter.unit, "semantic_type": "numeric",
            "source_fact_ids": [source_id], "required": True,
        }
        manifest[f"OUT_CASE_{index:03d}"] = {
            "name": f"case_{index}_{spec.output_name}", "value": row["value"],
            "unit": spec.output_unit, "semantic_type": "numeric",
            "source_fact_ids": [source_id], "required": True,
        }
    manifest.update({
        "OUT_BEST_PARAMETER": {"name": "best_parameter", "value": best["parameter"],
                               "unit": spec.parameter.unit, "semantic_type": "numeric",
                               "source_fact_ids": [source_id], "required": True},
        "OUT_BEST_RESULT": {"name": "best_result", "value": best["value"],
                            "unit": spec.output_unit, "semantic_type": "numeric",
                            "source_fact_ids": [source_id], "required": True},
        "OUT_WORST_PARAMETER": {"name": "worst_parameter", "value": worst["parameter"],
                                "unit": spec.parameter.unit, "semantic_type": "numeric",
                                "source_fact_ids": [source_id], "required": True},
        "OUT_WORST_RESULT": {"name": "worst_result", "value": worst["value"],
                               "unit": spec.output_unit, "semantic_type": "numeric",
                               "source_fact_ids": [source_id], "required": True},
        "OUT_MEAN_RESULT": {"name": "mean_result", "value": data["mean"],
                            "unit": spec.output_unit, "semantic_type": "numeric",
                            "source_fact_ids": [source_id], "required": True},
        "OUT_RANGE_RESULT": {"name": "range_result", "value": data["range"],
                             "unit": spec.output_unit, "semantic_type": "numeric",
                             "source_fact_ids": [source_id], "required": True},
    })
    return ComputationRecord(
        computation_id=calc_id, analysis_id=f"SIM-{calc_id}", purpose=request.goal or request.topic,
        source_input_ids=[source_id], formula_source_ids=[source_id], input_fact_ids=[source_id],
        bound_variables={spec.parameter.name: source_id},
        normalized_formula=normalize_formula(f"{spec.output_name}={spec.expression}"),
        source_formula=f"{spec.output_name}={spec.expression}",
        units={spec.parameter.name: spec.parameter.unit or "", spec.output_name: spec.output_unit or ""},
        execution_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        output={key: item.get("value") for key, item in manifest.items()},
        formula=spec.expression, input_facts=[{
            "name": spec.parameter.name, "value": spec.parameter.start, "unit": spec.parameter.unit,
            "evidence_id": source_id, "source_type": "user_fact"}],
        code_record=str(execution.get("code_record") or ""),
        output_files=[(Path("results") / "goal-research" / run_id / "analysis" / name).as_posix()
                      for name in (json_name, csv_name)],
        summary=f"{count} validated cases; best {spec.parameter.name}={best['parameter']}, "
                f"{spec.output_name}={best['value']} {spec.output_unit or ''}",
        validation_passed=True, attempts=1, output_manifest=manifest,
        attempt_records=[{"attempt": 1, "code": code, "validation_passed": True}],
        required_output_ids=list(manifest), produced_output_ids=list(manifest),
        used_input_ids=[source_id], contract_validation_passed=True,
    )
