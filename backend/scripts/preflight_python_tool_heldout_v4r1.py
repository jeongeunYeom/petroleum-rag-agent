"""LLM-free source/input and independent ground-truth integrity gates."""

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
from python_tool_heldout_v4r1_ground_truth import reference_outputs  # noqa: E402

BASE = ROOT / "evaluation"
BENCHMARK = BASE / "python_tool_heldout_v4r1.json"
CATALOG = BASE / "python_tool_heldout_v4r1_source_catalog.json"
EXCLUSIONS = BASE / "python_tool_heldout_v4r1_source_exclusions.json"
REFERENCE = BASE / "reference/python_tool_heldout_v4r1_ground_truth.py"
REFERENCE_OUTPUTS = BASE / "reference/python_tool_heldout_v4r1_reference_outputs.json"
REPORT = BASE / "review/python_tool_heldout_v4r1_preflight.json"
AUDIT = BASE / "review/python_tool_heldout_v4r1_gt_consistency.json"
MANIFEST = BASE / "python_tool_heldout_v4r1_manifest.json"
PRODUCT_SHA = "2646be1e5439cd689fdd236e064e2f9b64255274"
DB = Path(r"D:\petroleum-rag-agent\data\vector_db\chroma.sqlite3")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def same_value(a: object, b: object, tolerance: float = 0) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return math.isclose(float(a), float(b), rel_tol=0, abs_tol=tolerance)
    return a == b


def canonical_projection(target: dict, row: dict, errors: list[str], field: str) -> None:
    name = target["semantic_name"]
    if row.get("target_id") != target["target_id"]:
        errors.append(f"GT_DUPLICATE_SEMANTIC_CONFLICT:{field}:{name}")
    if row.get("value") != target["value"]:
        if target["target_type"] == "numeric":
            if not same_value(row.get("value"), target["value"], target["abs_tolerance"] / 10):
                errors.append(f"GT_NUMERIC_CONFLICT:{field}:{name}")
        elif target["target_type"] == "ranking":
            errors.append(f"GT_RANKING_CONFLICT:{field}:{name}")
        elif target.get("tie_set"):
            errors.append(f"GT_TIE_CONFLICT:{field}:{name}")
        else:
            errors.append(f"GT_TYPED_VALUE_CONFLICT:{field}:{name}")
        errors.append(f"GT_DUPLICATE_SEMANTIC_CONFLICT:{field}:{name}")
    if target["target_type"] == "numeric" and row.get("unit") != target["unit"]:
        errors.append(f"GT_UNIT_CONFLICT:{field}:{name}")
    if field == "expected_contract_outputs" and row.get("type") != target["target_type"]:
        errors.append(f"GT_TYPED_VALUE_CONFLICT:{field}:{name}")
    if field == "typed_targets" and row.get("type") != target["target_type"]:
        errors.append(f"GT_TYPED_VALUE_CONFLICT:{field}:{name}")


def validate_ground_truth_consistency(task: dict, reference_row: dict) -> list[str]:
    gt = task["ground_truth"]
    errors: list[str] = []
    if gt["expected_user_facts"] != reference_row["inputs"]:
        errors.append("GT_SCENARIO_MAPPING_CONFLICT:inputs")
    if gt["expected_evidence_facts"] != list(reference_row["evidence_inputs"].values()):
        errors.append("GT_SCENARIO_MAPPING_CONFLICT:evidence")
    inputs = {name: float(value) for name, value, _ in reference_row["inputs"]}
    evidence = {name: float(item[2]) for name, item in reference_row["evidence_inputs"].items()}
    recalculated = reference_outputs(task["task_id"], inputs, evidence)
    reference_targets = {row["semantic_name"]: row for row in reference_row["canonical_targets"]}
    canonical = {row["semantic_name"]: row for row in gt["canonical_targets"]}
    if len(canonical) != len(gt["canonical_targets"]) or len({row["target_id"] for row in gt["canonical_targets"]}) != len(canonical):
        errors.append("GT_DUPLICATE_SEMANTIC_CONFLICT:canonical_targets")
    if set(canonical) != {row["semantic_name"] for row in recalculated} or set(canonical) != set(reference_targets):
        errors.append("GT_REQUIRED_TARGET_MISSING:reference_set")
    for raw in recalculated:
        name = raw["semantic_name"]
        target = canonical.get(name)
        frozen_reference = reference_targets.get(name)
        if not target or not frozen_reference:
            continue
        for checked, field in ((target, "canonical_targets"), (frozen_reference, "reference_outputs")):
            if checked.get("target_type") != raw["target_type"]:
                errors.append(f"GT_TYPED_VALUE_CONFLICT:{field}:{name}")
            if checked.get("unit") != raw["unit"]:
                errors.append(f"GT_UNIT_CONFLICT:{field}:{name}")
            if not same_value(checked.get("value"), raw["value"], raw.get("abs_tolerance", 0) / 10):
                code = "GT_NUMERIC_CONFLICT" if raw["target_type"] == "numeric" else "GT_RANKING_CONFLICT" if raw["target_type"] == "ranking" else "GT_TYPED_VALUE_CONFLICT"
                errors.append(f"{code}:{field}:{name}")
        if target.get("scenario_id") != raw.get("scenario_id"):
            errors.append(f"GT_SCENARIO_MAPPING_CONFLICT:{name}")
        if target["target_type"] == "numeric" and (not target.get("unit") or target.get("abs_tolerance", 0) <= 0):
            errors.append(f"GT_UNIT_CONFLICT:canonical_targets:{name}")

    fields = {
        "numeric_targets": {name for name, row in canonical.items() if row["target_type"] == "numeric"},
        "typed_targets": {name for name, row in canonical.items() if row["target_type"] != "numeric"},
        "ranking_targets": {name for name, row in canonical.items() if row["target_type"] == "ranking"},
        "expected_contract_outputs": set(canonical),
    }
    for field, expected_names in fields.items():
        rows = gt[field]
        seen: set[str] = set()
        for row in rows:
            name = row["semantic_name"]
            if name in seen:
                errors.append(f"GT_DUPLICATE_SEMANTIC_CONFLICT:{field}:{name}")
            seen.add(name)
            if name not in canonical or name not in expected_names:
                errors.append(f"GT_ORPHAN_TARGET:{field}:{name}")
                continue
            canonical_projection(canonical[name], row, errors, field)
        for missing in expected_names - seen:
            errors.append(f"GT_REQUIRED_TARGET_MISSING:{field}:{missing}")

    by_id = {row["target_id"]: row for row in gt["canonical_targets"]}
    criterion_refs = set()
    for criterion in task["success_criteria"]:
        for ref in criterion.get("target_refs", []):
            criterion_refs.add(ref)
            if ref not in by_id:
                errors.append(f"GT_REQUIRED_TARGET_MISSING:criterion:{ref}")
    for target in gt["canonical_targets"]:
        if target["required"] and target["target_id"] not in criterion_refs:
            errors.append(f"GT_REQUIRED_TARGET_MISSING:criterion:{target['target_id']}")
    for claim in gt["required_claims"]:
        for ref in claim.get("target_refs", []):
            if ref not in by_id:
                errors.append(f"GT_REQUIRED_TARGET_MISSING:claim:{ref}")

    for target in gt["canonical_targets"]:
        name = target["semantic_name"]
        values = target.get("extremum_of") or target.get("ranking_of")
        if not values:
            continue
        if any(source not in canonical or canonical[source]["target_type"] != "numeric" for source in values.values()):
            errors.append(f"GT_ORPHAN_TARGET:relation:{name}")
            continue
        numbers = {label: canonical[source]["value"] for label, source in values.items()}
        if target.get("extremum"):
            value = min(numbers.values()) if target["extremum"] == "min" else max(numbers.values())
            winners = [label for label, number in numbers.items() if math.isclose(number, value, rel_tol=0, abs_tol=1e-9)]
            expected = winners if target.get("tie_set") else winners[0]
            if not same_value(target["value"], expected):
                code = "GT_TIE_CONFLICT" if target.get("tie_set") else "GT_ARGMIN_CONFLICT" if target["extremum"] == "min" else "GT_ARGMAX_CONFLICT"
                errors.append(f"{code}:{name}")
        if target.get("ranking_of"):
            reverse = target.get("order") == "desc"
            expected = sorted(numbers, key=lambda case: ((-numbers[case] if reverse else numbers[case]), case))
            if target["value"] != expected:
                errors.append(f"GT_RANKING_CONFLICT:{name}")
    return sorted(set(errors))


def find_old_source_overlap(source: dict, old: list[dict]) -> list[dict]:
    return [row for row in old if row["chunk_id"] == source["chunk_id"] or
            row["document"] == source["document"] and row["page"] == source["page"]]


def source_input_preflight(benchmark: dict, catalog: dict, exclusions: dict) -> tuple[list[dict], list[str], int]:
    if not DB.is_file():
        raise FileNotFoundError(f"Existing ChromaDB missing; will not create one: {DB}")
    import chromadb

    collection = chromadb.PersistentClient(path=str(DB.parent)).get_collection("petroleum_knowledge")
    errors: list[str] = []
    if collection.count() != 18976:
        errors.append(f"KB_COUNT:{collection.count()}")
    found = collection.get(ids=[source["chunk_id"] for source in catalog.values()], include=["metadatas", "documents"])
    by_id = {key: (meta, text) for key, meta, text in zip(found["ids"], found["metadatas"], found["documents"])}
    sources = {}
    old = exclusions["old_sources"]
    for key, source in catalog.items():
        actual = by_id.get(source["chunk_id"])
        overlap = find_old_source_overlap(source, old)
        valid = bool(actual and actual[0]["document"] == source["document"] and actual[0]["page"] == source["page"]
                     and source["anchor"] in actual[1]
                     and hashlib.sha256(actual[1].encode("utf-8")).hexdigest() == source["exact_source_excerpt_sha256"]
                     and not overlap)
        sources[key] = {"valid": valid, "text": actual[1] if actual else "", "overlap": overlap}
        if not valid:
            errors.append(f"SOURCE_INVALID_OR_OVERLAP:{key}")
    rows = []
    for task in benchmark["tasks"]:
        gt = task["ground_truth"]
        task_errors: list[str] = []
        users = UserFactRegistry.from_topic(task["topic"]).records
        user_hits = [item for item in gt["expected_user_facts"] if any(
            row.name.casefold() == item[0].casefold() and same_value(row.value, item[1], 1e-8)
            and row.unit.casefold() == item[2].casefold() for row in users)]
        if len(user_hits) != len(gt["expected_user_facts"]):
            task_errors.append("USERF_MISSING")
        unsupported = [unit for _, _, unit in gt["expected_user_facts"] if unit and not re.fullmatch(UNIT, unit, re.I)]
        if unsupported:
            task_errors.append("UNSUPPORTED_UNIT:" + ",".join(unsupported))
        evidence_hits = []
        for source_id, name, value, unit in gt["expected_evidence_facts"]:
            source = sources.get(source_id)
            if not source or not source["valid"]:
                continue
            records = EvidenceFactRegistry.from_evidence([{"evidence_id": source_id, "source_type": "knowledge_base",
                                                            "text": source["text"]}]).records
            if any(row.name.casefold() == name.casefold() and same_value(row.value, value, 1e-8)
                   and row.unit.casefold() == unit.casefold() for row in records):
                evidence_hits.append(name)
        if len(evidence_hits) != len(gt["expected_evidence_facts"]):
            task_errors.append("EFACT_MISSING")
        formula_hits = []
        for source_id, expression in gt["formula_sources"]:
            source = sources.get(source_id)
            if not source or not source["valid"]:
                continue
            records = FormulaSourceRegistry.from_evidence([{"evidence_id": source_id, "source_type": "knowledge_base",
                                                             "text": source["text"]}]).records
            if any(row.expression_candidate and normalize_formula(row.raw_span) == normalize_formula(expression)
                   for row in records):
                formula_hits.append(expression)
        if len(formula_hits) != len(gt["formula_sources"]):
            task_errors.append("FORMULA_MISSING_OR_UNPARSEABLE")
        if not set(gt["source_ids"]) <= catalog.keys() or any(not sources[key]["valid"] for key in gt["source_ids"] if key in sources):
            task_errors.append("SOURCE_LOCATOR_INVALID")
        rows.append({
            "task_id": task["task_id"], "status": "PASS" if not task_errors else "FAIL",
            "expected_user": len(gt["expected_user_facts"]), "matched_user": len(user_hits),
            "expected_evidence": len(gt["expected_evidence_facts"]), "matched_evidence": len(evidence_hits),
            "expected_formula": len(gt["formula_sources"]), "matched_formula": len(formula_hits),
            "unsupported_units": unsupported, "source_valid": not any(error.startswith("SOURCE_") for error in task_errors),
            "errors": task_errors,
        })
    return rows, errors, collection.count()


def audit() -> tuple[dict, dict]:
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    exclusions = json.loads(EXCLUSIONS.read_text(encoding="utf-8"))
    references = json.loads(REFERENCE_OUTPUTS.read_text(encoding="utf-8"))
    tasks = benchmark["tasks"]
    errors: list[str] = []
    if benchmark["benchmark_id"] != "python_tool_heldout_v4r1" or benchmark["product_code_sha"] != PRODUCT_SHA:
        errors.append("IDENTITY_OR_PRODUCT_SHA")
    if len(tasks) != 12 or len({row["task_id"] for row in tasks}) != 12:
        errors.append("TASK_COUNT")
    if Counter(row["python_expected"] for row in tasks) != {"required": 8, "optional": 2, "not_needed": 2}:
        errors.append("NEED_DISTRIBUTION")
    if Counter(row["evaluation_stratum"] for row in tasks if row["python_expected"] == "required") != {"pipeline": 6, "end_to_end": 2}:
        errors.append("STRATUM_DISTRIBUTION")
    domains = Counter(row["domain"] for row in tasks)
    if domains["reservoir_engineering"] < 5 or domains["well_test"] + domains["formation_evaluation"] < 5:
        errors.append("DOMAIN_DISTRIBUTION")
    required_count = sum(len(row["ground_truth"]["canonical_targets"]) for row in tasks if row["python_expected"] == "required")
    pipeline_count = sum(len(row["ground_truth"]["canonical_targets"]) for row in tasks if row["evaluation_stratum"] == "pipeline")
    if required_count < 55 or pipeline_count < 40:
        errors.append("OUTPUT_DEPTH")
    if sum(bool(row["ground_truth"]["canonical_targets"] and any(
        target["semantic_name"].startswith(("mean_", "total_", "max_", "forecast_", "rmse"))
        for target in row["ground_truth"]["canonical_targets"]))
        for row in tasks if row["python_expected"] == "required") < 5:
        errors.append("MULTI_CASE_AGGREGATE_DEPTH")
    if any(row["task_id"].startswith(tuple(exclusions["excluded_task_prefixes"])) for row in tasks):
        errors.append("OLD_TASK_PREFIX")
    input_rows, source_errors, chunk_count = source_input_preflight(benchmark, catalog, exclusions)
    errors.extend(source_errors)
    gt_rows = []
    for task in tasks:
        row = references.get(task["task_id"])
        conflicts = validate_ground_truth_consistency(task, row) if row else ["GT_REQUIRED_TARGET_MISSING:reference_row"]
        gt_rows.append({"task_id": task["task_id"], "status": "PASS" if not conflicts else "FAIL", "conflicts": conflicts,
                        "reference_targets": len(row["canonical_targets"]) if row else 0,
                        "canonical_targets": len(task["ground_truth"]["canonical_targets"]),
                        "numeric_targets": len(task["ground_truth"]["numeric_targets"]),
                        "typed_targets": len(task["ground_truth"]["typed_targets"]),
                        "ranking_targets": len(task["ground_truth"]["ranking_targets"]),
                        "expected_contract_targets": len(task["ground_truth"]["expected_contract_outputs"])})
    if set(references) != {task["task_id"] for task in tasks}:
        errors.append("REFERENCE_TASK_SET")
    gt_conflicts = [conflict for row in gt_rows for conflict in row["conflicts"]]
    summary = {
        "task_count": len(tasks), "required": 8, "optional": 2, "not_needed": 2, "pipeline": 6, "end_to_end": 2,
        "domains": dict(domains), "expected_user": sum(row["expected_user"] for row in input_rows),
        "matched_user": sum(row["matched_user"] for row in input_rows),
        "expected_evidence": sum(row["expected_evidence"] for row in input_rows),
        "matched_evidence": sum(row["matched_evidence"] for row in input_rows),
        "expected_formula": sum(row["expected_formula"] for row in input_rows),
        "matched_formula": sum(row["matched_formula"] for row in input_rows),
        "reference_targets": sum(row["reference_targets"] for row in gt_rows),
        "canonical_targets": sum(row["canonical_targets"] for row in gt_rows),
        "numeric_targets": sum(row["numeric_targets"] for row in gt_rows),
        "typed_targets": sum(row["typed_targets"] for row in gt_rows),
        "ranking_targets": sum(row["ranking_targets"] for row in gt_rows),
        "expected_contract_targets": sum(row["expected_contract_targets"] for row in gt_rows),
        "required_outputs": required_count, "pipeline_outputs": pipeline_count,
        "old_source_overlap": sum(error.startswith("SOURCE_INVALID_OR_OVERLAP") for error in errors),
        "unsupported_required_units": sum(len(row["unsupported_units"]) for row in input_rows),
        "gt_conflicts": len(gt_conflicts),
    }
    status = "PASS" if not errors and not gt_conflicts and all(row["status"] == "PASS" for row in input_rows) else "FAIL"
    hashes = {
        "benchmark_draft_sha256": digest(BENCHMARK), "source_catalog_sha256": digest(CATALOG),
        "source_exclusions_sha256": digest(EXCLUSIONS), "reference_calculator_sha256": digest(REFERENCE),
        "reference_outputs_sha256": digest(REFERENCE_OUTPUTS),
        **{name + "_sha256": digest(ROOT / "backend/app/services" / (name + ".py")) for name in (
            "user_fact_registry", "evidence_fact_registry", "formula_source_registry"
        )},
    }
    report = {"benchmark_id": benchmark["benchmark_id"], "status": status, "product_sha": PRODUCT_SHA,
              "llm_calls": 0, "agent_calls": 0, "planner_calls": 0, "collection_count": chunk_count,
              "summary": summary, "hashes": hashes, "errors": errors, "tasks": input_rows}
    consistency = {"benchmark_id": benchmark["benchmark_id"], "status": "PASS" if not gt_conflicts else "FAIL",
                   "reference_calculator_sha256": hashes["reference_calculator_sha256"],
                   "reference_outputs_sha256": hashes["reference_outputs_sha256"],
                   "conflict_count": len(gt_conflicts), "conflict_types": dict(Counter(x.split(":", 1)[0] for x in gt_conflicts)),
                   "tasks": gt_rows}
    return report, consistency


def can_freeze(report: dict, consistency: dict) -> bool:
    return (report["status"] == "PASS" and consistency["status"] == "PASS"
            and report["llm_calls"] == report["agent_calls"] == report["planner_calls"] == 0
            and report["summary"]["gt_conflicts"] == 0 and consistency["conflict_count"] == 0
            and not report["errors"] and all(row["status"] == "PASS" and not row["errors"] and row["source_valid"]
                and all(row[f"expected_{kind}"] == row[f"matched_{kind}"] for kind in ("user", "evidence", "formula"))
                for row in report["tasks"])
            and all(row["status"] == "PASS" and not row["conflicts"] for row in consistency["tasks"]))


def main() -> int:
    if MANIFEST.exists():
        raise RuntimeError("v4r1 frozen: preflight artifacts cannot be rewritten")
    report, consistency = audit()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    AUDIT.write_text(json.dumps(consistency, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# Python Tool Heldout v4r1 preflight: {report['status']}", "",
             f"Product SHA: {PRODUCT_SHA}", "LLM / Agent / Planner calls: 0 / 0 / 0", "",
             "| Task | Input | USERF | EFACT | FORMULA | GT conflicts |",
             "|---|---|---:|---:|---:|---:|"]
    for source, gt in zip(report["tasks"], consistency["tasks"]):
        lines.append(f"| {source['task_id']} | {source['status']} | {source['matched_user']}/{source['expected_user']} | "
                     f"{source['matched_evidence']}/{source['expected_evidence']} | "
                     f"{source['matched_formula']}/{source['expected_formula']} | {len(gt['conflicts'])} |")
    lines.extend(["", f"GT consistency: {consistency['status']}", f"All conflicts: {consistency['conflict_count']}",
                  f"Old source overlap: {report['summary']['old_source_overlap']}", "",
                  *[f"- {error}" for error in report["errors"]]])
    for row in consistency["tasks"]:
        lines.extend(f"- {row['task_id']}: {error}" for error in row["conflicts"])
    REPORT.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report["status"], report["summary"])
    print("GT", consistency["status"], consistency["conflict_types"])
    for row in report["tasks"]:
        if row["errors"]:
            print(row["task_id"], row["errors"])
    for row in consistency["tasks"]:
        if row["conflicts"]:
            print(row["task_id"], row["conflicts"])
    print("GLOBAL", report["errors"])
    return 0 if can_freeze(report, consistency) else 1


if __name__ == "__main__":
    raise SystemExit(main())
