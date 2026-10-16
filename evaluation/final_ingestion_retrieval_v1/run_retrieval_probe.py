"""Question-only top-10 probe, separate from the autonomous Agent's retrieval."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rubric", type=Path, default=Path(__file__).with_name("rubric.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("retrieval_probe_raw.jsonl"))
    parser.add_argument("--api-url", default="http://127.0.0.1:8001/api")
    args = parser.parse_args()
    tasks = json.loads(args.rubric.read_text(encoding="utf-8"))["tasks"]
    done = set()
    if args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if "response" in row:
                    done.add(row["question_id"])
    for task in tasks:
        if task["question_id"] in done:
            continue
        row = {"question_id": task["question_id"], "query": task["question"],
               "started_at": datetime.now(timezone.utc).isoformat()}
        start = time.monotonic()
        request = urllib.request.Request(
            f"{args.api_url}/research/evidence",
            data=json.dumps({"query": task["question"], "internal_top_k": 10,
                             "use_internal": True, "use_external": False,
                             "evidence_only": True, "model": "qwen3:8b"}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=150) as response:
                row["response"] = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
        row["elapsed_seconds"] = round(time.monotonic() - start, 3)
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(task["question_id"], row["elapsed_seconds"], "OK" if "response" in row else "ERROR", flush=True)


if __name__ == "__main__":
    main()
