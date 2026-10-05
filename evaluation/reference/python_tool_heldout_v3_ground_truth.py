"""Independent, deterministic arithmetic for the frozen v3 evaluation.

This module deliberately imports no product planner, Python tool, or CALC code.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "evaluation/python_tool_heldout_v3.json"
CATALOG = ROOT / "evaluation/python_tool_heldout_v3_source_catalog.json"
EXCLUSIONS = ROOT / "evaluation/review/python_tool_heldout_v3_source_exclusions.json"


def calculate(task: dict) -> dict[str, float]:
    """Calculate only from the frozen GT inputs, never an agent output."""
    data = task["ground_truth"]["input_values"]
    key = task["task_id"]
    if key == "PY3-RE-01":
        result = {f"{label}_Bt": bo + bg * (rsb - rs) for label, bo, bg, rsb, rs in data["cases"]}
        result["mean_Bt"] = statistics.mean(result.values())
        return result
    if key == "PY3-RE-02":
        result = {f"{label}_z": p * v / (n * data["R"] * temp) for label, p, v, n, temp in data["cases"]}
        result["mean_z"] = statistics.mean(result.values())
        return result
    if key == "PY3-RE-03":
        result = {
            f"{label}_mu": 10 ** (10 ** (3.0324 - 0.0202 * api - 1.163 * math.log10(temp))) - 1
            for label, api, temp in data["cases"]
        }
        result["max_min_ratio"] = max(result.values()) / min(result.values())
        return result
    if key == "PY3-FE-04":
        result = {}
        for label, phi, rt in data["zones"]:
            factor = data["a"] / phi ** data["m"]
            result[f"{label}_F"] = factor
            result[f"{label}_Sw"] = (factor * data["Rw"] / rt) ** (1 / data["n"])
        return result
    if key == "PY3-RE-05":
        result = {}
        for label, api in data["samples"]:
            sg = 141.5 / (api + 131.5)
            result[f"{label}_SG"] = sg
            result[f"{label}_density"] = sg * data["rho_water"]
        return result
    if key == "PY3-WT-06":
        hours, pressures = data["hours"], data["pressures_psia"]
        avg_hour, avg_pressure = statistics.mean(hours), statistics.mean(pressures)
        slope = sum((x - avg_hour) * (y - avg_pressure) for x, y in zip(hours, pressures)) / sum(
            (x - avg_hour) ** 2 for x in hours
        )
        return {
            "mean_pressure": avg_pressure,
            "population_std": statistics.pstdev(pressures),
            "ols_slope": slope,
            "endpoint_rise": pressures[-1] - pressures[0],
        }
    if key == "PY3-RE-07":
        temp_pc = sum(y * tc for _, y, tc, _ in data["rows"])
        pressure_pc = sum(y * pc for _, y, _, pc in data["rows"])
        return {"Tpc": temp_pc, "Ppc": pressure_pc, "Tpr": data["T"] / temp_pc, "Ppr": data["P"] / pressure_pc}
    if key == "PY3-FE-08":
        result = {f"{name}_phi": (rho_ma - data["rho_b"]) / (rho_ma - data["rho_f"]) for name, rho_ma in data["rows"]}
        result["admissible_count"] = sum(0 <= phi <= 1 for phi in result.values())
        return result
    if key == "PY3-RE-09":
        delta = data["high"] - data["low"]
        return {"absolute_difference": delta, "relative_difference": 100 * delta / data["low"]}
    if key == "PY3-WT-10":
        return {"decline": data["initial"] - data["later"]}
    if key in {"PY3-RE-11", "PY3-WT-12"}:
        return {}
    raise ValueError(f"Unknown task: {key}")


def validate() -> dict[str, int]:
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    exclusions = json.loads(EXCLUSIONS.read_text(encoding="utf-8"))["excluded"]
    tasks = benchmark["tasks"]
    assert len(tasks) == 12
    assert len({task["task_id"] for task in tasks}) == 12
    expected = Counter(task["python_expected"] for task in tasks)
    strata = Counter(task["evaluation_stratum"] for task in tasks)
    assert expected == {"required": 8, "optional": 2, "not_needed": 2}
    assert strata == {"pipeline": 6, "end_to_end": 2, "optional": 2, "not_needed": 2}
    domains = Counter("reservoir_engineering" if task["domain"] == "reservoir_engineering" else "well_test_or_formation" for task in tasks)
    assert min(domains.values()) >= 5
    assert sum(len(task["ground_truth"]["numeric_targets"]) for task in tasks if task["python_expected"] == "required") >= 45
    assert sum(len(task["ground_truth"]["numeric_targets"]) for task in tasks if task["evaluation_stratum"] == "pipeline") >= 32
    assert sum(bool(task["ground_truth"]["expected_evidence_facts"]) for task in tasks if task["python_expected"] == "required") >= 3
    assert sum(bool(task["ground_truth"]["expected_formula_source"]) for task in tasks if task["python_expected"] == "required") >= 6
    excluded_pages = {(row["document"], row["page"]) for row in exclusions}
    assert not excluded_pages.intersection((row["document"], row["page"]) for row in catalog.values())
    for task in tasks:
        criteria = task["success_criteria"]
        assert 3 <= len(criteria) <= 5
        assert len({item["criterion_id"] for item in criteria}) == len(criteria)
        gt = task["ground_truth"]
        assert all(source in catalog for source in gt["formula_sources"])
        assert all(fact["source_id"] in catalog for fact in gt["expected_evidence_facts"])
        if gt["expected_formula_source"]:
            assert gt["expected_formula_source"]["source_id"] in catalog
        calculated = calculate(task)
        targets = {item["name"]: item for item in gt["numeric_targets"]}
        assert calculated.keys() == targets.keys(), task["task_id"]
        for name, actual in calculated.items():
            target = targets[name]
            assert target["unit"] and target["abs_tolerance"] > 0
            assert abs(actual - target["value"]) <= min(target["abs_tolerance"], 1e-4 * max(1, abs(actual))), (task["task_id"], name)
    return {"tasks": len(tasks), "required_targets": sum(len(t["ground_truth"]["numeric_targets"]) for t in tasks if t["python_expected"] == "required"), "pipeline_targets": sum(len(t["ground_truth"]["numeric_targets"]) for t in tasks if t["evaluation_stratum"] == "pipeline")}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
