"""Frozen-v2 deterministic layer. Semantic judgements are left for the reviewer."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from run_experiment import HERE, load_benchmark


TRACKS = {
    "agent": HERE / "raw/agent",
    "qwen_closed_book": HERE / "raw/qwen",
    "openai_closed_book": HERE / "raw/openai",
    "qwen_same_evidence": HERE / "same_evidence/qwen",
    "openai_same_evidence": HERE / "same_evidence/openai",
}
CALC_CATEGORIES = {"direct_calculation", "kb_calculation", "simulation", "clarification"}
NUMBER = re.compile(r"(?<![\w.])[-+]?(?:\d[\d,]*)(?:\.\d+)?(?![\w.])")
CITE = re.compile(r"\[((?:KB|FIG|WEB)\d+)\]")


def numeric_hits(answer: str, expected: dict, tolerance: float) -> dict[str, bool]:
    observed = [float(item.group().replace(",", "")) for item in NUMBER.finditer(answer)]
    return {name: any(math.isclose(float(value), number, rel_tol=0, abs_tol=tolerance)
                      for number in observed) for name, value in expected.items()}


def unit_hits(answer: str, expected: dict) -> dict[str, bool]:
    text = answer.casefold().replace("³", "3").replace("²", "2")
    aliases = {"dimensionless": ["무차원", "dimensionless", "unitless"],
               "°api": ["°api", "api도", "degrees api"],
               "°c": ["°c", "celsius", "섭씨"],
               "m3": ["m3"], "m3/d": ["m3/d", "m3/day"],
               "scf/stb": ["scf/stb"], "stb/d": ["stb/d", "stb/day", "stbd"],
               "psi": ["psi"], "psia": ["psia"], "ppg": ["ppg"],
               "cp": ["cp"], "%": ["%", "percent", "퍼센트"]}
    return {field: any(alias in text for alias in aliases.get(str(unit).casefold(), [str(unit).casefold()]))
            for field, unit in expected.items() if str(unit).casefold() != "dimensionless"}


def evidence_items(response: dict) -> list[dict]:
    return [*response.get("internal_sources", []), *response.get("figures", [])]


def source_recall(task: dict, response: dict, catalog: dict) -> tuple[float | None, float | None, float | None]:
    refs = [catalog[key] for key in task["expected_source_ids"]]
    if not refs:
        return None, None, None
    hits = evidence_items(response)
    document = sum(any(hit.get("document") == ref["document"] for hit in hits) for ref in refs) / len(refs)
    page = sum(any(hit.get("document") == ref["document"] and
                   int(hit.get("page") or -1) == ref["page"] for hit in hits) for ref in refs) / len(refs)
    figure = None
    if task["category"] == "figure":
        figure = float(any(hit.get("document") == ref["document"] and
                           int(hit.get("page") or -1) == ref["page"]
                           for hit in response.get("figures", []) for ref in refs))
    return document, page, figure


def action_metrics(task: dict, payload: dict, response: dict) -> dict:
    actions = response.get("action_history", [])
    names = [str(row.get("action_type", "")).upper() for row in actions]
    required = [action for action in task.get("expected_actions", []) if action != "WAITING_FOR_USER_INPUT"]
    cursor = -1
    selected = True
    for action in required:
        try:
            cursor = names.index(action, cursor + 1)
        except ValueError:
            selected = False
            break
    if task["category"] in {"direct_calculation", "simulation"}:
        selected = selected and bool(names) and names[0] == ("CALCULATE" if task["category"] == "direct_calculation" else "SIMULATE") and "RETRIEVE" not in names
    first = payload.get("initial_response") or {}
    clarification = task["category"] == "clarification"
    if clarification:
        selected = selected and first.get("run_status") == "waiting_for_user_input"
    seen: set[tuple] = set()
    repeated = 0
    for row in actions:
        fingerprint = (row.get("action_type"), row.get("reason_code"), tuple(row.get("target_criteria") or []))
        stagnant = row.get("coverage_before") == row.get("coverage_after") and not row.get("evidence_added") and not row.get("computation_ids")
        if fingerprint in seen and stagnant:
            repeated += 1
        seen.add(fingerprint)
    return {"action_sequence": names, "correct_action_selection": selected,
            "clarification_success": first.get("run_status") == "waiting_for_user_input" if clarification else None,
            "same_run_resume_success": bool(payload.get("same_run_resume") and
                                            response.get("status") == "achieved") if clarification else None,
            "repeated_no_progress_action_rate": repeated / len(actions) if actions else 0.0}


def provenance(task: dict, response: dict, catalog: dict) -> tuple[bool | None, bool | None, bool | None]:
    if task["category"] not in CALC_CATEGORIES:
        return None, None, None
    records = [row for row in response.get("computations", []) if row.get("validation_passed")]
    if not records:
        return False, False, False
    from app.services.formula_source_registry import equation_ast, FormulaSourceRegistry, source_contains_equation
    sources = {row.get("evidence_id"): row for row in evidence_items(response)}
    complete = False
    correct_source = None if task["category"] not in {"kb_calculation", "clarification"} else False
    formula = None if "expected_formula" not in task and "user_formula" not in task else False
    expected_loci = {(catalog[key]["document"], catalog[key]["page"])
                     for key in task["expected_source_ids"]}
    target_ast = equation_ast(task.get("expected_formula") or task.get("user_formula") or "")
    for record in records:
        code = next((row.get("code") for row in reversed(record.get("attempt_records") or [])
                     if row.get("validation_passed") and isinstance(row.get("code"), str)), None)
        hash_ok = bool(code and hashlib.sha256(code.encode()).hexdigest() == record.get("execution_hash"))
        source_ids = record.get("formula_source_ids") or []
        input_ids = record.get("input_fact_ids") or []
        bindings = record.get("bound_variables") or {}
        output_manifest = record.get("output_manifest") or {}
        chain_ok = (record.get("contract_validation_passed") and hash_ok and source_ids and input_ids and bindings
                    and all(value in input_ids for value in bindings.values()) and record.get("normalized_formula")
                    and output_manifest and record.get("output") == {key: value.get("value") for key, value in output_manifest.items()})
        complete = complete or bool(chain_ok)
        if formula is not None:
            formula = formula or bool(target_ast and target_ast == equation_ast(record.get("source_formula") or record.get("formula") or ""))
        if correct_source is not None:
            for source_id in source_ids:
                source = sources.get(source_id)
                if not source or (source.get("document"), int(source.get("page") or -1)) not in expected_loci:
                    continue
                text = source.get("excerpt") or source.get("source_note") or ""
                registry = FormulaSourceRegistry.from_evidence([{"source_type": "knowledge_base", "evidence_id": source_id, "text": text}])
                if any(source_contains_equation(item, text, record.get("source_formula") or record.get("formula"))
                       for item in registry.records):
                    correct_source = True
    return bool(complete), correct_source, formula


def grade(task: dict, track: str, payload: dict | None, catalog: dict, invalid: set[str]) -> dict:
    result = {"task_id": task["task_id"], "category": task["category"], "domain": task["domain"],
              "track": track, "valid": task["task_id"] not in invalid, "available": bool(payload and not payload.get("error")),
              "error": (payload or {}).get("error"), "model_id": (payload or {}).get("model_id"),
              "wall_seconds": (payload or {}).get("wall_seconds")}
    if not result["available"]:
        return result
    response = payload.get("response", {}) if track == "agent" else {}
    answer = response.get("final_answer", "") if track == "agent" else payload.get("answer", "")
    result["answer"] = answer
    expected = task.get("expected_after_resume") or task.get("required_numeric_result") or {}
    tolerance = float(task.get("resume_tolerance") or (task.get("tolerance") or {}).get("absolute") or 1e-6)
    result["numeric_field_hits"] = numeric_hits(answer, expected, tolerance)
    result["numeric_accuracy_deterministic"] = all(result["numeric_field_hits"].values()) if expected else None
    result["unit_field_hits"] = unit_hits(answer, task.get("expected_units") or {})
    result["unit_accuracy_deterministic"] = all(result["unit_field_hits"].values()) if result["unit_field_hits"] else None
    evidence = evidence_items(response) if track == "agent" else payload.get("evidence", [])
    cites = CITE.findall(answer)
    valid_ids = {row.get("evidence_id") for row in evidence}
    result["citation_ids"] = cites
    result["citation_id_correctness"] = bool(cites) and all(cid in valid_ids for cid in cites) if track == "agent" or track.endswith("same_evidence") else None
    result["citation_semantic_support"] = None
    if track == "agent":
        result["run_id"] = response.get("run_id")
        result["run_status"] = response.get("run_status")
        result["agent_self_status"] = response.get("status")
        result["python_calls"] = response.get("python_calls_total", 0)
        result["validated_calculations"] = sum(bool(row.get("validation_passed")) for row in response.get("computations", []))
        result["document_recall_at_k"], result["page_recall_at_k"], result["figure_retrieval_accuracy"] = source_recall(task, response, catalog)
        result.update(action_metrics(task, payload, response))
        result["calculation_provenance_completeness"], result["formula_source_correctness"], result["formula_accuracy_deterministic"] = provenance(task, response, catalog)
        result["python_simulation_execution_success"] = (bool(result["validated_calculations"] and result["python_calls"])
                                                         if task["category"] in CALC_CATEGORIES else None)
        result["validated_calc_adoption"] = (bool(result["validated_calculations"] and result["numeric_accuracy_deterministic"])
                                             if expected else None)
        timing = response.get("timing") or {}
        result["retrieval_seconds"] = timing.get("retrieval_seconds")
        result["llm_generation_seconds"] = timing.get("llm_generation_seconds")
        result["calculation_simulation_seconds"] = sum(float(timing.get(name) or 0) for name in ("calculate_action_seconds", "simulate_action_seconds", "python_seconds"))
        result["verification_seconds"] = timing.get("verification_seconds")
    return result


def main() -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    benchmark = load_benchmark()
    path = HERE / "invalid_tasks.json"
    invalid = {row["task_id"] for row in json.loads(path.read_text(encoding="utf-8")).get("invalid", [])} if path.exists() else set()
    rows = []
    for task in benchmark["tasks"]:
        for track, directory in TRACKS.items():
            raw = directory / f"{task['task_id']}.json"
            payload = json.loads(raw.read_text(encoding="utf-8")) if raw.exists() else None
            rows.append(grade(task, track, payload, benchmark["source_catalog"], invalid))
    output = HERE / "metrics/deterministic_rows.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"rows={len(rows)} available={sum(row['available'] for row in rows)} valid_tasks={len(benchmark['tasks'])-len(invalid)}")


if __name__ == "__main__":
    main()
