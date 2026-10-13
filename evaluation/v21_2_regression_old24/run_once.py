"""Run the immutable observed 24-task set once against the frozen V21.2 product."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PRODUCT_SHA = "f5182b8ae2907452e1c53373055e66c5182c9b90"
BENCHMARK_SHA256 = "6913d38c697e00cc4601db3d53e3e4270350520600de0d9e9ac2fc25169e2b1f"
BENCHMARK_REF = "eval/v20-1-poster-reeval:evaluation/v20_1_poster_reeval/benchmark.json"
TERMINAL = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def save(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


def poll(base: str, row: dict, path: Path) -> None:
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        response = requests.get(f"{base}/api/research/goal-runs/{row['run_id']}", timeout=45)
        response.raise_for_status()
        run = response.json()
        if run.get("run_status") in TERMINAL:
            row.update(run=run, answer=run.get("final_answer", ""),
                       run_status=run.get("run_status"), status="completed",
                       finished_at=datetime.now(timezone.utc).isoformat(),
                       latency_seconds=round(time.monotonic() - row["started_monotonic"], 3))
            row.pop("started_monotonic", None)
            save(path, row)
            return
        time.sleep(2)
    raise TimeoutError(f"{row['run_id']}: existing run did not finish before deadline")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8002")
    args = parser.parse_args()
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if current != PRODUCT_SHA:
        raise RuntimeError("product SHA differs from the declared freeze")
    blob = subprocess.check_output(["git", "show", BENCHMARK_REF], cwd=REPO)
    if hashlib.sha256(blob).hexdigest() != BENCHMARK_SHA256:
        raise RuntimeError("observed benchmark bytes differ from the immutable reference")
    tasks = json.loads(blob)["tasks"]
    if len(tasks) != 24 or len({task["task_id"] for task in tasks}) != 24:
        raise RuntimeError("observed task denominator changed")
    for index, task in enumerate(tasks, 1):
        path = HERE / "raw" / f"{task['task_id']}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("run_id") and not row.get("run"):
                poll(args.api_url, row, path)
            else:
                print(f"{index}/24 {task['task_id']}: already attempted; skip", flush=True)
            continue
        row = {"task_id": task["task_id"], "question": task["question"],
               "system": "v21_2_agent", "product_sha": PRODUCT_SHA,
               "attempt_count": 1, "attempted_at": datetime.now(timezone.utc).isoformat(),
               "status": "attempted", "started_monotonic": time.monotonic()}
        save(path, row)  # Reserve the task before the sole POST.
        try:
            response = requests.post(f"{args.api_url}/api/research/goal-runs/from-message",
                                     json={"message": task["question"], "model": "qwen3:8b"}, timeout=45)
            row["start_http_status"] = response.status_code
            response.raise_for_status()
            row["run_id"] = response.json()["run_id"]
            save(path, row)
            poll(args.api_url, row, path)
            print(f"{index}/24 {task['task_id']}: {row['run_status']} {row['latency_seconds']}s", flush=True)
        except Exception as error:
            if row.get("status") != "completed":
                row.update(status="error", error=f"{type(error).__name__}: {error}",
                           finished_at=datetime.now(timezone.utc).isoformat())
                save(path, row)
            print(f"{index}/24 {task['task_id']}: {row['status']} (NO RETRY)", flush=True)
            if not row.get("run_id"):
                raise RuntimeError("unowned POST outcome; no second run allowed") from error


if __name__ == "__main__":
    main()
