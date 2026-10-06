"""Independent, frozen arithmetic for Python Tool Heldout v4.

No agent calculation, runtime contract, or CALC output is imported here.
"""

from __future__ import annotations

from statistics import mean, median, pstdev


def expected_outputs(task_id: str) -> dict[str, float]:
    if task_id == "PT4-RE-P1":
        oil = [3512, 3491, 3567, 3438, 3611, 3479, 3544, 3397]
        water = [3486, 3460, 3535, 3411, 3574, 3450, 3507, 3365]
        values = [a - b for a, b in zip(oil, water)]
        return {**{f"C{i}_Pc": v for i, v in enumerate(values, 1)},
                "mean_Pc": mean(values), "max_Pc": max(values)}
    if task_id == "PT4-RE-P2":
        pore = [138, 154, 127, 169, 141, 183, 132, 176]
        bulk = [620, 710, 590, 790, 660, 840, 605, 810]
        values = [a / b for a, b in zip(pore, bulk)]
        return {**{f"C{i}_phi": v for i, v in enumerate(values, 1)},
                "mean_phi": mean(values), "spread_phi": max(values) - min(values)}
    if task_id == "PT4-FE-P3":
        sim = [.58, .64, .55, .71, .62, .68, .60, .73]
        shale = [.11, .16, .09, .20, .13, .18, .12, .22]
        values = [(a - b) / (1 - b) for a, b in zip(sim, shale)]
        return {**{f"Z{i}_Sw": v for i, v in enumerate(values, 1)},
                "mean_Sw": mean(values), "range_Sw": max(values) - min(values)}
    if task_id == "PT4-WT-P4":
        oil = [440, 515, 390, 605, 480, 550, 420, 575]
        water = [95, 180, 130, 245, 125, 210, 160, 260]
        total = [a + b for a, b in zip(oil, water)]
        return {**{f"T{i}_qt": v for i, v in enumerate(total, 1)},
                "total_oil": sum(oil), "total_water": sum(water),
                "total_liquid": sum(total), "aggregate_watercut": 100 * sum(water) / sum(total)}
    if task_id == "PT4-RE-P5":
        pressures = [1210, 1775, 2290, 2875, 3330, 3925]
        values = [p / 668.4 for p in pressures]
        return {**{f"S{i}_Ppr": v for i, v in enumerate(values, 1)},
                "mean_Ppr": mean(values), "range_Ppr": max(values) - min(values)}
    if task_id == "PT4-FE-P6":
        values = [16.4, 18.1, 17.7, 21.2, 19.6, 14.8, 23.4, 20.5, 18.9, 22.1, 17.2, 19.3]
        return {**{f"D{i}_phi": v for i, v in enumerate(values, 1)},
                "mean_phi": mean(values), "median_phi": median(values),
                "population_sd": pstdev(values), "above_20_count": sum(x > 20 for x in values)}
    if task_id == "PT4-RE-E1":
        volumes = [8450, 9120, 10875, 7650, 11940, 9825]
        values = [v * .22 for v in volumes]
        return {**{f"B{i}_Vp": v for i, v in enumerate(values, 1)},
                "total_Vp": sum(values), "mean_Vp": mean(values)}
    if task_id == "PT4-WT-E2":
        pressures = [3600, 3450, 3250, 3050, 2800, 2550]
        stress = [9000 - p for p in pressures]
        return {**{f"Y{i}_stress": v for i, v in enumerate(stress, 1)},
                "mean_stress": mean(stress), "max_stress": max(stress),
                "observed_stress_change": 5000 - 2000}
    if task_id == "PT4-RE-O1":
        return {"Pc": 24.0}
    if task_id == "PT4-WT-O2":
        return {"qt": 655.0}
    if task_id in {"PT4-RE-N1", "PT4-WT-N2"}:
        return {}
    raise KeyError(task_id)
