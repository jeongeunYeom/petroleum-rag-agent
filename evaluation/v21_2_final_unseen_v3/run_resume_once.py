"""Four independent one-shot same-run clarification probes."""

from __future__ import annotations

import time
from uuid import uuid4

import requests

from common import BENCHMARK, CONFIG, utc_now, write_json
from integrity_check import frozen_hashes_ok, product_changed_files
from run_agent_once import poll_run


def main() -> None:
    if not frozen_hashes_ok() or product_changed_files():
        raise RuntimeError("frozen benchmark/product integrity failed")
    for index, probe in enumerate(BENCHMARK["resume_probes"], 1):
        path = __import__("pathlib").Path(__file__).resolve().parent / "resume" / f"{probe['probe_id']}.json"
        if path.exists():
            print(f"resume {index}/4 existing; no regeneration", flush=True)
            continue
        record = {
            "probe_id": probe["probe_id"],
            "attempt_id": str(uuid4()),
            "attempt_count": 1,
            "reserved_at": utc_now(),
            "response_status": "reserved",
            "technical_failure": False,
        }
        write_json(path, record)
        start = time.monotonic()
        try:
            response = requests.post(
                f"{CONFIG['agent_api_url']}/research/goal-runs/from-message",
                json={"message": probe["turn1"], "model": CONFIG["agent_model"]},
                timeout=CONFIG["agent_create_timeout_seconds"],
            )
            response.raise_for_status()
            record["run_id"] = response.json()["run_id"]
            write_json(path, record)
            turn1 = poll_run(record["run_id"])
            record["turn1_state"] = turn1
            record["turn1_waiting_correctly"] = turn1.get("run_status") == "waiting_for_user_input"
            write_json(path, record)
            if record["turn1_waiting_correctly"]:
                record["turn2_reserved_at"] = utc_now()
                write_json(path, record)
                resumed = requests.post(
                    f"{CONFIG['agent_api_url']}/research/goal-runs/{record['run_id']}/resume",
                    json={"message": probe["turn2"]},
                    timeout=CONFIG["agent_create_timeout_seconds"],
                )
                resumed.raise_for_status()
                record["resume_response_run_id"] = resumed.json().get("run_id")
                record["turn2_state"] = poll_run(record["run_id"])
            record["response_status"] = "completed"
            record["completed_at"] = utc_now()
            record["latency_seconds"] = round(time.monotonic() - start, 6)
        except Exception as exc:
            record["response_status"] = "technical_failure"
            record["technical_failure"] = True
            record["technical_error"] = f"{type(exc).__name__}: {exc}"[:1000]
            record["completed_at"] = utc_now()
            record["latency_seconds"] = round(time.monotonic() - start, 6)
        write_json(path, record)
        print(f"resume {index}/4 {probe['probe_id']} {record['response_status']} waiting={record.get('turn1_waiting_correctly')}", flush=True)


if __name__ == "__main__":
    main()
