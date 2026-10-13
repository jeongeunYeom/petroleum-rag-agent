"""One product execution per frozen primary question; only same-run polling may resume."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from uuid import uuid4

import requests

from common import HERE, PRODUCT_SHA, TERMINAL, frozen_assets, frozen_product, load, now, save


def poll(base: str, row: dict, path: Path) -> None:
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        response = requests.get(f"{base}/api/research/goal-runs/{row['run_id']}",timeout=45)
        response.raise_for_status()
        run = response.json()
        if run.get("run_status") in TERMINAL:
            row.update(run=run,answer=run.get("final_answer") or run.get("clarification_question") or "",
                       run_status=run.get("run_status"),status="completed",finished_at=now(),
                       latency_seconds=round(time.monotonic()-row["started_monotonic"],3))
            row.pop("started_monotonic",None)
            save(path,row)
            return
        time.sleep(2)
    raise TimeoutError(f"same run {row['run_id']} did not finish within polling window")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url",default="http://127.0.0.1:8002")
    args = parser.parse_args()
    frozen_assets()
    frozen_product()
    tasks = load("benchmark.json")["primary_tasks"]
    for index, task in enumerate(tasks,1):
        path = HERE / "raw" / "v21_2_agent" / f"{task['task_id']}.json"
        if path.exists():
            row = load(str(path.relative_to(HERE)))
            if row.get("run_id") and row.get("status") != "completed":
                poll(args.api_url,row,path)
                print(f"{index}/36 {task['task_id']}: same-run polling completed",flush=True)
            else:
                print(f"{index}/36 {task['task_id']}: already reserved; no replacement",flush=True)
            continue
        row = {"task_id":task["task_id"],"question":task["question"],"system":"v21_2_agent",
               "product_sha":PRODUCT_SHA,"attempt_id":str(uuid4()),"attempt_count":1,
               "attempted_at":now(),"status":"reserved","started_monotonic":time.monotonic()}
        save(path,row)
        try:
            response = requests.post(f"{args.api_url}/api/research/goal-runs/from-message",
                                     json={"message":task["question"],"model":"qwen3:8b"},timeout=45)
            row["start_http_status"] = response.status_code
            response.raise_for_status()
            row["run_id"] = response.json()["run_id"]
            row["status"] = "running"
            save(path,row)
            poll(args.api_url,row,path)
            print(f"{index}/36 {task['task_id']}: {row['run_status']} {row['latency_seconds']}s",flush=True)
        except Exception as error:
            row.update(status="error" if not row.get("run_id") else "poll_error",
                       error=f"{type(error).__name__}: {error}",finished_at=now())
            save(path,row)
            print(f"{index}/36 {task['task_id']}: {row['status']} (NO NEW RUN)",flush=True)


if __name__ == "__main__":
    main()
