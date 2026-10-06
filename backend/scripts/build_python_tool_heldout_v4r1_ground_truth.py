"""Author v4r1 from new scenarios and an independent, single-source GT calculator."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation/reference"))
from python_tool_heldout_v4r1_ground_truth import reference_outputs  # noqa: E402

BASE = ROOT / "evaluation"
BENCHMARK = BASE / "python_tool_heldout_v4r1.json"
CATALOG = BASE / "python_tool_heldout_v4r1_source_catalog.json"
REFERENCE_OUTPUTS = BASE / "reference/python_tool_heldout_v4r1_reference_outputs.json"
MANIFEST = BASE / "python_tool_heldout_v4r1_manifest.json"
DB = Path(r"D:\petroleum-rag-agent\data\vector_db\chroma.sqlite3")
PRODUCT_SHA = "2646be1e5439cd689fdd236e064e2f9b64255274"

SOURCES = {
    "R648": ("f9156c6016ef3dddce387aa3703983f4ed164713a72b96823d4e2480c2ad1d12:p648:c0", "F = NEo + NmEg + NEfw +We", "formula"),
    "H1424": ("779ed04201882344620f9332ecb57c58a34eeb3ed30cfd86d7adffe58d7048fc:p1424:c2", "Tap = 1 / (1 /Ta + 1 /Tb)", "formula"),
    "W316": ("01155892bc533f0bcead8df919b991f143103406ac5f138350fe32296fe15462:p316:c0", "Pwf = m* t + pt", "formula"),
    "W219": ("01155892bc533f0bcead8df919b991f143103406ac5f138350fe32296fe15462:p219:c1", "derivative plateau", "interpretation"),
    "R336": ("f9156c6016ef3dddce387aa3703983f4ed164713a72b96823d4e2480c2ad1d12:p336:c0", "volume = A*dx", "formula"),
    "P474": ("18cc9578972289d5894ec1af7abf2adcf74b8451553e00b6a5531c8de079d785:p474:c1", "Thickness of reservoir sand", "numeric"),
    "S42": ("3f863132a97e940476166548c7f88e2b3bc6107e5ec06778061c39cdd0646e94:p42:c0", "Permeability, khi", "numeric"),
    "F24": ("d3d33e53ea2478fe3729bba7019d8604095c5b6c2c2d3dc0bd7e9608a9931ebb:p24:c0", "Column stacking of rock grains", "numeric"),
}


def facts(rows: dict[str, tuple[float, str]]) -> list[list]:
    return [[name, value, unit] for name, (value, unit) in rows.items()]


def cases(values: dict[str, tuple], names: tuple[str, ...], units: tuple[str, ...]) -> list[list]:
    return [[f"{case}_{name}", value, unit]
            for case, row in values.items() for name, value, unit in zip(names, row, units)]


TASKS = [
    {
        "task_id": "PT4R1-RE-P1", "domain": "reservoir_engineering", "python_expected": "required",
        "evaluation_stratum": "pipeline", "input_provenance_expected": "user_fact_plus_formula",
        "intro": "Four new hypothetical material-balance bookkeeping periods. Each reported term is already a reservoir-volume contribution; do not multiply it by N again.",
        "inputs": cases({"A": (1200, 340, 95, 220), "B": (1480, 215, 125, 330),
                         "C": (1110, 540, 140, 180), "D": (1670, 310, 105, 260)},
                        ("NEo", "NmEg", "NEfw", "We"), ("bbl",) * 4),
        "goal": "Find the Havlena-Odeh shorthand F=NEo+NmEg+NEfw+We in the reservoir-engineering KB. Compute F for every period, mean F, maximum F, and the maximum period. Do not infer original oil in place from these terms alone.",
        "sources": ["R648"], "formulas": [["R648", "F = NEo + NmEg + NEfw +We"]],
    },
    {
        "task_id": "PT4R1-RE-P2", "domain": "reservoir_engineering", "python_expected": "required",
        "evaluation_stratum": "pipeline", "input_provenance_expected": "user_fact_plus_formula",
        "intro": "Four hypothetical reservoir-simulation cell interfaces. Ta and Tb are already normalized, dimensionless half-cell transmissibility factors; this is not a field-unit flow forecast.",
        "inputs": cases({"I1": (240, 360), "I2": (180, 510), "I3": (420, 275), "I4": (420, 275)},
                        ("Ta", "Tb"), ("", "")),
        "goal": "Use the handbook two-point harmonic interface relation Tap=1/(1/Ta+1/Tb). Calculate Tap at each interface, mean and maximum Tap, all tied top-interface IDs, and the full descending interface ranking with lexical tie break.",
        "sources": ["H1424"], "formulas": [["H1424", "Tap = 1 / (1 /Ta + 1 /Tb)"]],
    },
    {
        "task_id": "PT4R1-WT-P3", "domain": "well_test", "python_expected": "required",
        "evaluation_stratum": "pipeline", "input_provenance_expected": "user_fact_plus_formula",
        "intro": "Four independent, hypothetical constant-rate bounded-well forecasts. Each slope number is a psi/day coefficient, and each time is measured in days.",
        "inputs": cases({"A": (4320, -9.5, 14), "B": (4180, -7.75, 18),
                         "C": (4410, -12.25, 11), "D": (4275, -6.5, 20)},
                        ("p0", "slope_psi_per_day", "time"), ("psi", "", "days")),
        "goal": "Use the well-test semi-steady linear flowing-pressure relation Pwf=m*t+p0. Compute each forecast Pwf and pressure drop, mean Pwf, and the lowest-Pwf well. These are illustrative inputs, not a measured drainage-area estimate.",
        "sources": ["W316"], "formulas": [["W316", "Pwf = m* t + pt"]],
    },
    {
        "task_id": "PT4R1-WT-P4", "domain": "well_test", "python_expected": "required",
        "evaluation_stratum": "pipeline", "input_provenance_expected": "user_fact_plus_interpretation",
        "intro": "Five hypothetical pressure-derivative observations during one candidate middle-time window. Derivative values are pressure units, not pressure itself.",
        "inputs": cases({"D1": (0.5, 21.0), "D2": (1, 21.4), "D3": (2, 21.7),
                         "D4": (4, 21.6), "D5": (8, 21.8)},
                        ("time", "derivative"), ("hours", "psi")),
        "goal": "For each adjacent pair compute the log-log derivative slope ln(p'2/p'1)/ln(t2/t1); report mean and maximum absolute slope. State whether these data are a derivative-plateau candidate using the predeclared |slope|<0.05 rule, while noting this alone does not prove a unique reservoir model.",
        "sources": ["W219"], "formulas": [],
    },
    {
        "task_id": "PT4R1-RE-P5", "domain": "reservoir_engineering", "python_expected": "required",
        "evaluation_stratum": "pipeline", "input_provenance_expected": "user_fact_plus_evidence_fact_plus_formula",
        "intro": "Four hypothetical areal development blocks; their areas are user inputs. Locate the reservoir-sand thickness in the separate production-technology field example, and use it only as a common illustrative thickness.",
        "inputs": facts({"B1_area": (7.5, "acres"), "B2_area": (12.25, "acres"),
                         "B3_area": (9.8, "acres"), "B4_area": (14.1, "acres")}),
        "evidence": {"P474_thickness_ft": ["P474", "Thickness_of_reservoir_sand", 140, "ft"]},
        "goal": "Retrieve the source thickness and the separate porous-rock cuboid relation bulk volume=A*dx. Compute bulk volume in acre-ft for all four proposed blocks, total volume, and largest block. Do not turn bulk volume into pore volume without porosity.",
        "sources": ["P474", "R336"], "formulas": [["R336", "volume = A*dx"]],
    },
    {
        "task_id": "PT4R1-WT-P6", "domain": "well_test", "python_expected": "required",
        "evaluation_stratum": "pipeline", "input_provenance_expected": "user_fact",
        "intro": "Eight hypothetical shut-in gauge readings from a short calibration window. This is a numerical QC regression only, not reservoir-flow-regime identification.",
        "inputs": cases({f"M{i}": (i, p) for i, p in enumerate((3602, 3611, 3617, 3628, 3635, 3646, 3651, 3663), 1)},
                        ("time", "pressure"), ("hours", "psi")),
        "goal": "Fit ordinary least-squares pressure=a+b*time; report eight fitted values, slope in psi/hour, intercept, population RMSE of the eight residuals, and the 10-hour fitted forecast. Do not extrapolate a reservoir mechanism.",
        "sources": [], "formulas": [],
    },
    {
        "task_id": "PT4R1-RE-E1", "domain": "reservoir_engineering", "python_expected": "required",
        "evaluation_stratum": "end_to_end", "input_provenance_expected": "user_fact_plus_evidence_fact_plus_formula",
        "intro": "Two hypothetical simulation interfaces with different user-proposed face areas. Retrieve the low/high permeability and thickness values from the Heriot-Watt reservoir-simulation uncertainty table; pair low with low and high with high.",
        "inputs": facts({"J1_area": (12.5, "acres"), "J2_area": (9.75, "acres")}),
        "evidence": {
            "S42_low_k_mD": ["S42", "khi", 400, "mD"],
            "S42_high_k_mD": ["S42", "khi_2", 1600, "mD"],
            "S42_low_h_ft": ["S42", "Zhi", 20, "ft"],
            "S42_high_h_ft": ["S42", "Zhi_2", 40, "ft"],
        },
        "goal": "Retrieve the handbook Cartesian-grid relations Ta=Ka*Aa/(da/2), Tb=Kb*Ab/(db/2), Tap=1/(1/Ta+1/Tb). For each area compute Ta, Tb, Tap as unscaled mD*acre/ft indices, then mean Tap and the larger-Tap interface. Do not report physical flow rate without a conversion and mobility.",
        "sources": ["S42", "H1424"],
        "formulas": [["H1424", "Ta = Ka · Aa / (da / 2)"], ["H1424", "Tb = Kb · Ab / (db / 2)"],
                     ["H1424", "Tap = 1 / (1 /Ta + 1 /Tb)"]],
    },
    {
        "task_id": "PT4R1-FE-E2", "domain": "formation_evaluation", "python_expected": "required",
        "evaluation_stratum": "end_to_end", "input_provenance_expected": "user_fact_plus_evidence_fact",
        "intro": "Five hypothetical porosity-log readings. Find the formation-evaluation text's column-stacking and close-packing reference porosities; these are idealized geometry endpoints, not field cutoffs.",
        "inputs": facts({"L1_porosity": (29.5, "%"), "L2_porosity": (34.2, "%"),
                         "L3_porosity": (38.8, "%"), "L4_porosity": (42.1, "%"), "L5_porosity": (45.4, "%")}),
        "evidence": {
            "F24_column_porosity_percent": ["F24", "ure_2_Column_stacking_of_rock_grains_Porosity", 47.6, "%"],
            "F24_close_porosity_percent": ["F24", "gure_3_Close_packing_of_rock_grains_Porosity", 25.9, "%"],
        },
        "goal": "Compute each reading's normalized position (phi-close)/(column-close), their mean, count within the reference interval, and highest-position log. Keep source reference endpoints separate from user readings; do not infer lithology or saturation.",
        "sources": ["F24"], "formulas": [],
    },
    {
        "task_id": "PT4R1-RE-O1", "domain": "reservoir_engineering", "python_expected": "optional",
        "evaluation_stratum": "optional", "input_provenance_expected": "user_fact_plus_formula",
        "intro": "One independent hypothetical reservoir-volume bookkeeping check.",
        "inputs": facts({"NEo": (860, "bbl"), "NmEg": (110, "bbl"), "NEfw": (45, "bbl"), "We": (95, "bbl")}),
        "goal": "Use the KB shorthand F=NEo+NmEg+NEfw+We and report this one F with unit and formula citation. Direct arithmetic is sufficient; Python is optional.",
        "sources": ["R648"], "formulas": [["R648", "F = NEo + NmEg + NEfw +We"]],
    },
    {
        "task_id": "PT4R1-WT-O2", "domain": "well_test", "python_expected": "optional",
        "evaluation_stratum": "optional", "input_provenance_expected": "user_fact_plus_formula",
        "intro": "One hypothetical constant-rate semi-steady pressure check; slope is a psi/day coefficient.",
        "inputs": facts({"p0": (4025, "psi"), "slope_psi_per_day": (-8.25, ""), "time": (6, "days")}),
        "goal": "Apply the sourced Pwf=m*t+p0 relation once and report Pwf in psi. Direct arithmetic is enough; Python is optional.",
        "sources": ["W316"], "formulas": [["W316", "Pwf = m* t + pt"]],
    },
    {
        "task_id": "PT4R1-RE-N1", "domain": "reservoir_engineering", "python_expected": "not_needed",
        "evaluation_stratum": "not_needed", "input_provenance_expected": "knowledge_base",
        "intro": "A review of the Havlena-Odeh material-balance shorthand, with no case data or arithmetic request.",
        "inputs": [],
        "goal": "Explain which terms represent oil/free-gas/pore-water expansion and water influx, and why their presence does not by itself determine original oil in place. Cite the source. Do not calculate.",
        "sources": ["R648"], "formulas": [["R648", "F = NEo + NmEg + NEfw +We"]],
    },
    {
        "task_id": "PT4R1-FE-N2", "domain": "formation_evaluation", "python_expected": "not_needed",
        "evaluation_stratum": "not_needed", "input_provenance_expected": "knowledge_base",
        "intro": "A conceptual check about ideal grain-packing reference porosities, with no observed log readings.",
        "inputs": [],
        "goal": "Explain why the ideal column- and close-packing porosities in the formation-evaluation text are illustrative geometry values, not a direct field lithology or saturation diagnosis. Cite the source; no calculation is needed.",
        "sources": ["F24"], "formulas": [],
    },
]


def derived_ground_truth(spec: dict) -> tuple[dict, list[dict]]:
    values = {name: float(value) for name, value, _ in spec["inputs"]}
    evidence = {key: float(item[2]) for key, item in spec.get("evidence", {}).items()}
    raw = reference_outputs(spec["task_id"], values, evidence)
    canonical = []
    for row in raw:
        target = dict(row)
        target["target_id"] = "T_" + re.sub(r"[^A-Z0-9]+", "_", (spec["task_id"] + "_" + row["semantic_name"]).upper())
        target["required"] = True
        target["source"] = "reference_calculator"
        canonical.append(target)
    numeric = [{key: target[key] for key in ("target_id", "semantic_name", "value", "unit", "abs_tolerance", "required")}
               for target in canonical if target["target_type"] == "numeric"]
    typed = [{key: target[key] for key in ("target_id", "semantic_name", "value", "required")}
             | {"type": target["target_type"]}
             for target in canonical if target["target_type"] != "numeric"]
    rankings = [{key: target[key] for key in ("target_id", "semantic_name", "value", "required")}
                for target in canonical if target["target_type"] == "ranking"]
    contracts = [{key: target[key] for key in ("target_id", "semantic_name", "value", "unit", "required")}
                 | {"type": "numeric" if target["target_type"] == "numeric" else target["target_type"]}
                 for target in canonical]
    source_ids = spec["sources"]
    gt = {
        "canonical_targets": canonical,
        "required_claims": [{"claim_id": "CL_SOURCE", "text": "Use only the stated source relation or interpretation.",
                             "source_ids": source_ids, "target_refs": []}],
        "expected_user_facts": spec["inputs"],
        "required_user_facts": spec["inputs"],
        "expected_evidence_facts": list(spec.get("evidence", {}).values()),
        "required_evidence_facts": list(spec.get("evidence", {}).values()),
        "expected_formula_source": spec["formulas"],
        "formula_sources": spec["formulas"],
        "source_ids": source_ids,
        "expected_contract_outputs": contracts,
        "numeric_targets": numeric,
        "typed_targets": typed,
        "ranking_targets": rankings,
        "expected_provenance": {
            "user_fact": bool(spec["inputs"]), "evidence_fact": bool(spec.get("evidence")),
            "formula_source": bool(spec["formulas"]), "source_ids": source_ids,
        },
    }
    return gt, canonical


def make_benchmark() -> tuple[dict, dict]:
    tasks, references = [], {}
    for spec in TASKS:
        gt, canonical = derived_ground_truth(spec)
        lines = [spec["intro"]]
        lines.extend(f"{name}={value:g}{(' ' + unit) if unit else ''}" for name, value, unit in spec["inputs"])
        tasks.append({
            "task_id": spec["task_id"], "benchmark_id": "python_tool_heldout_v4r1",
            "domain": spec["domain"], "python_expected": spec["python_expected"],
            "evaluation_stratum": spec["evaluation_stratum"],
            "input_provenance_expected": spec["input_provenance_expected"],
            "topic": "\n".join(lines), "goal": spec["goal"], "expected_result": None,
            "success_criteria": [
                {"criterion_id": "C1", "description": "Use the specified relationship and distinguish USERF from KB facts.", "required": True},
                {"criterion_id": "C2", "description": "Report every required output with its scenario label and unit.",
                 "target_refs": [target["target_id"] for target in canonical], "required": True}
            ] if canonical else [
                {"criterion_id": "C1", "description": "Give the source-backed conceptual explanation without numerical calculation.", "required": True}
            ],
            "ground_truth": gt,
        })
        references[spec["task_id"]] = {"inputs": spec["inputs"], "evidence_inputs": spec.get("evidence", {}),
                                      "canonical_targets": canonical}
    return {"benchmark_id": "python_tool_heldout_v4r1", "product_code_sha": PRODUCT_SHA, "tasks": tasks}, references


def make_catalog() -> dict:
    if not DB.is_file():
        raise FileNotFoundError(f"Existing KB unavailable; refusing to create a ChromaDB: {DB}")
    import chromadb

    collection = chromadb.PersistentClient(path=str(DB.parent)).get_collection("petroleum_knowledge")
    found = collection.get(ids=[row[0] for row in SOURCES.values()], include=["metadatas", "documents"])
    by_id = {key: (meta, text) for key, meta, text in zip(found["ids"], found["metadatas"], found["documents"])}
    catalog = {}
    for key, (chunk_id, anchor, role) in SOURCES.items():
        meta, text = by_id[chunk_id]
        if anchor not in text:
            raise ValueError(f"Source anchor absent: {key}")
        catalog[key] = {"document": meta["document"], "page": meta["page"], "chunk_id": chunk_id,
                        "anchor": anchor, "source_role": [role],
                        "exact_source_excerpt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    return catalog


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    if MANIFEST.exists():
        raise RuntimeError("v4r1 is frozen; draft builder cannot rewrite assets")
    benchmark, references = make_benchmark()
    write_json(BENCHMARK, benchmark)
    write_json(REFERENCE_OUTPUTS, references)
    write_json(CATALOG, make_catalog())
    print(f"Drafted {len(benchmark['tasks'])} new tasks from one reference target registry per task")


if __name__ == "__main__":
    main()
