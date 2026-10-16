"""Frozen-policy, no-tool/no-web/no-KB OpenAI closed-book comparator."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
from run_external_baseline import Prompt, call_openai  # noqa: E402


MODEL = "gpt-6.1-sol"
SYSTEM = (
    "Answer the petroleum-engineering question accurately and concisely. "
    "You have no access to the user's internal documents, images, tools, Python, or the web. "
    "Do not fabricate document/page citations, figure observations, or exact private data. "
    "If a document-specific answer cannot be verified without those sources, say so. "
    "If the premise is false, correct it when you can do so reliably."
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rubric", type=Path, default=Path(__file__).with_name("rubric.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("baseline_raw.jsonl"))
    args = parser.parse_args()
    tasks = json.loads(args.rubric.read_text(encoding="utf-8"))["tasks"]
    done = set()
    if args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if "answer" in row:
                    done.add(row["question_id"])
    for task in tasks:
        task_id = task["question_id"]
        if task_id in done:
            continue
        print("START", task_id, flush=True)
        start = time.monotonic()
        row = {
            "question_id": task_id,
            "question": task["question"],
            "model_id": MODEL,
            "condition": "closed_book_no_kb_no_web_no_tools",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            result = call_openai(Prompt(system=SYSTEM, user=task["question"]), MODEL, 900, 150)
            row.update(
                answer=result.answer,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                reasoning_tokens=result.reasoning_tokens,
            )
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
        row["elapsed_seconds"] = round(time.monotonic() - start, 3)
        row["completed_at"] = datetime.now(timezone.utc).isoformat()
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print("END", task_id, row["elapsed_seconds"], "OK" if "answer" in row else "ERROR", flush=True)


if __name__ == "__main__":
    main()
