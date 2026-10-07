"""Author the v6 held-out draft from new cases and independent reference arithmetic."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation/reference"))
from python_tool_heldout_v6_ground_truth import reference_outputs  # noqa: E402

BASE = ROOT / "evaluation"
BENCHMARK_ID = "python_tool_heldout_v6"
PRODUCT_SHA = "ec987f074648a6eb442b911044dff4808bc87d84"
DB_DIR = Path(r"D:\petroleum-rag-agent\data\vector_db")

# Source locators are editorial choices, not retrieval tests. All old document/page
# and chunk locators are hard-blocked by the authoring gate below.
SOURCES = {
    "R349_RD": (349, "reD = re/rw", ["formula"], "reD=re/rw"),
    "W365_Q2": (365, "q2 = 10/T2", ["formula"], "q2=10/T2"),
    "H323_MSIG": (323, "MSIG = MPHI + MCBW", ["formula"], "MSIG=MPHI+MCBW"),
    "I703_KL": (703, "kL=kg/(1+b/p)", ["formula"], "kL=kg/(1+b/p)"),
    "R880_C13": (880, "re = 10,000ft", ["numeric"], None),
    "R880_C14": (880, "re = 5000ft", ["numeric"], None),
    "W88_LAYERS": (88, "Layer 1", ["numeric"], None),
    "W89_CASE": (89, "k = 24 md", ["numeric"], None),
    "F141_POR": (141, "porosity is 18%", ["numeric"], None),
    "W449_CONTEXT": (449, "being drained by the producing wells", ["interpretation"], None),
    "H168_CONTEXT": (168, "bound water and the formation connate water", ["interpretation"], None),
}


TASKS = json.loads((BASE / "python_tool_heldout_v6_spec.json").read_text(encoding="utf-8"))["tasks"]
def sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def write(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def old_sources() -> list[dict]:
    branch = "feature/python-tool-heldout-v4r1"
    def show(path: str) -> object:
        data = subprocess.check_output(["git", "show", f"{branch}:{path}"], cwd=ROOT)
        return json.loads(data)
    old = list(show("evaluation/python_tool_heldout_v4r1_source_exclusions.json")["old_sources"])
    for name, row in show("evaluation/python_tool_heldout_v4r1_source_catalog.json").items():
        old.append({"benchmark": "v4r1", "source_id": name, "document": row["document"],
                    "page": row["page"], "chunk_id": row["chunk_id"], "anchor": row["anchor"]})
    v5 = json.loads(subprocess.check_output(
        ["git", "show", "feature/python-tool-heldout-v5:evaluation/python_tool_heldout_v5_source_catalog.json"],
        cwd=ROOT))
    for name, row in v5.items():
        old.append({"benchmark": "v5", "source_id": name, "document": row["document"],
                    "page": row["page"], "chunk_id": row["chunk_id"], "anchor": row["anchor"]})
    return old


def build_catalog() -> tuple[dict, list[dict]]:
    if not (DB_DIR / "chroma.sqlite3").is_file():
        raise FileNotFoundError("Existing 18,976-chunk ChromaDB is required; no new DB is created")
    import chromadb
    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        raise ValueError(f"Unexpected collection count: {collection.count()}")
    old = old_sources()
    blocked = {(item["document"], item["page"]) for item in old}
    catalog = {}
    for key, (page, anchor, roles, signature) in SOURCES.items():
        found = collection.get(where={"page": page}, include=["metadatas", "documents"])
        matching = [(chunk_id, meta, text) for chunk_id, meta, text in
                    zip(found["ids"], found["metadatas"], found["documents"]) if anchor in text]
        if len(matching) != 1:
            raise ValueError(f"Source locator {key} matched {len(matching)} chunks")
        chunk_id, meta, text = matching[0]
        document = meta["document"]
        overlap = (document, page) in blocked or any(item["chunk_id"] == chunk_id for item in old)
        if overlap:
            raise ValueError(f"Old document/page or chunk overlap: {key} {document} p.{page}")
        catalog[key] = {
            "document": document, "page": page, "chunk_id": chunk_id, "anchor": anchor,
            "source_role": roles, "exact_source_excerpt_sha256": sha(text),
            "expected_equation_signature": signature,
            "expected_semantic_facts": [],
            "formula_variable_authoring_audit": [],
            "task_ids": [task["task_id"] for task in TASKS if key in task["sources"]],
            "old_source_overlap": False,
        }
    for task in TASKS:
        for key, name, value, unit in task.get("evidence", {}).values():
            catalog[key]["expected_semantic_facts"].append({"name": name, "value": value, "unit": unit})
        for key, expression in task["formulas"]:
            rhs = expression.split("=", 1)[1]
            variables = sorted(set(re.findall(r"\b[A-Za-z][A-Za-z0-9_]*\b", rhs)))
            catalog[key]["formula_variable_authoring_audit"].append({
                "task_id": task["task_id"], "rhs_variables": variables,
                "intended_user_facts": [{"name": name, "unit": unit} for name, _, unit in task["inputs"]],
                "intended_evidence_facts": [{"name": row[1], "unit": row[3]} for row in task.get("evidence", {}).values()],
                "scenario_labels": sorted({name.split("_", 1)[0] for name, _, _ in task["inputs"] if "_" in name}),
                "audit_note": "Editorial variable-role mapping only; product binder is not run in preflight.",
            })
    return catalog, old


def derived_ground_truth(spec: dict) -> tuple[dict, dict]:
    user = {name: float(value) for name, value, _ in spec["inputs"]}
    evidence = {key: float(row[2]) for key, row in spec.get("evidence", {}).items()}
    raw = reference_outputs(spec["task_id"], user, evidence)
    canonical = []
    for row in raw:
        target = dict(row)
        target["target_id"] = "T_" + re.sub(r"[^A-Z0-9]+", "_", (spec["task_id"] + "_" + row["semantic_name"]).upper())
        target["required"] = True
        target["source"] = "reference_calculator"
        canonical.append(target)
    numeric = [{k: target[k] for k in ("target_id", "semantic_name", "value", "unit", "abs_tolerance", "required")}
               for target in canonical if target["target_type"] == "numeric"]
    typed = [{k: target[k] for k in ("target_id", "semantic_name", "target_type", "value", "required")}
             for target in canonical if target["target_type"] != "numeric"]
    ranking = [dict(target) for target in canonical if target["target_type"] == "ranking"]
    task_id = spec["task_id"]
    variable_names = {
        "PT6-RE-S1": ("re", "rw"),
        "PT6-WT-S2": ("T2",),
        "PT6-FE-S3": ("MPHI", "MCBW"),
        "PT6-RE-R1": ("kg", "b", "p"),
    }
    if task_id in variable_names:
        bindings = {case: {variable: f"{case}_{variable}" for variable in variable_names[task_id]}
                    for case in "ABCD"}
    elif task_id == "PT6-RE-E1":
        bindings = {"C13": {"re": "C13_re", "rw": "C13_rw"},
                    "C14": {"re": "C14_re", "rw": "C14_rw"}}
    else:
        bindings = {}
    gt = {
        "canonical_targets": canonical, "numeric_targets": numeric, "typed_targets": typed,
        "ranking_targets": ranking,
        "expected_contract_outputs": [{"target_id": t["target_id"], "semantic_name": t["semantic_name"],
                                       "type": t["target_type"], "value": t["value"], "unit": t["unit"]}
                                      for t in canonical],
        "expected_user_facts": spec["inputs"],
        "expected_evidence_facts": list(spec.get("evidence", {}).values()),
        "formula_sources": spec["formulas"], "source_ids": spec["sources"],
        "expected_bindings": bindings,
        "required_claims": [{"claim_id": "CL_PROVENANCE", "text": "Attribute the relation and numeric facts to their respective sources.",
                             "source_ids": spec["sources"], "target_refs": []}],
    }
    reference = {"inputs": spec["inputs"], "evidence_inputs": spec.get("evidence", {}),
                 "canonical_targets": canonical, "numeric_targets": numeric, "typed_targets": typed,
                 "ranking_targets": ranking, "raw_reference_calculation": raw}
    return gt, reference


def main() -> None:
    catalog, old = build_catalog()
    tasks = []
    references = {}
    for spec in TASKS:
        gt, reference = derived_ground_truth(spec)
        references[spec["task_id"]] = reference
        target_ids = [row["target_id"] for row in gt["canonical_targets"]]
        criteria = [
            {"criterion_id": "C1", "description": "Use the stated relation and distinguish user and KB provenance.",
             "required": True},
            {"criterion_id": "C2", "description": "Report every requested numeric or typed output with scenario and unit.",
             "target_refs": target_ids, "required": True},
            {"criterion_id": "C3", "description": "Respect the scenario-specific interpretation and citation caveat.",
             "required": True},
        ]
        topic = spec["intro"] + ("\n" + "\n".join(f"{name}={value:g}{(' ' + unit) if unit else ''}"
                                                    for name, value, unit in spec["inputs"]) if spec["inputs"] else "")
        tasks.append({"task_id": spec["task_id"], "benchmark_id": BENCHMARK_ID,
                      "domain": spec["domain"], "python_expected": spec["python_expected"],
                      "evaluation_stratum": spec["evaluation_stratum"],
                      "recovery_challenge": spec.get("recovery_challenge"),
                      "input_provenance_expected": spec["input_provenance_expected"],
                      "topic": topic, "goal": spec["goal"], "expected_result": None,
                      "success_criteria": criteria, "ground_truth": gt})
    benchmark = {"benchmark_id": BENCHMARK_ID, "product_code_sha": PRODUCT_SHA, "tasks": tasks}
    exclusions = {"excluded_task_prefixes": ["PY-", "PY2-", "PY3-", "PY3R1-", "PT4-", "PT4R1-", "PT5-", "AG-Q-", "D1-D8"],
                  "old_sources": old}
    rubric = {"benchmark_id": BENCHMARK_ID, "authority": "independent deterministic GT; blind reviewer qualitative only",
              "goal_success": "all required external criteria pass", "numeric_tolerance": "per canonical target",
              "strong_python_benefit": "OFF criterion fail AND ON GT-correct CALC AND grounded adoption AND ON criterion pass",
              "no_selective_reruns": True}
    write(BASE / f"{BENCHMARK_ID}.json", benchmark)
    write(BASE / f"{BENCHMARK_ID}_source_catalog.json", catalog)
    write(BASE / f"{BENCHMARK_ID}_source_exclusions.json", exclusions)
    write(BASE / "reference" / f"{BENCHMARK_ID}_reference_outputs.json", references)
    write(BASE / f"{BENCHMARK_ID}_rubric.json", rubric)
    print(f"Draft {BENCHMARK_ID}: {len(tasks)} tasks, {len(catalog)} new source chunks, "
          f"{sum(len(t['ground_truth']['canonical_targets']) for t in tasks)} canonical targets")


if __name__ == "__main__":
    main()
