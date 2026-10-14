"""Regrade saved retrieval outputs against checked literal development labels."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(fraction * len(ordered) + 0.99999) - 1))]


def main() -> None:
    catalog = json.loads((HERE / "retrieval_dev.json").read_text(encoding="utf-8"))["cases"]
    summary = {}
    for mode in ("hybrid", "hybrid_rerank"):
        rows = {row["id"]: row for row in json.loads((HERE / f"retrieval_ab_{mode}.json").read_text(
            encoding="utf-8"))["rows"]}
        if len(rows) != 40:
            raise SystemExit(f"{mode}: expected 40 completed retrieval cases")
        reviewed = []
        for case in catalog:
            row = rows[case["id"]]
            hits = row["sources"]
            target = [index + 1 for index, source in enumerate(hits)
                      if source["document"] == case["document"] and source["page"] == case["page"]]
            formula = (any(case["formula"].replace(" ", "").casefold() in
                           source["excerpt"].replace(" ", "").casefold()
                           for source in hits if source["document"] == case["document"]
                           and source["page"] == case["page"])
                       if case.get("formula") else None)
            reviewed.append({"id": case["id"], "target_document_hit": any(
                source["document"] == case["document"] for source in hits),
                "target_page_rank": target[0] if target else None,
                "target_page_hit": bool(target), "target_formula_span_hit": formula,
                "seconds": row["seconds"], "error": row["error"]})
        formula_rows = [row for row in reviewed if row["target_formula_span_hit"] is not None]
        latency = [row["seconds"] for row in reviewed]
        summary[mode] = {
            "cases": len(reviewed), "errors": sum(bool(row["error"]) for row in reviewed),
            "target_document_hit_rate": sum(row["target_document_hit"] for row in reviewed) / 40,
            "target_page_hit_rate": sum(row["target_page_hit"] for row in reviewed) / 40,
            "target_formula_span_hit_rate": sum(row["target_formula_span_hit"] for row in formula_rows) / len(formula_rows),
            "formula_cases": len(formula_rows),
            "mean_gold_page_reciprocal_rank": sum(1 / row["target_page_rank"] for row in reviewed
                                                  if row["target_page_rank"]) / 40,
            "median_seconds": statistics.median(latency), "p95_seconds": percentile(latency, 0.95),
            "reviewed_rows": reviewed,
        }
    output = HERE / "retrieval_ab_summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for mode, result in summary.items():
        print(mode, {key: value for key, value in result.items() if key != "reviewed_rows"})


if __name__ == "__main__":
    main()
