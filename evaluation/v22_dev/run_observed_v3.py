"""One development-only replay of the already-observed V3 against frozen V22.

This is not an unseen evaluation or a replacement for the original V3 score.
No benchmark, source corpus, or product file is written by this script.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

HERE = Path(__file__).resolve().parent
NUMBER = re.compile(r"(?<![A-Za-z])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
TOKEN = re.compile(r"[A-Za-z]{4,}|[가-힣]{2,}")
STOP = {"from", "with", "that", "this", "when", "where", "which", "using", "source",
        "there", "they", "their", "should", "would", "could", "between", "internal"}


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def numerical_answer(answer: str, target: dict) -> bool:
    expected, tolerance = float(target["expected_value"]), float(target["tolerance"])
    present = any(math.isclose(float(value.group().replace(",", "")), expected,
                               abs_tol=tolerance, rel_tol=0) for value in NUMBER.finditer(answer))
    unit = str(target.get("expected_unit") or "")
    return present and (not unit or unit in {"dimensionless", "fraction", "score"} or
                        unit.casefold() in answer.casefold())


def claim_proxy(answer: str, claims: list[str]) -> float:
    # This intentionally conservative lexical diagnostic is NOT semantic adjudication.
    if not claims:
        return 1.0
    answer_tokens = {value.casefold() for value in TOKEN.findall(answer)} - STOP
    matches = []
    for claim in claims:
        terms = {value.casefold() for value in TOKEN.findall(claim)} - STOP
        matches.append(bool(terms and len(answer_tokens & terms) / len(terms) >= 0.5))
    return sum(matches) / len(matches)


def score(task: dict, state: dict) -> dict:
    answer = state.get("final_answer") or state.get("clarification_question") or ""
    sources = {source.get("evidence_id"): source for source in state.get("internal_sources") or []}
    citations = re.findall(r"\[(KB\d+|FIG\d+)\]", answer)
    cited_gold = any(any(source.get("document") == gold["document"] and
                             source.get("page") == gold["page"] for gold in task["gold_sources"])
                     for key in citations if (source := sources.get(key)))
    numerical = (all(numerical_answer(answer, target) for target in task["numeric_targets"])
                 if task["numeric_targets"] else None)
    calculations = [row for row in state.get("computations") or []
                    if row.get("validation_passed") and row.get("contract_validation_passed")]
    formula = task.get("formula_source") or {}
    formula_correct = (not formula.get("required") or any(
        any((source := sources.get(source_id)) and
            source.get("document") == formula.get("document") and
            source.get("page") == formula.get("page") and
            " ".join(str(formula.get("exact_formula_span") or "").split()).casefold() in
            " ".join(str(source.get("excerpt") or "").split()).casefold()
            for source_id in calc.get("formula_source_ids") or [])
        for calc in calculations))
    validation = state.get("validation") or {}
    unsupported = sum(int(validation.get(key) or 0) for key in (
        "unsupported_citation_claim_count", "unsupported_numeric_claim_count",
        "unsupported_engineering_claim_count", "engineering_contradiction_count"))
    grounded = (not task.get("citation_required_for_agent") or cited_gold)
    coverage = claim_proxy(answer, task.get("required_claims") or [])
    if task["numeric_targets"]:
        proxy_success = bool(numerical and calculations and formula_correct and grounded and
                             state.get("status") == "achieved")
    elif task.get("answerable"):
        proxy_success = bool(state.get("status") == "achieved" and grounded and coverage >= 0.5)
    else:
        proxy_success = bool(state.get("run_status") in {"stopped", "waiting_for_user_input"} and
                             not calculations and unsupported == 0)
    actions = [item.get("action_type") for item in state.get("action_history") or []]
    return {"task_id": task["task_id"], "category": task["category"],
            "question_language": task["question_language"], "multi_goal": task["multi_goal"],
            "run_status": state.get("run_status"), "status": state.get("status"),
            "action_sequence": actions, "python_calls": state.get("python_calls_total", 0),
            "numerical_correct": numerical, "formula_source_correct": formula_correct,
            "cited_gold_page": cited_gold, "claim_coverage_lexical_proxy": coverage,
            "hallucination_free_validator_proxy": unsupported == 0,
            "unnecessary_refusal_proxy": bool(task.get("answerable") and not answer.strip() or
                                              task.get("answerable") and state.get("status") != "achieved"),
            "goal_success_deterministic_proxy": proxy_success, "answer": answer,
            "run_id": state.get("run_id"), "validation": validation,
            "required_goals": (state.get("telemetry") or {}).get("required_goals")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if actual != args.product_sha:
        raise SystemExit(f"Frozen product SHA mismatch: {actual}")
    if not os.getenv("DATA_DIR"):
        raise SystemExit("DATA_DIR must name the existing production data directory")
    import chromadb
    from app.core.config import get_settings
    from app.main import app
    if get_settings().retrieval_mode != "hybrid":
        raise SystemExit("RETRIEVAL_MODE must be hybrid")
    db_path = Path(os.environ["DATA_DIR"]).resolve() / "vector_db"
    if not (db_path / "chroma.sqlite3").is_file():
        raise SystemExit("Existing ChromaDB was not found; refusing to create one")
    collection = chromadb.PersistentClient(path=str(db_path)).get_collection("petroleum_knowledge")
    if collection.count() != 18976:
        raise SystemExit("Production KB must contain exactly 18976 chunks")
    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    if len(benchmark["primary_tasks"]) != 36 or len(benchmark["resume_probes"]) != 4:
        raise SystemExit("Observed V3 catalog size mismatch")
    output = HERE / "observed_v3_results.json"
    if output.exists():
        raise SystemExit("Observed V3 has already been started; do not rerun it")
    result = {"label": "Observed V3 development regression; not unseen final evaluation",
              "product_sha": actual, "benchmark_path": str(args.benchmark.resolve()),
              "cases": [], "resume_probes": []}
    save(output, result)
    with TestClient(app) as client:
        def poll(run_id: str) -> dict:
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                response = client.get(f"/api/research/goal-runs/{run_id}")
                response.raise_for_status()
                state = response.json()
                if state["run_status"] in {"completed", "stopped", "failed", "canceled",
                                           "waiting_for_user_input"}:
                    return state
                time.sleep(1)
            return {"run_id": run_id, "run_status": "timeout", "status": "failed"}

        for task in benchmark["primary_tasks"]:
            started = time.monotonic()
            try:
                created = client.post("/api/research/goal-runs/from-message",
                                      json={"message": task["question"], "model": "qwen3:8b"})
                created.raise_for_status()
                state = poll(created.json()["run_id"])
                row = score(task, state)
                row["raw_run"] = state
            except Exception as exc:
                row = {"task_id": task["task_id"], "technical_error": f"{type(exc).__name__}: {exc}"}
            row["latency_seconds"] = round(time.monotonic() - started, 3)
            result["cases"].append(row)
            save(output, result)
            print(task["task_id"], row.get("status"), row["latency_seconds"], flush=True)

        for probe in benchmark["resume_probes"]:
            started = time.monotonic()
            try:
                created = client.post("/api/research/goal-runs/from-message",
                                      json={"message": probe["turn1"], "model": "qwen3:8b"})
                created.raise_for_status()
                run_id = created.json()["run_id"]
                first = poll(run_id)
                second = None
                if first["run_status"] == "waiting_for_user_input":
                    resumed = client.post(f"/api/research/goal-runs/{run_id}/resume",
                                          json={"message": probe["turn2"]})
                    resumed.raise_for_status()
                    second = poll(run_id)
                row = {"probe_id": probe["probe_id"], "run_id": run_id,
                       "first_state": first, "second_state": second,
                       "same_run": bool(second and second.get("run_id") == run_id),
                       "final_completion": bool(second and second.get("status") == "achieved" and
                                                second.get("run_status") == "completed")}
            except Exception as exc:
                row = {"probe_id": probe["probe_id"], "technical_error": f"{type(exc).__name__}: {exc}"}
            row["latency_seconds"] = round(time.monotonic() - started, 3)
            result["resume_probes"].append(row)
            save(output, result)
            print(probe["probe_id"], row.get("final_completion"), row["latency_seconds"], flush=True)

    rows = result["cases"]
    numeric = [row for row in rows if row.get("numerical_correct") is not None]
    def rate(key: str, selected: list[dict] = rows) -> float:
        return sum(bool(row.get(key)) for row in selected) / len(selected) if selected else 0.0
    result["summary"] = {
        "task_count": len(rows), "numeric_count": len(numeric),
        "goal_success_deterministic_proxy": rate("goal_success_deterministic_proxy"),
        "claim_coverage_lexical_proxy": statistics.mean(row.get("claim_coverage_lexical_proxy", 0) for row in rows),
        "hallucination_free_validator_proxy": rate("hallucination_free_validator_proxy"),
        "numerical_accuracy": rate("numerical_correct", numeric),
        "direct_goal_success_proxy": rate("goal_success_deterministic_proxy", [r for r in rows if r.get("category") == "direct_calculation"]),
        "user_formula_goal_success_proxy": rate("goal_success_deterministic_proxy", [r for r in rows if r.get("category") == "user_formula"]),
        "kb_formula_retrieve_calculate": sum(r.get("category") == "kb_formula" and
            "retrieve" in r.get("action_sequence", []) and "calculate" in r.get("action_sequence", [])
            for r in rows),
        "unnecessary_refusals_proxy": sum(bool(r.get("unnecessary_refusal_proxy")) for r in rows),
        "cross_language_goal_success_proxy": sum(bool(r.get("goal_success_deterministic_proxy"))
            for r in rows if r.get("question_language") == "ko"),
        "multi_goal_success_proxy": sum(bool(r.get("goal_success_deterministic_proxy"))
            for r in rows if r.get("multi_goal")),
        "resume_final_completion": sum(bool(r.get("final_completion")) for r in result["resume_probes"]),
    }
    save(output, result)


if __name__ == "__main__":
    main()
