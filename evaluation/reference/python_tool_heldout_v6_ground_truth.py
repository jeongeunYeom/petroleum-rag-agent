"""Independent held-out arithmetic. No product, retrieval, LLM, or CALC imports."""

from __future__ import annotations

import math
import statistics


def numeric(name: str, value: float, unit: str, *, scenario: str | None = None) -> dict:
    row = {"semantic_name": name, "target_type": "numeric", "value": float(value),
           "unit": unit, "abs_tolerance": 0.01}
    if scenario:
        row["scenario_id"] = scenario
    return row


def ranked(values: dict[str, float], output: str) -> list[dict]:
    order = sorted(values, key=lambda case: (-values[case], case))
    return [
        {"semantic_name": f"{output}_ranking", "target_type": "ranking", "value": order,
         "unit": None, "ranking_of": {case: f"{case}_{output}" for case in values}, "order": "desc"},
        {"semantic_name": f"{output}_leader", "target_type": "label", "value": order[0],
         "unit": None, "extremum": "max",
         "extremum_of": {case: f"{case}_{output}" for case in values}},
    ]


def series(values: dict[str, float], output: str, unit: str) -> list[dict]:
    rows = [numeric(f"{case}_{output}", value, unit, scenario=case) for case, value in values.items()]
    rows.extend([
        numeric(f"mean_{output}", statistics.mean(values.values()), unit),
        numeric(f"max_{output}", max(values.values()), unit),
        numeric(f"min_{output}", min(values.values()), unit),
        numeric(f"range_{output}", max(values.values()) - min(values.values()), unit),
    ])
    rows.extend(ranked(values, output))
    return rows


def reference_outputs(task_id: str, inputs: dict[str, float], evidence: dict[str, float]) -> list[dict]:
    if task_id == "PT6-RE-G1":
        values = {case: (inputs[f"{case}_initial"] - inputs[f"{case}_final"]) /
                  inputs[f"{case}_initial"] * 100 for case in "ABCD"}
        initial = sum(inputs[f"{case}_initial"] for case in "ABCD")
        final = sum(inputs[f"{case}_final"] for case in "ABCD")
        return series(values, "decline_pct", "percent") + [
            numeric("combined_initial_rate", initial, "stb/d"),
            numeric("combined_final_rate", final, "stb/d"),
            numeric("fleet_weighted_decline_pct", (initial - final) / initial * 100, "percent"),
        ]
    if task_id == "PT6-WT-G2":
        signed = {case: inputs[f"{case}_observed"] - inputs[f"{case}_reference"] for case in "ABCD"}
        magnitude = {case: abs(value) for case, value in signed.items()}
        rows = [numeric(f"{case}_signed_error", signed[case], "psi", scenario=case) for case in "ABCD"]
        rows.extend(numeric(f"{case}_abs_error", magnitude[case], "psi", scenario=case) for case in "ABCD")
        rows.extend([
            numeric("mean_signed_bias", statistics.mean(signed.values()), "psi"),
            numeric("mean_abs_error", statistics.mean(magnitude.values()), "psi"),
            numeric("rms_error", math.sqrt(statistics.mean(v * v for v in signed.values())), "psi"),
            numeric("max_abs_error", max(magnitude.values()), "psi"),
        ])
        return rows + ranked(magnitude, "abs_error")
    if task_id == "PT6-RE-S1":
        return series({case: inputs[f"{case}_re"] / inputs[f"{case}_rw"] for case in "ABCD"},
                      "reD", "dimensionless")
    if task_id == "PT6-WT-S2":
        return series({case: 10 / inputs[f"{case}_T2"] for case in "ABCD"}, "q2", "cc/s")
    if task_id == "PT6-FE-S3":
        return series({case: inputs[f"{case}_MPHI"] + inputs[f"{case}_MCBW"] for case in "ABCD"},
                      "MSIG", "percent")
    if task_id == "PT6-RE-R1":
        return series({case: inputs[f"{case}_kg"] /
                       (1 + inputs[f"{case}_b"] / inputs[f"{case}_p"]) for case in "ABCD"},
                      "kL", "mD")
    if task_id == "PT6-RE-E1":
        values = {
            "C13": evidence["C13_re"] / evidence["C13_rw"],
            "C14": evidence["C14_re"] / evidence["C14_rw"],
        }
        return series(values, "reD", "dimensionless") + [
            numeric("C13_to_C14_reD_ratio", values["C13"] / values["C14"], "dimensionless")
        ]
    if task_id == "PT6-WT-E2":
        values = {
            "A": evidence["L1_k"] * evidence["L1_h"],
            "B": evidence["L2_k"] * evidence["L2_h"],
            "C": evidence["L3_k"] * evidence["L3_h"],
            "D": evidence["D_k"] * evidence["D_h"],
        }
        return series(values, "kh_proxy", "mD-ft")
    if task_id == "PT6-RE-O1":
        return [numeric("drawdown", inputs["initial_pressure"] - inputs["flowing_pressure"], "psi")]
    if task_id == "PT6-FE-O2":
        return [numeric("porosity_shortfall", inputs["target_porosity"] -
                        evidence["crossplot_porosity"], "percentage_point")]
    if task_id in {"PT6-WT-N1", "PT6-FE-N2"}:
        return []
    raise KeyError(task_id)
