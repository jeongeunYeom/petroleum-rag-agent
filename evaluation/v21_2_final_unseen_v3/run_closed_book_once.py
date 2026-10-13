"""Run exactly one frozen-question attempt per closed-book system/task."""

from __future__ import annotations

import sys
import time

from common import CONFIG, TASKS, complete, fail, old_reservation, openai_once, qwen_once, reserve
from integrity_check import frozen_hashes_ok, product_changed_files


def run(system: str) -> None:
    if system not in {"qwen_closed_book", "gpt_reference"}:
        raise ValueError(system)
    if not frozen_hashes_ok() or product_changed_files():
        raise RuntimeError("frozen benchmark/product integrity failed")
    model = CONFIG["qwen_model"] if system == "qwen_closed_book" else CONFIG["gpt_reference_model"]
    failures = 0
    for index, task in enumerate(TASKS, 1):
        path, record, fresh = reserve(system, task["task_id"], model)
        if not fresh:
            if old_reservation(path, record):
                print(f"{system} {index}/36 {task['task_id']} existing; no regeneration", flush=True)
                failures += record.get("technical_failure") is True
                continue
        start = time.monotonic()
        try:
            if system == "qwen_closed_book":
                answer, meta = qwen_once(task["question"])
            else:
                answer, meta = openai_once(
                    model,
                    "Answer the user's petroleum-engineering question accurately and concisely without any tool, retrieval, web, or Python access. Identify specific missing information rather than inventing quantities. Do not claim to have searched the internal KB.",
                    task["question"],
                )
            complete(path, record, answer, time.monotonic() - start, **meta)
            status = "completed"
        except Exception as exc:  # sole generation attempt: every error is retained
            fail(path, record, f"{type(exc).__name__}: {exc}", time.monotonic() - start)
            failures += 1
            status = "technical_failure"
        print(f"{system} {index}/36 {task['task_id']} {status} failures={failures}", flush=True)
    print(f"{system} finished; technical_failures={failures}/36", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_closed_book_once.py qwen_closed_book|gpt_reference")
    run(sys.argv[1])
