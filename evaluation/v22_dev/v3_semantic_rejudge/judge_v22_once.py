"""Apply the frozen V3 semantic judge once to each preserved V22 answer."""

from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

from prepare_v22_raw import HERE, read_json, verify


def frozen_instruction(original: Path) -> str:
    tree = ast.parse((original / "judge_once.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "openai_once"]
    if len(calls) != 1:
        raise RuntimeError("Could not uniquely recover the original V3 judge instruction")
    return ast.literal_eval(calls[0].args[1])


def judge(original: Path) -> None:
    original = original.resolve()
    _, benchmark = verify(original)
    sys.path.insert(0, str(original))
    from common import CONFIG, openai_once, utc_now, write_json
    from judge_once import SCHEMA, make_prompt

    model = "gpt-5.4-2026-03-05"
    if CONFIG["judge_model"] != model or CONFIG["judge_temperature"] != 0:
        raise RuntimeError("Original exact judge model/temperature mismatch")
    prompt = frozen_instruction(original)
    labels = read_json(original / "judge" / "blinding_map.json")
    target = HERE / "judge" / "v22_agent"
    target.mkdir(parents=True, exist_ok=True)
    raw_dir = HERE / "raw" / "v22_agent"
    if len(list(raw_dir.glob("*.json"))) != 36:
        raise RuntimeError("Prepare all 36 preserved V22 answers before judging")
    for task in benchmark["primary_tasks"]:
        task_id = task["task_id"]
        path = target / f"{task_id}.json"
        if path.exists():
            print(f"judge {task_id} existing; no second call", flush=True)
            continue
        raw = read_json(raw_dir / f"{task_id}.json")
        label = labels[task_id]["v21_2_agent"]  # Original independently randomized anonymous label.
        record = {
            "task_id": task_id, "system": "v22_agent", "anonymous_label": label,
            "judge_model": model, "attempt_id": str(uuid4()), "attempt_count": 1,
            "reserved_at": utc_now(), "status": "reserved",
        }
        # Exclusive reservation ensures an interrupted judge call is never repeated.
        with path.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        started = time.monotonic()
        try:
            answer_prompt = make_prompt(task, raw["answer_text"], label)
            text, meta = openai_once(
                model, prompt, answer_prompt, judge=True, response_format=SCHEMA
            )
            judgment = json.loads(text)
            if len(judgment["claim_scores"]) != len(task["required_claims"]):
                raise ValueError("judge claim-score count mismatched frozen rubric")
            if meta.get("model_returned") != model:
                raise ValueError("provider returned a different judge model")
            record.update(status="completed", judgment=judgment, response_meta=meta,
                          latency_seconds=round(time.monotonic() - started, 6), completed_at=utc_now())
        except Exception as exc:
            record.update(status="judge_failure", error=f"{type(exc).__name__}: {exc}"[:1000],
                          latency_seconds=round(time.monotonic() - started, 6), completed_at=utc_now())
        write_json(path, record)
        print(f"judge {task_id} {record['status']}", flush=True)
    completed = sum(read_json(path).get("status") == "completed" for path in target.glob("*.json"))
    print(f"judge completed={completed}/36; no V22 answer was generated", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    judge(parser.parse_args().original)
