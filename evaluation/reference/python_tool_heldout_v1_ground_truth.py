"""Independent deterministic derivation of frozen Python-tool held-out targets.

This script never imports the Agent's calculation code or reads model outputs.
"""

from __future__ import annotations

import json
import math
from pathlib import Path


BENCHMARK = Path(__file__).resolve().parents[1] / "python_tool_heldout_v1.json"


def ols(depth: list[int], pressure: list[int]) -> tuple[float, float, list[float]]:
    dmean = sum(depth) / len(depth)
    pmean = sum(pressure) / len(pressure)
    slope = sum((d - dmean) * (p - pmean) for d, p in zip(depth, pressure)) / sum(
        (d - dmean) ** 2 for d in depth
    )
    intercept = pmean - slope * dmean
    residuals = [p - (intercept + slope * d) for d, p in zip(depth, pressure)]
    return slope, math.sqrt(sum(r * r for r in residuals) / len(residuals)), residuals


def derive(task: dict) -> dict[str, float]:
    x = task["ground_truth"]["input_values"]
    match task["task_id"]:
        case "PY-RE-001":
            products = [h * k for h, k in zip(x["h_ft"], x["k_mD"])]
            total = sum(products)
            return {"total_thickness": sum(x["h_ft"]), "k_effective": total / sum(x["h_ft"]),
                    **{f"L{i}_kh_share": 100 * products[i - 1] / total for i in (6, 4, 2)}}
        case "PY-RE-002":
            lengths, perms = x["L_ft"], x["k_mD"]
            harmonic = sum(lengths) / sum(length / k for length, k in zip(lengths, perms))
            arithmetic = sum(length * k for length, k in zip(lengths, perms)) / sum(lengths)
            return {"k_series": harmonic, "k_arithmetic": arithmetic,
                    "arithmetic_overstatement": 100 * (arithmetic / harmonic - 1)}
        case "PY-RE-003":
            return {f"J_{letter}": q / (pe - pw) for letter, q, pe, pw in zip(
                "ABCDE", x["q_STB_day"], x["pe_psia"], x["pw_psia"])}
        case "PY-RE-004":
            def volume(phi: float, sw: float, bo: float) -> float:
                return x["A_m2"] * x["h_m"] * phi * (1 - sw) / bo
            base = volume(x["phi"], x["Sw"], x["Bo"])
            cases = {"high_Sw": volume(x["phi"], x["case_Sw"], x["Bo"]),
                     "low_phi": volume(x["case_phi"], x["Sw"], x["Bo"]),
                     "high_Bo": volume(x["phi"], x["Sw"], x["case_Bo"])}
            return {"base_STOIIP": base,
                    **{f"{name}_STOIIP": value for name, value in cases.items()},
                    **{f"{name}_delta": 100 * (value / base - 1) for name, value in cases.items()}}
        case "PY-WT-005":
            slope, rmse, residuals = ols(x["depth_ft"], x["pressure_psia"])
            return {"global_slope": slope, "pressure_RMSE": rmse,
                    "largest_residual_depth": x["depth_ft"][max(range(len(residuals)), key=lambda i: abs(residuals[i]))]}
        case "PY-RE-006":
            in_place = [a * h * phi * (1 - sw) / bo for a, h, phi, sw, bo, rf in x["blocks"]]
            recovered = [volume * row[-1] for volume, row in zip(in_place, x["blocks"])]
            return {**{f"{name}_STOIIP": value for name, value in zip(("North", "Central", "South"), in_place)},
                    **{f"{name}_recoverable": value for name, value in zip(("North", "Central", "South"), recovered)},
                    "total_recoverable": sum(recovered)}
        case "PY-RE-007":
            return {"additional_recoverable": x["STOIIP_stock_tank_m3"] * (x["RF_high"] - x["RF_low"])}
        case "PY-WT-008":
            return {"gradient_difference": x["gradient_b_psi_ft"] - x["gradient_a_psi_ft"]}
        case "PY-WT-009" | "PY-WT-010":
            return {}
        case _:
            raise ValueError(task["task_id"])


def main() -> None:
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    for task in benchmark["tasks"]:
        computed = derive(task)
        expected = {target["name"]: target for target in task["ground_truth"]["numeric_targets"]}
        assert computed.keys() == expected.keys(), task["task_id"]
        for name, value in computed.items():
            target = expected[name]
            assert math.isclose(value, target["value"], abs_tol=target["abs_tolerance"], rel_tol=0), (
                task["task_id"], name, value, target["value"]
            )
            print(f"{task['task_id']} {name} = {value:.9g} {target['unit']}")
    print("Independent ground truth agrees with every frozen target.")


if __name__ == "__main__":
    main()
