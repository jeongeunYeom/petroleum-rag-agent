"""Complete all v2 semantic reviews with one independent local Gemma reviewer.

The incomplete OpenAI reviewer records remain untouched in review/*.json. This
separate 60-task set is the only semantic review used in final metrics.
"""

from __future__ import annotations

import json
import sys
import time

from review_semantic import INSTRUCTIONS, review_input
from run_experiment import HERE, load_benchmark, request_json, write_once
from score_deterministic import TRACKS


MODEL = "gemma4:latest"
PROMPT_VERSION = "final-v2-reviewer-1-local-gemma"


def parse_review(raw: str, mapping: dict[str, str], claim_count: int) -> dict:
    scores = json.loads(raw.strip())["scores"]
    if set(scores) != set(mapping):
        raise ValueError("Review labels incomplete")
    required = {"claim_verdicts", "partial_or_better", "unsupported_claim_count",
                "hallucination", "engineering_contradiction_count", "numeric_accuracy",
                "unit_accuracy", "formula_accuracy", "false_premise_handled",
                "safe_refusal_correct", "citation_semantic_support", "note"}
    for row in scores.values():
        if not required.issubset(row):
            raise ValueError("Review fields incomplete")
        if len(row["claim_verdicts"]) != claim_count or not all(type(x) is bool for x in row["claim_verdicts"]):
            raise ValueError("Claim verdicts malformed")
        if type(row["partial_or_better"]) is not bool or type(row["hallucination"]) is not bool:
            raise ValueError("Boolean fields malformed")
        if any(type(row[name]) is not int or row[name] < 0 for name in
               ("unsupported_claim_count", "engineering_contradiction_count")):
            raise ValueError("Count fields malformed")
        support = row["citation_semantic_support"]
        if support is not None and (not isinstance(support, (float, int)) or not 0 <= support <= 1):
            raise ValueError("Citation support malformed")
    return {mapping[label]: row for label, row in scores.items()}


def review_one(task: dict, catalog: dict) -> dict:
    item, mapping = review_input(task, catalog)
    started = time.perf_counter()
    attempts = []
    for attempt in range(1, 3):
        instruction = INSTRUCTIONS if attempt == 1 else INSTRUCTIONS + "\nStrictly preserve every required key and all five labels A-E in JSON."
        response = request_json("http://127.0.0.1:11434/api/chat", {
            "model": MODEL, "messages": [{"role": "system", "content": instruction},
                                    {"role": "user", "content": json.dumps(item, ensure_ascii=False)}],
            "stream": False, "think": False, "format": "json",
            "options": {"temperature": 0, "seed": 42, "num_ctx": 32768,
                        "num_predict": 3200}}, timeout=600)
        raw = response.get("message", {}).get("content", "")
        try:
            scores = parse_review(raw, mapping, len(task["expected_claims"]))
            return {"task_id": task["task_id"], "prompt_version": PROMPT_VERSION,
                    "reviewer_model_id": response.get("model"), "mapping": mapping,
                    "scores_by_track": scores, "raw_review": raw,
                    "parse_attempts": attempt, "prior_attempts": attempts,
                    "wall_seconds": round(time.perf_counter() - started, 3),
                    "input_tokens": response.get("prompt_eval_count"),
                    "output_tokens": response.get("eval_count"), "provider_payload": response}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            attempts.append({"attempt": attempt, "parse_error": type(exc).__name__,
                             "raw_review": raw, "provider_payload": response})
    return {"task_id": task["task_id"], "prompt_version": PROMPT_VERSION,
            "parse_error": "Two local reviewer outputs failed schema validation",
            "prior_attempts": attempts,
            "wall_seconds": round(time.perf_counter() - started, 3)}


def main() -> None:
    benchmark = load_benchmark()
    deterministic = HERE / "metrics/deterministic_rows.json"
    if not deterministic.exists():
        raise RuntimeError("Deterministic scoring required first")
    rows = json.loads(deterministic.read_text(encoding="utf-8"))
    if len(rows) != len(benchmark["tasks"]) * len(TRACKS) or not all(row["available"] for row in rows if row["valid"]):
        raise RuntimeError("Raw results incomplete")
    invalid_file = HERE / "invalid_tasks.json"
    invalid = {row["task_id"] for row in json.loads(invalid_file.read_text(encoding="utf-8")).get("invalid", [])} if invalid_file.exists() else set()
    for index, task in enumerate(benchmark["tasks"], 1):
        task_id = task["task_id"]
        if task_id in invalid:
            print(f"{index:02d}/60 {task_id} INVALID SKIP", flush=True)
            continue
        path = HERE / "review/local_gemma" / f"{task_id}.json"
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("parse_error") or record.get("error"):
                raise RuntimeError(f"Existing failed local review needs audit: {path}")
            print(f"{index:02d}/60 {task_id} EXISTING", flush=True)
            continue
        try:
            record = review_one(task, benchmark["source_catalog"])
        except Exception as exc:
            record = {"task_id": task_id, "prompt_version": PROMPT_VERSION,
                      "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        write_once(path, record)
        print(f"{index:02d}/60 {task_id} {record.get('error') or record.get('parse_error') or 'OK'} {record.get('wall_seconds', 0):.1f}s", flush=True)
        if record.get("error") or record.get("parse_error"):
            sys.exit(2)


if __name__ == "__main__":
    main()
