"""LLM-free, pre-freeze admissibility audit. It does not test Agent behavior."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "evaluation/reference")]

from app.services.evidence_fact_registry import EvidenceFactRegistry  # noqa: E402
from app.services.formula_source_registry import FormulaSourceRegistry, normalize_formula  # noqa: E402
from app.services.user_fact_registry import UNIT, UserFactRegistry  # noqa: E402
from python_tool_heldout_v4_ground_truth import expected_outputs  # noqa: E402

BASE = ROOT / "evaluation"
BENCHMARK = BASE / "python_tool_heldout_v4.json"
CATALOG = BASE / "python_tool_heldout_v4_source_catalog.json"
EXCLUSIONS = BASE / "python_tool_heldout_v4_source_exclusions.json"
REFERENCE = BASE / "reference/python_tool_heldout_v4_ground_truth.py"
REPORT = BASE / "review/python_tool_heldout_v4_preflight.json"
PRODUCT_SHA = "2646be1e5439cd689fdd236e064e2f9b64255274"
DATA_DIR = Path(r"D:\petroleum-rag-agent\data")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matches(expected: list, records: list) -> bool:
    return any(
        row.name.casefold() == str(expected[0]).casefold()
        and math.isclose(row.value, float(expected[1]), rel_tol=0, abs_tol=1e-8)
        and row.unit.casefold() == str(expected[2]).casefold()
        for row in records
    )


def can_freeze(report: dict) -> bool:
    return (
        report.get("status") == "PASS"
        and report.get("llm_calls") == 0
        and not report.get("errors")
        and len(report.get("tasks", [])) == 12
        and all(row.get("status") == "PASS"
                and row.get("matched_user") == row.get("expected_user")
                and row.get("matched_evidence") == row.get("expected_evidence")
                and row.get("matched_formula") == row.get("expected_formula")
                for row in report.get("tasks", []))
    )


def preflight() -> dict:
    import chromadb

    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    exclusions = json.loads(EXCLUSIONS.read_text(encoding="utf-8"))
    tasks = benchmark["tasks"]
    errors: list[str] = []
    if benchmark["product_code_sha"] != PRODUCT_SHA:
        errors.append("product_sha_mismatch")
    if len(tasks) != 12 or len({t["task_id"] for t in tasks}) != 12:
        errors.append("task_count_or_identity")
    if Counter(t["python_expected"] for t in tasks) != {"required": 8, "optional": 2, "not_needed": 2}:
        errors.append("python_need_distribution")
    if Counter(t["evaluation_stratum"] for t in tasks if t["python_expected"] == "required") != {"pipeline": 6, "end_to_end": 2}:
        errors.append("required_stratum_distribution")
    domains = Counter(t["domain"] for t in tasks)
    if domains["reservoir_engineering"] < 5 or domains["well_test"] + domains["formation_evaluation"] < 5:
        errors.append("domain_distribution")
    required_outputs = sum(len(t["ground_truth"]["expected_contract_outputs"]) for t in tasks if t["python_expected"] == "required")
    pipeline_outputs = sum(len(t["ground_truth"]["expected_contract_outputs"]) for t in tasks if t["evaluation_stratum"] == "pipeline")
    if required_outputs < 50 or pipeline_outputs < 38:
        errors.append("required_output_depth")
    if sum(
        len(t["ground_truth"]["numeric_targets"]) >= 4
        and any(x["semantic_name"].startswith(("mean_", "total_", "range_", "spread_", "max_")) for x in t["ground_truth"]["numeric_targets"])
        for t in tasks if t["python_expected"] == "required"
    ) < 5:
        errors.append("per_case_plus_aggregate_depth")
    db_file = DATA_DIR / "vector_db/chroma.sqlite3"
    if not db_file.is_file():
        raise FileNotFoundError(f"Real ChromaDB unavailable; no DB will be created: {db_file}")
    collection = chromadb.PersistentClient(path=str(db_file.parent)).get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        errors.append(f"kb_count={collection.count()}")
    found = collection.get(ids=[entry["chunk_id"] for entry in catalog.values()], include=["metadatas", "documents"])
    by_id = {key: (meta, text) for key, meta, text in zip(found["ids"], found["metadatas"], found["documents"])}
    old = exclusions["old_sources"]
    sources = {}
    for key, entry in catalog.items():
        actual = by_id.get(entry["chunk_id"])
        overlap = [
            row for row in old
            if (row["chunk_id"] == entry["chunk_id"] or
                row["document"] == entry["document"] and row["page"] == entry["page"])
        ]
        valid = bool(
            actual and actual[0]["document"] == entry["document"]
            and actual[0]["page"] == entry["page"]
            and entry["anchor"] in actual[1]
            and hashlib.sha256(actual[1].encode()).hexdigest() == entry["exact_source_excerpt_sha256"]
            and not overlap
        )
        sources[key] = {"valid": valid, "text": actual[1] if actual else "", "overlap": overlap}
        if not valid:
            errors.append(f"invalid_source_or_overlap:{key}")
    rows = []
    unsupported_units = 0
    unparseable_formulas = 0
    for task in tasks:
        gt = task["ground_truth"]
        task_errors: list[str] = []
        if any(task["task_id"].startswith(prefix) for prefix in exclusions["excluded_task_prefixes"]):
            task_errors.append("reused_task_prefix")
        if task["python_expected"] == "required" and not (
            len(gt["numeric_targets"]) >= 4 or len(gt["expected_user_facts"]) + len(gt["expected_evidence_facts"]) >= 6
        ):
            task_errors.append("required_task_too_shallow")
        user = UserFactRegistry.from_topic(task["topic"]).records
        user_hits = [item for item in gt["expected_user_facts"] if matches(item, user)]
        if len(user_hits) != len(gt["expected_user_facts"]):
            task_errors.append("USERF_missing")
        for _, _, unit in gt["expected_user_facts"]:
            if unit and not re.fullmatch(UNIT, unit, re.IGNORECASE):
                unsupported_units += 1
                task_errors.append(f"unsupported_required_input_unit:{unit}")
        evidence_hits = []
        for source_id, name, value, unit in gt["expected_evidence_facts"]:
            source = sources.get(source_id)
            if source and source["valid"]:
                records = EvidenceFactRegistry.from_evidence([{
                    "evidence_id": source_id, "source_type": "knowledge_base", "text": source["text"]
                }]).records
                if matches([name, value, unit], records):
                    evidence_hits.append([source_id, name, value, unit])
        if len(evidence_hits) != len(gt["expected_evidence_facts"]):
            task_errors.append("EFACT_missing")
        formula_hits = []
        for source_id, expression in gt["formula_sources"]:
            source = sources.get(source_id)
            if source and source["valid"]:
                records = FormulaSourceRegistry.from_evidence([{
                    "evidence_id": source_id, "source_type": "knowledge_base", "text": source["text"]
                }]).records
                if any(record.expression_candidate and normalize_formula(record.raw_span) == normalize_formula(expression) for record in records):
                    formula_hits.append([source_id, expression])
            if [source_id, expression] not in formula_hits:
                unparseable_formulas += 1
        if len(formula_hits) != len(gt["formula_sources"]):
            task_errors.append("FORMULA_missing_or_unparseable")
        for source_id, expression in gt["formula_sources"]:
            if any(normalize_formula(str(row.get("anchor") or "")) == normalize_formula(expression) for row in old):
                task_errors.append(f"old_formula_passage_overlap:{source_id}")
        if not set(gt["source_ids"]) <= catalog.keys() or any(not sources[key]["valid"] for key in gt["source_ids"] if key in sources):
            task_errors.append("source_locator_invalid")
        calculated = expected_outputs(task["task_id"])
        targets = {item["semantic_name"]: item for item in gt["numeric_targets"]}
        if calculated.keys() != targets.keys():
            task_errors.append("reference_target_set_mismatch")
        for name, value in calculated.items():
            target = targets.get(name)
            if target and (not target["unit"] or target["abs_tolerance"] <= 0 or
                           not math.isclose(value, target["value"], abs_tol=target["abs_tolerance"] / 10, rel_tol=0)):
                task_errors.append(f"reference_target_mismatch:{name}")
        if len(gt["expected_contract_outputs"]) != len(gt["numeric_targets"]) + len(gt["typed_targets"]):
            task_errors.append("contract_output_coverage")
        rows.append({
            "task_id": task["task_id"], "status": "PASS" if not task_errors else "FAIL",
            "expected_user": len(gt["expected_user_facts"]), "matched_user": len(user_hits),
            "expected_evidence": len(gt["expected_evidence_facts"]), "matched_evidence": len(evidence_hits),
            "expected_formula": len(gt["formula_sources"]), "matched_formula": len(formula_hits),
            "expected_outputs": len(gt["expected_contract_outputs"]),
            "source_valid": all(sources[key]["valid"] for key in gt["source_ids"] if key in sources),
            "errors": task_errors,
        })
    status = "PASS" if not errors and all(row["status"] == "PASS" for row in rows) else "FAIL"
    summary = {
        "tasks": len(rows), "required": 8, "optional": 2, "not_needed": 2,
        "pipeline": 6, "end_to_end": 2, "expected_user": sum(r["expected_user"] for r in rows),
        "matched_user": sum(r["matched_user"] for r in rows),
        "expected_evidence": sum(r["expected_evidence"] for r in rows),
        "matched_evidence": sum(r["matched_evidence"] for r in rows),
        "expected_formula": sum(r["expected_formula"] for r in rows),
        "matched_formula": sum(r["matched_formula"] for r in rows),
        "expected_required_outputs": required_outputs,
        "expected_pipeline_outputs": pipeline_outputs,
        "unsupported_required_units": unsupported_units,
        "unparseable_formulas": unparseable_formulas,
        "old_source_overlap": sum(len(source["overlap"]) for source in sources.values()),
    }
    return {
        "benchmark_id": benchmark["benchmark_id"], "status": status, "product_sha": PRODUCT_SHA,
        "llm_calls": 0, "agent_calls": 0, "planner_calls": 0,
        "collection_count": collection.count(), "summary": summary,
        "hashes": {
            "benchmark_draft_sha256": digest(BENCHMARK),
            "source_catalog_sha256": digest(CATALOG),
            "source_exclusions_sha256": digest(EXCLUSIONS),
            "reference_calculator_sha256": digest(REFERENCE),
            **{name + "_sha256": digest(ROOT / "backend/app/services" / (name + ".py")) for name in (
                "user_fact_registry", "evidence_fact_registry", "formula_source_registry"
            )},
        },
        "errors": errors, "tasks": rows,
    }


def main() -> int:
    report = preflight()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# Python Tool Heldout v4 preflight: {report['status']}", "",
        f"Product SHA: {report['product_sha']}",
        "LLM / Agent / Planner calls: 0 / 0 / 0", "",
        f"Real KB chunks: {report['collection_count']}", "",
        "| Task | Status | USERF | EFACT | FORMULA | Outputs | Source |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in report["tasks"]:
        lines.append(
            f"| {row['task_id']} | {row['status']} | {row['matched_user']}/{row['expected_user']} | "
            f"{row['matched_evidence']}/{row['expected_evidence']} | "
            f"{row['matched_formula']}/{row['expected_formula']} | {row['expected_outputs']} | "
            f"{'PASS' if row['source_valid'] else 'FAIL'} |"
        )
        lines.extend(f"- {row['task_id']}: {error}" for error in row["errors"])
    lines.extend(["", *[f"- {error}" for error in report["errors"]]])
    REPORT.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report["status"], report["summary"])
    for row in report["tasks"]:
        if row["errors"]:
            print(row["task_id"], row["errors"])
    print(report["errors"])
    return 0 if can_freeze(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
