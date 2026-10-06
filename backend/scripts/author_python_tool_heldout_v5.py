"""Author the v5 held-out draft from new cases and independent reference arithmetic."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation/reference"))
from python_tool_heldout_v5_ground_truth import reference_outputs  # noqa: E402

BASE = ROOT / "evaluation"
BENCHMARK_ID = "python_tool_heldout_v5"
PRODUCT_SHA = "8a720a02caa557a893c4d75245bed01df565b85f"
DB_DIR = Path(r"D:\petroleum-rag-agent\data\vector_db")

# Source locators are editorial choices, not retrieval tests. All old document/page
# and chunk locators are hard-blocked by the authoring gate below.
SOURCES = {
    "R13_K": (13, "Equilibrium Ratio K=y/x", ["formula"], "K=y/x"),
    "W201_PD": (201, "pD  = tD /CD", ["formula"], "pD=tD/CD"),
    "F273_RWA": (273, "Rwa = Rt /F", ["formula"], "Rwa=Rt/F"),
    "W606_VG": (606, "Vg = Vgi - DVg", ["formula"], "Vg=Vgi-DVg"),
    "R74_PF": (74, "pressure in a reservoir at the OWC is 3625 psi", ["numeric"], None),
    "R242_STRESS": (242, "Po = Pf + Pc", ["formula", "interpretation"], "Po=Pf+Pc"),
    "W85_Q": (85, "q =q1+q2", ["formula"], "q=q1+q2"),
    "W169_RATE": (169, "qs   = 9500 STB/D", ["numeric"], None),
    "W171_RATE": (171, "qs = 6130 STB/D", ["numeric"], None),
    "W172_RATE": (172, "qo =  4500 STB/D", ["numeric"], None),
    "F169_SW": (169, "Sw = 50%, 1/Sw", ["numeric", "interpretation"], None),
    "F235_SW": (235, "Therefore, Sw = 35%", ["numeric"], None),
    "F268_SW": (268, "The saturation is 12.4%", ["numeric"], None),
    "W397_SW": (397, "Sw = 1 - Sor", ["formula"], "Sw=1-Sor"),
    "F169_CONTEXT": (169, "require that formation water resistivity", ["interpretation"], None),
}


def inputs(values: dict[str, tuple[float, str]]) -> list[list]:
    return [[name, value, unit] for name, (value, unit) in values.items()]


def cases(rows: dict[str, tuple], names: tuple[str, ...], units: tuple[str, ...]) -> list[list]:
    return [[f"{case}_{name}", float(value), unit]
            for case, values in rows.items() for name, value, unit in zip(names, values, units)]


TASKS = [
    {
        "task_id": "PT5-RE-D1", "domain": "reservoir_engineering", "python_expected": "required",
        "evaluation_stratum": "pipeline_direct", "input_provenance_expected": "user_fact_plus_formula",
        "intro": "Four independent hypothetical vapour-liquid component snapshots. x and y are mole fractions; each row is a separate equilibrium check, not a single mixture.",
        "inputs": cases({"A": (0.12, 0.30), "B": (0.18, 0.36), "C": (0.24, 0.42), "D": (0.32, 0.40)},
                        ("x", "y"), ("", "")),
        "goal": "Use the reservoir-engineering KB equilibrium ratio K=y/x. Report K for A-D, its mean, maximum, minimum, range, the highest-K case, and descending case ranking. Do not interpret these invented snapshots as a real PVT experiment.",
        "sources": ["R13_K"], "formulas": [["R13_K", "K=y/x"]],
    },
    {
        "task_id": "PT5-WT-D2", "domain": "well_test", "python_expected": "required",
        "evaluation_stratum": "pipeline_direct", "input_provenance_expected": "user_fact_plus_formula",
        "intro": "Four independent hypothetical early wellbore-storage type-curve points. All tD and CD inputs are dimensionless; do not infer reservoir permeability.",
        "inputs": cases({"A": (0.24, 0.04), "B": (0.55, 0.11), "C": (0.81, 0.09), "D": (1.04, 0.16)},
                        ("tD", "CD"), ("", "")),
        "goal": "From the KB early-storage relation pD=tD/CD, compute pD at A-D, mean, maximum, minimum, range, highest-pD point and descending ranking. State that this relation applies to the early storage unit-slope period, not radial flow.",
        "sources": ["W201_PD"], "formulas": [["W201_PD", "pD  = tD /CD"]],
    },
    {
        "task_id": "PT5-FE-D3", "domain": "formation_evaluation", "python_expected": "required",
        "evaluation_stratum": "pipeline_direct", "input_provenance_expected": "user_fact_plus_formula",
        "intro": "Four hypothetical normalized resistivity-index checks. Rt and F here are dimensionless normalized inputs, so report a dimensionless Rwa index, not a physical ohm-m water-resistivity measurement.",
        "inputs": cases({"A": (4.8, 24), "B": (7.2, 30), "C": (5.4, 18), "D": (9.6, 32)},
                        ("Rt", "F"), ("", "")),
        "goal": "Apply the KB ratio structure Rwa=Rt/F to each normalized case A-D. Give each Rwa index, mean, maximum, minimum, range, top case and descending ranking; do not label these synthetic ratios measured water resistivity.",
        "sources": ["F273_RWA"], "formulas": [["F273_RWA", "Rwa = Rt /F"]],
    },
    {
        "task_id": "PT5-WT-D4", "domain": "well_test", "python_expected": "required",
        "evaluation_stratum": "pipeline_direct", "input_provenance_expected": "user_fact",
        "intro": "Eight independent hypothetical pressure-derivative instrument QC amplitudes. This is descriptive statistics only; no flow-regime interpretation is requested.",
        "inputs": cases({"A": (18.2,), "B": (21.7,), "C": (19.5,), "D": (24.4,),
                         "E": (16.8,), "F": (22.1,), "G": (20.6,), "H": (23.3,)},
                        ("derivative",), ("psi",)),
        "goal": "Normalize each of eight derivative amplitudes by the maximum. Report all eight dimensionless normalized values, mean and median raw amplitude, population standard deviation, raw range, coefficient of variation, and descending case ranking. Do not infer radial or storage flow from this cross-case QC set.",
        "sources": [], "formulas": [],
    },
    {
        "task_id": "PT5-RE-R1", "domain": "reservoir_engineering", "python_expected": "required",
        "evaluation_stratum": "pipeline_recovery_challenge", "recovery_challenge": "formula",
        "input_provenance_expected": "user_fact_plus_formula",
        "intro": "Four hypothetical gas-volume bookkeeping cases. Each Vgi and DVg is already in the same reservoir-volume unit; these are not gas-in-place estimates.",
        "inputs": cases({"A": (1280, 84), "B": (1460, 155), "C": (1195, 72), "D": (1530, 204)},
                        ("Vgi", "DVg"), ("bbl", "bbl")),
        "goal": "Locate the separate KB gas-volume relation Vg=Vgi-DVg. Calculate remaining Vg for A-D, mean, maximum, minimum, range, the leading case and descending ranking. Distinguish the user volumes from the cited formula.",
        "sources": ["W606_VG"], "formulas": [["W606_VG", "Vg = Vgi - DVg"]],
    },
    {
        "task_id": "PT5-RE-R2", "domain": "reservoir_engineering", "python_expected": "required",
        "evaluation_stratum": "pipeline_recovery_challenge", "recovery_challenge": "fact_and_formula",
        "input_provenance_expected": "user_fact_plus_evidence_fact_plus_formula",
        "intro": "Use the separately documented example fluid pressure at the oil-water contact as a shared illustrative Pf. Four proposed compacting-stress values below are hypothetical; they are not observed in that field.",
        "inputs": cases({"A": (315,), "B": (475,), "C": (625,), "D": (790,)}, ("Pc",), ("psi",)),
        "evidence": {"R74_fluid_pressure_psi": ["R74_PF", "If_the_pressure_in_a_reservoir_at_the_OWC", 3625, "psi"]},
        "goal": "Retrieve the example Pf and the separate rock-stress balance Po=Pf+Pc. Compute illustrative Po for A-D, mean, maximum, minimum, range, top case and descending ranking in psi. Do not claim these hypothetical overburden stresses are field measurements.",
        "sources": ["R74_PF", "R242_STRESS"], "formulas": [["R242_STRESS", "Po = Pf + Pc"]],
    },
    {
        "task_id": "PT5-WT-E1", "domain": "well_test", "python_expected": "required",
        "evaluation_stratum": "end_to_end", "input_provenance_expected": "evidence_fact_plus_formula",
        "intro": "Find three distinct historical well-test exercise rates, all in STB/D. A, B and C are separate examples, not simultaneous layers in one actual reservoir. Pairing them is an explicitly hypothetical arithmetic comparison.",
        "inputs": [],
        "evidence": {
            "W169_rate": ["W169_RATE", "qs", 9500, "STB/D"],
            "W171_rate": ["W171_RATE", "qs", 6130, "STB/D"],
            "W172_rate": ["W172_RATE", "qo", 4500, "STB/D"],
        },
        "goal": "Using the KB layer-rate addition identity q=q1+q2, compute the counterfactual pairwise sums AB, AC and BC from the three cited example rates. Report each sum in STB/D, mean, maximum, minimum, range, leading pair and descending ranking. Never call the paired sums actual field production.",
        "sources": ["W169_RATE", "W171_RATE", "W172_RATE", "W85_Q"],
        "formulas": [["W85_Q", "q =q1+q2"]],
    },
    {
        "task_id": "PT5-FE-E2", "domain": "formation_evaluation", "python_expected": "required",
        "evaluation_stratum": "end_to_end", "input_provenance_expected": "evidence_fact_plus_relation",
        "intro": "Locate three explicitly labelled illustrative water-saturation examples in separate formation-evaluation passages. They are not samples from the same interval.",
        "inputs": [],
        "evidence": {
            "F169_water_saturation": ["F169_SW", "Sw", 50, "%"],
            "F235_water_saturation": ["F235_SW", "Sw", 35, "%"],
            "F268_water_saturation": ["F268_SW", "saturation", 12.4, "%"],
        },
        "goal": "For each cited illustrative Sw, use the saturation-budget relation non-water fraction = 100% - Sw (oil plus any gas, not oil saturation alone). Report A-C non-water percentages, their mean, maximum, minimum and range; also report mean and range of the three Sw values, leading non-water example and descending ranking. Keep provenance and distinct-example caveats explicit.",
        "sources": ["F169_SW", "F235_SW", "F268_SW"], "formulas": [],
    },
    {
        "task_id": "PT5-RE-O1", "domain": "reservoir_engineering", "python_expected": "optional",
        "evaluation_stratum": "optional", "input_provenance_expected": "user_fact_plus_formula",
        "intro": "One independent, hypothetical rock-stress identity check.",
        "inputs": inputs({"fluid_pressure": (3210, "psi"), "compacting_stress": (540, "psi")}),
        "goal": "Apply the cited Po=Pf+Pc balance once and report overburden pressure in psi. Direct arithmetic is sufficient; Python is optional.",
        "sources": ["R242_STRESS"], "formulas": [["R242_STRESS", "Po = Pf + Pc"]],
    },
    {
        "task_id": "PT5-WT-O2", "domain": "well_test", "python_expected": "optional",
        "evaluation_stratum": "optional", "input_provenance_expected": "user_fact_plus_formula",
        "intro": "One hypothetical saturation-bookkeeping check, not a flow-regime inference.",
        "inputs": inputs({"residual_oil_saturation": (0.28, "")}),
        "goal": "Use the source water/oil saturation identity Sw=1-Sor once. Report Sw as a dimensionless fraction. Direct arithmetic is sufficient; Python is optional.",
        "sources": ["W397_SW"], "formulas": [["W397_SW", "Sw = 1 - Sor"]],
    },
    {
        "task_id": "PT5-RE-N1", "domain": "reservoir_engineering", "python_expected": "not_needed",
        "evaluation_stratum": "not_needed", "input_provenance_expected": "knowledge_base",
        "intro": "Conceptual explanation only; no case numbers or calculation request.", "inputs": [],
        "goal": "Explain the physical distinction among overburden pressure, pore-fluid pressure and compacting stress in the cited reservoir-rock discussion, including what can change during depletion. Cite the source; do not calculate.",
        "sources": ["R242_STRESS"], "formulas": [],
    },
    {
        "task_id": "PT5-FE-N2", "domain": "formation_evaluation", "python_expected": "not_needed",
        "evaluation_stratum": "not_needed", "input_provenance_expected": "knowledge_base",
        "intro": "Conceptual log-interpretation caution only; no arithmetic request.", "inputs": [],
        "goal": "Describe the assumptions required for a resistivity-versus-porosity crossplot to support water-saturation interpretation, and why gas zones can mislead neutron-resistivity interpretation. Cite the KB; do not calculate.",
        "sources": ["F169_CONTEXT"], "formulas": [],
    },
]


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
        "PT5-RE-D1": ("x", "y"), "PT5-WT-D2": ("tD", "CD"),
        "PT5-FE-D3": ("Rt", "F"), "PT5-RE-R1": ("Vgi", "DVg"),
    }
    if task_id in variable_names:
        bindings = {case: {variable: f"{case}_{variable}" for variable in variable_names[task_id]}
                    for case in "ABCD"}
    elif task_id == "PT5-RE-R2":
        bindings = {case: {"Pf": "R74_fluid_pressure_psi", "Pc": f"{case}_Pc"} for case in "ABCD"}
    elif task_id == "PT5-WT-E1":
        bindings = {"AB": {"q1": "W169_rate", "q2": "W171_rate"},
                    "AC": {"q1": "W169_rate", "q2": "W172_rate"},
                    "BC": {"q1": "W171_rate", "q2": "W172_rate"}}
    elif task_id == "PT5-RE-O1":
        bindings = {"default": {"Pf": "fluid_pressure", "Pc": "compacting_stress"}}
    elif task_id == "PT5-WT-O2":
        bindings = {"default": {"Sor": "residual_oil_saturation"}}
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
    exclusions = {"excluded_task_prefixes": ["PY-", "PY2-", "PY3-", "PY3R1-", "PT4-", "PT4R1-", "AG-Q-", "D1-D8"],
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
