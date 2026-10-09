"""Deterministic first-pass grading of the frozen final experiment.

Never changes the benchmark or product. Semantic fields remain null until the
separate AI-assisted reviewer has been run; null is not silently scored as zero.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re

from run_experiment import HERE, load_benchmark


TRACKS = {
    "agent": HERE / "raw/agent",
    "qwen_closed_book": HERE / "raw/qwen",
    "openai_closed_book": HERE / "raw/openai",
    "gemini_closed_book": HERE / "raw/gemini",
    "qwen_same_evidence": HERE / "same_evidence/qwen",
    "openai_same_evidence": HERE / "same_evidence/openai",
    "gemini_same_evidence": HERE / "same_evidence/gemini",
}
NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?(?![\w.])")
CITE = re.compile(r"\[((?:KB|FIG|WEB)\d+)\]")


def numbers(text: str) -> list[float]:
    return [float(match.group().replace(",", "")) for match in NUMBER.finditer(text)]


def expected_numeric(task: dict) -> tuple[dict, float | None]:
    if task.get("expected_after_resume"):
        return task["expected_after_resume"], task.get("resume_tolerance")
    value = task.get("required_numeric_result") or {}
    return value, (task.get("tolerance") or {}).get("absolute")


def numeric_hit(answer: str, value: float, tolerance: float | None) -> bool:
    return any(math.isclose(number, value, abs_tol=tolerance or 1e-8, rel_tol=0)
               for number in numbers(answer))


def unit_expected(field: str) -> str | None:
    if field == "oil_rate":
        return "stb/d"
    if "api_gravity" in field:
        return "api"
    if "scf_per_stb" in field:
        return "scf/stb"
    if "psi_per_ft" in field:
        return "psi/ft"
    if field.endswith("_psi"):
        return "psi"
    if field.endswith("_percent"):
        return "%"
    if field.endswith("_stbd"):
        return "stb/d"
    if field.endswith("_stock_tank_m3") or field.endswith("_m3"):
        return "m3"
    if field.endswith("_m3d"):
        return "m3/d"
    if field.endswith("_usd_day"):
        return "usd/day"
    if field.endswith("_ft"):
        return "ft"
    return None


def unit_hit(answer: str, unit: str) -> bool:
    lower = answer.casefold()
    patterns = {
        "api": ["°api", "ºapi", "degrees api", "api도"],
        "scf/stb": ["scf/stb"],
        "psi/ft": ["psi/ft"],
        "psi": ["psi"],
        "%": ["%", "퍼센트", "percent"],
        "stb/d": ["stb/d", "stbd", "stb/day"],
        "m3": ["m³", "m3"],
        "m3/d": ["m³/d", "m3/d", "m³/day", "m3/day"],
        "usd/day": ["usd/day", "usd/d", "달러/일", "$/day"],
        "ft": ["ft", "피트"],
    }
    return any(marker in lower for marker in patterns.get(unit, []))


def retrieved_sources(response: dict) -> list[dict]:
    return [*response.get("internal_sources", []), *response.get("figures", [])]


def recall(task: dict, response: dict, catalog: dict) -> tuple[float | None, float | None, float | None]:
    refs = [catalog[key] for key in task["expected_source_ids"]]
    if not refs:
        return None, None, None
    hits = retrieved_sources(response)
    document = sum(any(item.get("document") == ref["document"] for item in hits)
                   for ref in refs) / len(refs)
    page = sum(any(item.get("document") == ref["document"] and
                   item.get("page") == ref["page"] for item in hits)
               for ref in refs) / len(refs)
    figures = None
    if task["figure_requirement"]:
        figures = float(any(item.get("document") == ref["document"] and
                            item.get("page") == ref["page"] for item in response.get("figures", [])
                            for ref in refs if ref.get("figure_note")))
    return document, page, figures


def citation_check(task: dict, answer: str, source_items: list[dict], *, applicable: bool) -> tuple[bool | None, int, int]:
    found = CITE.findall(answer)
    if not applicable:
        return None, len(found), 0
    ids = {item.get("evidence_id") for item in source_items}
    invalid = sum(value not in ids for value in found)
    if not task["expected_source_ids"] and not found:
        return None, 0, 0
    return bool(found) and invalid == 0, len(found), invalid


def formula_source_correct(task: dict, response: dict, catalog: dict) -> bool | None:
    if task["category"] != "kb_calculation":
        return None
    by_id = {item.get("evidence_id"): item for item in retrieved_sources(response)}
    expected = {(catalog[key]["document"], catalog[key]["page"])
                for key in task["expected_source_ids"]}
    for record in response.get("computations", []):
        source_id = record.get("formula_source_id")
        source = by_id.get(source_id)
        if (record.get("validation_passed") and source and
                (source.get("document"), source.get("page")) in expected):
            return True
    return False


def grade(task: dict, track: str, payload: dict | None, catalog: dict, invalid: set[str]) -> dict:
    task_id = task["task_id"]
    result = {"task_id": task_id, "track": track, "category": task["category"],
              "difficulty": task["difficulty"], "valid": task_id not in invalid,
              "error": (payload or {}).get("error"), "model_id": (payload or {}).get("model_id"),
              "wall_seconds": (payload or {}).get("wall_seconds")}
    if payload is None or payload.get("error"):
        result["available"] = False
        return result
    result["available"] = True
    response = payload.get("response", {}) if track == "agent" else {}
    answer = response.get("final_answer", "") if track == "agent" else payload.get("answer", "")
    result["answer"] = answer
    result["run_status"] = response.get("run_status") if track == "agent" else None
    result["agent_self_status"] = response.get("status") if track == "agent" else None
    target_values, tolerance = expected_numeric(task)
    result["numeric_field_hits"] = {field: numeric_hit(answer, value, tolerance)
                                     for field, value in target_values.items()}
    result["numeric_accuracy_deterministic"] = (
        all(result["numeric_field_hits"].values()) if target_values else None)
    units = {unit_expected(field) for field in target_values if unit_expected(field)}
    result["unit_accuracy_deterministic"] = (
        all(unit_hit(answer, unit) for unit in units) if units else None)
    applicable_citation = track == "agent" or track.endswith("same_evidence")
    sources = retrieved_sources(response) if track == "agent" else payload.get("evidence", [])
    result["citation_correctness_deterministic"], result["citation_count"], result["invalid_citation_count"] = (
        citation_check(task, answer, sources, applicable=applicable_citation))
    result["document_recall_at_k"] = None
    result["page_recall_at_k"] = None
    result["figure_retrieval_accuracy"] = None
    result["formula_source_correctness"] = None
    result["calculation_provenance_accuracy"] = None
    result["correct_action_selection"] = None
    result["clarification_success"] = None
    result["same_run_resume_success"] = None
    result["python_simulation_execution_success"] = None
    result["validated_calc_adoption"] = None
    result["repeated_no_progress_action_rate"] = None
    result["retrieval_seconds"] = None
    result["llm_generation_seconds"] = None
    result["calculation_simulation_seconds"] = None
    result["verification_seconds"] = None
    if track == "agent":
        doc, page, fig = recall(task, response, catalog)
        result.update(document_recall_at_k=doc, page_recall_at_k=page,
                      figure_retrieval_accuracy=fig)
        formula_correct = formula_source_correct(task, response, catalog)
        result["formula_source_correctness"] = formula_correct
        result["calculation_provenance_accuracy"] = formula_correct
        actions = response.get("action_history", [])
        types = [str(item.get("action_type", "")).upper() for item in actions]
        required = [kind for kind in task["expected_actions"] if kind != "WAITING_FOR_USER_INPUT"]
        position = -1
        matches = True
        for kind in required:
            try:
                position = types.index(kind, position + 1)
            except ValueError:
                matches = False
                break
        if task["category"] == "direct_calculation":
            matches = matches and (not types or types[0] == "CALCULATE") and "RETRIEVE" not in types
        if task["clarification_required"]:
            first = payload.get("initial_response") or {}
            matches = matches and first.get("run_status") == "waiting_for_user_input"
            result["clarification_success"] = bool(first.get("run_status") == "waiting_for_user_input")
            result["same_run_resume_success"] = bool(payload.get("same_run_resume"))
        result["correct_action_selection"] = matches
        calc = response.get("computations", [])
        if task["calculation_required"]:
            result["python_simulation_execution_success"] = bool(
                response.get("python_calls_total", 0) and any(x.get("validation_passed") for x in calc))
            result["validated_calc_adoption"] = bool(
                any(x.get("validation_passed") for x in calc) and
                result["numeric_accuracy_deterministic"])
        seen_action_blockers = set()
        repeated_no_progress = 0
        for item in actions:
            fingerprint = (item.get("action_type"), tuple(item.get("target_criteria") or []),
                           item.get("reason_code"))
            unchanged = (item.get("coverage_after") == item.get("coverage_before") and
                         not item.get("evidence_added") and not item.get("computation_ids"))
            if fingerprint in seen_action_blockers and unchanged:
                repeated_no_progress += 1
            seen_action_blockers.add(fingerprint)
        result["repeated_no_progress_action_rate"] = (
            repeated_no_progress / len(actions) if actions else 0.0)
        timing = response.get("timing", {})
        result["retrieval_seconds"] = timing.get("retrieval_seconds")
        result["llm_generation_seconds"] = timing.get("llm_generation_seconds")
        result["calculation_simulation_seconds"] = sum(
            timing.get(key, 0.0) for key in ("calculate_action_seconds", "simulate_action_seconds"))
        result["verification_seconds"] = timing.get("verification_seconds")
        result["action_sequence"] = types
        result["run_id"] = response.get("run_id")
        result["python_calls"] = response.get("python_calls_total", 0)
        result["validated_calculations"] = sum(x.get("validation_passed", False) for x in calc)
    return result


def main() -> None:
    benchmark = load_benchmark()
    invalid = {item["task_id"] for item in json.loads((HERE / "invalid_tasks.json").read_text(encoding="utf-8"))["invalid"]}
    output = HERE / "metrics/deterministic_rows.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for task in benchmark["tasks"]:
        for track, folder in TRACKS.items():
            path = folder / f"{task['task_id']}.json"
            payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
            rows.append(grade(task, track, payload, benchmark["source_catalog"], invalid))
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"deterministic_rows={len(rows)} available={sum(x['available'] for x in rows)} valid_tasks={50-len(invalid)}")


if __name__ == "__main__":
    main()
