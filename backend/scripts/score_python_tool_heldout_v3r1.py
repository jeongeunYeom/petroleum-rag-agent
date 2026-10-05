"""Independent, source-aware scoring of the one frozen v3r1 A/B run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_python_tool_heldout_v3r1 import CATALOG, ROOT, load_frozen

sys.path.insert(0, str(ROOT / "backend"))
from app.services.evidence_fact_registry import EvidenceFactRegistry  # noqa: E402
from app.services.formula_source_registry import FormulaSourceRegistry, normalize_formula  # noqa: E402
from app.services.user_fact_registry import UserFactRegistry  # noqa: E402

NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
FUNNEL = ("decision_parsed", "tool_selected", "plan_parsed", "plan_materialized",
          "expected_user_available", "expected_evidence_available", "expected_formula_available",
          "required_user_selected", "required_evidence_selected", "formula_selected",
          "facts_verified", "formula_verified", "execution_boundary", "code_generated",
          "sandbox_passed", "subprocess", "result_validated", "calc_created", "calc_adopted")
UNITS = {
    "ratio": r"\b(?:ratio|dimensionless|fold|times|RB/STB|bbl/bbl)\b|×",
    "fraction": r"\b(?:fraction|dimensionless)\b|%|percent",
    "dimensionless": r"\b(?:dimensionless|skin|ratio|unitless)\b",
    "bbl": r"\bbbl\b|barrels?",
    "psi": r"\bpsi\b|\bpsia\b",
    "%": r"%|percent",
    "percentage points": r"percentage points?|\bpp\b",
}


def sha(value: object) -> str:
    payload = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def answer_citation_mapping(response: dict) -> dict[str, object]:
    mapped = {f"[{s['evidence_id']}]":[s.get("document"),s.get("page"),s.get("chunk_id")]
              for s in response.get("internal_sources", [])}
    mapped.update({f"[{c['computation_id']}]":[c.get("source_evidence_ids"),c.get("source_input_ids"),c.get("formula_evidence_ids")]
                   for c in response.get("computations", [])})
    return {citation: mapped.get(citation) for citation in sorted(set(re.findall(r"\[(?:KB|FIG|WEB|CALC|USERF)\d+\]", response.get("final_answer", ""))))}


def _candidate_lines(text: str, target_name: str) -> list[str]:
    lines = [line for line in text.replace("|", " ").splitlines() if line.strip()]
    label = target_name.split("_", 1)[0]
    if re.fullmatch(r"[A-E]|V[1-4]|R(?:10|[1-9])", label):
        pattern = re.compile(rf"(?<![A-Za-z0-9])(?:case\s+)?{re.escape(label)}(?![A-Za-z0-9])", re.I)
        selected = [line for line in lines if pattern.search(line)]
        return selected
    if target_name.startswith("mean_"):
        selected = [line for line in lines if re.search(r"\b(?:mean|average)\b", line, re.I)]
        return selected
    if target_name == "rms":
        selected = [line for line in lines if re.search(r"\b(?:RMS|root.mean.square)\b", line, re.I)]
        return selected
    return lines


def numeric_match(text: str, target: list) -> tuple[bool, bool]:
    name, wanted, unit, tolerance = target
    for line in _candidate_lines(text, name):
        for found in NUMBER.finditer(line):
            value = float(found.group().replace(",", ""))
            after = line[found.end():found.end()+12]
            is_percent = bool(re.match(r"\s*(?:%|percent\b)", after, re.I)) if after else False
            comparable = value / 100 if unit == "fraction" and is_percent else value
            if abs(comparable - wanted) > tolerance:
                continue
            vicinity = line[max(0, found.start()-35):min(len(line), found.end()+35)]
            pattern = UNITS.get(unit, re.escape(unit))
            unit_ok = bool(re.search(pattern, vicinity, re.I))
            if unit in {"ratio", "fraction", "dimensionless"} and is_percent and unit == "fraction":
                unit_ok = True
            return True, unit_ok
    return False, False


def numeric_score(text: str, targets: list[list]) -> dict:
    matches = {target[0]: numeric_match(text, target) for target in targets}
    return {"numeric_total": len(targets), "numeric_correct": sum(v for v, _ in matches.values()),
            "unit_correct": sum(v and u for v, u in matches.values()),
            "numeric_complete": all(v for v, _ in matches.values()),
            "target_matches": {name: {"value": value, "unit": unit} for name, (value, unit) in matches.items()}}


def _source_records(response: dict) -> tuple[list[dict], dict[str, dict]]:
    records = [{"evidence_id": s["evidence_id"], "source_type": "knowledge_base",
                "locator": f"{s.get('document')} p.{s.get('page')}", "text": s.get("excerpt", "")}
               for s in response.get("internal_sources", [])]
    return records, {s["evidence_id"]: s for s in response.get("internal_sources", [])}


def runtime_registry(task: dict, response: dict, catalog: dict, traces: list[dict]) -> dict:
    gt = task["ground_truth"]
    evidence, _ = _source_records(response)
    retrieved = {key: [s["evidence_id"] for s in response.get("internal_sources", [])
                       if s.get("chunk_id") == catalog[key]["chunk_id"]]
                 for key in gt["source_ids"]}
    user = UserFactRegistry.from_topic(task["topic"]).records
    efacts = EvidenceFactRegistry.from_evidence(evidence).records
    formulas = FormulaSourceRegistry.from_evidence(evidence).records
    def same(row, expected):
        return row.name.casefold() == str(expected[0]).casefold() and math.isclose(row.value, float(expected[1]), abs_tol=1e-9) and row.unit.casefold() == str(expected[2]).casefold()
    expected_user_ids = {next((r.fact_id for r in user if same(r, item)), None) for item in gt["required_user_facts"]}
    expected_user_ids.discard(None)
    expected_evidence_ids = set()
    for key, name, value, unit in gt["required_evidence_facts"]:
        for row in efacts:
            if row.source_id in retrieved.get(key, []) and same(row, [name, value, unit]):
                expected_evidence_ids.add(row.fact_id)
                break
    expected_formula_ids = set()
    for key, equation in gt["formula_sources"]:
        for row in formulas:
            if row.source_id in retrieved.get(key, []) and row.expression_candidate and normalize_formula(row.raw_span) == normalize_formula(equation):
                expected_formula_ids.add(row.formula_id)
                break
    selected = {item for trace in traces for item in trace.get("selected_fact_ids", [])}
    selected_formulas = {trace.get("selected_formula_id") for trace in traces if trace.get("selected_formula_id")}
    def recall(actual: int, expected: int) -> float | None:
        return actual / expected if expected else None
    return {"retrieved_source_ids": {key: bool(value) for key, value in retrieved.items()},
            "source_recall": recall(sum(bool(v) for v in retrieved.values()), len(retrieved)),
            "user_registry_recall": recall(len(expected_user_ids), len(gt["required_user_facts"])),
            "evidence_registry_recall": recall(len(expected_evidence_ids), len(gt["required_evidence_facts"])),
            "formula_registry_recall": recall(len(expected_formula_ids), len(gt["formula_sources"])),
            "user_selection_recall": recall(len(expected_user_ids & selected), len(gt["required_user_facts"])),
            "evidence_selection_recall": recall(len(expected_evidence_ids & selected), len(gt["required_evidence_facts"])),
            "formula_selection_accuracy": bool(expected_formula_ids & selected_formulas) if gt["formula_sources"] else None,
            "expected_user_ids": sorted(expected_user_ids), "expected_evidence_ids": sorted(expected_evidence_ids),
            "expected_formula_ids": sorted(expected_formula_ids),
            "selected_fact_ids": sorted(selected), "selected_formula_ids": sorted(selected_formulas),
            "evidence_source_map": {key: value[0] for key, value in retrieved.items() if value}}


def funnel(task: dict, response: dict, registry: dict) -> dict:
    traces = [row["python_trace"] for row in response.get("iterations", []) if row.get("python_trace")]
    valid = [c for c in response.get("computations", []) if c.get("validation_passed")]
    all_selected = set(registry["selected_fact_ids"])
    stages = {
        "decision_parsed": any(t.get("planner_decision_status") not in (None,"planner_decision_parse_failed") for t in traces),
        "tool_selected": any(t.get("tool_selected") for t in traces),
        "plan_parsed": any(t.get("plan_present") for t in traces),
        "plan_materialized": any(t.get("planner_plan_status") == "materialized" for t in traces),
        "expected_user_available": registry["user_registry_recall"] in (None, 1),
        "expected_evidence_available": registry["evidence_registry_recall"] in (None, 1),
        "expected_formula_available": registry["formula_registry_recall"] in (None, 1),
        "required_user_selected": set(registry["expected_user_ids"]) <= all_selected and registry["user_registry_recall"] in (None,1),
        "required_evidence_selected": set(registry["expected_evidence_ids"]) <= all_selected and registry["evidence_registry_recall"] in (None,1),
        "formula_selected": registry["formula_selection_accuracy"] in (None, True),
        "facts_verified": any(t.get("facts_verified") for t in traces),
        "formula_verified": any(t.get("formula_verified") for t in traces),
        "execution_boundary": any(t.get("call_boundary_reached") for t in traces),
        "code_generated": any(t.get("code_generated") for t in traces),
        "sandbox_passed": any(t.get("sandbox_validation_passed") for t in traces),
        "subprocess": any(t.get("subprocess_reached") for t in traces),
        "result_validated": any(t.get("result_validation_passed") for t in traces),
        "calc_created": bool(valid),
        "calc_adopted": False,
    }
    return stages


def calc_score(task: dict, response: dict, workspace: Path) -> dict:
    valid = [c for c in response.get("computations", []) if c.get("validation_passed")]
    corpus = "\n".join(c.get("summary", "") for c in valid)
    for record in valid:
        for raw_path in record.get("output_files", []):
            path = (workspace / raw_path).resolve()
            if path.is_relative_to(workspace.resolve()) and path.is_file() and path.suffix.lower() == ".json":
                corpus += "\n" + path.read_text(encoding="utf-8")
    scored = numeric_score(corpus, task["ground_truth"]["numeric_targets"]) if valid else None
    return {"validated_calc_count": len(valid),
            "calc_numeric_total": scored["numeric_total"] if scored else None,
            "calc_numeric_correct": scored["numeric_correct"] if scored else None,
            "calc_unit_correct": scored["unit_correct"] if scored else None,
            "calc_complete": scored["numeric_complete"] if scored else None,
            "calc_target_matches": scored["target_matches"] if scored else None}


def formula_provenance(task: dict, response: dict, registry: dict) -> bool | None:
    if not task["ground_truth"]["formula_sources"]:
        return None
    return any(c.get("validation_passed") and c.get("formula_source_id") in registry["expected_formula_ids"]
               for c in response.get("computations", []))


def adoption(task: dict, response: dict, numeric: dict, calc: dict, registry: dict) -> dict:
    answer = response.get("final_answer", "")
    computations = {c["computation_id"]: c for c in response.get("computations", []) if c.get("validation_passed")}
    cited_calcs = {id for id in computations if f"[{id}]" in answer}
    user_provenance = (not task["ground_truth"]["required_user_facts"] or
                       bool(re.search(r"\[USERF\d+\]", answer)) or
                       bool(re.search(r"user[- ]supplied|hypothetical|provided by (?:the )?user", answer, re.I)))
    source_ids = set(registry["evidence_source_map"].values())
    formula_cited = not task["ground_truth"]["formula_sources"] or any(f"[{evidence_id}]" in answer for evidence_id in source_ids)
    adopted = bool(cited_calcs) and numeric["numeric_complete"] and user_provenance and formula_cited
    return {"calc_citation_present": bool(cited_calcs), "user_provenance_present": user_provenance,
            "formula_kb_citation_present": formula_cited, "calc_adopted": adopted}


def attribution(task: dict, response: dict, registry: dict, stages: dict, calc: dict, numeric: dict) -> list[str]:
    if response.get("error"):
        return ["product_error"]
    if any(not present for present in registry["retrieved_source_ids"].values()):
        return ["retrieval_source_missing"]
    if registry["evidence_registry_recall"] not in (None,1):
        return ["evidence_registry_missing"]
    if registry["formula_registry_recall"] not in (None,1):
        return ["formula_registry_missing"]
    blocked = {t.get("blocked_stage") for i in response.get("iterations", []) for t in [i.get("python_trace") or {}] if t.get("blocked_stage")}
    if blocked:
        return sorted(blocked)
    if task["python_expected"] == "required" and not stages["tool_selected"]:
        return ["planner_not_selected"]
    if stages["tool_selected"] and not stages["plan_materialized"]:
        return ["plan_materialization_failure"]
    if stages["calc_created"] and calc["calc_complete"] is False:
        return ["calc_incorrect_or_incomplete"]
    if stages["calc_created"] and not numeric["numeric_complete"]:
        return ["calc_correct_final_answer_failed"] if calc["calc_complete"] else ["final_answer_numeric_failure"]
    return []


def paired_bootstrap(pairs: list[tuple[float, float]], samples: int = 10000, seed: int = 42) -> dict:
    if not pairs:
        return {"delta": None, "ci95": None}
    differences = [on - off for off, on in pairs]
    rng = random.Random(seed)
    n = len(differences)
    estimates = sorted(sum(differences[rng.randrange(n)] for _ in range(n)) / n for _ in range(samples))
    return {"delta": statistics.mean(differences),
            "ci95": [estimates[int(0.025 * samples)], estimates[int(0.975 * samples)-1]],
            "samples": samples, "seed": seed}


def summary(rows: list[dict]) -> dict:
    total = sum(r["numeric_total"] for r in rows)
    latencies = sorted(r["elapsed_seconds"] for r in rows)
    return {"n": len(rows),
            "goal_success": statistics.mean(r["goal_success"] for r in rows) if rows else None,
            "external_coverage": statistics.mean(r["external_coverage"] for r in rows) if rows else None,
            "numeric_accuracy": sum(r["numeric_correct"] for r in rows) / total if total else None,
            "unit_accuracy": sum(r["unit_correct"] for r in rows) / total if total else None,
            "latency_mean": statistics.mean(latencies) if latencies else None,
            "latency_median": statistics.median(latencies) if latencies else None,
            "latency_p95": latencies[math.ceil(0.95*len(latencies))-1] if latencies else None}


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        names = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict,list)) else value
                          for key, value in row.items()} for row in rows)


def score(run_dir: Path, output_dir: Path) -> dict:
    benchmark, manifest = load_frozen()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    raw = {name: json.loads((run_dir / f"{name}.json").read_text(encoding="utf-8"))
           for name in ("python_off","python_on")}
    expected_ids = [task["task_id"] for task in benchmark["tasks"]]
    for name, payload in raw.items():
        if not payload["complete"] or payload["benchmark_sha256"] != manifest["benchmark_sha256"] or [r["task_id"] for r in payload["results"]] != expected_ids:
            raise ValueError(f"Incomplete or changed run: {name}")
    if raw["python_off"]["run_id"] != raw["python_on"]["run_id"]:
        raise ValueError("Unpaired run identities")
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace = ROOT / "workspace"
    rows: list[dict] = []
    iterations: list[dict] = []
    for name in ("python_off","python_on"):
        for task, raw_row in zip(benchmark["tasks"], raw[name]["results"]):
            response = raw_row.get("response") or {}
            traces = [i["python_trace"] for i in response.get("iterations", []) if i.get("python_trace")]
            registry = runtime_registry(task, response, catalog, traces)
            numeric = numeric_score(response.get("final_answer", ""), task["ground_truth"]["numeric_targets"])
            calc = calc_score(task, response, workspace)
            stages = funnel(task, response, registry)
            adopted = adoption(task, response, numeric, calc, registry)
            stages["calc_adopted"] = adopted["calc_adopted"]
            labels = attribution(task, response, registry, stages, calc, numeric)
            criterion_pass = {"C1": bool(task["ground_truth"]["source_ids"] and registry["source_recall"] == 1),
                              "C2": numeric["numeric_complete"], "C3": False}
            if task["python_expected"] == "not_needed":
                criterion_pass = {"C1": False, "C2": False, "C3": not stages["subprocess"]}
            coverage = sum(criterion_pass.values()) / len(criterion_pass)
            row = {"task_id": task["task_id"], "condition": name, "domain": task["domain"],
                   "python_expected": task["python_expected"], "evaluation_stratum": task["evaluation_stratum"],
                   "elapsed_seconds": raw_row["elapsed_seconds"], "product_exception": raw_row.get("product_exception"),
                   "product_status": response.get("status"), "internal_coverage": response.get("goal_coverage"),
                   "external_coverage": coverage, "goal_success": False,
                   "criterion_pass_preliminary": criterion_pass,
                   "final_answer": response.get("final_answer", ""),
                   "answer_sha256": sha(response.get("final_answer", "").encode()),
                   "citation_mapping_sha256": sha(answer_citation_mapping(response)),
                   "failure_attribution": labels, "formula_provenance_success": formula_provenance(task,response,registry),
                   "python_calls_total": response.get("python_calls_total",0),
                   "python_attempts_total": response.get("python_attempts_total",0),
                   "python_seconds": sum(i.get("timing",{}).get("python_seconds",0) for i in response.get("iterations", [])),
                   "engineering_contradiction_count": sum(i.get("engineering_contradiction_count",0) for i in response.get("iterations", [])),
                   "unsupported_engineering_claim_count": sum(i.get("unsupported_engineering_claim_count",0) for i in response.get("iterations", [])),
                   **numeric, **calc, **registry, **stages, **adopted}
            rows.append(row)
            for item in response.get("iterations", []):
                iterations.append({"task_id":task["task_id"],"condition":name,"iteration":item.get("iteration"),
                                   "python_seconds":item.get("timing",{}).get("python_seconds",0),
                                   **(item.get("python_trace") or {})})
    off = rows[:12]
    on = rows[12:]
    pairs = list(zip(off,on))
    if any(a["task_id"] != b["task_id"] for a,b in pairs):
        raise ValueError("Task pair mismatch")
    populations = {"all_12": lambda r: True, "required_8": lambda r: r["python_expected"] == "required",
                   "pipeline_6": lambda r: r["evaluation_stratum"] == "pipeline",
                   "end_to_end_2": lambda r: r["evaluation_stratum"] == "end_to_end"}
    comparison = {"benchmark_id":benchmark["benchmark_id"], "run_id":raw["python_off"]["run_id"],
                  "freeze_commit_sha":manifest["freeze_commit_sha"], "product_code_sha":manifest["product_code_sha"],
                  "scoring_status":"PRELIMINARY_DETERMINISTIC_PENDING_BLIND_AND_MANUAL_QA",
                  "populations":{}, "funnel":{}, "bootstrap":{}, "rows":rows}
    for population, keep in populations.items():
        selected = [(a,b) for a,b in pairs if keep(a)]
        comparison["populations"][population] = {"python_off": summary([a for a,_ in selected]),
                                                  "python_on": summary([b for _,b in selected])}
        comparison["bootstrap"][population] = {
            "numeric_accuracy":paired_bootstrap([(a["numeric_correct"]/a["numeric_total"] if a["numeric_total"] else 0,
                                                  b["numeric_correct"]/b["numeric_total"] if b["numeric_total"] else 0)
                                                 for a,b in selected]),
            "external_coverage_preliminary":paired_bootstrap([(a["external_coverage"],b["external_coverage"])
                                                                 for a,b in selected])}
        comparison["funnel"][population] = {stage:sum(bool(b[stage]) for _,b in selected) for stage in FUNNEL}
    required_pairs = [(a,b) for a,b in pairs if a["python_expected"] == "required"]
    comparison["required_benefit_preliminary"] = dict(Counter(
        "benefit" if b["numeric_correct"] > a["numeric_correct"] else
        "harm" if b["numeric_correct"] < a["numeric_correct"] else "neutral" for a,b in required_pairs))
    comparison["strong_python_benefit"] = sum(not a["numeric_complete"] and b["calc_created"] and
                                            b["numeric_complete"] for a,b in required_pairs)
    comparison["calc_correctness"] = {
        "validated_calc_rows":sum(bool(r["validated_calc_count"]) for r in on),
        "target_denominator":sum(r["calc_numeric_total"] or 0 for r in on),
        "numeric_accuracy":(sum(r["calc_numeric_correct"] or 0 for r in on)/sum(r["calc_numeric_total"] or 0 for r in on))
                            if any(r["calc_numeric_total"] for r in on) else None,
        "unit_accuracy":(sum(r["calc_unit_correct"] or 0 for r in on)/sum(r["calc_numeric_total"] or 0 for r in on))
                        if any(r["calc_numeric_total"] for r in on) else None,
        "adoption_rate":sum(r["calc_adopted"] for r in on)/sum(bool(r["validated_calc_count"]) for r in on)
                        if any(r["validated_calc_count"] for r in on) else None}
    json_path = output_dir / "python_tool_heldout_v3r1_deterministic.json"
    if json_path.exists():
        raise FileExistsError(json_path)
    json_path.write_text(json.dumps(comparison,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    write_csv(output_dir / "python_tool_heldout_v3r1_rows.csv",rows)
    write_csv(output_dir / "python_tool_heldout_v3r1_iterations.csv",iterations)
    write_csv(output_dir / "python_tool_heldout_v3r1_funnel.csv",[
        {"population":p,"stage":stage,"python_on_count":count,"n":comparison["populations"][p]["python_on"]["n"]}
        for p,stages in comparison["funnel"].items() for stage,count in stages.items()])
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir",type=Path)
    parser.add_argument("--output-dir",type=Path,default=ROOT / "evaluation/review")
    args = parser.parse_args()
    result = score(args.run_dir,args.output_dir)
    print(json.dumps({"run_id":result["run_id"],"populations":result["populations"],
                      "calc_correctness":result["calc_correctness"]},ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
