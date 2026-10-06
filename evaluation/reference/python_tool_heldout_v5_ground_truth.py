"""Independent held-out arithmetic. No product, retrieval, LLM, or CALC imports."""

from __future__ import annotations

import statistics


def numeric(name: str, value: float, unit: str, *, scenario: str | None = None) -> dict:
    row = {"semantic_name": name, "target_type": "numeric", "value": float(value),
           "unit": unit, "abs_tolerance": 0.01}
    if scenario:
        row["scenario_id"] = scenario
    return row


def ranked(values: dict[str, float], output: str, *, descending: bool = True) -> list[dict]:
    order = sorted(values, key=lambda case: ((-values[case] if descending else values[case]), case))
    return [
        {"semantic_name": f"{output}_ranking", "target_type": "ranking", "value": order,
         "unit": None, "ranking_of": {case: f"{case}_{output}" for case in values},
         "order": "desc" if descending else "asc"},
        {"semantic_name": f"{output}_leader", "target_type": "label", "value": order[0],
         "unit": None, "extremum": "max" if descending else "min",
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
    if task_id == "PT5-RE-D1":
        values = {case: inputs[f"{case}_y"] / inputs[f"{case}_x"] for case in "ABCD"}
        return series(values, "K", "dimensionless")
    if task_id == "PT5-WT-D2":
        values = {case: inputs[f"{case}_tD"] / inputs[f"{case}_CD"] for case in "ABCD"}
        return series(values, "pD", "dimensionless")
    if task_id == "PT5-FE-D3":
        values = {case: inputs[f"{case}_Rt"] / inputs[f"{case}_F"] for case in "ABCD"}
        return series(values, "Rwa_index", "dimensionless")
    if task_id == "PT5-WT-D4":
        values = {case: inputs[f"{case}_derivative"] for case in "ABCDEFGH"}
        maximum = max(values.values())
        result = [numeric(f"{case}_normalized", value / maximum, "dimensionless", scenario=case)
                  for case, value in values.items()]
        result.extend([
            numeric("mean_derivative", statistics.mean(values.values()), "psi"),
            numeric("median_derivative", statistics.median(values.values()), "psi"),
            numeric("population_sd", statistics.pstdev(values.values()), "psi"),
            numeric("derivative_range", maximum - min(values.values()), "psi"),
            numeric("coefficient_of_variation", statistics.pstdev(values.values()) /
                    statistics.mean(values.values()), "dimensionless"),
        ])
        result.append({"semantic_name": "derivative_ranking", "target_type": "ranking",
                       "value": sorted(values, key=lambda case: (-values[case], case)), "unit": None,
                       "ranking_of": {case: f"{case}_normalized" for case in values}, "order": "desc"})
        return result
    if task_id == "PT5-RE-R1":
        values = {case: inputs[f"{case}_Vgi"] - inputs[f"{case}_DVg"] for case in "ABCD"}
        return series(values, "Vg", "bbl")
    if task_id == "PT5-RE-R2":
        pf = evidence["R74_fluid_pressure_psi"]
        values = {case: pf + inputs[f"{case}_Pc"] for case in "ABCD"}
        return series(values, "Po", "psi")
    if task_id == "PT5-WT-E1":
        rates = {"A": evidence["W169_rate"], "B": evidence["W171_rate"],
                 "C": evidence["W172_rate"]}
        pairs = {"AB": rates["A"] + rates["B"], "AC": rates["A"] + rates["C"],
                 "BC": rates["B"] + rates["C"]}
        return series(pairs, "paired_rate", "stb/d")
    if task_id == "PT5-FE-E2":
        saturations = {"A": evidence["F169_water_saturation"],
                       "B": evidence["F235_water_saturation"],
                       "C": evidence["F268_water_saturation"]}
        nonwater = {case: 100 - value for case, value in saturations.items()}
        result = series(nonwater, "nonwater_percent", "percent")
        result.extend([
            numeric("mean_water_saturation", statistics.mean(saturations.values()), "percent"),
            numeric("water_saturation_range", max(saturations.values()) - min(saturations.values()),
                    "percentage_point"),
        ])
        return result
    if task_id == "PT5-RE-O1":
        return [numeric("overburden_pressure", inputs["fluid_pressure"] + inputs["compacting_stress"], "psi")]
    if task_id == "PT5-WT-O2":
        return [numeric("water_saturation", 1 - inputs["residual_oil_saturation"], "dimensionless")]
    if task_id in {"PT5-RE-N1", "PT5-FE-N2"}:
        return []
    raise KeyError(task_id)
