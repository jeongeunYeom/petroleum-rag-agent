"""Objective V4 flags only; semantic outcomes use the separately frozen rubric."""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
NUMBER = re.compile(r"(?<![\w])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?![\w])")
CITATION = re.compile(r"\[(?:KB|FIG)\d+\]")
RAW_ERROR = re.compile(r"traceback|keyerror:|jsondecodeerror|chromadb\.error|connectionerror:|file not found|internal server error", re.I)
LIMITATION = re.compile(r"확인할 수 없|확인하지 못|찾지 못|검증할 수 없|근거가 없|제공.*없|cannot verify|not found|unverified|unable to|no (?:verified|available|such|matching) (?:formula|source|relation)", re.I)


def read(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def file_hash(name: str) -> str:
    return hashlib.sha256((HERE / name).read_bytes()).hexdigest()


def numeric_flags(answer: str, expected: list[dict]) -> list[dict]:
    unmarked = re.sub(r"\[[^\]]+\]", "", answer or "")
    visible = [(float(match.group().replace(",", "")), match.start()) for match in NUMBER.finditer(unmarked)]
    flags = []
    for item in expected:
        matches = [(value, offset) for value, offset in visible
                   if abs(value - item["value"]) <= item["tolerance"]]
        unit = item["unit"].casefold()
        if unit == "dimensionless":
            unit_seen = True
        elif unit == "%":
            unit_seen = bool(re.search(r"%|percent|퍼센트|백분율", unmarked, re.I))
        elif unit == "°api":
            unit_seen = bool(re.search(r"°\s*API|degrees?\s*API|API도", unmarked, re.I))
        elif unit == "ohm-m":
            unit_seen = bool(re.search(r"ohm[ -]?m|Ω[· ]?m", unmarked, re.I))
        else:
            unit_seen = unit in unmarked.casefold()
        flags.append({"target": item["target"], "expected": item["value"],
                      "tolerance": item["tolerance"], "unit": item["unit"],
                      "value_present_heuristic": bool(matches), "unit_present_heuristic": unit_seen,
                      "candidate_values": [value for value, _ in matches[:6]]})
    return flags


def agent_flags(task: dict, row: dict) -> dict:
    answer = row.get("final_answer") or ""
    visible = answer or row.get("final_clarification") or row.get("first_turn_clarification") or ""
    sources = {item.get("evidence_id"): item for item in row.get("internal_sources", [])}
    cited = {marker[1:-1] for marker in CITATION.findall(answer)}
    citation_ids_valid = not (cited - sources.keys())
    validation = row.get("validation") or {}
    validated = [item for item in row.get("computations", []) if item.get("validation_passed")]
    numerics = numeric_flags(answer, task["gold"]["numeric_outputs"])
    formula_source_ok = True
    for item in task["gold"]["numeric_outputs"]:
        if not item["requires_kb_formula"]:
            continue
        required = {source["key"]: source for source in task["gold"]["source_spans"]}
        expected_sources = [required[key] for key in item["formula_source_keys"]]
        grounded = False
        for calc in validated:
            for source_id in calc.get("formula_source_ids") or []:
                used = sources.get(source_id)
                if used and any(used.get("document") == gold["document"]
                                and used.get("page") == gold["page"]
                                and re.sub(r"\s+", "", gold["needle"]).casefold()
                                in re.sub(r"\s+", "", str(used.get("excerpt") or "")).casefold()
                                for gold in expected_sources):
                    grounded = True
        formula_source_ok &= grounded
    category = task["category"]
    if category == "resume":
        correct_state = (row.get("first_turn_status") == "waiting_for_user_input"
                         and row.get("follow_up_sent") and row.get("first_turn_run_id") == row.get("run_id")
                         and row.get("final_status") == "completed")
    elif category == "unanswerable":
        correct_state = (row.get("final_status") in {"stopped", "completed"}
                         and bool(LIMITATION.search(visible)))
    else:
        correct_state = row.get("final_status") == "completed"
    crash = bool(row.get("error") or row.get("final_status") in
                 {"failed", "canceled", "timeout", "harness_error"})
    repeated_clarification = bool(row.get("follow_up_sent")
                                  and row.get("first_turn_clarification")
                                  and row.get("first_turn_clarification") == row.get("final_clarification")
                                  and row.get("final_status") == "waiting_for_user_input")
    return {"id": task["id"], "category": category, "language": task["language"],
            "correct_interaction_state_heuristic": correct_state,
            "numeric_outputs": numerics, "all_numeric_and_units_heuristic": all(
                item["value_present_heuristic"] and item["unit_present_heuristic"] for item in numerics),
            "validated_calculation_count": len(validated),
            "formula_source_correct_heuristic": formula_source_ok,
            "cited_ids": sorted(cited), "invalid_cited_ids": sorted(cited - sources.keys()),
            "citation_ids_valid": citation_ids_valid,
            "citation_semantic_passed_product": validation.get("citation_semantic_passed"),
            "unsupported_numeric_claim_count_product": validation.get("unsupported_numeric_claim_count"),
            "engineering_contradiction_count_product": validation.get("engineering_contradiction_count"),
            "external_sources_count": len(row.get("external_sources") or []),
            "crash": crash, "blank_visible": not bool(visible.strip()),
            "raw_error_leak": bool(RAW_ERROR.search(visible)),
            "repeated_identical_clarification": repeated_clarification,
            "possible_unnecessary_refusal": category != "unanswerable" and not correct_state and not crash,
            "seconds": row["seconds"]}


def baseline_flags(task: dict, row: dict) -> dict:
    answer = row.get("final_answer") or ""
    numerics = numeric_flags(answer, task["gold"]["numeric_outputs"])
    return {"id": task["id"], "category": task["category"], "language": task["language"],
            "numeric_outputs": numerics, "all_numeric_and_units_heuristic": all(
                item["value_present_heuristic"] and item["unit_present_heuristic"] for item in numerics),
            "error": row.get("error"), "blank_visible": not bool(answer.strip()),
            "raw_error_leak": bool(RAW_ERROR.search(answer)), "seconds": row["seconds"]}


def latency(rows: list[dict]) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["category"]].append(row["seconds"])
        grouped["overall"].append(row["seconds"])
    def p95(values: list[float]) -> float:
        values = sorted(values)
        return values[min(len(values) - 1, max(0, int(0.95 * len(values) + 0.999999) - 1))]
    return {category: {"n": len(values), "median_seconds": round(statistics.median(values), 3),
                       "p95_seconds": round(p95(values), 3)}
            for category, values in grouped.items()}


def main() -> None:
    catalog_hash = file_hash("v4_catalog.json")
    if catalog_hash != (HERE / "v4_catalog.sha256").read_text(encoding="ascii").split()[0]:
        raise RuntimeError("Sealed catalog hash mismatch")
    catalog = read("v4_catalog.json")
    agent = read("agent_results.json")
    baseline = read("qwen_closed_book_results.json")
    for result in (agent, baseline):
        if result["catalog_sha256"] != catalog_hash or len(result["rows"]) != 60 or result.get("inflight"):
            raise RuntimeError("Incomplete or mismatched one-shot result")
    arows = {row["id"]: row for row in agent["rows"]}
    brows = {row["id"]: row for row in baseline["rows"]}
    expected_ids = {task["id"] for task in catalog["tasks"]}
    if set(arows) != expected_ids or set(brows) != expected_ids:
        raise RuntimeError("Result task IDs differ from sealed catalog")
    scores = {"catalog_sha256": catalog_hash,
              "agent_results_sha256": file_hash("agent_results.json"),
              "closed_book_results_sha256": file_hash("qwen_closed_book_results.json"),
              "agent": [agent_flags(task, arows[task["id"]]) for task in catalog["tasks"]],
              "qwen_closed_book": [baseline_flags(task, brows[task["id"]]) for task in catalog["tasks"]]}
    agent_flags_list = scores["agent"]
    scores["summary"] = {
        "agent_interaction_state_heuristic": sum(item["correct_interaction_state_heuristic"] for item in agent_flags_list),
        "agent_crashes": sum(item["crash"] for item in agent_flags_list),
        "agent_blank": sum(item["blank_visible"] for item in agent_flags_list),
        "agent_raw_error_leaks": sum(item["raw_error_leak"] for item in agent_flags_list),
        "agent_invalid_citation_id_rows": sum(not item["citation_ids_valid"] for item in agent_flags_list),
        "agent_external_source_rows": sum(item["external_sources_count"] > 0 for item in agent_flags_list),
        "agent_repeated_clarifications": sum(item["repeated_identical_clarification"] for item in agent_flags_list),
        "agent_latency": latency(agent_flags_list),
        "closed_book_latency": latency(scores["qwen_closed_book"]),
    }
    (HERE / "automatic_scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")
    print(json.dumps(scores["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
