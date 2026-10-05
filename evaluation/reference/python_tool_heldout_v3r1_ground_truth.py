"""Independent arithmetic reference for the frozen v3r1 benchmark."""

from __future__ import annotations

import math
from statistics import mean


def expected_outputs(task_id: str) -> dict[str, float]:
    if task_id == "PY3R1-RE-01":
        values = dict(zip("ABCDE", [144 / 120, 183 / 150, 262.5 / 175, 99 / 90, 213 / 180]))
        return {**{f"{k}_Bo": v for k, v in values.items()}, "mean_Bo": mean(values.values())}
    if task_id == "PY3R1-RE-02":
        values = {k: (100 - swi - sgr) / (100 - swi) for k, swi, sgr in
                  zip("ABCDE", [18, 24, 30, 12, 22], [12, 9, 18, 8, 15])}
        return {**{f"{k}_ED": v for k, v in values.items()}, "mean_ED": mean(values.values())}
    if task_id == "PY3R1-RE-03":
        values = {k: sg / (100 - swi - sorw) for k, sg, swi, sorw in
                  zip("ABCDE", [6, 12, 8, 15, 4], [24, 30, 26, 22, 18], [18, 20, 14, 18, 12])}
        return {f"{k}_Fpvg": v for k, v in values.items()}
    if task_id == "PY3R1-WT-04":
        return {f"{k}_Sa": sd + sp for k, sd, sp in
                zip("ABCDE", [4.2, 2.6, -1.5, 6.1, 0.4], [1.4, 2.8, 3.2, -0.8, 4.5])}
    if task_id == "PY3R1-WT-05":
        return {"reference_A": 1 / 0.05, **{f"V{i}_A": 1 / kv for i, kv in
                enumerate([0.04, 0.08, 0.2, 0.5], 1)}}
    if task_id == "PY3R1-WT-06":
        first = [3100, 3120, 3085, 3150, 3200, 3175, 3225, 3050, 3300, 3250]
        repeat = [3101, 3118, 3086, 3154, 3199, 3175, 3222, 3051, 3296, 3252]
        delta = [abs(a - b) for a, b in zip(first, repeat)]
        return {**{f"R{i}_abs": v for i, v in enumerate(delta, 1)},
                "mean_absolute": mean(delta), "rms": math.sqrt(mean(v * v for v in delta))}
    if task_id == "PY3R1-RE-07":
        sums = {k: 48626 + a + b for k, a, b in
                zip("ABCD", [21600, 17500, 34000, 11200], [18400, 12500, 28000, 9400])}
        return {**{f"{k}_total_We": v for k, v in sums.items()},
                "C_percent_increment": 100 * (sums["C"] - 48626) / 48626}
    if task_id == "PY3R1-WT-08":
        return {"early_radial_example_A": 200 / 2, "prf3_example_A": 100 / 10,
                "contrast": (200 / 2) / (100 / 10)}
    if task_id == "PY3R1-RE-09":
        return {"gap_pp": 21 - 18, "relative_gap": 100 * (21 - 18) / 18}
    if task_id == "PY3R1-WT-10":
        return {"increase": 1 - (-2.5)}
    if task_id in {"PY3R1-RE-11", "PY3R1-WT-12"}:
        return {}
    raise KeyError(task_id)
