"""Three isolated two-turn V18 runs; never starts a replacement run on failure."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent
TASKS = json.loads((ROOT / "resume_suite.json").read_text(encoding="utf-8"))["tasks"]
TERMINAL = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def save(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def poll(base: str, run_id: str) -> dict:
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        response = requests.get(f"{base}/api/research/goal-runs/{run_id}", timeout=45)
        response.raise_for_status()
        run = response.json()
        if run.get("run_status") in TERMINAL:
            return run
        time.sleep(2)
    raise TimeoutError("run did not reach a terminal/waiting status; no retry")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    args = parser.parse_args()
    for task in TASKS:
        path = ROOT / "raw" / "resume_suite" / f"{task['task_id']}.json"
        if path.exists():
            print(task["task_id"], "already attempted; skip", flush=True)
            continue
        row = {"task_id": task["task_id"], "attempt_count": 1,
               "attempted_at": datetime.now(timezone.utc).isoformat(), "status": "attempted"}
        save(path, row)
        started = time.perf_counter()
        try:
            response = requests.post(
                f"{args.api_url}/api/research/goal-runs/from-message",
                json={"message": task["turn_1"], "model": "qwen3:8b"}, timeout=45,
            )
            response.raise_for_status()
            row["run_id"] = response.json()["run_id"]
            save(path, row)
            row["turn_1_run"] = poll(args.api_url, row["run_id"])
            save(path, row)
            if row["turn_1_run"]["run_status"] == "waiting_for_user_input":
                response = requests.post(
                    f"{args.api_url}/api/research/goal-runs/{row['run_id']}/resume",
                    json={"message": task["turn_2"]}, timeout=45,
                )
                response.raise_for_status()
                row["turn_2_run"] = poll(args.api_url, row["run_id"])
                row["status"] = "completed"
            else:
                row["status"] = "did_not_wait"
        except Exception as error:
            row["status"] = "error"
            row["error"] = f"{type(error).__name__}: {error}"
        row["latency_seconds"] = round(time.perf_counter() - started, 3)
        row["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(path, row)
        print(task["task_id"], row["status"], row["latency_seconds"], flush=True)


if __name__ == "__main__":
    main()
