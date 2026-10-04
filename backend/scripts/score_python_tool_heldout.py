"""Deterministic Python-tool scoring plus one blinded local qualitative review."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import statistics
import sys
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_python_tool_heldout import BENCHMARK, MANIFEST, POLICY, ROOT, _save, sha256  # noqa: E402


NUMBERS = re.compile(r"(?<![\w])[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?")
NUMERIC_ONLY = {"C2"}


def numeric_hits(answer: str, target: dict) -> dict:
    """Find stated output values; never use reviewer arithmetic as ground truth."""
    unit = target["unit"]
    found_value = False
    for match in NUMBERS.finditer(answer.split("\n\nLimitations:")[0]):
        before = answer[max(0, match.start() - 90):match.start()]
        after = answer[match.end():match.end() + 65]
        context = before + after
        value = float(match.group().replace(",", ""))
        if re.match(r"\s*(?:million|MM)\b", after, re.I):
            value *= 1_000_000
        if target["value"] < 0 and value > 0 and re.search(r"reduc|decreas|drop|하락|감소", context, re.I):
            value = -value
        if abs(value - target["value"]) > target["abs_tolerance"]:
            continue
        found_value = True
        if target["name"] == "largest_residual_depth" and not re.search(r"largest|greatest|max(?:imum)?|residual|잔차", context, re.I):
            continue
        if unit == "%":
            valid_unit = bool(re.match(r"\s*(?:%|percent\b)", after, re.I))
        elif unit == "stock-tank m3":
            valid_unit = bool(re.search(r"\b(?:m\^?3|m³|cubic metres?|cubic meters?)\b", after, re.I) and
                              re.search(r"stock[- ]tank|STOIIP|OOIP|oil in place|recoverable|reserves", context, re.I))
        elif unit == "STB/day/psi":
            valid_unit = bool(re.search(r"STB\s*/\s*(?:day|d)\s*/\s*psi", after, re.I))
        else:
            valid_unit = bool(re.search(r"^\s*" + re.escape(unit) + r"\b", after, re.I))
        if valid_unit:
            return {"passed": True, "value": value, "unit_passed": True, "quote": answer[max(0, match.start()-35):match.end()+45]}
    return {"passed": False, "value_present": found_value, "unit_passed": False, "quote": ""}


def bootstrap(left: list[float], right: list[float], *, seed: int = 42, n: int = 10000) -> dict:
    if len(left) != len(right) or not left:
        raise ValueError("Aligned, nonempty pairs required")
    differences = [b - a for a, b in zip(left, right)]
    rng = random.Random(seed)
    draws = sorted(sum(differences[rng.randrange(len(differences))] for _ in differences) / len(differences) for _ in range(n))
    return {"delta": statistics.mean(differences), "ci95_low": draws[int(n * .025)],
            "ci95_high": draws[int(n * .975) - 1], "samples": n, "seed": seed}


def traces(response: dict) -> dict:
    items = [it.get("python_trace") or {} for it in response.get("iterations", [])]
    keys = ("tool_selected", "plan_present", "permission_passed", "facts_verified", "call_boundary_reached",
            "code_generated", "sandbox_validation_passed", "subprocess_reached", "result_validation_passed")
    row = {key: any(bool(trace.get(key)) for trace in items) for key in keys}
    row["blocked_stage"] = next((x["blocked_stage"] for x in reversed(items) if x.get("blocked_stage") and x["blocked_stage"] != "validated"), None)
    row["calc_id"] = next((c["computation_id"] for c in response.get("computations", []) if c.get("validation_passed")), None)
    return row


def blind_packet(tasks: list[dict], raw: dict, run_dir: Path) -> tuple[list[dict], dict]:
    entries = [(task, condition, raw[condition]["results"][index]) for index, task in enumerate(tasks) for condition in ("python_off", "python_on")]
    random.Random(42).shuffle(entries)
    packet, mapping = [], {}
    for index, (task, condition, row) in enumerate(entries, 1):
        anon = f"AR-{index:03d}"
        mapping[anon] = {"task_id": task["task_id"], "condition": condition}
        response = row["response"]
        answer = re.sub(r"\[(?:CALC|USER)\d+\]", "[INPUT_OR_ANALYSIS]", response.get("final_answer", ""))
        answer = re.sub(r"\bPython\b", "[METHOD]", answer, flags=re.I)
        packet.append({"anonymous_id": anon, "topic": task["topic"], "goal": task["goal"],
                       "qualitative_criteria": [{"criterion_id": c["criterion_id"], "description": c["description"]}
                                                for c in task["success_criteria"] if c["criterion_id"] not in (NUMERIC_ONLY if task["task_id"] != "PY-WT-008" else {"C1"})],
                       "required_claims": task["ground_truth"]["required_claims"],
                       "candidate_answer": answer,
                       "displayed_evidence": [{"evidence_id": s["evidence_id"], "document": s["document"],
                                               "page": s["page"], "excerpt": s["excerpt"][:1200]}
                                              for s in response.get("internal_sources", [])]})
    _save(run_dir / "review/blind_packet.json", {"reviewer_method": "single AI-assisted semantic reviewer", "items": packet})
    _save(run_dir / "review/blind_mapping.json", mapping)
    return packet, mapping


def review_one(item: dict, model: str = "gemma4:latest") -> dict:
    keys = [c["criterion_id"] for c in item["qualitative_criteria"]]
    schema = {"type": "object", "properties": {
        "criterion_passed": {"type": "object", "properties": {key: {"type": "boolean"} for key in keys},
                             "required": keys, "additionalProperties": False},
        "criterion_quotes": {"type": "object", "properties": {key: {"type": "string"} for key in keys},
                             "required": keys, "additionalProperties": False},
        "hallucination": {"type": "boolean"}, "engineering_contradiction": {"type": "boolean"},
        "notes": {"type": "string"}},
        "required": ["criterion_passed", "criterion_quotes", "hallucination", "engineering_contradiction", "notes"],
        "additionalProperties": False}
    system = ("You are a single independent petroleum-engineering semantic reviewer. Judge ONLY qualitative engineering meaning "
              "and cited evidence support. The candidate condition and tool process are hidden. Numeric values, units, "
              "arithmetic, and execution are scored separately; do not judge them. A criterion passes only if the answer "
              "supports every qualitative component, with an exact verbatim quote from candidate_answer. Do not copy "
              "a ground-truth sentence as a quote. Flag material invented engineering facts and contradictions. Return JSON only.")
    body = {"model": model, "messages": [{"role": "system", "content": system},
                                           {"role": "user", "content": json.dumps(item, ensure_ascii=False)}],
            "stream": False, "think": False, "format": schema,
            "options": {"temperature": 0, "seed": 42, "num_predict": 900}}
    request = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body, ensure_ascii=False).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=600) as handle:
        parsed = json.loads(json.load(handle)["message"]["content"])
    if set(parsed["criterion_passed"]) != set(keys) or set(parsed["criterion_quotes"]) != set(keys):
        raise ValueError("Reviewer criterion keys mismatch")
    for key in keys:
        if parsed["criterion_passed"][key] and (not parsed["criterion_quotes"][key] or parsed["criterion_quotes"][key] not in item["candidate_answer"]):
            parsed["criterion_passed"][key] = False
            parsed["criterion_quotes"][key] = ""
    return parsed


def numeric_and_calc(task: dict, row: dict, run_dir: Path) -> tuple[dict, dict]:
    response = row["response"]
    targets = task["ground_truth"]["numeric_targets"]
    final = {target["name"]: numeric_hits(response.get("final_answer", ""), target) for target in targets}
    calc = {target["name"]: False for target in targets}
    for record in response.get("computations", []):
        if not record.get("validation_passed"):
            continue
        for filename in record.get("output_files", []):
            if not filename.endswith(".json"):
                continue
            path = run_dir / "workspace" / filename
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            values = []
            def visit(value):
                if isinstance(value, dict):
                    for child in value.values():
                        visit(child)
                elif isinstance(value, list):
                    for child in value:
                        visit(child)
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    values.append(float(value))
            visit(data.get("result"))
            for target in targets:
                if any(abs(value - target["value"]) <= target["abs_tolerance"] for value in values):
                    calc[target["name"]] = True
    return final, calc


def provenance(task: dict, row: dict) -> dict:
    response = row["response"]
    sources = {s["evidence_id"]: s for s in response.get("internal_sources", [])}
    calculations = [c for c in response.get("computations", []) if c.get("validation_passed")]
    expected = task["ground_truth"]["formula_sources"]
    catalog = json.loads(BENCHMARK.read_text(encoding="utf-8"))["source_catalog"]
    def formula_ok(evidence_id: str) -> bool:
        source = sources.get(evidence_id)
        return bool(source and any(source["document"] == catalog[key]["document"] and source["page"] == catalog[key]["page"] for key in expected))
    user = task["input_origin"] == "user_fact"
    user_created = any("USER" in c.get("source_input_ids", []) or any(s.startswith("USER") for s in c.get("source_input_ids", [])) for c in calculations)
    formula = any(c.get("formula_evidence_ids") and all(formula_ok(s) for s in c["formula_evidence_ids"]) for c in calculations)
    answer = response.get("final_answer", "")
    return {"user_source_created": user_created if user else None,
            "user_fact_provenance_correct": any(c.get("source_input_ids") and not any(s.startswith("USER") for s in c.get("source_evidence_ids", [])) for c in calculations) if user else None,
            "formula_provenance_correct": formula if calculations else None,
            "final_cites_calc": bool(re.search(r"\[CALC\d+\]", answer)),
            "final_cites_user": bool(re.search(r"\[USER\d+\]", answer)) if user else None,
            "final_cites_formula_evidence": any(re.search(r"\[" + re.escape(sid) + r"\]", answer) and formula_ok(sid) for sid in sources)}


def score_row(task: dict, row: dict, judgment: dict, run_dir: Path) -> dict:
    response = row["response"]
    final, calc = numeric_and_calc(task, row, run_dir)
    numeric_only = {"C1"} if task["task_id"] == "PY-WT-008" else NUMERIC_ONLY
    criteria = {}
    for item in task["success_criteria"]:
        cid = item["criterion_id"]
        targets = [n["name"] for n in task["ground_truth"]["numeric_targets"] if n["criterion_id"] == cid]
        numeric_ok = all(final[name]["passed"] for name in targets)
        qualitative_ok = judgment["criterion_passed"].get(cid, True) if cid not in numeric_only else True
        criteria[cid] = bool(numeric_ok and qualitative_ok)
    trace = traces(response)
    total = len(task["ground_truth"]["numeric_targets"])
    result = {"task_id": task["task_id"], "condition": row["condition"], "python_expected": task["python_expected"],
              "domain": task["domain"], "goal_success": all(criteria.values()) and not judgment["engineering_contradiction"],
              "external_coverage": sum(criteria.values()) / len(criteria), "criteria_passed": criteria,
              "numeric_passed": sum(v["passed"] for v in final.values()), "numeric_total": total,
              "numeric_accuracy": sum(v["passed"] for v in final.values()) / total if total else None,
              "unit_accuracy": sum(v["unit_passed"] for v in final.values()) / total if total else None,
              "calc_numeric_passed": sum(calc.values()), "calc_numeric_total": total if response.get("computations") else 0,
              "final_numeric_targets": final, "calc_numeric_targets": calc,
              "hallucination": judgment["hallucination"], "engineering_contradiction": judgment["engineering_contradiction"],
              "latency_seconds": row["elapsed_seconds"], "python_seconds": sum(it.get("timing", {}).get("python_seconds", 0) for it in response.get("iterations", [])),
              "python_calls": response.get("python_calls_total", 0), "python_attempts": response.get("python_attempts_total", 0),
              "internal_goal_coverage_telemetry": response.get("goal_coverage"), **trace, **provenance(task, row)}
    result["failure_attribution"] = failure_attribution(result) if task["python_expected"] == "required" and not result["goal_success"] else None
    return result


def failure_attribution(row: dict) -> str:
    if not row["tool_selected"]: return "tool_not_selected"
    if not row["plan_present"]: return "no_plan"
    if not row["permission_passed"]: return "permission_failure"
    if row["blocked_stage"] == "input_fact_verification_failed": return "input_fact_failure"
    if row["blocked_stage"] == "formula_provenance_failed": return "formula_provenance_failure"
    if row["blocked_stage"] == "budget_exhausted": return "budget_exhausted"
    if not row["code_generated"]: return "code_generation_failure"
    if not row["sandbox_validation_passed"]: return "sandbox_validation_failure"
    if not row["subprocess_reached"]: return "runtime_failure"
    if not row["result_validation_passed"]: return "result_validation_failure"
    if row["calc_id"] and not row["goal_success"]: return "calc_correct_but_final_answer_failed" if row["calc_numeric_passed"] == row["calc_numeric_total"] else "other"
    return "research_evidence_failure"


def aggregate(tasks: list[dict], rows: list[dict]) -> dict:
    by = {c: {r["task_id"]: r for r in rows if r["condition"] == c} for c in ("python_off", "python_on")}
    def mean(values): return statistics.mean(values) if values else None
    def stats(group):
        lat = sorted(r["latency_seconds"] for r in group)
        numeric = [r for r in group if r["numeric_total"]]
        return {"goal_success": mean([r["goal_success"] for r in group]), "external_coverage": mean([r["external_coverage"] for r in group]),
                "numeric_accuracy": sum(r["numeric_passed"] for r in numeric) / sum(r["numeric_total"] for r in numeric) if numeric else None,
                "unit_accuracy": mean([r["unit_accuracy"] for r in numeric]), "hallucination_rate": mean([r["hallucination"] for r in group]),
                "engineering_error_rate": mean([r["engineering_contradiction"] for r in group]),
                "latency_mean": mean(lat), "latency_median": statistics.median(lat), "latency_p95": lat[math.ceil(.95*len(lat))-1]}
    required = [t["task_id"] for t in tasks if t["python_expected"] == "required"]
    all_ids = [t["task_id"] for t in tasks]
    on_req = [by["python_on"][tid] for tid in required]
    selected = sum(r["tool_selected"] for r in on_req)
    negatives = [r for r in rows if r["condition"] == "python_on" and r["python_expected"] == "not_needed"]
    fp = sum(r["tool_selected"] for r in negatives)
    precision = selected / (selected + fp) if selected + fp else None
    recall = selected / len(required)
    f1 = 2*precision*recall/(precision+recall) if precision is not None and precision+recall else 0
    benefit = harm = neutral = 0
    for tid in required:
        a, b = by["python_off"][tid], by["python_on"][tid]
        gained = b["external_coverage"] > a["external_coverage"] or b["numeric_passed"] > a["numeric_passed"]
        lost = b["external_coverage"] < a["external_coverage"] or b["numeric_passed"] < a["numeric_passed"]
        if gained and not lost: benefit += 1
        elif lost and not gained: harm += 1
        else: neutral += 1
    pairs = lambda ids, key: bootstrap([by["python_off"][tid][key] for tid in ids], [by["python_on"][tid][key] for tid in ids])
    return {"overall": {condition: stats(list(by[condition].values())) for condition in by},
            "required": {condition: stats([by[condition][tid] for tid in required]) for condition in by},
            "selection": {"true_positive": selected, "false_positive_not_needed": fp, "precision": precision, "recall": recall, "f1": f1},
            "funnel": {key: sum(r[key] for r in on_req) for key in ("tool_selected", "plan_present", "permission_passed", "facts_verified", "call_boundary_reached", "code_generated", "sandbox_validation_passed", "subprocess_reached", "result_validation_passed")},
            "calc_created": sum(bool(r["calc_id"]) for r in on_req),
            "benefit": {"benefit_rate": benefit/6, "neutral_rate": neutral/6, "harm_rate": harm/6},
            "overuse": {category: {"selected": sum(r["tool_selected"] for r in rows if r["condition"] == "python_on" and r["python_expected"] == category),
                                   "executed": sum(r["subprocess_reached"] for r in rows if r["condition"] == "python_on" and r["python_expected"] == category)} for category in ("optional", "not_needed")},
            "paired": {"goal_success": pairs(all_ids, "goal_success"), "external_coverage": pairs(all_ids, "external_coverage"),
                       "required_goal_success": pairs(required, "goal_success"), "required_numeric_accuracy": pairs(required, "numeric_accuracy")},
            "failure_attribution": dict(Counter(r["failure_attribution"] for r in on_req if r["failure_attribution"])),
            "python_mean_seconds": mean([r["python_seconds"] for r in rows if r["condition"] == "python_on"]),
            "python_calls": sum(r["python_calls"] for r in rows if r["condition"] == "python_on"),
            "python_attempts": sum(r["python_attempts"] for r in rows if r["condition"] == "python_on"),
            "repair_opportunities": sum(r["python_attempts"] > r["python_calls"] for r in rows if r["condition"] == "python_on"),
            "repair_successes": sum(r["python_attempts"] > r["python_calls"] and bool(r["calc_id"]) for r in rows if r["condition"] == "python_on")}


def write_csv(path: Path, rows: list[dict]) -> None:
    keys = list(rows[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows({key: json.dumps(row[key], ensure_ascii=False) if isinstance(row[key], (dict, list)) else row[key] for key in keys} for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--score", action="store_true")
    args = parser.parse_args()
    if args.review == args.score:
        parser.error("Select exactly one of --review or --score")
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if sha256(BENCHMARK) != manifest["benchmark_sha256"] or sha256(POLICY) != manifest["rubric_sha256"]:
        raise ValueError("Frozen evaluation checksum mismatch")
    raw = {c: json.loads((args.run_dir / f"{c}.json").read_text(encoding="utf-8")) for c in ("python_off", "python_on")}
    if not all(data["complete"] and len(data["results"]) == 10 for data in raw.values()):
        raise ValueError("Both complete ten-task conditions required")
    packet_path = args.run_dir / "review/blind_packet.json"
    if args.review:
        if packet_path.exists():
            raise FileExistsError("Original blind packet already exists")
        packet, _ = blind_packet(benchmark["tasks"], raw, args.run_dir)
        result = {"method": "single AI-assisted semantic reviewer", "model": "gemma4:latest", "items": {}}
        output = args.run_dir / "review/review_original.json"
        for index, item in enumerate(packet, 1):
            print(f"review {index}/20 {item['anonymous_id']}", flush=True)
            result["items"][item["anonymous_id"]] = review_one(item)
            _save(output, result)
        return 0
    mapping = json.loads((args.run_dir / "review/blind_mapping.json").read_text(encoding="utf-8"))
    review = json.loads((args.run_dir / "review/review_original.json").read_text(encoding="utf-8"))
    if len(review["items"]) != 20:
        raise ValueError("Incomplete original qualitative review")
    judgments = {(item["task_id"], item["condition"]): review["items"][anon] for anon, item in mapping.items()}
    rows = [score_row(task, raw[condition]["results"][index], judgments[(task["task_id"], condition)], args.run_dir)
            for index, task in enumerate(benchmark["tasks"]) for condition in ("python_off", "python_on")]
    summary = aggregate(benchmark["tasks"], rows)
    root = args.run_dir.parents[2]
    _save(root / "python_tool_heldout_v1_comparison.json", {"summary": summary, "rows": rows,
                                                            "run_dir": str(args.run_dir), "reviewer_method": review["method"]})
    write_csv(root / "python_tool_heldout_v1_comparison.csv", rows)
    write_csv(root / "python_tool_heldout_v1_funnel.csv", [{key: row.get(key) for key in ("task_id", "python_expected", "tool_selected", "plan_present", "permission_passed", "facts_verified", "blocked_stage", "call_boundary_reached", "code_generated", "sandbox_validation_passed", "subprocess_reached", "result_validation_passed", "calc_id")}
                                                            for row in rows if row["condition"] == "python_on"])
    write_csv(root / "python_tool_heldout_v1_poster.csv", [{"metric": key, "python_off": summary["overall"]["python_off"].get(key),
                                                              "python_on": summary["overall"]["python_on"].get(key)}
                                                             for key in summary["overall"]["python_off"]])
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
