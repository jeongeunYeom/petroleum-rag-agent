"""Single-attempt, tool-free qwen and optional GPT reference generations."""

from __future__ import annotations

import argparse
import os
import time
from uuid import uuid4

import requests

from common import HERE, frozen_assets, load, now, save


QWEN = "qwen3:8b"
GPT = "gpt-5.4-mini-2026-03-17"


def response_text(payload: dict) -> str:
    return "\n".join(part.get("text","") for output in payload.get("output",[])
                     for part in output.get("content",[]) if part.get("type")=="output_text").strip()


def generate(system: str, question: str) -> tuple[str,dict]:
    if system == "qwen_closed_book":
        response = requests.post("http://127.0.0.1:11434/api/chat",
            json={"model":QWEN,"messages":[{"role":"user","content":question}],
                  "stream":False,"options":{"temperature":0}},timeout=1200)
        response.raise_for_status()
        payload = response.json()
        return payload.get("message",{}).get("content","").strip(),{"actual_model":payload.get("model"),"http_status":response.status_code,"usage":{"prompt_eval_count":payload.get("prompt_eval_count"),"eval_count":payload.get("eval_count")}}
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY unavailable")
    response = requests.post("https://api.openai.com/v1/responses",
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
        json={"model":GPT,"input":question,"temperature":0,"store":False},timeout=1200)
    response.raise_for_status()
    payload = response.json()
    return response_text(payload),{"actual_model":payload.get("model"),"http_status":response.status_code,"usage":payload.get("usage",{})}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system",required=True,choices=["qwen_closed_book","gpt_reference"])
    args = parser.parse_args()
    frozen_assets()
    tasks = load("benchmark.json")["primary_tasks"]
    for index, task in enumerate(tasks,1):
        path = HERE / "raw" / args.system / f"{task['task_id']}.json"
        if path.exists():
            print(f"{index}/36 {task['task_id']}: already reserved; no retry",flush=True)
            continue
        row = {"task_id":task["task_id"],"question":task["question"],"system":args.system,
               "attempt_id":str(uuid4()),"attempt_count":1,"attempted_at":now(),"status":"reserved"}
        save(path,row)
        started = time.monotonic()
        try:
            answer,meta = generate(args.system,task["question"])
            row.update(meta)
            row.update(answer=answer,status="completed")
        except Exception as error:
            row.update(status="error",error=f"{type(error).__name__}: {error}")
        row.update(finished_at=now(),latency_seconds=round(time.monotonic()-started,3))
        save(path,row)
        print(f"{index}/36 {task['task_id']}: {row['status']} {row['latency_seconds']}s",flush=True)


if __name__ == "__main__":
    main()
