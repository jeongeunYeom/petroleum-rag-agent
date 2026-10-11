"""Bounded parameter sweep through the existing approved Python sandbox."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import keyword
import math
import operator
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
from app.services.formula_source_registry import expression_variables
from app.services.calculation_requirements import normalize_symbol
from app.services.user_fact_registry import UserFactRegistry
from app.tools.python_tools import PythonTools


def user_formula_bindings(equation: str, facts: UserFactRegistry) -> tuple[dict[str, object], list[str]]:
    """Bind each literal variable once; never borrow textbook example values."""
    variables = expression_variables(equation)
    if variables is None:
        return {}, ["유효한 사용자 관계식"]
    bound: dict[str, object] = {}
    missing = []
    for variable in sorted(variables):
        matches = [fact for fact in facts.records if normalize_symbol(fact.name) == normalize_symbol(variable)]
        if len(matches) != 1:
            missing.append(f"{variable} 값" if not matches else f"{variable} 값 확인")
        else:
            bound[variable] = matches[0]
    return bound, missing


def direct_operation_operands(text: str, facts: UserFactRegistry,
                              operations: list[str]) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Require an explicit numerator/order for noncommutative arithmetic."""
    names = [row.name for row in facts.records]
    selected: dict[str, tuple[str, str]] = {}
    missing = []
    for operation in ("ratio", "difference"):
        if operation not in operations:
            continue
        candidates = []
        for left in names:
            for right in names:
                if left == right:
                    continue
                a, b = re.escape(left), re.escape(right)
                separator = (r"\s*(?:/|divided\s+by|to)\s*" if operation == "ratio" else
                             r"\s*(?:-|minus)\s*")
                english_or_symbol = re.search(
                    rf"(?<![A-Za-z0-9_]){a}{separator}{b}(?![A-Za-z0-9_])", text, re.I)
                korean = (re.search(rf"(?<![A-Za-z0-9_]){a}(?:를|을)?\s*{b}(?:로|으로)\s*나눈|"
                                     rf"(?<![A-Za-z0-9_]){a}\s*대\s*{b}(?![A-Za-z0-9_])", text)
                          if operation == "ratio" else
                          re.search(rf"(?<![A-Za-z0-9_]){a}에서\s*{b}(?:를|을)?\s*뺀", text))
                if english_or_symbol or korean:
                    candidates.append((left, right))
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) == 1:
            selected[operation] = candidates[0]
        else:
            missing.append("비율의 분자/분모 순서" if operation == "ratio" else "차이를 낼 값의 순서")
    return selected, missing


def _arithmetic_value(node: ast.AST, values: dict[str, float]) -> float:
    """Independent arithmetic check; only the validated AST subset is accepted."""
    if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in values:
        return values[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _arithmetic_value(node.operand, values)
        return value if isinstance(node.op, ast.UAdd) else -value
    binary = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv, ast.Pow: operator.pow}
    if isinstance(node, ast.BinOp) and type(node.op) in binary:
        return float(binary[type(node.op)](_arithmetic_value(node.left, values),
                                           _arithmetic_value(node.right, values)))
    raise ValueError("unsupported user formula expression")


async def run_user_formula_calculation(settings: Settings, request: GoalResearchRequest,
                                       run_id: str, equation: str, facts: UserFactRegistry,
                                       calc_id: str, source_id: str) -> ComputationRecord:
    if not (request.allow_python_execution and request.python_execution_approved):
        raise PermissionError("Python calculation requires approval")
    variables, missing = user_formula_bindings(equation, facts)
    if missing:
        raise ValueError("missing user formula inputs: " + ", ".join(missing))
    lhs, rhs = [part.strip() for part in equation.split("=", 1)]
    if len(rhs) > 200 or len(variables) > 12:
        raise ValueError("user formula exceeds safe bounds")
    tree = ast.parse(rhs, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 40 or any(type(node) not in (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Constant,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Load,
    ) for node in ast.walk(tree)):
        raise ValueError("unsafe user formula")
    if any(isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow) and
           (not isinstance(node.right, ast.Constant) or type(node.right.value) not in {int, float}
            or abs(node.right.value) > 8) for node in ast.walk(tree)):
        raise ValueError("formula exponent exceeds safe bounds")
    units = {name: fact.unit for name, fact in variables.items()}
    if any(isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)) and
           isinstance(node.left, ast.Name) and isinstance(node.right, ast.Name) and
           units[node.left.id].casefold() != units[node.right.id].casefold()
           for node in ast.walk(tree)):
        raise ValueError("incompatible user formula units")
    values = {name: fact.value for name, fact in variables.items()}
    try:
        expected = _arithmetic_value(tree.body, values)
    except (ZeroDivisionError, OverflowError) as exc:
        raise ValueError("invalid user formula result") from exc
    if not math.isfinite(expected):
        raise ValueError("non-finite user formula result")
    workspace = settings.agent_workspace_dir.resolve()
    analysis_dir = (workspace / "results" / "goal-research" / run_id / "analysis").resolve()
    analysis_dir.relative_to(workspace)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    scoped = replace(settings, agent_workspace_dir=analysis_dir)
    permissions = PermissionManager(scoped)
    permissions.require_tool_level(AgentPermissionLevel.APPROVED_EXECUTION, AgentToolName.RUN_PYTHON)
    python = PythonTools(scoped, permissions)
    code = ("import json\nimport math\n" +
            "\n".join(f"{name} = {fact.value!r}" for name, fact in variables.items()) +
            f"\nresult = {rhs}\n" +
            "if not math.isfinite(result):\n    raise ValueError('non-finite result')\n" +
            "with open('calculation.json', 'w', encoding='utf-8') as handle:\n" +
            "    json.dump({'value': result}, handle, allow_nan=False)\n")
    python.validate(code)
    execution = await asyncio.to_thread(python.run_python, code,
                                        task_id=f"goal-research/{run_id}/calculation/{calc_id}")
    action = AgentAction(action_id=f"{calc_id}-user-formula", tool=AgentToolName.RUN_PYTHON,
                         description="Bounded user-supplied formula", arguments={"expected_outputs": ["calculation.json"]})
    checked = AgentResultValidator(scoped, permissions).validate_action(action, execution)
    if not checked or not checked["passed"]:
        raise ValueError("user formula output validation failed")
    output_path = analysis_dir / "calculation.json"
    if output_path.stat().st_size > settings.agent_max_file_bytes:
        raise ValueError("calculation output exceeds file size limit")
    output = json.loads(output_path.read_text(encoding="utf-8"),
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    actual = output.get("value")
    if type(actual) not in {int, float} or not math.isfinite(actual) or not math.isclose(
            actual, expected, rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError("user formula result failed independent validation")
    input_ids = [fact.fact_id for fact in variables.values()]
    manifest = {"OUT_RESULT": {"name": lhs, "value": actual, "unit": None,
                               "semantic_type": "numeric", "source_fact_ids": input_ids,
                               "required": True}}
    return ComputationRecord(
        computation_id=calc_id, analysis_id=f"USER-FORMULA-{calc_id}",
        purpose=request.goal or request.topic, source_input_ids=input_ids,
        formula_source_ids=[source_id], input_fact_ids=input_ids,
        bound_variables={name: fact.fact_id for name, fact in variables.items()},
        normalized_formula=normalize_formula(equation), source_formula=equation,
        units={**units, lhs: ""}, execution_hash=hashlib.sha256(code.encode()).hexdigest(),
        output={"OUT_RESULT": actual}, formula=equation,
        input_facts=[{"name": name, "value": fact.value, "unit": fact.unit,
                      "evidence_id": fact.fact_id, "source_type": "user_fact"}
                     for name, fact in variables.items()],
        code_record=str(execution.get("code_record") or ""),
        output_files=[(Path("results") / "goal-research" / run_id / "analysis" / "calculation.json").as_posix()],
        summary=f"Validated {lhs}={actual}", validation_passed=True, attempts=1,
        output_manifest=manifest, attempt_records=[{"attempt": 1, "code": code, "validation_passed": True}],
        required_output_ids=["OUT_RESULT"], produced_output_ids=["OUT_RESULT"],
        used_input_ids=input_ids, contract_validation_passed=True,
    )


async def run_direct_arithmetic(settings: Settings, request: GoalResearchRequest,
                                run_id: str, facts: UserFactRegistry,
                                operations: list[str], calc_id: str,
                                operand_orders: dict[str, tuple[str, str]] | None = None) -> ComputationRecord:
    """Execute explicit generic arithmetic from user facts without retrieval or an LLM plan."""
    allowed = {"mean", "sum", "ranking", "maximum", "minimum", "range", "ratio", "difference"}
    selected = list(dict.fromkeys(operations))
    operand_orders = operand_orders or {}
    if (not selected or set(selected) - allowed or len(facts.records) < 2
            or len(facts.records) > 30):
        raise ValueError("direct arithmetic inputs or operations are unsupported")
    if any(name not in operand_orders for name in set(selected) & {"ratio", "difference"}):
        raise ValueError("direct arithmetic operand order missing")
    if not (request.allow_python_execution and request.python_execution_approved):
        raise PermissionError("Python calculation requires approval")
    names = [row.name for row in facts.records]
    if len(set(names)) != len(names):
        raise ValueError("ambiguous duplicate user input names")
    units = {row.unit.casefold() for row in facts.records}
    if len(units) != 1:
        raise ValueError("incompatible direct arithmetic units")
    workspace = settings.agent_workspace_dir.resolve()
    analysis_dir = (workspace / "results" / "goal-research" / run_id / "analysis").resolve()
    analysis_dir.relative_to(workspace)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    scoped = replace(settings, agent_workspace_dir=analysis_dir)
    permissions = PermissionManager(scoped)
    permissions.require_tool_level(AgentPermissionLevel.APPROVED_EXECUTION, AgentToolName.RUN_PYTHON)
    python = PythonTools(scoped, permissions)
    values = {row.name: row.value for row in facts.records}
    if any(name not in values for pair in operand_orders.values() for name in pair):
        raise ValueError("direct arithmetic operand is not a supplied fact")
    if "ratio" in selected and values[operand_orders["ratio"][1]] == 0:
        raise ValueError("ratio denominator is zero")
    display_names = ({name: name.removesuffix("_rate") for name in values}
                     if all(name.endswith("_rate") for name in values) else
                     {name: name for name in values})
    code = (
        "import json\nimport math\n" + f"values = {values!r}\n" +
        f"labels = {display_names!r}\n" +
        "numbers = list(values.values())\nresult = {}\n" +
        ("result['mean'] = sum(numbers) / len(numbers)\n" if "mean" in selected else "") +
        ("result['sum'] = sum(numbers)\n" if "sum" in selected else "") +
        ("result['ranking'] = [labels[key] for key in sorted(values, key=lambda key: (-values[key], key))]\n"
         if "ranking" in selected else "") +
        ("result['maximum'] = max(numbers)\n" if "maximum" in selected else "") +
        ("result['minimum'] = min(numbers)\n" if "minimum" in selected else "") +
        ("result['range'] = max(numbers) - min(numbers)\n" if "range" in selected else "") +
        (f"result['ratio'] = values[{operand_orders['ratio'][0]!r}] / values[{operand_orders['ratio'][1]!r}]\n"
         if "ratio" in selected else "") +
        (f"result['difference'] = values[{operand_orders['difference'][0]!r}] - values[{operand_orders['difference'][1]!r}]\n"
         if "difference" in selected else "") +
        "with open('calculation.json', 'w', encoding='utf-8') as handle:\n"
        "    json.dump(result, handle, allow_nan=False)\n"
    )
    python.validate(code)
    execution = await asyncio.to_thread(python.run_python, code,
                                        task_id=f"goal-research/{run_id}/calculation/{calc_id}")
    action = AgentAction(action_id=f"{calc_id}-direct", tool=AgentToolName.RUN_PYTHON,
                         description="Bounded user-fact arithmetic", arguments={"expected_outputs": ["calculation.json"]})
    checked = AgentResultValidator(scoped, permissions).validate_action(action, execution)
    if not checked or not checked["passed"]:
        raise ValueError("direct arithmetic output validation failed")
    output_path = analysis_dir / "calculation.json"
    if output_path.stat().st_size > settings.agent_max_file_bytes:
        raise ValueError("calculation output exceeds file size limit")
    output = json.loads(output_path.read_text(encoding="utf-8"),
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    numbers = list(values.values())
    expected = {}
    if "mean" in selected:
        expected["mean"] = sum(numbers) / len(numbers)
    if "sum" in selected:
        expected["sum"] = sum(numbers)
    if "ranking" in selected:
        expected["ranking"] = [display_names[key] for key in sorted(values, key=lambda key: (-values[key], key))]
    if "maximum" in selected:
        expected["maximum"] = max(numbers)
    if "minimum" in selected:
        expected["minimum"] = min(numbers)
    if "range" in selected:
        expected["range"] = max(numbers) - min(numbers)
    if "ratio" in selected:
        left, right = operand_orders["ratio"]
        expected["ratio"] = values[left] / values[right]
    if "difference" in selected:
        left, right = operand_orders["difference"]
        expected["difference"] = values[left] - values[right]
    if set(output) != set(expected) or any(
            output[key] != value if isinstance(value, list) else
            type(output[key]) not in {int, float} or not math.isclose(output[key], value, rel_tol=1e-10, abs_tol=1e-12)
            for key, value in expected.items()):
        raise ValueError("direct arithmetic failed independent validation")
    input_ids = [row.fact_id for row in facts.records]
    manifest = {f"OUT_{name}": {
        "name": name, "value": value,
        "unit": None if isinstance(value, list) or name == "ratio" else facts.records[0].unit or None,
        "semantic_type": "ranking" if isinstance(value, list) else "numeric",
        "source_fact_ids": input_ids, "required": True,
    } for name, value in output.items()}
    return ComputationRecord(
        computation_id=calc_id, analysis_id=f"DIRECT-{calc_id}", purpose=request.goal or request.topic,
        source_input_ids=input_ids, formula_source_ids=["USER_REQUEST"], input_fact_ids=input_ids,
        bound_variables={row.name: row.fact_id for row in facts.records},
        normalized_formula="generic:" + ",".join(selected),
        units={row.name: row.unit for row in facts.records},
        execution_hash=hashlib.sha256(code.encode()).hexdigest(),
        output={key: row["value"] for key, row in manifest.items()},
        formula="generic:" + ",".join(selected),
        input_facts=[{"name": row.name, "value": row.value, "unit": row.unit,
                      "evidence_id": row.fact_id, "source_type": "user_fact"} for row in facts.records],
        code_record=str(execution.get("code_record") or ""),
        output_files=[(Path("results") / "goal-research" / run_id / "analysis" / "calculation.json").as_posix()],
        summary="Validated direct arithmetic: " + ", ".join(selected),
        validation_passed=True, attempts=1, output_manifest=manifest,
        attempt_records=[{"attempt": 1, "code": code, "validation_passed": True}],
        required_output_ids=list(manifest), produced_output_ids=list(manifest),
        used_input_ids=input_ids, contract_validation_passed=True,
    )


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
