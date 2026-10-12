"""One reserved autonomous product run per unchanged frozen question."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

import requests

from common import ROOT, assert_frozen, read_json, save_json


TERMINAL = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}
TASKS = read_json(ROOT / "benchmark.json")["tasks"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def poll(base: str, row: dict, path) -> None:
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        response = requests.get(f"{base}/api/research/goal-runs/{row['run_id']}", timeout=45)
        response.raise_for_status()
        run = response.json()
        if run.get("run_status") in TERMINAL:
            row["run"] = run
            row["answer"] = run.get("final_answer", "")
            row["actual_model"] = "qwen3:8b"
            row["run_status"] = run.get("run_status")
            row["status"] = "completed"
            row["finished_at"] = now()
            row["latency_seconds"] = (round(time.perf_counter() - row.pop("_started_perf"), 3)
                                      if "_started_perf" in row else round(
                (datetime.now(timezone.utc) - datetime.fromisoformat(row["attempted_at"])).total_seconds(), 3))
            save_json(path, row)
            return
        time.sleep(2)
    row["status"] = "poll_deadline_exceeded"
    row["error"] = "existing run did not reach terminal/waiting state; no replacement run created"
    save_json(path, row)
    raise TimeoutError(row["error"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", required=True)
    args = parser.parse_args()
    assert_frozen()
    folder = ROOT / "raw" / "v20_1_agent"
    for index, task in enumerate(TASKS, start=1):
        path = folder / f"{task['task_id']}.json"
        if path.exists():
            row = read_json(path)
            if row.get("run_id") and not row.get("run"):
                print(f"{index}/24 {task['task_id']}: poll existing {row['run_id']}", flush=True)
                poll(args.api_url, row, path)
            else:
                print(f"{index}/24 {task['task_id']}: already attempted; skip", flush=True)
            continue
        row = {"task_id": task["task_id"], "question": task["question"], "system": "v20_1_agent",
               "attempt_count": 1, "attempted_at": now(), "status": "attempted"}
        save_json(path, row)  # reservation precedes the sole POST
        started = time.perf_counter()
        try:
            response = requests.post(
                f"{args.api_url}/api/research/goal-runs/from-message",
                json={"message": task["question"], "model": "qwen3:8b"}, timeout=45,
            )
            row["start_http_status"] = response.status_code
            if not response.ok:
                row["error_body"] = response.text[:1000]
            response.raise_for_status()
            row["run_id"] = response.json()["run_id"]
            save_json(path, row)
            row["_started_perf"] = started
            poll(args.api_url, row, path)
        except Exception as error:
            if row.get("status") != "completed":
                row.pop("_started_perf", None)
                row["status"] = "error"
                row["error"] = f"{type(error).__name__}: {error}"
                row["finished_at"] = now()
                row["latency_seconds"] = round(time.perf_counter() - started, 3)
                save_json(path, row)
            print(f"{index}/24 {task['task_id']}: {row['status']} (NO RETRY)", flush=True)
            if not row.get("run_id"):
                raise RuntimeError("unowned POST outcome; stop rather than risk a second run") from error
        else:
            print(f"{index}/24 {task['task_id']}: {row['run_status']} {row['latency_seconds']}s", flush=True)


if __name__ == "__main__":
    main()
