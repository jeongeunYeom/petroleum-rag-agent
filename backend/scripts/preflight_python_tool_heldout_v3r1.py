"""LLM-free pre-freeze audit of v3r1 against the immutable v4 input contract."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "evaluation/reference"))

from app.services.evidence_fact_registry import EvidenceFactRegistry  # noqa: E402
from app.services.formula_source_registry import FormulaSourceRegistry, normalize_formula  # noqa: E402
from app.services.user_fact_registry import UserFactRegistry  # noqa: E402
from python_tool_heldout_v3r1_ground_truth import expected_outputs  # noqa: E402

BENCHMARK = ROOT / "evaluation/python_tool_heldout_v3r1.json"
CATALOG = ROOT / "evaluation/python_tool_heldout_v3r1_source_catalog.json"
EXCLUSIONS = ROOT / "evaluation/review/python_tool_heldout_v3r1_source_exclusions.json"
REPORT = ROOT / "evaluation/review/python_tool_heldout_v3r1_preflight.json"
MARKDOWN = REPORT.with_suffix(".md")
PRODUCT_SHA = "f71896627cc77cd6df569bb3cd140289d3667fac"
DATA = Path(r"D:\petroleum-rag-agent\data")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matched(expected: list, actual: list) -> bool:
    return any(
        row.name.casefold() == str(expected[0]).casefold()
        and math.isclose(row.value, float(expected[1]), rel_tol=0, abs_tol=1e-9)
        and row.unit.casefold() == str(expected[2]).casefold()
        for row in actual
    )


def can_freeze(report: dict) -> bool:
    return report.get("status") == "PASS" and report.get("llm_calls") == 0 and all(
        row.get("status") == "PASS" for row in report.get("tasks", [])
    )


def audit() -> dict:
    import chromadb

    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    exclusions = json.loads(EXCLUSIONS.read_text(encoding="utf-8"))
    tasks = benchmark["tasks"]
    errors: list[str] = []
    if benchmark["product_code_sha"] != PRODUCT_SHA:
        errors.append("product SHA mismatch")
    if len(tasks) != 12 or len({t["task_id"] for t in tasks}) != 12:
        errors.append("12 unique tasks required")
    expected_distribution = Counter({"required": 8, "optional": 2, "not_needed": 2})
    if Counter(t["python_expected"] for t in tasks) != expected_distribution:
        errors.append("python-need distribution mismatch")
    if Counter(t["evaluation_stratum"] for t in tasks if t["python_expected"] == "required") != Counter({"pipeline": 6, "end_to_end": 2}):
        errors.append("required stratum distribution mismatch")
    domains = Counter(t["domain"] for t in tasks)
    if domains["reservoir_engineering"] < 5 or domains["well_test"] + domains["formation_evaluation"] < 5:
        errors.append("domain balance mismatch")
    for task in tasks:
        if any(task["task_id"].startswith(prefix) for prefix in exclusions["excluded_task_prefixes"]):
            errors.append(f"{task['task_id']}: previous task ID/prefix reused")
        if not 3 <= len(task["success_criteria"]) <= 5:
            errors.append(f"{task['task_id']}: expected 3-5 criteria")
        gt = task["ground_truth"]
        if task["python_expected"] == "required" and not (
            len(gt["required_user_facts"]) + len(gt["required_evidence_facts"]) >= 6
            or len(gt["numeric_targets"]) >= 4
            or "expected_ranking" in gt
            or "expected_extrema" in gt
            or task["task_id"] == "PY3R1-WT-08"  # two-case comparison
        ):
            errors.append(f"{task['task_id']}: required-task depth criterion missing")
    db_file = DATA / "vector_db/chroma.sqlite3"
    if not db_file.is_file():
        raise FileNotFoundError(f"Never create a replacement DB: {db_file}")
    collection = chromadb.PersistentClient(path=str(db_file.parent)).get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        errors.append(f"KB count {collection.count()} != 18976")
    metadata = collection.get(include=["metadatas"])["metadatas"]
    document_count = len({m.get("document") for m in metadata if m and m.get("document")})
    if document_count != 12:
        errors.append(f"KB documents {document_count} != 12")
    found = collection.get(ids=[v["chunk_id"] for v in catalog.values()], include=["documents", "metadatas"])
    by_id = {i: (m, d) for i, m, d in zip(found["ids"], found["metadatas"], found["documents"])}
    sources = {}
    for key, entry in catalog.items():
        actual = by_id.get(entry["chunk_id"])
        valid = bool(actual and actual[0].get("document") == entry["document"]
                     and actual[0].get("page") == entry["page"]
                     and entry["anchor"] in actual[1]
                     and entry["page"] not in exclusions["excluded_pages"].get(entry["document"], []))
        if not valid:
            errors.append(f"{key}: source locator/anchor/exclusion invalid")
        sources[key] = {"valid": valid, "source_text_sha256": hashlib.sha256(actual[1].encode()).hexdigest() if actual else None,
                        "text": actual[1] if actual else ""}
    rows = []
    for task in tasks:
        gt = task["ground_truth"]
        task_errors = []
        user = UserFactRegistry.from_topic(task["topic"]).records
        user_hit = [fact for fact in gt["required_user_facts"] if matched(fact, user)]
        if len(user_hit) != len(gt["required_user_facts"]):
            missing = [fact for fact in gt["required_user_facts"] if not matched(fact, user)]
            task_errors.append(f"USERF missing {missing}")
        evidence_hit = []
        for expected in gt["required_evidence_facts"]:
            source_id, name, value, unit = expected
            source = sources.get(source_id)
            if source and source["valid"]:
                records = EvidenceFactRegistry.from_evidence([{
                    "evidence_id": source_id, "source_type": "knowledge_base", "text": source["text"]
                }]).records
                if matched([name, value, unit], records):
                    evidence_hit.append(expected)
        if len(evidence_hit) != len(gt["required_evidence_facts"]):
            task_errors.append(f"EFACT missing {[x for x in gt['required_evidence_facts'] if x not in evidence_hit]}")
        formula_hit = []
        for source_id, equation in gt["formula_sources"]:
            source = sources.get(source_id)
            if source and source["valid"]:
                records = FormulaSourceRegistry.from_evidence([{
                    "evidence_id": source_id, "source_type": "knowledge_base", "text": source["text"]
                }]).records
                if any(r.expression_candidate and normalize_formula(r.raw_span) == normalize_formula(equation) for r in records):
                    formula_hit.append([source_id, equation])
        if len(formula_hit) != len(gt["formula_sources"]):
            task_errors.append(f"FORMULA missing {[x for x in gt['formula_sources'] if x not in formula_hit]}")
        if not set(gt["source_ids"]) <= catalog.keys() or any(not sources[s]["valid"] for s in gt["source_ids"] if s in sources):
            task_errors.append("ground-truth source invalid")
        reference = expected_outputs(task["task_id"])
        target_map = {name: (value, unit, tolerance) for name, value, unit, tolerance in gt["numeric_targets"]}
        if reference.keys() != target_map.keys():
            task_errors.append("reference/target names mismatch")
        for name, computed in reference.items():
            if name in target_map:
                value, unit, tolerance = target_map[name]
                if not unit or tolerance <= 0 or not math.isclose(computed, value, rel_tol=0, abs_tol=tolerance / 10):
                    task_errors.append(f"numeric GT mismatch: {name}")
        rows.append({"task_id": task["task_id"], "status": "PASS" if not task_errors else "FAIL",
                     "expected_user": len(gt["required_user_facts"]), "matched_user": len(user_hit),
                     "expected_evidence": len(gt["required_evidence_facts"]), "matched_evidence": len(evidence_hit),
                     "expected_formula": len(gt["formula_sources"]), "matched_formula": len(formula_hit),
                     "source_valid": all(sources[s]["valid"] for s in gt["source_ids"] if s in sources),
                     "errors": task_errors})
    status = "PASS" if not errors and all(r["status"] == "PASS" for r in rows) else "FAIL"
    return {"benchmark_id": benchmark["benchmark_id"], "status": status, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "product_code_sha": PRODUCT_SHA, "llm_calls": 0, "agent_calls": 0, "planner_calls": 0,
            "collection_count": collection.count(), "document_count": document_count,
            "hashes": {"benchmark_draft_sha256": digest(BENCHMARK), "source_catalog_sha256": digest(CATALOG),
                       "exclusions_sha256": digest(EXCLUSIONS),
                       **{name + "_sha256": digest(BACKEND / "app/services" / (name + ".py")) for name in
                          ("user_fact_registry", "evidence_fact_registry", "formula_source_registry")}},
            "source_text_sha256": {key: source["source_text_sha256"] for key, source in sources.items()},
            "summary": {"tasks": len(rows), "expected_user": sum(r["expected_user"] for r in rows),
                        "matched_user": sum(r["matched_user"] for r in rows),
                        "expected_evidence": sum(r["expected_evidence"] for r in rows),
                        "matched_evidence": sum(r["matched_evidence"] for r in rows),
                        "expected_formula": sum(r["expected_formula"] for r in rows),
                        "matched_formula": sum(r["matched_formula"] for r in rows)},
            "errors": errors, "tasks": rows}


def main() -> int:
    report = audit()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# v3r1 pre-freeze contract audit: {report['status']}", "",
             f"Timestamp (UTC): {report['timestamp_utc']}",
             f"Product SHA: `{report['product_code_sha']}`", "LLM/Agent/Planner calls: 0/0/0", "",
             f"Real KB: {report['collection_count']} chunks / {report['document_count']} documents", "",
             "| Task | Status | USERF | EFACT | FORMULA | Source |", "|---|---|---:|---:|---:|---|" ]
    for row in report["tasks"]:
        lines.append(f"| {row['task_id']} | {row['status']} | {row['matched_user']}/{row['expected_user']} | "
                     f"{row['matched_evidence']}/{row['expected_evidence']} | {row['matched_formula']}/{row['expected_formula']} | "
                     f"{'PASS' if row['source_valid'] else 'FAIL'} |")
        lines.extend(f"- {row['task_id']}: {error}" for error in row["errors"])
    lines.extend(["", *[f"- {error}" for error in report["errors"]]])
    MARKDOWN.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{report['status']} {report['summary']}")
    for row in report["tasks"]:
        if row["status"] != "PASS":
            print(row["task_id"], row["errors"])
    for error in report["errors"]:
        print(error)
    return 0 if can_freeze(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
