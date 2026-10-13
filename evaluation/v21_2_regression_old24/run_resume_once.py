"""The three unchanged observed two-turn cases, one start/resume each."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone

import requests

from run_once import HERE, REPO, PRODUCT_SHA, TERMINAL, save


SUITE_REF = "eval/v20-1-poster-reeval:evaluation/v20_1_poster_reeval/resume_suite.json"
SUITE_SHA256 = "00ff41b1e4bf301c3047146aaad1ad1b64743725dfbfc5b1f86e8079aa5232ee"
BASE = "http://127.0.0.1:8002"


def poll(run_id: str) -> dict:
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        response = requests.get(f"{BASE}/api/research/goal-runs/{run_id}", timeout=45)
        response.raise_for_status()
        run = response.json()
        if run.get("run_status") in TERMINAL:
            return run
        time.sleep(2)
    raise TimeoutError("existing run did not finish; no replacement allowed")


def main() -> None:
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip() != PRODUCT_SHA:
        raise RuntimeError("product SHA differs from freeze")
    blob = subprocess.check_output(["git", "show", SUITE_REF], cwd=REPO)
    if hashlib.sha256(blob).hexdigest() != SUITE_SHA256:
        raise RuntimeError("observed resume suite changed")
    tasks = json.loads(blob)["tasks"]
    if len(tasks) != 3:
        raise RuntimeError("resume denominator changed")
    for task in tasks:
        path = HERE / "raw" / "resume_suite" / f"{task['task_id']}.json"
        if path.exists():
            print(task["task_id"], "already attempted; skip", flush=True)
            continue
        row = {"task_id": task["task_id"], "product_sha": PRODUCT_SHA, "attempt_count": 1,
               "attempted_at": datetime.now(timezone.utc).isoformat(), "status": "attempted"}
        save(path, row)
        started = time.monotonic()
        try:
            response = requests.post(f"{BASE}/api/research/goal-runs/from-message",
                                     json={"message": task["turn_1"], "model": "qwen3:8b"}, timeout=45)
            response.raise_for_status()
            row["run_id"] = response.json()["run_id"]
            save(path, row)
            row["turn_1_run"] = poll(row["run_id"])
            save(path, row)
            if row["turn_1_run"]["run_status"] == "waiting_for_user_input":
                response = requests.post(f"{BASE}/api/research/goal-runs/{row['run_id']}/resume",
                                         json={"message": task["turn_2"]}, timeout=45)
                response.raise_for_status()
                row["turn_2_run"] = poll(row["run_id"])
                row["status"] = "completed"
            else:
                row["status"] = "did_not_wait"
        except Exception as error:
            row.update(status="error", error=f"{type(error).__name__}: {error}")
        row["latency_seconds"] = round(time.monotonic() - started, 3)
        row["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(path, row)
        print(task["task_id"], row["status"], row["latency_seconds"], flush=True)


if __name__ == "__main__":
    main()
