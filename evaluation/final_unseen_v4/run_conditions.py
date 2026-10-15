"""One-shot frozen V4 Agent or local Qwen closed-book execution.

Every task is journaled once. An interrupted in-flight task requires inspection;
the script never silently repeats it. The catalog and frozen product are checked first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FROZEN_PRODUCT = "62e5c36f3d66e25addc8a2c37b63af12e2636e78"
DONE = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}
BASELINE_SYSTEM = (
    "You are answering a petroleum-engineering user directly. Use only the visible "
    "conversation; you have no internal documents, retrieval, browser, Python, or tools. "
    "Answer every requested part accurately. If a required formula or input is unknown, "
    "say so or ask for it. Do not invent citations, sources, or numerical results."
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, payload: dict) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=path.stem + "-", suffix=".tmp", delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def preflight(condition: str) -> tuple[dict, str]:
    if os.environ.get("RETRIEVAL_MODE") != "hybrid" or os.environ.get("WEB_FETCH_ENABLED") != "0":
        raise RuntimeError("Require hybrid retrieval and WEB_FETCH_ENABLED=0")
    catalog = HERE / "v4_catalog.json"
    actual = digest(catalog)
    expected = (HERE / "v4_catalog.sha256").read_text(encoding="ascii").split()[0]
    if actual != expected:
        raise RuntimeError("Sealed V4 catalog hash mismatch")
    if not (HERE / "PRECHECK.md").is_file() or not (HERE / "V4_SCORING_RUBRIC.md").is_file():
        raise RuntimeError("Precheck or fixed rubric missing")
    for args in (["git", "diff", "--quiet", FROZEN_PRODUCT, "HEAD", "--", "backend", "frontend"],
                 ["git", "diff", "--quiet", "--", "backend", "frontend"],
                 ["git", "diff", "--cached", "--quiet", "--", "backend", "frontend"]):
        if subprocess.run(args, cwd=ROOT, check=False).returncode != 0:
            raise RuntimeError("Frozen product files differ from the product SHA")
    data = json.loads(catalog.read_text(encoding="utf-8"))
    if len(data["tasks"]) != 60 or data["frozen_product_sha"] != FROZEN_PRODUCT:
        raise RuntimeError("Unexpected sealed catalog")

    sys.path.insert(0, str(ROOT / "backend"))
    from app.core.config import Settings
    from app.services.goal_message_parser import GoalMessageRequest, parse_goal_message

    settings = Settings()
    if settings.retrieval_mode != "hybrid" or settings.web_fetch_enabled:
        raise RuntimeError("Runtime settings are not hybrid / web-off")
    for task in data["tasks"]:
        request = parse_goal_message(GoalMessageRequest(message=task["prompt"], model="qwen3:8b"))
        if request.use_external:
            raise RuntimeError(f"Sealed task unexpectedly requests web: {task['id']}")
    if condition == "agent":
        sqlite = Path(os.environ["DATA_DIR"]).resolve() / "vector_db" / "chroma.sqlite3"
        if not sqlite.is_file():
            raise RuntimeError("Existing production KB missing")
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        collection = chromadb.PersistentClient(
            path=str(sqlite.parent),
            settings=ChromaSettings(anonymized_telemetry=settings.anonymized_telemetry),
        ).get_collection("petroleum_knowledge")
        if collection.count() != 18976:
            raise RuntimeError("Existing KB is not 18,976 chunks")
    return data, actual


def poll(client, run_id: str, timeout: float = 240) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"/api/research/goal-runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run["run_status"] in DONE:
            return run
        if time.monotonic() >= deadline:
            return {"run_id": run_id, "run_status": "timeout", "error": "bounded_240_second_timeout"}
        time.sleep(0.6)


def execute_agent(task: dict, client, checkpoint: dict, output: Path) -> dict:
    started = time.monotonic()
    run_id = None
    first = {}
    final = {}
    try:
        response = client.post("/api/research/goal-runs/from-message",
                               json={"message": task["prompt"], "model": "qwen3:8b"})
        response.raise_for_status()
        run_id = response.json()["run_id"]
        checkpoint["inflight"]["run_id"] = run_id
        save(output, checkpoint)
        first = poll(client, run_id)
        final = first
        if task["follow_up"] is not None and first["run_status"] == "waiting_for_user_input":
            response = client.post(f"/api/research/goal-runs/{run_id}/resume",
                                   json={"message": task["follow_up"]})
            response.raise_for_status()
            final = poll(client, run_id)
    except Exception as exc:
        final = {"run_status": "harness_error", "error": f"{type(exc).__name__}: {exc}"}
    return {"id": task["id"], "category": task["category"], "language": task["language"],
            "run_id": run_id, "first_turn_run_id": first.get("run_id"),
            "first_turn_status": first.get("run_status"),
            "first_turn_clarification": first.get("clarification_question"),
            "follow_up_sent": task["follow_up"] is not None and first.get("run_status") == "waiting_for_user_input",
            "final_status": final.get("run_status"),
            "final_answer": final.get("final_answer"),
            "final_clarification": final.get("clarification_question"),
            "error": final.get("error"),
            "goal_status": final.get("goal_status"), "stop_reason": final.get("stop_reason"),
            "action_history": final.get("action_history", []),
            "computations": final.get("computations", []),
            "internal_sources": final.get("internal_sources", []),
            "external_sources": final.get("external_sources", []),
            "validation": final.get("validation"), "criteria": final.get("criteria"),
            "telemetry": final.get("telemetry"),
            "seconds": round(time.monotonic() - started, 3), "completed_at": utc_now()}


def qwen_turn(client, messages: list[dict[str, str]]) -> tuple[str, dict, float]:
    started = time.monotonic()
    response = client.post("http://127.0.0.1:11434/api/chat", json={
        "model": "qwen3:8b", "messages": messages, "stream": False,
        "think": False, "keep_alive": "30m",
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1024},
    })
    response.raise_for_status()
    payload = response.json()
    return (payload.get("message", {}).get("content", "").strip(),
            {"done_reason": payload.get("done_reason"), "eval_count": payload.get("eval_count")},
            round(time.monotonic() - started, 3))


def execute_closed_book(task: dict, client) -> dict:
    started = time.monotonic()
    first_answer = ""
    final_answer = ""
    first_seconds = None
    second_seconds = None
    metadata = {}
    error = None
    try:
        messages = [{"role": "system", "content": BASELINE_SYSTEM},
                    {"role": "user", "content": task["prompt"]}]
        first_answer, first_metadata, first_seconds = qwen_turn(client, messages)
        final_answer, metadata = first_answer, first_metadata
        if task["follow_up"] is not None:
            messages.extend([{"role": "assistant", "content": first_answer},
                             {"role": "user", "content": task["follow_up"]}])
            final_answer, metadata, second_seconds = qwen_turn(client, messages)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {"id": task["id"], "category": task["category"], "language": task["language"],
            "first_answer": first_answer, "final_answer": final_answer,
            "first_seconds": first_seconds, "second_seconds": second_seconds,
            "seconds": round(time.monotonic() - started, 3), "metadata": metadata,
            "error": error, "completed_at": utc_now()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("condition", choices=["agent", "closed_book"])
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--validate-app", action="store_true",
                        help="initialize the Agent app without submitting any V4 prompt")
    args = parser.parse_args()
    catalog, catalog_hash = preflight(args.condition)
    if args.validate_app:
        if args.condition != "agent":
            raise RuntimeError("--validate-app applies only to the Agent condition")
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app):
            print("Agent app initialized with the preflight Chroma settings; no V4 task submitted")
        return
    if args.validate_only:
        print(json.dumps({"condition": args.condition, "tasks": len(catalog["tasks"]),
                          "catalog_sha256": catalog_hash, "web": "off", "product": FROZEN_PRODUCT}))
        return
    output = HERE / ("agent_results.json" if args.condition == "agent" else "qwen_closed_book_results.json")
    checkpoint = (json.loads(output.read_text(encoding="utf-8")) if output.exists() else
                  {"condition": args.condition, "model": "qwen3:8b", "catalog_sha256": catalog_hash,
                   "frozen_product_sha": FROZEN_PRODUCT, "started_at": utc_now(),
                   "rows": [], "inflight": None})
    if (checkpoint["catalog_sha256"] != catalog_hash or checkpoint["condition"] != args.condition
            or checkpoint.get("inflight")):
        raise RuntimeError("Mismatched checkpoint or interrupted in-flight task; inspect before resuming")
    completed = {row["id"] for row in checkpoint["rows"]}
    if len(completed) != len(checkpoint["rows"]):
        raise RuntimeError("Duplicate one-shot result rows")

    if args.condition == "agent":
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as client:
            for task in catalog["tasks"]:
                if task["id"] in completed:
                    continue
                checkpoint["inflight"] = {"id": task["id"], "started_at": utc_now()}
                save(output, checkpoint)
                row = execute_agent(task, client, checkpoint, output)
                checkpoint["rows"].append(row)
                checkpoint["inflight"] = None
                save(output, checkpoint)
                print(f"AGENT {task['id']} {row['final_status']} {row['seconds']}s", flush=True)
    else:
        import httpx
        with httpx.Client(timeout=600) as client:
            for task in catalog["tasks"]:
                if task["id"] in completed:
                    continue
                checkpoint["inflight"] = {"id": task["id"], "started_at": utc_now()}
                save(output, checkpoint)
                row = execute_closed_book(task, client)
                checkpoint["rows"].append(row)
                checkpoint["inflight"] = None
                save(output, checkpoint)
                print(f"CLOSED_BOOK {task['id']} {'ERROR' if row['error'] else 'done'} {row['seconds']}s", flush=True)
    checkpoint["finished_at"] = utc_now()
    save(output, checkpoint)
    if len(checkpoint["rows"]) != 60:
        raise RuntimeError("One-shot result is incomplete")
    if args.condition == "agent":
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from app.core.config import Settings
        sqlite = Path(os.environ["DATA_DIR"]).resolve() / "vector_db" / "chroma.sqlite3"
        if chromadb.PersistentClient(path=str(sqlite.parent), settings=ChromaSettings(
                anonymized_telemetry=Settings().anonymized_telemetry)).get_collection(
                    "petroleum_knowledge").count() != 18976:
            raise RuntimeError("KB count changed after one-shot Agent execution")


if __name__ == "__main__":
    main()
