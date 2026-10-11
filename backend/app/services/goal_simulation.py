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
import statistics
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
from app.services.calculation_requirements import normalize_symbol, symbol_names
from app.services.user_fact_registry import UserFactRegistry
from app.services.direct_operation_v3 import OPERATIONS as V3_OPERATIONS, build as build_v3_operation
from app.tools.python_tools import PythonTools


def user_formula_bindings(equation: str, facts: UserFactRegistry) -> tuple[dict[str, object], list[str]]:
    """Bind each literal variable once; never borrow textbook example values."""
    variables = expression_variables(equation)
    if variables is None:
        return {}, ["유효한 사용자 관계식"]
    bound: dict[str, object] = {}
    missing = []
    for variable in sorted(variables):
        matches = [fact for fact in facts.records if normalize_symbol(fact.name) in symbol_names(variable)]
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
    for operation in ("ratio", "difference", "divide", "subtract"):
        if operation not in operations:
            continue
        candidates = []
        for left in names:
            for right in names:
                if left == right:
                    continue
                a, b = re.escape(left), re.escape(right)
                separator = (r"\s*(?:/|divided\s+by|to)\s*" if operation in {"ratio", "divide"} else
                             r"\s*(?:-|minus)\s*")
                english_or_symbol = re.search(
                    rf"(?<![A-Za-z0-9_]){a}{separator}{b}(?![A-Za-z0-9_])", text, re.I)
                korean = (re.search(rf"(?<![A-Za-z0-9_]){a}(?:를|을)?\s*{b}(?:로|으로)\s*나눈|"
                                     rf"(?<![A-Za-z0-9_]){a}\s*대\s*{b}(?![A-Za-z0-9_])", text)
                          if operation in {"ratio", "divide"} else
                          re.search(rf"(?<![A-Za-z0-9_]){a}에서\s*{b}(?:를|을)?\s*뺀", text))
                if english_or_symbol or korean:
                    candidates.append((left, right))
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) == 1:
            selected[operation] = candidates[0]
        else:
            missing.append("비율의 분자/분모 순서" if operation in {"ratio", "divide"} else "차이를 낼 값의 순서")
    return selected, missing


def _special_direct(operation: str, text: str, values: dict[str, float],
                    units: dict[str, str]) -> tuple[str, dict[str, float], dict[str, str | None]]:
    """Build bounded code from named user facts; calculate an independent expected result."""
    if operation in V3_OPERATIONS:
        return build_v3_operation(operation, text, values, units)
    if operation == "weighted_average":
        weights = {key[:-7]: value for key, value in values.items() if key.endswith("_weight")}
        if not weights or any(key not in values for key in weights):
            raise ValueError("weighted average needs paired values and weights")
        pairs = {key: (values[key], weight) for key, weight in weights.items()}
        if sum(weights.values()) <= 0 or any(weight < 0 for weight in weights.values()):
            raise ValueError("invalid nonpositive weights")
        code = f"pairs = {pairs!r}\nresult['weighted_average'] = sum(x*w for x,w in pairs.values()) / sum(w for x,w in pairs.values())\n"
        expected = {"weighted_average": math.fsum(value * weight for value, weight in pairs.values()) / math.fsum(weights.values())}
        return code, expected, {"weighted_average": units[next(iter(weights))]}
    if operation == "combined_rate":
        distances = [value for key, value in values.items() if key.endswith("_distance") or units[key] in {"m", "km"}]
        times = [value for key, value in values.items() if key.endswith("_time") or units[key] in {"h", "min"}]
        if not distances or len(distances) != len(times) or sum(times) <= 0:
            raise ValueError("combined rate needs matching positive total distance and time")
        if len({units[key] for key in values if key.endswith("_distance") or units[key] in {"m", "km"}}) != 1 or len({units[key] for key in values if key.endswith("_time") or units[key] in {"h", "min"}}) != 1:
            raise ValueError("combined rate has incompatible units")
        distance_unit = next((units[key] for key in values if key.endswith("_distance") or units[key] in {"m", "km"}), "")
        time_unit = next((units[key] for key in values if key.endswith("_time") or units[key] in {"h", "min"}), "")
        code = f"distances = {distances!r}\ntimes = {times!r}\nresult['combined_rate'] = sum(distances) / sum(times)\n"
        return code, {"combined_rate": math.fsum(distances) / math.fsum(times)}, {"combined_rate": f"{distance_unit}/{time_unit}"}
    if operation in {"interpolation", "trapezoid"}:
        points = sorted((float(key[4:]) if key.startswith("day_") else
                         float(key[6:].replace("n", "-").replace("p", ".")), value)
                        for key, value in values.items()
                        if re.fullmatch(r"day_\d+|point_[np\d]+", key))
        if len(points) < 2 or len({x for x, _ in points}) != len(points):
            raise ValueError("integration/interpolation needs at least two distinct points")
        if operation == "trapezoid":
            code = f"points = {points!r}\nresult['trapezoid'] = sum((points[i+1][0]-points[i][0])*(points[i+1][1]+points[i][1])/2 for i in range(len(points)-1))\n"
            expected = sum((right_x-left_x)*(left_y+right_y)/2 for (left_x,left_y),(right_x,right_y) in zip(points, points[1:]))
            return code, {"trapezoid": expected}, {"trapezoid": None}
        target = values.get("target_day", values.get("target_x"))
        if target is None or target < points[0][0] or target > points[-1][0]:
            raise ValueError("interpolation target must be within supplied points")
        pair = next(((a,b) for a,b in zip(points, points[1:]) if a[0] <= target <= b[0]), None)
        if pair is None:
            raise ValueError("interpolation bracket unavailable")
        (x0,y0),(x1,y1) = pair
        code = (f"x0,y0,x1,y1,target = {x0!r},{y0!r},{x1!r},{y1!r},{target!r}\n"
                "result['interpolation'] = y0 + (target-x0)*(y1-y0)/(x1-x0)\n")
        return code, {"interpolation": y0 + (target-x0)*(y1-y0)/(x1-x0)}, {"interpolation": None}
    if operation == "repeated_percent":
        if not {"initial", "change_percent", "repeat_count"} <= set(values):
            raise ValueError("repeated percent needs initial value, rate and count")
        count = values["repeat_count"]
        if count < 1 or count > 100 or int(count) != count:
            raise ValueError("invalid repeat count")
        sign = -1 if re.search(r"감소|decreas", text, re.I) else 1 if re.search(r"증가|increas", text, re.I) else 0
        if not sign:
            raise ValueError("increase/decrease direction missing")
        factor = 1 + sign * values["change_percent"] / 100
        if factor < 0:
            raise ValueError("invalid percent change")
        code = f"result['repeated_percent'] = values['initial'] * ({factor!r} ** int(values['repeat_count']))\n"
        return code, {"repeated_percent": values["initial"] * factor ** int(count)}, {"repeated_percent": units["initial"] or None}
    if operation == "allocation":
        weights = {key[:-7]: value for key, value in values.items() if key.endswith("_weight")}
        if "total" not in values or not weights or sum(weights.values()) <= 0 or any(value < 0 for value in weights.values()):
            raise ValueError("allocation needs total and positive weights")
        code = f"weights = {weights!r}\nresult.update({{'allocation_'+k: values['total']*w/sum(weights.values()) for k,w in weights.items()}})\n"
        expected = {"allocation_"+key: values["total"]*weight/sum(weights.values()) for key,weight in weights.items()}
        return code, expected, {key: units["total"] or None for key in expected}
    if operation == "piecewise_cost":
        tiers = sorted({int(match.group(1)) for key in values if (match := re.fullmatch(r"tier_(\d+)_(?:volume|price)", key))})
        if not tiers or any(f"tier_{index}_volume" not in values or f"tier_{index}_price" not in values for index in tiers):
            raise ValueError("piecewise cost needs each tier volume and price")
        pairs = [(values[f"tier_{index}_volume"], values[f"tier_{index}_price"]) for index in tiers]
        code = f"tiers = {pairs!r}\nresult['piecewise_cost'] = sum(volume*price for volume,price in tiers)\n"
        return code, {"piecewise_cost": math.fsum(volume*price for volume,price in pairs)}, {"piecewise_cost": "USD"}
    raise ValueError("unsupported direct operation")


def direct_readiness(text: str, facts: UserFactRegistry, operations: list[str]) -> list[str]:
    """Check special primitive operands before selecting Python; never search KB for them."""
    special = {"weighted_average", "combined_rate", "interpolation", "trapezoid",
               "repeated_percent", "allocation", "piecewise_cost"} | V3_OPERATIONS
    chosen = set(operations) & special
    if not chosen:
        return []
    if len(operations) != 1:
        return ["요청한 직접 계산의 연산 구분"]
    try:
        _special_direct(operations[0], text, {row.name: row.value for row in facts.records},
                        {row.name: row.unit for row in facts.records})
    except ValueError as exc:
        return [str(exc)]
    return []


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


def _formula_output_unit(node: ast.AST, units: dict[str, str]) -> str:
    """Infer simple dimensions from the same bounded AST used for numeric validation."""
    if isinstance(node, ast.Constant):
        return ""
    if isinstance(node, ast.Name):
        return units[node.id]
    if isinstance(node, ast.UnaryOp):
        return _formula_output_unit(node.operand, units)
    if not isinstance(node, ast.BinOp):
        raise ValueError("unsupported user formula expression")
    left = _formula_output_unit(node.left, units)
    right = _formula_output_unit(node.right, units)
    if isinstance(node.op, (ast.Add, ast.Sub)):
        if left.casefold() != right.casefold():
            raise ValueError("incompatible user formula units")
        return left
    if isinstance(node.op, ast.Mult):
        return "*".join(part for part in (left, right) if part)
    if isinstance(node.op, ast.Div):
        if not right:
            return left
        if left.casefold() == right.casefold():
            return ""
        return f"{left}/{right}" if left else f"1/{right}"
    if isinstance(node.op, ast.Pow):
        exponent = node.right.value
        return "" if not left or exponent == 0 else left if exponent == 1 else f"{left}^{exponent}"
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
    output_unit = _formula_output_unit(tree.body, units)
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
    manifest = {"OUT_RESULT": {"name": lhs, "value": actual, "unit": output_unit or None,
                               "semantic_type": "numeric", "source_fact_ids": input_ids,
                               "required": True}}
    return ComputationRecord(
        computation_id=calc_id, analysis_id=f"USER-FORMULA-{calc_id}",
        purpose=request.goal or request.topic, source_input_ids=input_ids,
        formula_source_ids=[source_id], input_fact_ids=input_ids,
        bound_variables={name: fact.fact_id for name, fact in variables.items()},
        normalized_formula=normalize_formula(equation), source_formula=equation,
        units={**units, lhs: output_unit}, execution_hash=hashlib.sha256(code.encode()).hexdigest(),
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
    allowed = {"mean", "sum", "ranking", "maximum", "minimum", "range", "ratio", "difference",
               "median", "std_population", "std_sample", "variance_population", "variance",
               "geometric_mean", "add", "multiply", "divide", "subtract", "elapsed_time",
               "percent_conversion", "weighted_average", "combined_rate", "interpolation",
               "trapezoid", "repeated_percent", "allocation", "piecewise_cost"} | V3_OPERATIONS
    selected = list(dict.fromkeys(operations))
    operand_orders = operand_orders or {}
    special = {"weighted_average", "combined_rate", "interpolation", "trapezoid",
               "repeated_percent", "allocation", "piecewise_cost"} | V3_OPERATIONS
    if (not selected or set(selected) - allowed or len(facts.records) < (1 if selected in (["percent_conversion"], ["unit_conversion"]) else 2)
            or len(facts.records) > 30 or (set(selected) & special and len(selected) != 1)):
        raise ValueError("direct arithmetic inputs or operations are unsupported")
    if any(name not in operand_orders for name in set(selected) & {"ratio", "difference", "divide", "subtract"}):
        raise ValueError("direct arithmetic operand order missing")
    if not (request.allow_python_execution and request.python_execution_approved):
        raise PermissionError("Python calculation requires approval")
    names = [row.name for row in facts.records]
    if len(set(names)) != len(names):
        raise ValueError("ambiguous duplicate user input names")
    units = {row.unit.casefold() for row in facts.records}
    if len(units) != 1 and not (set(selected) <= {"elapsed_time"} or set(selected) & special):
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
    special_code = ""
    special_expected: dict[str, float] = {}
    special_units: dict[str, str | None] = {}
    if set(selected) & special:
        special_code, special_expected, special_units = _special_direct(
            selected[0], request.goal or request.topic, values, {row.name: row.unit for row in facts.records})
    if "elapsed_time" in selected and not {"start_time", "end_time"} <= set(values):
        raise ValueError("elapsed time needs explicit start and end")
    if "geometric_mean" in selected and any(value <= 0 for value in values.values()):
        raise ValueError("geometric mean requires positive inputs")
    if any(name not in values for pair in operand_orders.values() for name in pair):
        raise ValueError("direct arithmetic operand is not a supplied fact")
    if any(operation in selected and values[operand_orders[operation][1]] == 0
           for operation in ("ratio", "divide")):
        raise ValueError("ratio denominator is zero")
    display_names = ({name: name.removesuffix("_rate") for name in values}
                     if all(name.endswith("_rate") for name in values) else
                     {name: name for name in values})
    code = (
        "import json\nimport math\nimport statistics\n" + f"values = {values!r}\n" +
        f"labels = {display_names!r}\n" +
        "numbers = list(values.values())\nresult = {}\n" +
        ("result['mean'] = sum(numbers) / len(numbers)\n" if "mean" in selected else "") +
        ("result['median'] = statistics.median(numbers)\n" if "median" in selected else "") +
        ("result['std_population'] = statistics.pstdev(numbers)\n" if "std_population" in selected else "") +
        ("result['std_sample'] = statistics.stdev(numbers)\n" if "std_sample" in selected else "") +
        ("result['variance_population'] = statistics.pvariance(numbers)\n" if "variance_population" in selected else "") +
        ("result['variance'] = statistics.pvariance(numbers)\n" if "variance" in selected else "") +
        ("result['geometric_mean'] = statistics.geometric_mean(numbers)\n" if "geometric_mean" in selected else "") +
        ("result['sum'] = sum(numbers)\n" if "sum" in selected else "") +
        ("result['add'] = sum(numbers)\n" if "add" in selected else "") +
        ("result['multiply'] = math.prod(numbers)\n" if "multiply" in selected else "") +
        (f"result['divide'] = values[{operand_orders['divide'][0]!r}] / values[{operand_orders['divide'][1]!r}]\n"
         if "divide" in selected else "") +
        (f"result['subtract'] = values[{operand_orders['subtract'][0]!r}] - values[{operand_orders['subtract'][1]!r}]\n"
         if "subtract" in selected else "") +
        ("result['elapsed_time'] = (values['end_time'] - values['start_time']) % 1440\n" if "elapsed_time" in selected else "") +
        ("result['percent_conversion'] = numbers[0] / 100 if "
         + repr(bool(facts.records[0].unit == "%")) + " else numbers[0] * 100\n"
         if "percent_conversion" in selected else "") +
        special_code +
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
    if "median" in selected:
        expected["median"] = __import__("statistics").median(numbers)
    if "std_population" in selected:
        expected["std_population"] = __import__("statistics").pstdev(numbers)
    if "std_sample" in selected:
        expected["std_sample"] = __import__("statistics").stdev(numbers)
    if "variance_population" in selected:
        expected["variance_population"] = __import__("statistics").pvariance(numbers)
    if "variance" in selected:
        expected["variance"] = __import__("statistics").pvariance(numbers)
    if "geometric_mean" in selected:
        expected["geometric_mean"] = math.exp(sum(math.log(value) for value in numbers) / len(numbers))
    if "sum" in selected:
        expected["sum"] = sum(numbers)
    if "add" in selected:
        expected["add"] = sum(numbers)
    if "multiply" in selected:
        expected["multiply"] = math.prod(numbers)
    if "divide" in selected:
        left, right = operand_orders["divide"]
        expected["divide"] = values[left] / values[right]
    if "subtract" in selected:
        left, right = operand_orders["subtract"]
        expected["subtract"] = values[left] - values[right]
    if "elapsed_time" in selected:
        expected["elapsed_time"] = (values["end_time"] - values["start_time"]) % 1440
    if "percent_conversion" in selected:
        expected["percent_conversion"] = numbers[0] / 100 if facts.records[0].unit == "%" else numbers[0] * 100
    expected.update(special_expected)
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
        "unit": (special_units[name] if name in special_units else
                 "%" if name == "percent_conversion" and facts.records[0].unit != "%" else
                 None if isinstance(value, list) or name in {"ratio", "divide", "percent_conversion"} else
                 "min" if name == "elapsed_time" else
                 f"({facts.records[0].unit})^2" if name in {"variance", "variance_population"} and facts.records[0].unit else
                 facts.records[0].unit or None),
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
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,40}", spec.output_name):
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
