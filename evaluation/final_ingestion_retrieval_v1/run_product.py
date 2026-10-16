"""Evaluation-only HTTP runner for the frozen autonomous product endpoint."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


TERMINAL = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def request_json(url: str, *, body: dict | None = None, timeout: float = 30) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8001/api")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--task-timeout", type=float, default=360)
    parser.add_argument("--id", action="append", default=[])
    args = parser.parse_args()
    tasks = json.loads(args.input.read_text(encoding="utf-8"))["tasks"]
    done: set[str] = set()
    if args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("response") and row["response"].get("run_status") in TERMINAL:
                    done.add(row["question_id"])
    for task in tasks:
        task_id = task["question_id"]
        if task_id in done or (args.id and task_id not in args.id):
            continue
        print(f"START {task_id}", flush=True)
        start = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        row = {"question_id": task_id, "question": task["question"], "started_at": started_at}
        try:
            response = request_json(
                f"{args.api_url}/research/goal-runs/from-message",
                body={"message": task["question"], "model": args.model},
                timeout=90,
            )
            run_id = response["run_id"]
            while response.get("run_status") not in TERMINAL:
                if time.monotonic() - start > args.task_timeout:
                    row["error"] = "poll_timeout_without_cancel"
                    break
                time.sleep(1.0)
                response = request_json(
                    f"{args.api_url}/research/goal-runs/{run_id}", timeout=30
                )
            row["response"] = response
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["elapsed_seconds"] = round(time.monotonic() - start, 3)
        row["completed_at"] = datetime.now(timezone.utc).isoformat()
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        result = row.get("response", {})
        print(
            f"END {task_id} {result.get('run_status', 'ERROR')} "
            f"{result.get('status', 'ERROR')} {row['elapsed_seconds']}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
