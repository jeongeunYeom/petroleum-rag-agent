"""Checkpointed local-product stress run; fresh development prompts, never V4."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

from run_real_kb_dev import NUMBER, CITATION, answer_has_number

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
DONE = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def assess(case: dict, row: dict) -> tuple[bool, list[str]]:
    answer = row["visible_answer"] or ""
    category = case["category"]
    failures: list[str] = []
    if not answer.strip():
        failures.append("blank_response")
    if row["error"] or row["final_status"] in {"failed", "timeout", "http_error"}:
        failures.append("technical_crash")
    if category in {"knowledge", "direct", "user_formula", "kb_formula", "multi_goal", "false_premise", "resume"} and row["final_status"] != "completed":
        failures.append("goal_not_completed")
    if any(token in answer.casefold() for token in
           ("traceback", "keyerror:", "jsondecodeerror", "chromadb.error", "connectionerror:")):
        failures.append("raw_error_leak")
    cited = {marker[1:-1] for marker in CITATION.findall(answer)}
    source_ids = {source["id"] for source in row["sources"]}
    if cited - source_ids:
        failures.append("fabricated_source_id")
    validation = row.get("validation") or {}
    if (validation.get("unsupported_numeric_claim_count") or 0) > 0:
        failures.append("unsupported_numeric_result")
    if validation.get("citation_semantic_passed") is False and category in {"knowledge", "kb_formula", "false_premise"}:
        failures.append("citation_semantic_unsupported")
    validated = [calc for calc in row["computations"] if calc["validation_passed"]]
    if category in {"direct", "user_formula", "multi_goal", "kb_formula"}:
        if not validated:
            failures.append("requested_calculation_not_validated")
        for expected in case.get("numeric", []):
            if not answer_has_number(answer, expected):
                failures.append("requested_number_missing")
        if category in {"direct", "user_formula"} and "retrieve" in row["actions"]:
            failures.append("unnecessary_retrieval")
    if category == "kb_formula":
        if not cited:
            failures.append("missing_formula_citation")
        if validated and not any(any(source_id in source_ids for source_id in calc["formula_source_ids"])
                                 for calc in validated):
            failures.append("unverified_formula_source")
    if category == "knowledge" and not cited:
        failures.append("unnecessary_refusal_or_uncited_answer")
    if category == "false_premise":
        if not cited or not re.search(
                r"\b(?:no|not|incorrect|false|contradict\w*)\b|아니|잘못|틀린|반대|"
                r"맞지\s*않|옳지\s*않|정확하지\s*않|사실이\s*아니", answer, re.I):
            failures.append("premise_not_corrected_with_citation")
    if category == "out_of_domain" and (row["computations"] or cited):
        failures.append("out_of_domain_unsafe_action")
    if category == "resume":
        if row["turn1_status"] != "waiting_for_user_input" or row["final_status"] != "completed":
            failures.append("resume_not_completed")
        if row["turn1_run_id"] != row["run_id"]:
            failures.append("new_run_on_resume")
        if not validated:
            failures.append("missing_validated_calc_after_resume")
        if row["turn1_clarification"] and row["turn1_clarification"] == row["final_clarification"]:
            failures.append("repeated_clarification")
    if category in {"direct", "user_formula", "multi_goal", "kb_formula"} and row["final_status"] == "waiting_for_user_input":
        failures.append("unnecessary_clarification")
    return not failures, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--retry-failed", action="store_true", help="append another attempt only for failed development prompts")
    parser.add_argument("--catalog", default="conference_stress.json")
    parser.add_argument("--output", default="conference_stress_results.json")
    parser.add_argument("--case-id")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    data_dir = os.getenv("DATA_DIR")
    if not data_dir:
        raise SystemExit("DATA_DIR must identify the existing production data parent")

    import chromadb
    from fastapi.testclient import TestClient
    from app.main import app

    db = Path(data_dir).resolve() / "vector_db"
    if not (db / "chroma.sqlite3").is_file():
        raise SystemExit("Existing ChromaDB not found; refusing to create a new one")
    collection = chromadb.PersistentClient(path=str(db)).get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        raise SystemExit("Unexpected KB count; refusing to proceed")
    all_cases = json.loads((HERE / args.catalog).read_text(encoding="utf-8"))["cases"]
    cases = all_cases
    if len(cases) < 200:
        raise SystemExit("Stress suite requires at least 200 fresh prompts")
    if args.category:
        cases = [case for case in cases if case["category"] == args.category]
    if args.case_id:
        cases = [case for case in cases if case["id"] == args.case_id]
        if not cases:
            raise SystemExit("Unknown development case ID")
    if args.limit is not None:
        cases = cases[:args.limit]
    output = HERE / args.output
    rows = json.loads(output.read_text(encoding="utf-8"))["rows"] if output.exists() else []
    latest = {row["id"]: row for row in rows}
    case_by_id = {case["id"]: case for case in all_cases}
    done = (set() if args.force else {row_id for row_id, row in latest.items()
             if assess(case_by_id[row_id], row)[0]}
            if args.retry_failed else set(latest))
    with TestClient(app) as client:
        def poll(run_id: str) -> dict:
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                response = client.get(f"/api/research/goal-runs/{run_id}")
                response.raise_for_status()
                payload = response.json()
                if payload["run_status"] in DONE:
                    return payload
                time.sleep(0.7)
            return {"run_id": run_id, "run_status": "timeout", "error": "bounded_timeout"}

        for case in cases:
            if case["id"] in done:
                continue
            started = time.monotonic()
            try:
                response = client.post("/api/research/goal-runs/from-message",
                                       json={"message": case["message"], "model": "qwen3:8b"})
                response.raise_for_status()
                run_id = response.json()["run_id"]
                first = poll(run_id)
                final = first
                if case.get("reply") and first["run_status"] == "waiting_for_user_input":
                    response = client.post(f"/api/research/goal-runs/{run_id}/resume",
                                           json={"message": case["reply"]})
                    response.raise_for_status()
                    final = poll(run_id)
                row = {"id": case["id"], "category": case["category"], "run_id": run_id,
                       "turn1_run_id": first.get("run_id"), "turn1_status": first["run_status"],
                       "turn1_clarification": first.get("clarification_question"),
                       "final_status": final["run_status"],
                       "final_clarification": final.get("clarification_question"),
                       "visible_answer": final.get("final_answer") or final.get("clarification_question") or "",
                       "error": final.get("error"),
                       "actions": [item.get("action_type") for item in final.get("action_history", [])],
                       "computations": [{"validation_passed": item.get("validation_passed"),
                                         "formula_source_ids": item.get("formula_source_ids") or [],
                                         "input_fact_ids": item.get("input_fact_ids") or [],
                                         "normalized_formula": item.get("normalized_formula"),
                                         "output_manifest": item.get("output_manifest")}
                                        for item in final.get("computations", [])],
                       "sources": [{"id": source.get("evidence_id"), "document": source.get("document"),
                                    "page": source.get("page"), "chunk_id": source.get("chunk_id"),
                                    "excerpt": str(source.get("excerpt") or "")[:3000]}
                                   for source in [*final.get("internal_sources", []), *final.get("figures", [])]],
                       "validation": final.get("validation"), "stop_reason": final.get("stop_reason"),
                       "seconds": round(time.monotonic() - started, 3)}
            except Exception as exc:
                row = {"id": case["id"], "category": case["category"], "run_id": None,
                       "turn1_run_id": None, "turn1_status": "http_error", "turn1_clarification": None,
                       "final_status": "http_error", "final_clarification": None, "visible_answer": "",
                       "error": f"{type(exc).__name__}: {exc}", "actions": [], "computations": [],
                       "sources": [], "validation": {}, "stop_reason": None,
                       "seconds": round(time.monotonic() - started, 3)}
            row["handled"], row["failure_reasons"] = assess(case, row)
            rows.append(row)
            output.write_text(json.dumps({"model": "qwen3:8b", "rows": rows}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
            print(f"{case['id']} {case['category']} {row['final_status']} handled={row['handled']} "
                  f"{row['seconds']}s {row['failure_reasons']}", flush=True)
    if collection.count() != 18976:
        raise SystemExit("KB count changed during stress run")
    latest = {row["id"]: row for row in rows}
    latencies = sorted(row["seconds"] for row in latest.values())
    print(json.dumps({"completed": len(latest), "handled": sum(row["handled"] for row in latest.values()),
                      "median_seconds": statistics.median(latencies) if latencies else None}, indent=2))


if __name__ == "__main__":
    main()
