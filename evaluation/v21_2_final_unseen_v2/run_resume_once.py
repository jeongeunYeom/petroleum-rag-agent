"""Four separate same-run clarification probes; each turn is posted at most once."""

from __future__ import annotations

import argparse
import time
from uuid import uuid4

import requests

from common import HERE, PRODUCT_SHA, TERMINAL, frozen_assets, frozen_product, load, now, save


def poll(base: str, run_id: str) -> dict:
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        response = requests.get(f"{base}/api/research/goal-runs/{run_id}",timeout=45)
        response.raise_for_status()
        run = response.json()
        if run.get("run_status") in TERMINAL:
            return run
        time.sleep(2)
    raise TimeoutError(f"existing run {run_id} did not finish within polling window")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url",default="http://127.0.0.1:8002")
    args = parser.parse_args()
    frozen_assets()
    frozen_product()
    probes = load("benchmark.json")["resume_probes"]
    for index, probe in enumerate(probes,1):
        path = HERE / "resume" / f"{probe['probe_id']}.json"
        if path.exists():
            print(f"{index}/4 {probe['probe_id']}: already reserved; no new run",flush=True)
            continue
        row = {"probe_id":probe["probe_id"],"product_sha":PRODUCT_SHA,
               "attempt_id":str(uuid4()),"attempt_count":1,"attempted_at":now(),"status":"reserved"}
        save(path,row)
        started = time.monotonic()
        try:
            response = requests.post(f"{args.api_url}/api/research/goal-runs/from-message",
                                     json={"message":probe["turn_1"],"model":"qwen3:8b"},timeout=45)
            response.raise_for_status()
            row["run_id"] = response.json()["run_id"]
            row["status"] = "turn_1_running"
            save(path,row)
            first = poll(args.api_url,row["run_id"])
            row["turn_1_run"] = first
            row["turn_1_status"] = first.get("run_status")
            save(path,row)
            if first.get("run_status") == "waiting_for_user_input":
                row["resume_attempt_id"] = str(uuid4())
                row["resume_attempt_count"] = 1
                row["status"] = "resume_reserved"
                save(path,row)
                response = requests.post(f"{args.api_url}/api/research/goal-runs/{row['run_id']}/resume",
                                         json={"message":probe["turn_2"]},timeout=45)
                response.raise_for_status()
                row["resume_http_status"] = response.status_code
                row["status"] = "resume_running"
                save(path,row)
                final = poll(args.api_url,row["run_id"])
                row["final_run"] = final
                row["final_status"] = final.get("run_status")
            row["status"] = "completed"
        except Exception as error:
            row.update(status="error",error=f"{type(error).__name__}: {error}")
        row.update(finished_at=now(),latency_seconds=round(time.monotonic()-started,3))
        save(path,row)
        print(f"{index}/4 {probe['probe_id']}: {row['status']} {row.get('turn_1_status')} -> {row.get('final_status')}",flush=True)


if __name__ == "__main__":
    main()
