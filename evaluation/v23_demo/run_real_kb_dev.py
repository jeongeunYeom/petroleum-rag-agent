"""Run and conservatively score fresh V23 development tasks against local product.

This is not a final benchmark. It performs no ingestion or KB writes. Results are
checkpointed after every case so interrupted runs can resume without repeats.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
DONE = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}
NUMBER = re.compile(r"(?<![A-Za-z0-9])[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
CITATION = re.compile(r"\[(?:KB|FIG)\d+\]")


def answer_has_number(answer: str, target: float) -> bool:
    for match in NUMBER.finditer(answer):
        value = float(match.group().replace(",", ""))
        if abs(value - target) <= max(0.08, abs(target) * 0.005):
            return True
    return False


def assess(case: dict, row: dict) -> tuple[bool, list[str]]:
    failures: list[str] = []
    category = case.get("category", "resume")
    answer = row["final_answer"] or ""
    actions = row["actions"]
    calcs = [calc for calc in row["computations"] if calc["validation_passed"]]
    sources = row["sources"]
    source_ids = {source["id"] for source in sources}
    cited = {marker[1:-1] for marker in CITATION.findall(answer)}
    visible_answer = answer or row.get("final_clarification") or row.get("turn1_clarification") or ""
    if not visible_answer.strip():
        failures.append("blank_answer")
    if row["error"] or row["final_status"] in {"failed", "timeout", "http_error"}:
        failures.append("technical_error")
    if category in {"knowledge", "direct", "user_formula", "kb_formula", "multi_goal", "false_premise", "resume"} and row["final_status"] != "completed":
        failures.append("goal_not_completed")
    if any(marker in answer.lower() for marker in ("traceback", "keyerror:", "jsondecodeerror",
                                                      "chromadb.error", "connectionerror:")):
        failures.append("raw_error_leak")
    if cited - source_ids:
        failures.append("fabricated_citation_id")
    validation = row.get("validation") or {}
    if validation.get("citation_semantic_passed") is False or (validation.get("unsupported_citation_claim_count") or 0) > 0:
        failures.append("citation_semantic_unsupported")
    if (validation.get("unsupported_numeric_claim_count") or 0) > 0:
        failures.append("unsupported_numeric_claim")
    if (validation.get("engineering_contradiction_count") or 0) > 0:
        failures.append("engineering_contradiction")
    if category in {"knowledge", "kb_formula", "false_premise"} or case.get("source_document"):
        if not cited or not sources:
            failures.append("missing_kb_citation")
    if category in {"direct", "user_formula", "multi_goal"} and case.get("numeric"):
        if not calcs:
            failures.append("missing_validated_calculation")
        if "retrieve" in actions and category in {"direct", "user_formula"}:
            failures.append("unnecessary_retrieval")
    if category == "kb_formula":
        if not calcs:
            failures.append("missing_validated_calculation")
        if "retrieve" not in actions:
            failures.append("missing_formula_retrieval")
        grounded = False
        for calc in calcs:
            for source_id in calc["formula_source_ids"]:
                matched = next((source for source in sources if source["id"] == source_id), None)
                marker = case.get("formula_marker", "").replace(" ", "").casefold()
                if (matched and case["source_document"] in matched["document"] and
                        matched["page"] == case["source_page"] and
                        (not marker or marker in matched["excerpt"].replace(" ", "").casefold())):
                    grounded = True
        if not grounded:
            failures.append("formula_source_wrong_page_span_or_missing")
    for expected in case.get("numeric", []):
        if not answer_has_number(answer, expected):
            failures.append(f"final_numeric_missing_{expected}")
    if case.get("no_calculation") and calcs:
        failures.append("unsupported_calculation")
    if category == "unanswerable" and not any(term in answer.casefold() for term in
                                                ("확인할 수 없", "확인하지 못", "찾지 못", "검증할 수 없", "근거가 없",
                                                 "cannot verify", "not found", "did not establish",
                                                 "unverified", "unable to")):
        failures.append("unsupported_formula_not_disclaimed")
    if category == "false_premise":
        if not any(term.casefold() in answer.casefold() for term in case["reject_terms"]):
            failures.append("no_explicit_premise_rejection")
    if case.get("support_terms") and not any(term.casefold() in answer.casefold()
                                               for term in case["support_terms"]):
        failures.append("missing_expected_relation")
    if case.get("required_relation_terms") and not any(term.casefold() in answer.casefold()
                                                        for term in case["required_relation_terms"]):
        failures.append("missing_corrected_direction_or_equation")
    if category == "resume":
        if row["turn1_status"] != "waiting_for_user_input":
            failures.append("did_not_wait_for_missing_input")
        if row["turn1_run_id"] != row["run_id"]:
            failures.append("new_run_instead_of_resume")
        if not calcs:
            failures.append("no_validated_calc_after_resume")
        if row["final_status"] != "completed":
            failures.append("resume_not_completed")
    return not failures, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", choices=["knowledge", "direct", "user_formula", "kb_formula",
                                                 "multi_goal", "false_premise", "unanswerable", "resume"])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--retry-failed", action="store_true", help="append a new attempt for failed development cases")
    parser.add_argument("--case-id", help="run one development case")
    parser.add_argument("--force", action="store_true", help="append another attempt even if already handled")
    parser.add_argument("--catalog", default="real_kb_dev.json")
    parser.add_argument("--output", default="real_kb_dev_results.json")
    args = parser.parse_args()
    data_dir = os.getenv("DATA_DIR")
    if not data_dir:
        raise SystemExit("DATA_DIR must identify the existing production data parent")

    import chromadb
    from fastapi.testclient import TestClient
    from app.main import app

    db_path = Path(data_dir).resolve() / "vector_db"
    if not (db_path / "chroma.sqlite3").is_file():
        raise SystemExit("Existing ChromaDB not found; refusing to create one")
    collection = chromadb.PersistentClient(path=str(db_path)).get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        raise SystemExit("Unexpected Chroma count; refusing to run")
    catalog = json.loads((HERE / args.catalog).read_text(encoding="utf-8"))
    if len(catalog["cases"]) != 50 or len(catalog["resume_probes"]) != 10:
        raise SystemExit("Expected exactly 50 development tasks and 10 resume probes")
    cases = [*catalog["cases"], *catalog["resume_probes"]]
    if args.case_id:
        cases = [case for case in cases if case["id"] == args.case_id]
        if not cases:
            raise SystemExit("Unknown development case ID")
    if args.category:
        cases = [case for case in cases if case["category"] == args.category]
    if args.limit is not None:
        cases = cases[:args.limit]
    output = HERE / args.output
    rows = json.loads(output.read_text(encoding="utf-8"))["rows"] if output.exists() else []
    latest = {row["id"]: row for row in rows}
    case_by_id = {case["id"]: case for case in [*catalog["cases"], *catalog["resume_probes"]]}
    rescored = {row_id: assess(case_by_id[row_id], row)[0] for row_id, row in latest.items()}
    done = (set() if args.force else
            {row_id for row_id, handled in rescored.items() if handled}
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
            start = time.monotonic()
            try:
                response = client.post("/api/research/goal-runs/from-message",
                                       json={"message": case["message"], "model": "qwen3:8b"})
                response.raise_for_status()
                run_id = response.json()["run_id"]
                turn1 = poll(run_id)
                final = turn1
                if "reply" in case and turn1["run_status"] == "waiting_for_user_input":
                    response = client.post(f"/api/research/goal-runs/{run_id}/resume",
                                           json={"message": case["reply"]})
                    response.raise_for_status()
                    final = poll(run_id)
                row = {"id": case["id"], "category": case["category"], "run_id": run_id,
                       "turn1_run_id": turn1.get("run_id"), "turn1_status": turn1["run_status"],
                       "turn1_clarification": turn1.get("clarification_question"),
                       "final_status": final["run_status"], "final_answer": final.get("final_answer"),
                       "error": final.get("error"), "actions": [a.get("action_type") for a in final.get("action_history", [])],
                       "computations": [{"id": c.get("computation_id"), "validation_passed": c.get("validation_passed"),
                                         "formula_source_ids": c.get("formula_source_ids") or [],
                                         "output_manifest": c.get("output_manifest")}
                                        for c in final.get("computations", [])],
                       "sources": [{"id": s.get("evidence_id"), "document": s.get("document"),
                                    "page": s.get("page"), "excerpt": str(s.get("excerpt") or "")}
                                   for s in [*final.get("internal_sources", []), *final.get("figures", [])]],
                       "validation": final.get("validation"),
                       "goal_status": final.get("goal_status"),
                       "stop_reason": final.get("stop_reason"),
                       "unresolved_information": final.get("unresolved_information"),
                       "criteria": final.get("criteria"),
                       "action_history": final.get("action_history"),
                       "telemetry": final.get("telemetry"),
                       "seconds": round(time.monotonic() - start, 3)}
            except Exception as exc:
                row = {"id": case["id"], "category": case["category"], "run_id": None,
                       "turn1_run_id": None, "turn1_status": "http_error", "turn1_clarification": None,
                       "final_status": "http_error", "final_answer": "", "error": f"{type(exc).__name__}: {exc}",
                       "actions": [], "computations": [], "sources": [], "validation": {},
                       "seconds": round(time.monotonic() - start, 3)}
            row["handled"], row["failure_reasons"] = assess(case, row)
            rows.append(row)
            output.write_text(json.dumps({"model": "qwen3:8b", "rows": rows}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
            print(f"{case['id']} {row['final_status']} handled={row['handled']} "
                  f"{row['seconds']}s {row['failure_reasons']}", flush=True)
    if collection.count() != 18976:
        raise SystemExit("ChromaDB count changed unexpectedly")
    grouped = {}
    latest = {row["id"]: row for row in rows}
    for row_id, row in latest.items():
        row["handled"], row["failure_reasons"] = assess(case_by_id[row_id], row)
    for category in sorted({row["category"] for row in latest.values()}):
        subset = [row for row in latest.values() if row["category"] == category]
        grouped[category] = {"handled": sum(row["handled"] for row in subset), "total": len(subset),
                             "median_seconds": statistics.median(row["seconds"] for row in subset)}
    print(json.dumps(grouped, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
