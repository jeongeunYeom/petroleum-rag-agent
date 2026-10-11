"""Bounded dimensional operations over literal user facts only."""

from __future__ import annotations

import math
import re


OPERATIONS = {"unit_conversion", "finite_difference", "centered_difference",
              "linear_regression_slope", "percentage_decrease", "net_difference",
              "cylinder_volume", "power_times_duration", "concentration_mass_per_volume",
              "weighted_average_by_duration"}


def build(operation: str, text: str, values: dict[str, float],
          units: dict[str, str]) -> tuple[str, dict[str, float], dict[str, str | None]]:
    """Return executable code and separately checked expected outputs; reject ambiguity."""
    if operation == "unit_conversion":
        supplied = [(name, unit) for name, unit in units.items() if unit and "factor" not in name]
        if len(supplied) != 1:
            raise ValueError("unit conversion needs one unambiguous input")
        name, source = supplied[0]
        target_match = re.search(r"\b(?:to|into|in)\s+(stb/h|stb/d|m3/h|m3/d|ft|in|h|d)\b|"
                                 r"(시간당|일당|피트로|인치로)", text, re.I)
        target = target_match.group(1) if target_match else None
        if target_match and not target:
            cue = target_match.group(2)
            target = {"시간당": {"stb/d": "stb/h", "m3/d": "m3/h"},
                      "일당": {"stb/h": "stb/d", "m3/h": "m3/d"},
                      "피트로": {"in": "ft"}, "인치로": {"ft": "in"}}.get(cue, {}).get(source)
        factors = {("stb/d", "stb/h"): 1 / 24, ("stb/h", "stb/d"): 24,
                   ("m3/d", "m3/h"): 1 / 24, ("m3/h", "m3/d"): 24,
                   ("d", "h"): 24, ("h", "d"): 1 / 24,
                   ("in", "ft"): 1 / 12, ("ft", "in"): 12}
        if (source, target) not in factors:
            raise ValueError("unsupported or ambiguous unit conversion")
        factor = values.get("conversion_factor", factors[source, target])
        return (f"result['unit_conversion'] = values[{name!r}] * {factor!r}\n",
                {"unit_conversion": values[name] * factor}, {"unit_conversion": target})

    if operation in {"finite_difference", "centered_difference", "linear_regression_slope"}:
        points = sorted((float(key[4:]) if key.startswith("day_") else
                         float(key[6:].replace("n", "-").replace("p", ".")), value)
                        for key, value in values.items()
                        if re.fullmatch(r"day_\d+|point_[np\d]+", key))
        minimum = 2 if operation == "finite_difference" else 3
        if len(points) < minimum or len({x for x, _ in points}) != len(points):
            raise ValueError("difference or slope needs distinct coordinate points")
        if operation == "linear_regression_slope":
            xs, ys = zip(*points)
            xmean, ymean = math.fsum(xs) / len(xs), math.fsum(ys) / len(ys)
            value = math.fsum((x - xmean) * (y - ymean) for x, y in points) / math.fsum(
                (x - xmean) ** 2 for x in xs)
            code = (f"points = {points!r}\nxmean = sum(x for x,y in points)/len(points)\n"
                    "ymean = sum(y for x,y in points)/len(points)\n"
                    "result['linear_regression_slope'] = sum((x-xmean)*(y-ymean) for x,y in points) / "
                    "sum((x-xmean)**2 for x,y in points)\n")
        else:
            right = len(points) - 1 if operation == "finite_difference" else 2
            value = (points[right][1] - points[0][1]) / (points[right][0] - points[0][0])
            code = (f"points = {points!r}\nresult[{operation!r}] = "
                    f"(points[{right}][1]-points[0][1])/(points[{right}][0]-points[0][0])\n")
        return code, {operation: value}, {operation: None}

    if operation in {"percentage_decrease", "net_difference"}:
        if not {"initial", "final"} <= set(values) or units["initial"] != units["final"]:
            raise ValueError("initial/final values and matching units required")
        if operation == "percentage_decrease":
            if values["initial"] == 0:
                raise ValueError("percentage baseline is zero")
            expression = "(values['initial']-values['final'])/values['initial']*100"
            value = (values["initial"] - values["final"]) / values["initial"] * 100
            unit = "%"
        else:
            expression = "values['final']-values['initial']"
            value = values["final"] - values["initial"]
            unit = units["initial"] or None
        return f"result[{operation!r}] = {expression}\n", {operation: value}, {operation: unit}

    if operation == "cylinder_volume":
        diameter = next((name for name in values if "diameter" in name.casefold() or name.casefold() in {"d", "직경"}), None)
        length = next((name for name in values if "length" in name.casefold() or name.casefold() in {"l", "길이"}), None)
        if not diameter or not length or units[diameter] not in {"in", "ft", "m"} or units[length] not in {"ft", "m"}:
            raise ValueError("cylinder needs diameter and length with compatible units")
        if units[diameter] == "in" and units[length] == "ft":
            radius, output_unit = values[diameter] / 24, "ft3"
        elif units[diameter] == units[length]:
            radius, output_unit = values[diameter] / 2, "ft3" if units[length] == "ft" else "m3"
        else:
            raise ValueError("cylinder units require an explicit conversion")
        if radius <= 0 or values[length] <= 0:
            raise ValueError("cylinder dimensions must be positive")
        wants_bbl = bool(re.search(r"\bbbl\b|배럴", text, re.I))
        if wants_bbl and output_unit != "ft3":
            raise ValueError("barrel conversion requires a compatible volume unit")
        factor = values.get("conversion_factor", 5.615) if wants_bbl else None
        if factor is not None and factor <= 0:
            raise ValueError("conversion factor must be positive")
        value = math.pi * radius ** 2 * values[length] / (factor or 1)
        code = f"result['cylinder_volume'] = math.pi * {radius!r}**2 * values[{length!r}] / {(factor or 1)!r}\n"
        return code, {"cylinder_volume": value}, {"cylinder_volume": "bbl" if factor else output_unit}

    if operation == "power_times_duration":
        powers = [(name, value) for name, value in values.items() if units[name] == "kW"]
        shared = values.get("shared_duration")
        if not powers or (shared is None and not all(name.rsplit("_", 1)[0] + "_duration" in values
                                                     for name, _ in powers)):
            raise ValueError("power and matching duration required")
        if shared is not None and units.get("shared_duration") != "h":
            raise ValueError("duration must be in hours")
        pairs = [(power, shared if shared is not None else values[name.rsplit("_", 1)[0] + "_duration"])
                 for name, power in powers]
        value = math.fsum(power * duration for power, duration in pairs)
        code = f"pairs = {pairs!r}\nresult['power_times_duration'] = sum(p*t for p,t in pairs)\n"
        return code, {"power_times_duration": value}, {"power_times_duration": "kWh"}

    if operation == "concentration_mass_per_volume":
        masses = [(name, value) for name, value in values.items() if units[name] == "mg"]
        volumes = [(name, value) for name, value in values.items() if units[name] == "L"]
        if len(masses) != 1 or len(volumes) != 1 or volumes[0][1] == 0:
            raise ValueError("one mass and one nonzero volume required")
        value = masses[0][1] / volumes[0][1]
        code = f"result['concentration_mass_per_volume'] = values[{masses[0][0]!r}] / values[{volumes[0][0]!r}]\n"
        return code, {"concentration_mass_per_volume": value}, {"concentration_mass_per_volume": "mg/L"}

    if operation == "weighted_average_by_duration":
        rates = {name[:-5]: value for name, value in values.items() if name.endswith("_rate")}
        durations = {name[:-9]: value for name, value in values.items() if name.endswith("_duration")}
        if not rates or set(rates) != set(durations) or any(value <= 0 for value in durations.values()):
            raise ValueError("each segment needs a rate and positive duration")
        rate_units = {units[key + "_rate"] for key in rates}
        duration_units = {units[key + "_duration"] for key in rates}
        if len(rate_units) != 1 or len(duration_units) != 1:
            raise ValueError("weighted average needs compatible rate and duration units")
        pairs = [(rates[key], durations[key]) for key in sorted(rates)]
        value = math.fsum(rate * duration for rate, duration in pairs) / math.fsum(durations.values())
        code = f"pairs = {pairs!r}\nresult['weighted_average_by_duration'] = sum(r*t for r,t in pairs)/sum(t for r,t in pairs)\n"
        return code, {"weighted_average_by_duration": value}, {"weighted_average_by_duration": next(iter(rate_units))}

    raise ValueError("unsupported direct operation")
