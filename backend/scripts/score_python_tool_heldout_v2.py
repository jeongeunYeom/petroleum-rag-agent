"""Independent deterministic scoring and blinded qualitative review for heldout v2."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen

from run_python_tool_heldout_v2 import BENCHMARK, MANIFEST, ROOT, load_and_validate, sha256


NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?\s*(?:million|thousand|mmbbl)?", re.I)
STAGES = ("no_decision", "decision_parsed", "selected", "plan_parsed", "plan_materialized",
          "facts_verified", "formula_verified", "execution_boundary", "code_generated", "sandbox_passed",
          "subprocess", "result_validated", "calc_created")
UNITS = {
    "STB": r"(?:STB|stock[- ]tank barrels?|bbl)",
    "STB/day/psi": r"(?:STB|stb|bbl|barrels?)[/ ](?:day|d)[/ ]psi|(?:STB|stb|bbl|barrels?)[/ ](?:day|d)[/ ](?:psi)",
    "psi/hr": r"psi\s*/\s*(?:hr|hour)", "psi/m": r"psi\s*/\s*m\b",
    "psi/ft": r"psi\s*/\s*ft\b", "mD": r"\bmD\b", "ft": r"\bft\b|feet",
    "m": r"\bm\b|meter", "psi": r"\bpsi\b", "%": r"%|percent", "ratio": r"ratio|fold|times|×",
}


def all_traces(response: dict) -> list[dict]:
    return [i["python_trace"] for i in response.get("iterations", []) if i.get("python_trace")]


def _stage(trace: dict, response: dict) -> int:
    stage = 0
    if trace.get("planner_decision_status") not in (None, "planner_decision_parse_failed"):
        stage = 1
    if trace.get("tool_selected"):
        stage = max(stage, 2)
    if trace.get("planner_plan_status") not in (None, "planner_plan_parse_failed"):
        stage = max(stage, 3)
    if trace.get("planner_plan_status") == "materialized":
        stage = max(stage, 4)
    if trace.get("facts_verified"):
        stage = max(stage, 5)
        stage = max(stage, 6)  # execute() sets facts_verified only after formula/fact verification.
    for index, key in ((7, "call_boundary_reached"), (8, "code_generated"),
                       (9, "sandbox_validation_passed"), (10, "subprocess_reached"),
                       (11, "result_validation_passed")):
        if trace.get(key):
            stage = max(stage, index)
    valid_ids = {c["computation_id"] for c in response.get("computations", []) if c.get("validation_passed")}
    if trace.get("computation_id") in valid_ids:
        stage = 12
    return stage


def aggregate_iterations(response: dict) -> dict:
    traces = all_traces(response)
    if not traces:
        return {"furthest_stage": 0, "furthest_stage_name": STAGES[0], "failure_attribution": [],
                "trace_integrity_error": False, "selected_user_fact_ids": [], "available_user_fact_ids": [],
                **{key: False for key in ("decision_first_try", "decision_retry", "decision_failure", "ever_selected",
                                            "plan_first_try", "plan_retry", "plan_failure", "ever_plan",
                                            "plan_materialized", "facts_verified", "formula_verified", "call_boundary",
                                            "code_generated", "sandbox_passed", "subprocess", "result_validated", "calc_created")}}
    stage = max(_stage(t, response) for t in traces)
    valid = [c for c in response.get("computations", []) if c.get("validation_passed")]
    selected = list(dict.fromkeys(fid for t in traces for fid in t.get("selected_user_fact_ids", [])))
    available = list(dict.fromkeys(fid for t in traces for fid in t.get("available_user_fact_ids", [])))
    statuses = {t.get("blocked_stage") for t in traces}
    failures = []
    mapping = {
        "planner_decision_parse_failed": "planner_decision_parse_failure",
        "planner_not_selected": "planner_not_selected", "planner_plan_parse_failed": "planner_plan_parse_failure",
        "fact_registry_empty": "fact_registry_failure", "materialization_failed": "fact_selection_failure",
        "input_fact_verification_failed": "fact_verification_failure",
        "formula_verification_failed": "formula_provenance_failure", "permission_not_approved": "permission_failure",
        "permission_manager_rejected": "permission_failure", "budget_exhausted": "budget_failure",
        "code_generation_failed": "code_generation_failure", "sandbox_validation_failed": "sandbox_failure",
        "execution_failed": "runtime_failure", "result_validation_failed": "result_validation_failure",
    }
    failures = sorted({mapping[s] for s in statuses if s in mapping})
    if not failures and not valid and response.get("status") != "achieved":
        failures = ["other"]
    integrity = bool(valid) and not any(t.get("subprocess_reached") for t in traces)
    return {
        "decision_first_try": any(t.get("planner_decision_attempts") == 1 and t.get("planner_decision_status") != "planner_decision_parse_failed" for t in traces),
        "decision_retry": any(t.get("planner_decision_attempts") == 2 and t.get("planner_decision_status") != "planner_decision_parse_failed" for t in traces),
        "decision_failure": any(t.get("planner_decision_status") == "planner_decision_parse_failed" for t in traces),
        "ever_selected": any(t.get("tool_selected") for t in traces),
        "plan_first_try": any(t.get("planner_plan_attempts") == 1 and t.get("planner_plan_status") not in (None, "planner_plan_parse_failed") for t in traces),
        "plan_retry": any(t.get("planner_plan_attempts") == 2 and t.get("planner_plan_status") not in (None, "planner_plan_parse_failed") for t in traces),
        "plan_failure": any(t.get("planner_plan_status") == "planner_plan_parse_failed" for t in traces),
        "ever_plan": any(t.get("plan_present") for t in traces),
        "plan_materialized": any(t.get("planner_plan_status") == "materialized" for t in traces),
        "facts_verified": any(t.get("facts_verified") for t in traces),
        "formula_verified": any(t.get("facts_verified") for t in traces),
        "call_boundary": any(t.get("call_boundary_reached") for t in traces),
        "code_generated": any(t.get("code_generated") for t in traces),
        "sandbox_passed": any(t.get("sandbox_validation_passed") for t in traces),
        "subprocess": any(t.get("subprocess_reached") for t in traces),
        "result_validated": any(t.get("result_validation_passed") for t in traces),
        "calc_created": bool(valid),
        "selected_user_fact_ids": selected, "available_user_fact_ids": available,
        "furthest_stage": stage, "furthest_stage_name": STAGES[stage],
        "failure_attribution": failures, "trace_integrity_error": integrity,
    }


def registry_score(task: dict, agg: dict) -> dict:
    from app.services.user_fact_registry import UserFactRegistry

    records = UserFactRegistry.from_topic(task["topic"]).records
    expected = task["ground_truth"]["expected_user_facts"]
    matched_ids = set()
    for fact in expected:
        for record in records:
            if record.name == fact["name"] and record.unit.casefold() == fact["unit"].casefold() and math.isclose(record.value, fact["value"], rel_tol=0, abs_tol=1e-8):
                matched_ids.add(record.fact_id)
                break
    selected = set(agg["selected_user_fact_ids"])
    available = {r.fact_id for r in records}
    return {
        "expected_user_fact_count": len(expected), "registry_user_fact_count": len(matched_ids),
        "selected_user_fact_count": len(selected & matched_ids),
        "unknown_user_fact_count": len(selected - available),
        "extra_user_fact_count": len(selected - matched_ids),
        "registry_recall": len(matched_ids) / len(expected) if expected else None,
        "selection_recall": len(selected & matched_ids) / len(expected) if expected else None,
    }


def _numbers(text: str):
    for match in NUMBER.finditer(text):
        raw = match.group().strip()
        factor = 1_000_000 if raw.lower().endswith(("million", "mmbbl")) else 1_000 if raw.lower().endswith("thousand") else 1
        value = re.sub(r"\s*(?:million|thousand|mmbbl)$", "", raw, flags=re.I).replace(",", "")
        try:
            yield float(value) * factor, match.start(), match.end()
        except ValueError:
            pass


def numeric_match(text: str, target: dict) -> tuple[bool, bool]:
    unit_pattern = UNITS.get(target["unit"], re.escape(target["unit"]))
    for value, start, end in _numbers(text):
        if abs(value - target["value"]) > target["abs_tolerance"]:
            continue
        context = text[max(0, start - 65): min(len(text), end + 65)]
        unit = bool(re.search(unit_pattern, context, flags=re.I))
        return True, unit
    return False, False


def calc_score(task: dict, response: dict, workspace: Path) -> dict:
    targets = task["ground_truth"]["numeric_targets"]
    valid = [c for c in response.get("computations", []) if c.get("validation_passed")]
    flat = ""
    for record in valid:
        for output in record.get("output_files", []):
            candidate = (workspace / output).resolve()
            if not candidate.is_relative_to(workspace.resolve()) or not candidate.is_file() or candidate.suffix != ".json":
                continue
            flat += " " + candidate.read_text(encoding="utf-8")
    results = [numeric_match(flat, t) for t in targets] if flat else []
    return {"calc_numeric_correct": sum(v for v, _ in results), "calc_unit_correct": sum(v and u for v, u in results),
            "calc_target_total": len(targets) if valid else 0,
            "calc_complete": bool(valid) and all(v for v, _ in results) and len(results) == len(targets)}


def numeric_score(task: dict, answer: str) -> dict:
    matches = [numeric_match(answer, target) for target in task["ground_truth"]["numeric_targets"]]
    return {"numeric_correct": sum(v for v, _ in matches), "unit_correct": sum(v and u for v, u in matches),
            "numeric_total": len(matches), "scenario_complete": all(v for v, _ in matches),
            "target_matches": {t["name"]: {"value": v, "unit": u} for t, (v, u) in zip(task["ground_truth"]["numeric_targets"], matches)}}


def selection_metrics(rows: list[dict]) -> dict:
    classified = [r for r in rows if r["python_expected"] != "optional"]
    tp = sum(r["ever_selected"] and r["python_expected"] == "required" for r in classified)
    fp = sum(r["ever_selected"] and r["python_expected"] == "not_needed" for r in classified)
    fn = sum(not r["ever_selected"] and r["python_expected"] == "required" for r in classified)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}


def paired_bootstrap(pairs: list[tuple[float, float]], samples: int = 10000, seed: int = 42) -> dict:
    rng = random.Random(seed)
    diffs = [on - off for off, on in pairs]
    if not diffs:
        return {"delta": None, "ci95": None}
    n = len(diffs)
    estimates = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(samples))
    return {"delta": statistics.mean(diffs), "ci95": [estimates[int(0.025 * samples)], estimates[int(0.975 * samples) - 1]]}


def formula_provenance(task: dict, response: dict) -> bool | None:
    if not task["ground_truth"]["expected_tool_behavior"]["specialist_formula"]:
        return None
    catalog = load_and_validate()[0]["source_catalog"]
    expected = {(catalog[key]["document"], catalog[key]["page"]) for key in task["ground_truth"]["formula_sources"]}
    evidence = {item["evidence_id"]: (item["document"], item["page"]) for item in response.get("internal_sources", [])}
    return any(
        any(evidence.get(source_id) in expected for source_id in record.get("formula_evidence_ids", []))
        for record in response.get("computations", []) if record.get("validation_passed")
    )


def blind_packet(task: dict, response: dict, anonymous_id: str) -> dict:
    answer = response.get("final_answer", "")
    answer = re.sub(r"\[(?:CALC|USERF)\d+\]", "[derived or user input]", answer, flags=re.I)
    answer = re.sub(r"\b(?:Python|tool execution|calculator)\b", "analysis", answer, flags=re.I)
    catalog = load_and_validate()[0]["source_catalog"]
    allowed = {(catalog[key]["document"], catalog[key]["page"]) for key in task["ground_truth"]["acceptable_evidence"]}
    sources = [s for s in response.get("internal_sources", []) if (s["document"], s["page"]) in allowed]
    return {"blind_id": anonymous_id, "task": {"topic": task["topic"], "goal": task["goal"],
                                                 "criteria": task["success_criteria"]},
            "numeric_criterion_ids_do_not_review": sorted({t["criterion_id"] for t in task["ground_truth"]["numeric_targets"]}),
            "qualitative_gt_notes": [c["text"] for c in task["ground_truth"]["required_claims"]],
            "allowed_sources": [{"document": s["document"], "page": s["page"], "excerpt": s["excerpt"][:1200]}
                                for s in sources[:8]],
            "candidate_answer": answer}


def _review(packet: dict, model: str, base_url: str) -> dict:
    prompt = ("Review qualitative engineering meaning and source support ONLY. Do not score numbers, units, "
              "calculations, tool use, or infer hidden A/B condition. Return JSON with criterion_pass object mapping "
              "criterion IDs to true/false for qualitative criteria; engineering_contradiction_count integer; "
              "hallucination_count integer; user_fact_leakage_count integer; rationale short. Numeric criteria should "
              "be omitted from criterion_pass, as listed in numeric_criterion_ids_do_not_review. "
              "Candidate answer may be empty.\n" + json.dumps(packet, ensure_ascii=False))
    body = {"model": model, "stream": False, "format": "json", "options": {"temperature": 0, "seed": 42},
            "messages": [{"role": "user", "content": prompt}]}
    request = Request(base_url.rstrip("/") + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=600) as handle:
        raw = json.load(handle)
    content = raw["message"]["content"]
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError) as exc:
        parsed = {"criterion_pass": {}, "review_parse_error": type(exc).__name__}
    return {"raw": raw, "parsed": parsed}


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def _mean(rows: list[dict], key: str) -> float:
    return statistics.mean(float(r[key]) for r in rows) if rows else 0.0


def _summary(rows: list[dict]) -> dict:
    targets = sum(r["numeric_total"] for r in rows)
    return {"n": len(rows), "goal_success": _mean(rows, "goal_success"),
            "external_coverage": _mean(rows, "external_coverage"),
            "numeric_accuracy": sum(r["numeric_correct"] for r in rows) / targets if targets else None,
            "unit_accuracy": sum(r["unit_correct"] for r in rows) / targets if targets else None,
            "hallucination": _mean(rows, "hallucination_count"),
            "engineering_error": _mean(rows, "engineering_contradiction_count"),
            "calibration_error": _mean(rows, "calibration_error"),
            "latency_mean": _mean(rows, "elapsed_seconds"),
            "latency_median": statistics.median(r["elapsed_seconds"] for r in rows) if rows else 0,
            "latency_p95": sorted(r["elapsed_seconds"] for r in rows)[math.ceil(0.95 * len(rows)) - 1] if rows else 0}


def score(run_dir: Path, *, review: bool = False, base_url: str = "http://127.0.0.1:11434") -> dict:
    benchmark, manifest = load_and_validate()
    root = run_dir.parent.parent.parent
    prefix = root / "python_tool_heldout_v2"
    det_path = prefix.with_name(prefix.name + "_deterministic.json")
    comparison_path = prefix.with_name(prefix.name + "_comparison.json")
    if det_path.exists() or comparison_path.exists():
        raise FileExistsError("Scores already exist; never silently overwrite")
    raw = {condition: json.loads((run_dir / f"{condition}.json").read_text(encoding="utf-8")) for condition in ("python_off", "python_on")}
    for condition, payload in raw.items():
        if not payload["complete"] or payload["benchmark_sha256"] != manifest["benchmark_sha256"] or payload["manifest_sha256"] != sha256(MANIFEST):
            raise ValueError(f"Incomplete or non-frozen raw run: {condition}")
        if [r["task_id"] for r in payload["results"]] != [t["task_id"] for t in benchmark["tasks"]]:
            raise ValueError(f"Missing or reordered rows: {condition}")
    workspace = run_dir.parent.parent / "workspace"
    rows = []
    iterations = []
    reviewer_raw = []
    deterministic = []
    review_path = ROOT / "evaluation/review/python_tool_heldout_v2_reviewer_raw.json"
    review_partial = review_path.with_suffix(".incomplete.json")
    if review and (review_path.exists() or review_partial.exists()):
        raise FileExistsError("Reviewer results already exist; never overwrite")
    blind_id = 0
    for condition in ("python_off", "python_on"):
        for task, raw_row in zip(benchmark["tasks"], raw[condition]["results"]):
            response = raw_row["response"]
            agg = aggregate_iterations(response)
            facts = registry_score(task, agg)
            numeric = numeric_score(task, response.get("final_answer", ""))
            calc = calc_score(task, response, workspace)
            deterministic.append({"task_id": task["task_id"], "condition": condition, "numeric": numeric,
                                  "calc": calc, "aggregate": agg, "registry": facts})
            blind_id += 1
            packet = blind_packet(task, response, f"BR-{blind_id:03d}")
            reviewer = _review(packet, manifest["model_settings"]["semantic_reviewer_model"], base_url) if review else None
            if reviewer:
                reviewer_raw.append({"blind_id": packet["blind_id"], "packet": packet, **reviewer})
                review_partial.parent.mkdir(parents=True, exist_ok=True)
                review_partial.write_text(json.dumps(reviewer_raw, ensure_ascii=False, indent=2), encoding="utf-8")
            parsed = reviewer["parsed"] if reviewer else {}
            qualitative = parsed.get("criterion_pass", {})
            numeric_by_criterion = {}
            for target in task["ground_truth"]["numeric_targets"]:
                numeric_by_criterion.setdefault(target["criterion_id"], []).append(numeric["target_matches"][target["name"]]["value"])
            criterion_pass = {}
            for criterion in task["success_criteria"]:
                cid = criterion["criterion_id"]
                # Numeric correctness is authoritative; qualitative reviewer may additionally reject a criterion.
                criterion_pass[cid] = all(numeric_by_criterion[cid]) if cid in numeric_by_criterion else bool(qualitative.get(cid, False))
                if cid in numeric_by_criterion and cid in qualitative:
                    criterion_pass[cid] &= bool(qualitative[cid])
            coverage = sum(criterion_pass.values()) / len(criterion_pass)
            hallucinations = int(parsed.get("hallucination_count", 0)) if review else 0
            errors = int(parsed.get("engineering_contradiction_count", 0)) if review else 0
            row = {"task_id": task["task_id"], "condition": condition, "domain": task["domain"],
                   "python_expected": task["python_expected"], "input_provenance_expected": task["input_provenance_expected"],
                   "elapsed_seconds": raw_row["elapsed_seconds"], "internal_coverage": response.get("goal_coverage", 0),
                   "external_coverage": coverage, "calibration_error": abs(response.get("goal_coverage", 0) - coverage),
                   "goal_success": coverage == 1 and hallucinations == 0 and errors == 0,
                   "criterion_pass": criterion_pass, "hallucination_count": hallucinations,
                   "engineering_contradiction_count": errors, "user_fact_leakage_count": int(parsed.get("user_fact_leakage_count", 0)) if review else 0,
                   "final_answer": response.get("final_answer", ""),
                   "final_answer_calc_citation": bool(re.search(r"\[CALC\d+\]", response.get("final_answer", ""))),
                   "final_answer_user_citation": bool(re.search(r"\[USERF\d+\]", response.get("final_answer", ""))),
                   "reviewer_blind_id": packet["blind_id"], **numeric, **calc, **facts, **agg,
                   "formula_provenance_success": formula_provenance(task, response),
                   "tool_timing_seconds": raw_row.get("tool_timing_seconds", {}),
                   "python_stage_seconds": sum(i.get("timing", {}).get("python_seconds", 0) for i in response.get("iterations", []))}
            if agg["calc_created"] and calc["calc_complete"] and not numeric["scenario_complete"]:
                row["failure_attribution"] = sorted(set(row["failure_attribution"] + ["calc_correct_final_answer_failed"]))
            rows.append(row)
            for item in response.get("iterations", []):
                trace = item.get("python_trace") or {}
                iterations.append({"task_id": task["task_id"], "condition": condition, "iteration": item["iteration"],
                                   "python_seconds": item.get("timing", {}).get("python_seconds", 0),
                                   "furthest_stage": _stage(trace, response) if trace else 0, **trace})
    off = [r for r in rows if r["condition"] == "python_off"]
    on = [r for r in rows if r["condition"] == "python_on"]
    off_req = [r for r in off if r["python_expected"] == "required"]
    on_req = [r for r in on if r["python_expected"] == "required"]
    paired = list(zip(off, on))
    required_paired = [(a, b) for a, b in paired if a["python_expected"] == "required"]
    def target_fraction(r, key):
        return r[key] / r["numeric_total"] if r["numeric_total"] else 0.0
    bootstrap = {
        "overall_goal": paired_bootstrap([(float(a["goal_success"]), float(b["goal_success"])) for a, b in paired]),
        "overall_coverage": paired_bootstrap([(a["external_coverage"], b["external_coverage"]) for a, b in paired]),
        "required_goal": paired_bootstrap([(float(a["goal_success"]), float(b["goal_success"])) for a, b in required_paired]),
        "required_coverage": paired_bootstrap([(a["external_coverage"], b["external_coverage"]) for a, b in required_paired]),
        "required_numeric": paired_bootstrap([(target_fraction(a, "numeric_correct"), target_fraction(b, "numeric_correct")) for a, b in required_paired]),
        "required_unit": paired_bootstrap([(target_fraction(a, "unit_correct"), target_fraction(b, "unit_correct")) for a, b in required_paired]),
    }
    benefits = Counter("benefit" if b["external_coverage"] > a["external_coverage"] or b["numeric_correct"] > a["numeric_correct"]
                       else "harm" if b["external_coverage"] < a["external_coverage"] or b["numeric_correct"] < a["numeric_correct"]
                       else "neutral" for a, b in required_paired)
    comparison = {"benchmark_id": benchmark["benchmark_id"], "product_code_sha": manifest["product_code_sha"],
                  "manifest_sha256": sha256(MANIFEST), "run_id": raw["python_off"]["run_id"],
                  "review_complete": review, "method": "single AI-assisted semantic reviewer" if review else "deterministic only",
                  "overall": {"python_off": _summary(off), "python_on": _summary(on)},
                  "required": {"python_off": _summary(off_req), "python_on": _summary(on_req)},
                  "selection": selection_metrics(on), "bootstrap": bootstrap, "required_benefit": dict(benefits),
                  "funnel": {key: sum(bool(r[key]) for r in on_req) for key in ("decision_first_try", "decision_retry", "decision_failure", "ever_selected", "plan_first_try", "plan_retry", "plan_failure", "ever_plan", "plan_materialized", "facts_verified", "formula_verified", "call_boundary", "code_generated", "sandbox_passed", "subprocess", "result_validated", "calc_created")},
                  "rows": rows}
    (prefix.parent).mkdir(parents=True, exist_ok=True)
    det_path.write_text(json.dumps(deterministic, ensure_ascii=False, indent=2), encoding="utf-8")
    comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(prefix.with_name(prefix.name + "_comparison.csv"), rows)
    _write_csv(prefix.with_name(prefix.name + "_funnel.csv"), [r for r in on])
    _write_csv(prefix.with_name(prefix.name + "_iterations.csv"), iterations)
    poster = [{"population": p, "condition": c, **values} for p, by_condition in (("overall", comparison["overall"]), ("required", comparison["required"])) for c, values in by_condition.items()]
    _write_csv(prefix.with_name(prefix.name + "_poster.csv"), poster)
    if review:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_partial.replace(review_path)
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--ollama-base-url", default="http://127.0.0.1:11434")
    args = parser.parse_args()
    result = score(args.run_dir, review=args.review, base_url=args.ollama_base_url)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
