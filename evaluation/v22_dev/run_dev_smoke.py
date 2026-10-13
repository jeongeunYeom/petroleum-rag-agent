"""Run the fresh, non-frozen V22 development cases against the local product.

Requires DATA_DIR to point at the existing production data parent. This script
never ingests or mutates ChromaDB and does not invoke an external provider.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--rerun", action="store_true", help="rerun cases already recorded")
    args = parser.parse_args()
    if not os.getenv("DATA_DIR"):
        raise SystemExit("DATA_DIR must point to the existing production data directory")
    if os.getenv("RETRIEVAL_MODE") != "hybrid":
        raise SystemExit("RETRIEVAL_MODE must be hybrid")

    import chromadb
    from fastapi.testclient import TestClient
    from app.main import app

    data = Path(os.environ["DATA_DIR"]).resolve()
    collection = chromadb.PersistentClient(path=str(data / "vector_db")).get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        raise SystemExit(f"Existing KB count is {collection.count()}, expected 18976")
    catalog = json.loads((HERE / "real_kb_smoke.json").read_text(encoding="utf-8"))
    cases = [*catalog["cases"], *catalog["resume_probes"]]
    if args.case_id:
        cases = [case for case in cases if case["id"] == args.case_id]
        if not cases:
            raise SystemExit("Unknown case ID")

    output_path = HERE / "smoke_results.json"
    results = (json.loads(output_path.read_text(encoding="utf-8")).get("cases", [])
               if output_path.exists() else [])
    if args.rerun:
        selected_ids = {case["id"] for case in cases}
        results = [row for row in results if row["id"] not in selected_ids]
    else:
        completed_ids = {row["id"] for row in results}
        cases = [case for case in cases if case["id"] not in completed_ids]
    with TestClient(app) as client:
        def poll(run_id: str) -> dict:
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                response = client.get(f"/api/research/goal-runs/{run_id}")
                response.raise_for_status()
                payload = response.json()
                if payload["run_status"] in {"completed", "stopped", "failed", "canceled",
                                             "waiting_for_user_input"}:
                    return payload
                time.sleep(1)
            return {"run_id": run_id, "run_status": "timeout", "error": "bounded_timeout"}

        for case in cases:
            started = time.monotonic()
            response = client.post("/api/research/goal-runs/from-message",
                                   json={"message": case["message"], "model": "qwen3:8b"})
            response.raise_for_status()
            run_id = response.json()["run_id"]
            turn1 = poll(run_id)
            final = turn1
            if "reply" in case and turn1["run_status"] == "waiting_for_user_input":
                resumed = client.post(f"/api/research/goal-runs/{run_id}/resume",
                                      json={"message": case["reply"]})
                resumed.raise_for_status()
                final = poll(run_id)
            row = {
                "id": case["id"], "category": case.get("category", "resume"),
                "run_id": run_id, "elapsed_seconds": round(time.monotonic() - started, 3),
                "turn1_status": turn1["run_status"],
                "turn1_clarification": turn1.get("clarification_question"),
                "turn1_sources": [{"id": source.get("evidence_id"), "document": source.get("document"),
                                    "page": source.get("page"), "chunk_id": source.get("chunk_id"),
                                    "excerpt": str(source.get("excerpt") or "")[:1400]}
                                   for source in turn1.get("internal_sources", [])],
                "turn1_telemetry": {key: value for key, value in (turn1.get("telemetry") or {}).items()
                                    if key in {"formula", "formula_execution_contract", "formula_variables_missing",
                                               "formula_execution_blockers", "formula_dependency_target",
                                               "clarification_candidate", "required_goals",
                                               "formula_definition_expansion_attempted",
                                               "formula_local_expansion_attempted", "formula_local_expansion_used",
                                               "formula_local_expansion_evidence_ids",
                                               "formula_pin_upgraded_with_context"}},
                "final_status": final["run_status"],
                "final_answer": final.get("final_answer"),
                "error": final.get("error"),
                "action_sequence": [item.get("action_type") for item in final.get("action_history", [])],
                "computations": [{"id": calc.get("computation_id"),
                                  "validation_passed": calc.get("validation_passed"),
                                  "formula_source_ids": calc.get("formula_source_ids"),
                                  "output_manifest": calc.get("output_manifest")}
                                 for calc in final.get("computations", [])],
                "sources": [{"id": source.get("evidence_id"), "document": source.get("document"),
                             "page": source.get("page"), "excerpt": str(source.get("excerpt") or "")[:500]}
                            for source in final.get("internal_sources", [])],
                "validation": final.get("validation"),
                "telemetry": {key: value for key, value in (final.get("telemetry") or {}).items()
                              if key in {"intent_route", "request_computation_class", "actionability_state",
                                         "formula_execution_ready", "formula_execution_blockers",
                                         "target_output_satisfied", "stop_rejected_actionable_work",
                                         "formula_execution_forced", "required_goals",
                                         "clarification_rejected_existing_fact"}},
            }
            results.append(row)
            output_path.write_text(json.dumps({"cases": results}, ensure_ascii=False,
                                              indent=2), encoding="utf-8")
            print(f"{case['id']} {row['final_status']} {row['elapsed_seconds']}s "
                  f"{','.join(row['action_sequence'])}", flush=True)


if __name__ == "__main__":
    main()
