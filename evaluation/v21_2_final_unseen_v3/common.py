"""One-attempt raw-record helpers for the frozen V3 evaluation."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import requests


HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "execution_config.json").read_text(encoding="utf-8"))
BENCHMARK = json.loads((HERE / "benchmark.json").read_text(encoding="utf-8"))
TASKS = BENCHMARK["primary_tasks"]
FINAL_RUN_STATUSES = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def reserve(system: str, task_id: str, model: str) -> tuple[Path, dict, bool]:
    path = HERE / "raw" / system / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path, json.loads(path.read_text(encoding="utf-8")), False
    record = {
        "system": system,
        "task_id": task_id,
        "model": model,
        "attempt_id": str(uuid4()),
        "attempt_count": 1,
        "reserved_at": utc_now(),
        "response_status": "reserved",
        "answer_text": "",
        "technical_failure": False,
    }
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return path, record, True


def complete(path: Path, record: dict, answer: str, seconds: float, **extra: object) -> None:
    if not answer.strip():
        fail(path, record, "malformed empty transport response", seconds, **extra)
        return
    record.update(
        response_status="completed",
        answer_text=answer.strip(),
        technical_failure=False,
        completed_at=utc_now(),
        latency_seconds=round(seconds, 6),
        **extra,
    )
    write_json(path, record)


def fail(path: Path, record: dict, error: str, seconds: float, **extra: object) -> None:
    record.update(
        response_status="technical_failure",
        answer_text="",
        technical_failure=True,
        technical_error=error[:1000],
        completed_at=utc_now(),
        latency_seconds=round(seconds, 6),
        **extra,
    )
    write_json(path, record)


def old_reservation(path: Path, record: dict) -> bool:
    """Never generate again after a reservation, including an interrupted call."""
    if record.get("response_status") == "reserved" and not record.get("run_id"):
        fail(path, record, "generation reservation interrupted; outcome unavailable; no retry", 0.0)
        return True
    return record.get("response_status") != "reserved"


def response_text(payload: dict) -> str:
    parts = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def openai_once(model: str, instructions: str, user_input: str, *, judge: bool = False, response_format: dict | None = None) -> tuple[str, dict]:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY unavailable")
    prefix = "judge" if judge else "gpt"
    payload: dict = {
        "model": model,
        "instructions": instructions,
        "input": user_input,
        "temperature": CONFIG[f"{prefix}_temperature"],
        "reasoning": {"effort": CONFIG[f"{prefix}_reasoning_effort"]},
        "max_output_tokens": CONFIG[f"{prefix}_max_output_tokens"],
        "tools": [],
        "store": False,
    }
    if response_format:
        payload["text"] = {"format": response_format}
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
        timeout=CONFIG[f"{prefix}_timeout_seconds"],
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "completed":
        raise RuntimeError(f"OpenAI response status {data.get('status')}: {data.get('incomplete_details')}")
    text = response_text(data)
    if not text:
        raise RuntimeError("malformed empty transport response")
    return text, {"response_id": data.get("id"), "model_returned": data.get("model"), "usage": data.get("usage")}


def qwen_once(question: str) -> tuple[str, dict]:
    payload = {
        "model": CONFIG["qwen_model"],
        "messages": [
            {"role": "system", "content": "Answer the user's petroleum-engineering question accurately and concisely. No tools, retrieval, web, or Python are available. If essential information is missing, say what is missing rather than inventing it."},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "think": False,
        "keep_alive": "30m",
        "options": {
            "temperature": CONFIG["qwen_temperature"],
            "num_ctx": CONFIG["qwen_num_ctx"],
            "num_predict": CONFIG["qwen_num_predict"],
        },
    }
    response = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=CONFIG["qwen_timeout_seconds"])
    response.raise_for_status()
    data = response.json()
    text = (data.get("message") or {}).get("content", "").strip()
    if not text:
        raise RuntimeError("malformed empty transport response")
    return text, {"ollama_done_reason": data.get("done_reason"), "ollama_eval_count": data.get("eval_count"), "ollama_prompt_eval_count": data.get("prompt_eval_count")}
