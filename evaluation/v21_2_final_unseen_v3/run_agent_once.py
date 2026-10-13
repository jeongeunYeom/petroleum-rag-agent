"""Run the frozen product's normal from-message API, one run per task."""

from __future__ import annotations

import time

import requests

from common import CONFIG, TASKS, complete, fail, reserve, write_json
from integrity_check import frozen_hashes_ok, product_changed_files


def poll_run(run_id: str) -> dict:
    deadline = time.monotonic() + CONFIG["agent_poll_deadline_seconds"]
    last_error = None
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{CONFIG['agent_api_url']}/research/goal-runs/{run_id}", timeout=25)
            response.raise_for_status()
            state = response.json()
            if state.get("run_status") in {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}:
                return state
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(CONFIG["agent_poll_interval_seconds"])
    raise TimeoutError(f"existing run_id {run_id} not terminal before deadline; last polling error={last_error}")


def run() -> None:
    if not frozen_hashes_ok() or product_changed_files():
        raise RuntimeError("frozen benchmark/product integrity failed")
    failures = 0
    for index, task in enumerate(TASKS, 1):
        path, record, fresh = reserve("v21_2_agent", task["task_id"], CONFIG["agent_model"])
        if not fresh and record.get("response_status") != "reserved":
            print(f"agent {index}/36 {task['task_id']} existing; no regeneration", flush=True)
            failures += record.get("technical_failure") is True
            continue
        start = time.monotonic()
        try:
            if not fresh:
                if not record.get("run_id"):
                    raise RuntimeError("generation reservation interrupted before run_id returned; no replacement run")
                run_id = record["run_id"]
            else:
                response = requests.post(
                    f"{CONFIG['agent_api_url']}/research/goal-runs/from-message",
                    json={"message": task["question"], "model": CONFIG["agent_model"]},
                    timeout=CONFIG["agent_create_timeout_seconds"],
                )
                response.raise_for_status()
                initial = response.json()
                run_id = initial["run_id"]
                record["run_id"] = run_id
                write_json(path, record)  # durable before any polling
            state = poll_run(run_id)
            answer = (state.get("final_answer") or state.get("clarification_question") or "").strip()
            if state.get("run_status") == "failed":
                raise RuntimeError(f"agent worker failed: {state.get('error')}")
            complete(path, record, answer, time.monotonic() - start, run=state)
            status = "completed"
        except Exception as exc:
            extra = {"run_id": record.get("run_id")}
            try:
                if record.get("run_id"):
                    extra["last_run_state"] = requests.get(
                        f"{CONFIG['agent_api_url']}/research/goal-runs/{record['run_id']}", timeout=10
                    ).json()
            except requests.RequestException:
                pass
            fail(path, record, f"{type(exc).__name__}: {exc}", time.monotonic() - start, **extra)
            failures += 1
            status = "technical_failure"
        print(f"agent {index}/36 {task['task_id']} {status} failures={failures}", flush=True)
    print(f"agent finished; technical_failures={failures}/36", flush=True)


if __name__ == "__main__":
    run()
