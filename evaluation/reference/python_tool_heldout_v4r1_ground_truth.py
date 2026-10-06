"""Independent arithmetic for heldout v4r1; no product or LLM imports."""

from __future__ import annotations

import math
import statistics


def numeric(name: str, value: float, unit: str, tolerance: float = 0.02, **extra: object) -> dict:
    return {"semantic_name": name, "target_type": "numeric", "value": float(value),
            "unit": unit, "abs_tolerance": tolerance, **extra}


def label(name: str, value: str | list[str] | bool, **extra: object) -> dict:
    kind = "ranking" if "ranking_of" in extra else "label_list" if isinstance(value, list) else "boolean" if isinstance(value, bool) else "label"
    return {"semantic_name": name, "target_type": kind, "value": value, "unit": None, **extra}


def reference_outputs(task_id: str, inputs: dict[str, float], evidence: dict[str, float]) -> list[dict]:
    """Calculate every scored result solely from authored inputs and sourced facts."""
    result: list[dict] = []
    if task_id.endswith("RE-P1"):
        totals = {}
        for case in ("A", "B", "C", "D"):
            value = sum(inputs[f"{case}_{term}"] for term in ("NEo", "NmEg", "NEfw", "We"))
            totals[case] = value
            result.append(numeric(f"{case}_F", value, "bbl", scenario_id=case))
        result += [numeric("mean_F", statistics.mean(totals.values()), "bbl"),
                   numeric("max_F", max(totals.values()), "bbl"),
                   label("max_period", max(totals, key=totals.get), extremum="max", extremum_of={case: f"{case}_F" for case in totals})]
    elif task_id.endswith("RE-P2"):
        taps = {}
        for case in ("I1", "I2", "I3", "I4"):
            ta, tb = inputs[f"{case}_Ta"], inputs[f"{case}_Tb"]
            value = 1 / (1 / ta + 1 / tb)
            taps[case] = value
            result.append(numeric(f"{case}_Tap", value, "dimensionless", 0.001, scenario_id=case))
        result += [numeric("mean_Tap", statistics.mean(taps.values()), "dimensionless", 0.001),
                   numeric("max_Tap", max(taps.values()), "dimensionless", 0.001),
                   label("top_interfaces", [case for case, value in taps.items() if math.isclose(value, max(taps.values()))],
                         extremum="max", extremum_of={case: f"{case}_Tap" for case in taps}, tie_set=True),
                   label("interface_ranking", sorted(taps, key=lambda case: (-taps[case], case)),
                         ranking_of={case: f"{case}_Tap" for case in taps}, order="desc")]
    elif task_id.endswith("WT-P3"):
        pressures = {}
        for well in ("A", "B", "C", "D"):
            intercept = inputs[f"{well}_p0"]
            decline = -inputs[f"{well}_slope_psi_per_day"] * inputs[f"{well}_time"]
            pressures[well] = intercept - decline
            result.extend((numeric(f"{well}_Pwf", pressures[well], "psi", scenario_id=well),
                           numeric(f"{well}_drop", decline, "psi", scenario_id=well)))
        result += [numeric("mean_Pwf", statistics.mean(pressures.values()), "psi"),
                   label("lowest_Pwf_well", min(pressures, key=pressures.get), extremum="min",
                         extremum_of={well: f"{well}_Pwf" for well in pressures})]
    elif task_id.endswith("WT-P4"):
        slopes = []
        for index in range(1, 5):
            t0, t1 = inputs[f"D{index}_time"], inputs[f"D{index+1}_time"]
            p0, p1 = inputs[f"D{index}_derivative"], inputs[f"D{index+1}_derivative"]
            slope = math.log(p1 / p0) / math.log(t1 / t0)
            slopes.append(slope)
            result.append(numeric(f"segment_{index}_log_slope", slope, "dimensionless", 0.002, scenario_id=f"segment_{index}"))
        result += [numeric("mean_abs_log_slope", statistics.mean(map(abs, slopes)), "dimensionless", 0.002),
                   numeric("max_abs_log_slope", max(map(abs, slopes)), "dimensionless", 0.002),
                   label("interpretation", "derivative_plateau_candidate" if max(map(abs, slopes)) < 0.05 else "not_plateau")]
    elif task_id.endswith("RE-P5"):
        thickness = evidence["P474_thickness_ft"]
        volumes = {case: inputs[f"{case}_area"] * thickness for case in ("B1", "B2", "B3", "B4")}
        result += [numeric(f"{case}_bulk_volume", value, "acre-ft", scenario_id=case) for case, value in volumes.items()]
        result += [numeric("total_bulk_volume", sum(volumes.values()), "acre-ft"),
                   label("largest_block", max(volumes, key=volumes.get), extremum="max",
                         extremum_of={case: f"{case}_bulk_volume" for case in volumes})]
    elif task_id.endswith("WT-P6"):
        times = [inputs[f"M{i}_time"] for i in range(1, 9)]
        pressures = [inputs[f"M{i}_pressure"] for i in range(1, 9)]
        tbar, pbar = statistics.mean(times), statistics.mean(pressures)
        slope = sum((t - tbar) * (p - pbar) for t, p in zip(times, pressures)) / sum((t - tbar) ** 2 for t in times)
        intercept = pbar - slope * tbar
        fitted = [intercept + slope * t for t in times]
        result += [numeric(f"M{i}_fitted", value, "psi", scenario_id=f"M{i}") for i, value in enumerate(fitted, 1)]
        result += [numeric("slope_psi_per_hour", slope, "psi/hour", 0.02),
                   numeric("intercept", intercept, "psi"),
                   numeric("rmse", math.sqrt(statistics.mean((a-b)**2 for a, b in zip(pressures, fitted))), "psi"),
                   numeric("forecast_10hr", intercept + slope * 10, "psi")]
    elif task_id.endswith("RE-E1"):
        ka, kb = evidence["S42_low_k_mD"], evidence["S42_high_k_mD"]
        da, db = evidence["S42_low_h_ft"], evidence["S42_high_h_ft"]
        taps = {}
        for case in ("J1", "J2"):
            area = inputs[f"{case}_area"]
            ta, tb = ka * area / (da / 2), kb * area / (db / 2)
            tap = 1 / (1 / ta + 1 / tb)
            taps[case] = tap
            for name, value in (("Ta", ta), ("Tb", tb), ("Tap", tap)):
                result.append(numeric(f"{case}_{name}", value, "mD*acre/ft", 0.01, scenario_id=case))
        result += [numeric("mean_Tap", statistics.mean(taps.values()), "mD*acre/ft", 0.01),
                   label("larger_Tap_interface", max(taps, key=taps.get), extremum="max",
                         extremum_of={case: f"{case}_Tap" for case in taps})]
    elif task_id.endswith("FE-E2"):
        high, low = evidence["F24_column_porosity_percent"], evidence["F24_close_porosity_percent"]
        positions = {}
        for index in range(1, 6):
            name = f"L{index}"
            positions[name] = (inputs[f"{name}_porosity"] - low) / (high - low)
            result.append(numeric(f"{name}_normalized_position", positions[name], "dimensionless", 0.002, scenario_id=name))
        result += [numeric("mean_normalized_position", statistics.mean(positions.values()), "dimensionless", 0.002),
                   numeric("within_bounds_count", sum(0 <= value <= 1 for value in positions.values()), "dimensionless", 0.01),
                   label("highest_position_log", max(positions, key=positions.get), extremum="max",
                         extremum_of={name: f"{name}_normalized_position" for name in positions})]
    elif task_id.endswith("RE-O1"):
        result = [numeric("single_F", sum(inputs.values()), "bbl")]
    elif task_id.endswith("WT-O2"):
        result = [numeric("single_Pwf", inputs["p0"] + inputs["slope_psi_per_day"] * inputs["time"], "psi")]
    elif not (task_id.endswith("RE-N1") or task_id.endswith("FE-N2")):
        raise KeyError(task_id)
    return result
