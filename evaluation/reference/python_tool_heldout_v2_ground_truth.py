"""Independent deterministic calculations for Python Tool Heldout v2.

This module never imports the product planner, code generator, or CALC output.
Inputs are frozen in evaluation/python_tool_heldout_v2.json.
"""

from __future__ import annotations

from statistics import mean


def expected_user_facts(task: dict) -> list[dict]:
    """Semantic input map authored from frozen GT, independent of product extraction."""
    values = task["ground_truth"]["input_values"]
    task_id = task["task_id"]
    facts: list[dict] = []

    def add(name: str, value: float, unit: str = "") -> None:
        facts.append({"name": name, "value": value, "unit": unit})

    if task_id == "PY2-RE-001":
        for row in values["layers"]:
            add(f"{row['id']}_thickness", row["h_ft"], "ft")
            add(f"{row['id']}_permeability", row["k_md"], "mD")
    elif task_id == "PY2-RE-002":
        for index, row in enumerate(values["segments"], 1):
            add(f"L{index}", row["length_ft"], "ft")
            add(f"k{index}", row["k_md"], "mD")
    elif task_id == "PY2-RE-003":
        for name, key, unit in (("A", "A_acres", "acres"), ("h", "h_ft", "ft"),
                                ("phi", "phi", ""), ("Sw", "Sw", ""), ("Bo", "Bo", ""),
                                ("h_alt", "h_alt_ft", "ft"), ("phi_alt", "phi_alt", ""),
                                ("Sw_alt", "Sw_alt", "")):
            add(name, values[key], unit)
    elif task_id == "PY2-RE-004":
        for index, row in enumerate(values["blocks"], 1):
            for prefix, key, unit in (("A", "A_acres", "acres"), ("h", "h_ft", "ft"),
                                      ("phi", "phi", ""), ("Sw", "Sw", ""),
                                      ("Bo", "Bo", ""), ("RF", "RF", "")):
                add(f"{prefix}{index}", row[key], unit)
    elif task_id == "PY2-WT-001":
        for row in values["wells"]:
            for name, key, unit in (("q", "q_stbd", "stb/d"), ("pr", "pr_psi", "psi"),
                                    ("pwf", "pwf_psi", "psi")):
                add(f"Well_{row['id']}_{name}", row[key], unit)
    elif task_id == "PY2-WT-002":
        for key, value in values["semilog_slopes_psi"].items():
            add(f"m{key}", value, "psi")
    elif task_id == "PY2-RE-005":
        add("STOIIP", values["stoiip_stb"], "STB")
        add("RF_initial", values["rf_initial"])
        add("RF_improved", values["rf_improved"])
    return facts


def derive(task: dict) -> dict[str, float]:
    values = task["ground_truth"]["input_values"]
    task_id = task["task_id"]
    if task_id == "PY2-RE-001":
        layers = values["layers"]
        total_h = sum(row["h_ft"] for row in layers)
        total_kh = sum(row["h_ft"] * row["k_md"] for row in layers)
        return {"total_thickness": total_h, "effective_k": total_kh / total_h,
                **{f"{row['id']}_contribution_pct": 100 * row["h_ft"] * row["k_md"] / total_kh for row in layers}}
    if task_id == "PY2-RE-002":
        segments = values["segments"]
        length = sum(row["length_ft"] for row in segments)
        resistance = sum(row["length_ft"] / row["k_md"] for row in segments)
        harmonic = length / resistance
        arithmetic = sum(row["length_ft"] * row["k_md"] for row in segments) / length
        return {"total_length": length, "series_k": harmonic, "arithmetic_k": arithmetic,
                "arithmetic_bias_pct": 100 * (arithmetic / harmonic - 1),
                "largest_resistance_share_pct": 100 * max(row["length_ft"] / row["k_md"] for row in segments) / resistance}
    if task_id == "PY2-RE-003":
        def volume(h: float, phi: float, sw: float) -> float:
            return 7758 * values["A_acres"] * h * phi * (1 - sw) / values["Bo"]
        base = volume(values["h_ft"], values["phi"], values["Sw"])
        high_h = volume(values["h_alt_ft"], values["phi"], values["Sw"])
        low_phi = volume(values["h_ft"], values["phi_alt"], values["Sw"])
        high_sw = volume(values["h_ft"], values["phi"], values["Sw_alt"])
        return {"base_stoiip": base, "thickness_case_stoiip": high_h,
                "porosity_case_stoiip": low_phi, "water_case_stoiip": high_sw,
                "thickness_delta_pct": 100 * (high_h / base - 1),
                "porosity_delta_pct": 100 * (low_phi / base - 1),
                "water_delta_pct": 100 * (high_sw / base - 1)}
    if task_id == "PY2-RE-004":
        recoverable = {row["id"]: 7758 * row["A_acres"] * row["h_ft"] * row["phi"] * (1 - row["Sw"]) / row["Bo"] * row["RF"] for row in values["blocks"]}
        total = sum(recoverable.values())
        return {**{f"{key}_recoverable": value for key, value in recoverable.items()},
                "total_recoverable": total, "largest_block_share_pct": 100 * max(recoverable.values()) / total}
    if task_id == "PY2-WT-001":
        productivity = {row["id"]: row["q_stbd"] / (row["pr_psi"] - row["pwf_psi"]) for row in values["wells"]}
        return {**{f"{key}_pi": value for key, value in productivity.items()},
                "pi_spread_pct": 100 * (max(productivity.values()) / min(productivity.values()) - 1)}
    if task_id == "PY2-WT-002":
        plateau = {key: value / 2.303 for key, value in values["semilog_slopes_psi"].items()}
        return {**{f"{key}_plateau": value for key, value in plateau.items()},
                "plateau_max_min_ratio": max(plateau.values()) / min(plateau.values())}
    if task_id == "PY2-WT-003":
        rows = values["sleipner_rows"]
        gaps = [abs(row["k1_md"] - row["k2_md"]) for row in rows]
        index = max(range(len(rows)), key=lambda i: gaps[i])
        return {"mean_k1": mean(row["k1_md"] for row in rows),
                "mean_k2": mean(row["k2_md"] for row in rows),
                "largest_k_gap": gaps[index], "largest_k_gap_depth": rows[index]["depth_m"],
                "endpoint_pressure_gradient": (rows[-1]["pressure_psi"] - rows[0]["pressure_psi"]) / (rows[-1]["depth_m"] - rows[0]["depth_m"])}
    if task_id == "PY2-WT-004":
        early, late = values["early_rows"], values["late_rows"]
        early_mean = mean(row["pressure_psi"] for row in early)
        late_mean = mean(row["pressure_psi"] for row in late)
        return {"early_mean_pressure": early_mean, "late_mean_pressure": late_mean,
                "late_minus_early_mean": late_mean - early_mean,
                "early_endpoint_rate": (early[-1]["pressure_psi"] - early[0]["pressure_psi"]) / (early[-1]["time_hr"] - early[0]["time_hr"]),
                "late_endpoint_rate": (late[-1]["pressure_psi"] - late[0]["pressure_psi"]) / (late[-1]["time_hr"] - late[0]["time_hr"])}
    if task_id == "PY2-RE-005":
        base, improved = values["stoiip_stb"], values["rf_improved"]
        initial = base * values["rf_initial"]
        return {"incremental_recoverable": base * improved - initial,
                "recoverable_change_pct": 100 * (improved / values["rf_initial"] - 1)}
    if task_id == "PY2-WT-005":
        low, high = values["gradient_low"], values["gradient_high"]
        return {"gradient_difference": high - low, "gradient_change_pct": 100 * (high / low - 1)}
    return {}
