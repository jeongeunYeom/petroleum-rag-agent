"""LLM-free authoring gates. Never runs retrieval, agent, binder, or contract code."""

from __future__ import annotations

import hashlib
import json
import math
import re
import ast
import subprocess
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evaluation/reference"))
from app.services.evidence_fact_registry import EvidenceFactRegistry  # noqa: E402
from app.services.formula_source_registry import FormulaSourceRegistry, expression_variables, normalize_formula  # noqa: E402
from app.services.user_fact_registry import UNIT, UserFactRegistry  # noqa: E402
from python_tool_heldout_v5_ground_truth import reference_outputs  # noqa: E402

BASE = ROOT / "evaluation"
PREFIX = "python_tool_heldout_v5"
PRODUCT_SHA = "8a720a02caa557a893c4d75245bed01df565b85f"
DB = Path(r"D:\petroleum-rag-agent\data\vector_db\chroma.sqlite3")


def path(suffix: str) -> Path:
    return BASE / f"{PREFIX}{suffix}"


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def write(p: Path, data: object) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def same(a: object, b: object, tolerance: float = 0) -> bool:
    if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
        return math.isclose(float(a), float(b), abs_tol=tolerance, rel_tol=0)
    return a == b


def normalized_scenario(value: str) -> str:
    """Erase numeric literals so mere number substitutions cannot evade reuse checks."""
    return re.sub(r"\s+", " ", re.sub(r"\d+(?:\.\d+)?", "#", value.casefold())).strip()


def contamination_checks(tasks: list[dict]) -> tuple[list[dict], list[dict]]:
    old_tasks = []
    for version in ("v1", "v2", "v3", "v3r1", "v4", "v4r1"):
        branch = f"feature/python-tool-heldout-{version}"
        file = f"evaluation/python_tool_heldout_{version}.json"
        raw = subprocess.check_output(["git", "show", f"{branch}:{file}"], cwd=ROOT)
        old_tasks.extend(json.loads(raw)["tasks"])
    old_tasks.extend(load(BASE / "agentic_heldout_v1.json").get("tasks", []))
    task_overlap = []
    for task in tasks:
        goal = normalized_scenario(task["goal"])
        topic = normalized_scenario(task["topic"])
        for old in old_tasks:
            old_goal = normalized_scenario(old.get("goal", ""))
            old_topic = normalized_scenario(old.get("topic", ""))
            if (goal == old_goal or topic == old_topic or
                    old_goal and SequenceMatcher(None, goal, old_goal).ratio() >= 0.9 and
                    old_topic and SequenceMatcher(None, topic, old_topic).ratio() >= 0.9):
                task_overlap.append({"new": task["task_id"], "old": old.get("task_id", old.get("question_id", "unknown"))})
    smoke_literals = []
    for file in [*sorted((ROOT / "backend/scripts").glob("smoke_python_tool_v*.py")),
                 *sorted((ROOT / "backend/tests").glob("test_goal_python_v*.py"))]:
        tree = ast.parse(file.read_text(encoding="utf-8"))
        smoke_literals.extend(node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and
                              isinstance(node.value, str) and len(node.value) >= 40)
    smoke_overlap = []
    for task in tasks:
        for literal in smoke_literals:
            probe = normalized_scenario(literal)
            if len(probe) >= 50 and (probe == normalized_scenario(task["goal"]) or
                                      probe == normalized_scenario(task["topic"])):
                smoke_overlap.append({"task": task["task_id"], "literal": literal[:80]})
    return task_overlap, smoke_overlap


def validate_ground_truth_consistency(task: dict, reference: dict) -> list[str]:
    """Recompute once, then compare every frozen scoring projection to canonical GT."""
    gt = task["ground_truth"]
    errors = []
    users = {name: float(value) for name, value, _ in reference["inputs"]}
    evidence = {key: float(row[2]) for key, row in reference["evidence_inputs"].items()}
    fresh = reference_outputs(task["task_id"], users, evidence)
    canonical = gt["canonical_targets"]
    if gt["expected_user_facts"] != reference["inputs"] or gt["expected_evidence_facts"] != list(reference["evidence_inputs"].values()):
        errors.append("SCENARIO_MAPPING_CONFLICT:inputs")
    if len(canonical) != len(fresh) or len({r["target_id"] for r in canonical}) != len(canonical):
        errors.append("REQUIRED_TARGET_MISSING:canonical")
    by_name = {row["semantic_name"]: row for row in canonical}
    if len(by_name) != len(canonical) or set(by_name) != {row["semantic_name"] for row in fresh}:
        errors.append("DUPLICATE_SEMANTIC_OR_MISSING_TARGET")
    for row in fresh:
        current = by_name.get(row["semantic_name"])
        if not current:
            continue
        for key in ("target_type", "unit", "scenario_id"):
            if current.get(key) != row.get(key):
                errors.append(("UNIT" if key == "unit" else "SCENARIO" if key == "scenario_id" else "TYPED") +
                              f"_CONFLICT:{row['semantic_name']}:{key}")
        if not same(current["value"], row["value"], row.get("abs_tolerance", 0) / 10):
            kind = "NUMERIC" if row["target_type"] == "numeric" else "RANKING" if row["target_type"] == "ranking" else "TYPED"
            errors.append(f"{kind}_CONFLICT:{row['semantic_name']}")
        if row["target_type"] == "numeric" and (not row.get("unit") or row.get("abs_tolerance", 0) <= 0):
            errors.append(f"UNIT_CONFLICT:{row['semantic_name']}")
        if current.get("required") is not True:
            errors.append(f"REQUIRED_TARGET_MISSING:{row['semantic_name']}")
    expected = {
        "numeric_targets": {r["semantic_name"] for r in canonical if r["target_type"] == "numeric"},
        "typed_targets": {r["semantic_name"] for r in canonical if r["target_type"] != "numeric"},
        "ranking_targets": {r["semantic_name"] for r in canonical if r["target_type"] == "ranking"},
        "expected_contract_outputs": set(by_name),
    }
    for field, names in expected.items():
        rows = gt[field]
        seen = [r["semantic_name"] for r in rows]
        if len(seen) != len(set(seen)):
            errors.append(f"DUPLICATE_SEMANTIC_CONFLICT:{field}")
        for name in names - set(seen):
            errors.append(f"REQUIRED_TARGET_MISSING:{field}:{name}")
        for row in rows:
            name = row["semantic_name"]
            if name not in names:
                errors.append(f"ORPHAN_TARGET:{field}:{name}")
                continue
            canonical_row = by_name[name]
            if row["target_id"] != canonical_row["target_id"] or not same(row["value"], canonical_row["value"], canonical_row.get("abs_tolerance", 0) / 10):
                errors.append(f"NUMERIC_OR_TYPED_CONFLICT:{field}:{name}")
            if row.get("unit") != canonical_row.get("unit") and field != "typed_targets":
                errors.append(f"UNIT_CONFLICT:{field}:{name}")
    criterion_refs = {ref for criterion in task["success_criteria"] for ref in criterion.get("target_refs", [])}
    if criterion_refs != {row["target_id"] for row in canonical}:
        errors.append("REQUIRED_TARGET_MISSING:criteria")
    for row in canonical:
        relation = row.get("ranking_of") or row.get("extremum_of")
        if not relation:
            continue
        if any(name not in by_name or by_name[name]["target_type"] != "numeric" for name in relation.values()):
            errors.append(f"ORPHAN_TARGET:relation:{row['semantic_name']}")
            continue
        numbers = {case: by_name[name]["value"] for case, name in relation.items()}
        if row.get("ranking_of"):
            answer = sorted(numbers, key=lambda case: ((-numbers[case] if row["order"] == "desc" else numbers[case]), case))
            if row["value"] != answer:
                errors.append(f"RANKING_CONFLICT:{row['semantic_name']}")
        if row.get("extremum"):
            answer = sorted(numbers, key=lambda case: ((-numbers[case] if row["extremum"] == "max" else numbers[case]), case))[0]
            if row["value"] != answer:
                errors.append(f"ARG{'MAX' if row['extremum'] == 'max' else 'MIN'}_CONFLICT:{row['semantic_name']}")
    return sorted(set(errors))


def audit() -> tuple[dict, dict]:
    benchmark = load(path(".json"))
    catalog = load(path("_source_catalog.json"))
    exclusions = load(path("_source_exclusions.json"))
    references = load(BASE / "reference" / f"{PREFIX}_reference_outputs.json")
    tasks = benchmark["tasks"]
    errors = []
    need = Counter(task["python_expected"] for task in tasks)
    strata = Counter(task["evaluation_stratum"] for task in tasks if task["python_expected"] == "required")
    domains = Counter(task["domain"] for task in tasks)
    if benchmark["benchmark_id"] != PREFIX or benchmark["product_code_sha"] != PRODUCT_SHA:
        errors.append("IDENTITY_OR_PRODUCT_SHA")
    if len(tasks) != 12 or len({task["task_id"] for task in tasks}) != 12:
        errors.append("TASK_COUNT")
    if need != {"required": 8, "optional": 2, "not_needed": 2}:
        errors.append("NEED_DISTRIBUTION")
    if strata != {"pipeline_direct": 4, "pipeline_recovery_challenge": 2, "end_to_end": 2}:
        errors.append("STRATUM_DISTRIBUTION")
    if not (domains["reservoir_engineering"] >= 4 and domains["well_test"] >= 3 and domains["formation_evaluation"] >= 2):
        errors.append("DOMAIN_DISTRIBUTION")
    required = [task for task in tasks if task["python_expected"] == "required"]
    canonical = [target for task in required for target in task["ground_truth"]["canonical_targets"]]
    numeric = sum(target["target_type"] == "numeric" for target in canonical)
    typed = len(canonical) - numeric
    ranking = sum(target["target_type"] == "ranking" for target in canonical)
    if len(canonical) < 60 or numeric < 50:
        errors.append("GT_TARGET_SCALE")
    if sum(bool(task["ground_truth"]["numeric_targets"]) and
           bool(task["ground_truth"]["typed_targets"]) for task in required) < 6:
        errors.append("MULTIOUTPUT_DISTRIBUTION")
    if set(references) != {task["task_id"] for task in tasks}:
        errors.append("REFERENCE_TASK_SET")
    old = exclusions["old_sources"]
    old_pairs = {(row["document"], row["page"]) for row in old}
    old_chunks = {row["chunk_id"] for row in old}
    overlaps = [key for key, row in catalog.items() if (row["document"], row["page"]) in old_pairs or row["chunk_id"] in old_chunks]
    if overlaps:
        errors.append("OLD_SOURCE_OVERLAP:" + ",".join(overlaps))
    if any(not task["task_id"].startswith("PT5-") or any(task["task_id"].startswith(prefix)
           for prefix in exclusions["excluded_task_prefixes"]) for task in tasks):
        errors.append("OLD_TASK_REUSE")
    task_overlap, smoke_overlap = contamination_checks(tasks)
    if task_overlap:
        errors.append("OLD_SCENARIO_REUSE:" + str(task_overlap))
    if smoke_overlap:
        errors.append("SYNTHETIC_SMOKE_REUSE:" + str(smoke_overlap))
    if not DB.is_file():
        raise FileNotFoundError(f"Existing DB missing; will not create one: {DB}")
    import chromadb
    collection = chromadb.PersistentClient(path=str(DB.parent)).get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        errors.append(f"KB_COUNT:{collection.count()}")
    found = collection.get(ids=[row["chunk_id"] for row in catalog.values()], include=["metadatas", "documents"])
    by_id = {key: (meta, text) for key, meta, text in zip(found["ids"], found["metadatas"], found["documents"])}
    source_text = {}
    for key, row in catalog.items():
        actual = by_id.get(row["chunk_id"])
        if not actual or actual[0].get("document") != row["document"] or actual[0].get("page") != row["page"] or row["anchor"] not in actual[1] or hashlib.sha256(actual[1].encode()).hexdigest() != row["exact_source_excerpt_sha256"]:
            errors.append(f"SOURCE_INVALID:{key}")
        else:
            source_text[key] = actual[1]
    rows = []
    gt_errors = {}
    for task in tasks:
        task_id = task["task_id"]
        gt = task["ground_truth"]
        checks = []
        extracted = UserFactRegistry.from_topic(task["topic"]).records
        matched_user = [item for item in gt["expected_user_facts"] if any(
            row.name.casefold() == item[0].casefold() and same(row.value, item[1], 1e-9) and
            row.unit.casefold() == item[2].casefold() for row in extracted)]
        if len(matched_user) != len(gt["expected_user_facts"]):
            checks.append("USERF_MISSING")
        unsupported = [unit for _, _, unit in gt["expected_user_facts"] if unit and not re.fullmatch(UNIT, unit, re.I)]
        if unsupported:
            checks.append("UNSUPPORTED_USER_UNIT:" + ",".join(unsupported))
        evidence_hits = []
        for source_id, name, value, unit in gt["expected_evidence_facts"]:
            text = source_text.get(source_id)
            if text:
                facts = EvidenceFactRegistry.from_evidence([{"evidence_id": source_id, "source_type": "knowledge_base", "text": text}]).records
                if any(row.name.casefold() == name.casefold() and same(row.value, value, 1e-9) and row.unit.casefold() == unit.casefold() for row in facts):
                    evidence_hits.append(name)
        if len(evidence_hits) != len(gt["expected_evidence_facts"]):
            checks.append("EFACT_MISSING")
        formula_hits = []
        for source_id, expression in gt["formula_sources"]:
            text = source_text.get(source_id)
            if text:
                formulas = FormulaSourceRegistry.from_evidence([{"evidence_id": source_id, "source_type": "knowledge_base", "text": text}]).records
                if any(row.expression_candidate and normalize_formula(row.raw_span) == normalize_formula(expression) for row in formulas):
                    formula_hits.append(expression)
        if len(formula_hits) != len(gt["formula_sources"]):
            checks.append("FORMULA_MISSING_OR_UNPARSEABLE")
        fact_keys = {item[0] for item in gt["expected_user_facts"]} | {key for key in references[task_id]["evidence_inputs"]}
        for _, expression in gt["formula_sources"]:
            variables = expression_variables(expression)
            if variables is None:
                checks.append("AUTHORING_FORMULA_VARIABLES_UNPARSEABLE")
                continue
            for scenario, bindings in gt["expected_bindings"].items():
                if set(bindings) != variables or set(bindings.values()) - fact_keys:
                    checks.append(f"AUTHORING_VARIABLE_MAPPING:{scenario}")
        if not set(gt["source_ids"]) <= catalog.keys():
            checks.append("SOURCE_ID_MISSING")
        conflicts = validate_ground_truth_consistency(task, references.get(task_id, {"inputs": [], "evidence_inputs": {}}))
        gt_errors[task_id] = conflicts
        checks.extend(conflicts)
        rows.append({"task_id": task_id, "status": "PASS" if not checks else "FAIL",
                     "expected_user": len(gt["expected_user_facts"]), "matched_user": len(matched_user),
                     "expected_evidence": len(gt["expected_evidence_facts"]), "matched_evidence": len(evidence_hits),
                     "expected_formula": len(gt["formula_sources"]), "matched_formula": len(formula_hits),
                     "unsupported_required_units": unsupported, "errors": checks})
    errors.extend(f"{row['task_id']}:{','.join(row['errors'])}" for row in rows if row["errors"])
    counts = {
        "user": {"expected": sum(row["expected_user"] for row in rows), "matched": sum(row["matched_user"] for row in rows)},
        "evidence": {"expected": sum(row["expected_evidence"] for row in rows), "matched": sum(row["matched_evidence"] for row in rows)},
        "formula": {"expected": sum(row["expected_formula"] for row in rows), "matched": sum(row["matched_formula"] for row in rows)},
    }
    report = {"benchmark_id": PREFIX, "product_sha": PRODUCT_SHA, "status": "PASS" if not errors else "FAIL",
              "task_count": len(tasks), "python_need_count": dict(need), "required_stratum_count": dict(strata),
              "domain_count": dict(domains), "required_canonical_targets": len(canonical),
              "required_numeric_targets": numeric, "required_typed_targets": typed,
              "required_ranking_targets": ranking, "representability": counts,
              "old_task_overlap": len(task_overlap), "old_source_overlap": len(overlaps),
              "synthetic_smoke_reuse": len(smoke_overlap),
              "calls": {key: 0 for key in ("llm", "agent", "planner", "binder", "contract", "retrieval")},
              "kb_collection_count": collection.count(), "rows": rows, "errors": errors,
              "hashes": {"benchmark_draft_sha256": digest(path(".json"))}}
    conflict_categories = {kind: sum(kind in issue for issues in gt_errors.values() for issue in issues)
                           for kind in ("NUMERIC", "UNIT", "TYPED", "RANKING", "TIE", "ARGMIN", "ARGMAX",
                                        "SCENARIO", "DUPLICATE", "ORPHAN", "MISSING")}
    audit = {"status": "PASS" if not any(gt_errors.values()) else "FAIL", "conflict_count": sum(map(len, gt_errors.values())),
             "conflict_categories": conflict_categories, "by_task": gt_errors}
    return report, audit


def main() -> int:
    report, gt = audit()
    write(BASE / "review" / f"{PREFIX}_preflight.json", report)
    write(BASE / "review" / f"{PREFIX}_gt_consistency.json", gt)
    md = [f"# {PREFIX} preflight", "", f"Status: {report['status']}",
          f"Product SHA: {PRODUCT_SHA}", f"Tasks: {report['task_count']}",
          f"Need: {report['python_need_count']}", f"Strata: {report['required_stratum_count']}",
          f"Domains: {report['domain_count']}", f"Representability: {report['representability']}",
          f"Required targets: {report['required_canonical_targets']} (numeric {report['required_numeric_targets']}, typed {report['required_typed_targets']})",
          f"Old source overlaps: {report['old_source_overlap']}",
          f"LLM/Agent/Planner/Binder/Contract/Retrieval calls: {report['calls']}",
          f"GT conflicts: {gt['conflict_count']}", "", "## Errors", ""]
    md.extend(f"- {error}" for error in report["errors"])
    (BASE / "review" / f"{PREFIX}_preflight.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "task_count", "python_need_count", "required_stratum_count",
                                               "domain_count", "required_canonical_targets", "required_numeric_targets",
                                               "representability", "old_source_overlap", "calls", "errors")}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" and gt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
