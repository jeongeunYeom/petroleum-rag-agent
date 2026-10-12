"""Run each frozen question once; reservations prevent accidental retries."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parent
TASKS = json.loads((ROOT / "benchmark.json").read_text(encoding="utf-8"))["tasks"]
SYSTEM_TEXT = (
    "Answer the user's question accurately and concisely. "
    "Do not assume access to private documents or external tools."
)
TERMINAL = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def output_text(response: dict) -> str:
    return "\n".join(
        part.get("text", "")
        for item in response.get("output", [])
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    ).strip()


def run_qwen(task: dict, row: dict) -> None:
    response = requests.post(
        "http://127.0.0.1:11434/api/chat",
        json={
            "model": "qwen3:8b",
            "stream": False,
            "think": False,
            "messages": [
                {"role": "system", "content": SYSTEM_TEXT},
                {"role": "user", "content": task["question"]},
            ],
            "options": {"temperature": 0},
        },
        timeout=900,
    )
    row["http_status"] = response.status_code
    response.raise_for_status()
    data = response.json()
    row["answer"] = data.get("message", {}).get("content", "")
    row["usage"] = {k: data.get(k) for k in ("prompt_eval_count", "eval_count", "total_duration")}
    row["actual_model"] = data.get("model")


def run_gpt(task: dict, row: dict) -> None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": "gpt-5.4-mini-2026-03-17",
            "instructions": SYSTEM_TEXT,
            "input": task["question"],
            "temperature": 0,
            "store": False,
        },
        timeout=900,
    )
    row["http_status"] = response.status_code
    if not response.ok:
        row["error_body"] = response.text[:1000]
    response.raise_for_status()
    data = response.json()
    row["answer"] = output_text(data)
    row["usage"] = data.get("usage", {})
    row["actual_model"] = data.get("model")
    row["response_id"] = data.get("id")


def run_agent(task: dict, row: dict, base_url: str, path: Path) -> None:
    if row.get("run_id"):
        run_id = row["run_id"]
    else:
        response = requests.post(
            f"{base_url}/api/research/goal-runs/from-message",
            json={"message": task["question"], "model": "qwen3:8b"},
            timeout=45,
        )
        row["start_http_status"] = response.status_code
        if not response.ok:
            row["error_body"] = response.text[:1000]
        response.raise_for_status()
        run_id = response.json()["run_id"]
        row["run_id"] = run_id
        save(path, row)
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        response = requests.get(f"{base_url}/api/research/goal-runs/{run_id}", timeout=45)
        response.raise_for_status()
        data = response.json()
        if data.get("run_status") in TERMINAL:
            row["run"] = data
            row["answer"] = data.get("final_answer", "")
            row["actual_model"] = "qwen3:8b"
            row["run_status"] = data.get("run_status")
            return
        time.sleep(2)
    row["error"] = "poll_deadline_exceeded; run not restarted"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", choices=["qwen_closed_book", "v17_agent", "v18_agent", "gpt_reference"], required=True)
    parser.add_argument("--api-url")
    args = parser.parse_args()
    if args.system.endswith("_agent") and not args.api_url:
        parser.error("--api-url required for agent")
    folder = ROOT / "raw" / args.system
    for index, task in enumerate(TASKS, start=1):
        path = folder / f"{task['task_id']}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("run_id") and not row.get("run") and args.system.endswith("_agent"):
                print(f"{args.system} {index}/24 {task['task_id']}: resume polling existing run", flush=True)
                run_agent(task, row, args.api_url, path)
                row["finished_at"] = utc_now()
                save(path, row)
            else:
                print(f"{args.system} {index}/24 {task['task_id']}: already attempted; skip", flush=True)
            continue
        row = {"task_id": task["task_id"], "question": task["question"], "system": args.system,
               "attempted_at": utc_now(), "attempt_count": 1, "status": "attempted"}
        save(path, row)
        started = time.perf_counter()
        try:
            if args.system == "qwen_closed_book":
                run_qwen(task, row)
            elif args.system == "gpt_reference":
                run_gpt(task, row)
            else:
                run_agent(task, row, args.api_url, path)
            row["status"] = "completed" if row.get("answer") or row.get("run") else "incomplete"
        except Exception as error:
            row["status"] = "error"
            row["error"] = f"{type(error).__name__}: {error}"
        row["latency_seconds"] = round(time.perf_counter() - started, 3)
        row["finished_at"] = utc_now()
        save(path, row)
        print(f"{args.system} {index}/24 {task['task_id']}: {row['status']} ({row['latency_seconds']}s)", flush=True)


if __name__ == "__main__":
    main()
