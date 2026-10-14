"""Rescore the latest development attempts; never treats these as unseen V4."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from pathlib import Path

from run_conference_stress import assess as assess_stress
from run_real_kb_dev import assess as assess_real


HERE = Path(__file__).resolve().parent


def read(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = fraction * (len(ordered) - 1)
    low = math.floor(index)
    high = math.ceil(index)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (index - low), 3)


def score(cases: list[dict], rows: list[dict], assessor) -> dict:
    latest = {row["id"]: row for row in rows}
    results = []
    for case in cases:
        row = latest.get(case["id"])
        if row is None:
            results.append({"id": case["id"], "category": case["category"],
                            "handled": False, "failure_reasons": ["not_run"], "seconds": None})
            continue
        handled, reasons = assessor(case, row)
        results.append({"id": case["id"], "category": case["category"],
                        "handled": handled, "failure_reasons": reasons,
                        "seconds": row.get("seconds"), "final_status": row.get("final_status")})
    by_category = {}
    for category in sorted({case["category"] for case in cases}):
        group = [row for row in results if row["category"] == category]
        times = [float(row["seconds"]) for row in group if row["seconds"] is not None]
        by_category[category] = {"handled": sum(row["handled"] for row in group),
                                 "total": len(group), "median_seconds": percentile(times, .5),
                                 "p95_seconds": percentile(times, .95)}
    failures = Counter(reason for row in results for reason in row["failure_reasons"])
    return {"handled": sum(row["handled"] for row in results), "total": len(results),
            "completed_cases": sum(row["seconds"] is not None for row in results),
            "by_category": by_category, "failure_counts": dict(sorted(failures.items())),
            "rows": results}


def main() -> None:
    real_catalog = read("real_kb_dev.json")
    stress_catalog = read("conference_stress.json")
    real = score([*real_catalog["cases"], *real_catalog["resume_probes"]],
                 read("real_kb_dev_results.json")["rows"], assess_real)
    stress = score(stress_catalog["cases"], read("conference_stress_results.json")["rows"], assess_stress)
    summary = {"kind": "development_only_not_unseen_final_benchmark",
               "real_kb": real, "stress": stress}
    (HERE / "dev_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    print(json.dumps({key: {"handled": value["handled"], "total": value["total"],
                            "completed_cases": value["completed_cases"],
                            "by_category": value["by_category"],
                            "failure_counts": value["failure_counts"]}
                      for key, value in (("real_kb", real), ("stress", stress))},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
