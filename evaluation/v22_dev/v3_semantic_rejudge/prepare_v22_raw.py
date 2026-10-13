"""Normalize saved V22 V3 outputs without generating or changing an answer."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OBSERVED = HERE.parent / "observed_v3_results.json"
PRODUCT_SHA = "0bfffd45043c9a9f50e76dc6e57b7a44458da665"
ORIGINAL_SHA = "8af20278b1905be02fcd2a855471b749da094e38"
FROZEN_HASHES = {
    "benchmark.json": "a720ff0282038fd89a11f94dc6ce435cfe8fcda39e16cffa1cef82d171cca6a5",
    "rubric.json": "3e50b3faf93041a001b6741a05df57fb038d2e87e7bb158784b1fb76d65de4d2",
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify(original: Path) -> tuple[dict, dict]:
    original = original.resolve()
    original_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=original.parents[1], text=True
    ).strip()
    if original_head != ORIGINAL_SHA:
        raise RuntimeError(f"Original V3 checkout is not the finalized commit: {original_head}")
    for name, expected in FROZEN_HASHES.items():
        actual = hashlib.sha256((original / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Frozen {name} SHA256 mismatch: {actual}")
    if not OBSERVED.is_file():
        raise RuntimeError("Saved V22 output is missing; answer generation is forbidden")
    observed = read_json(OBSERVED)
    benchmark = read_json(original / "benchmark.json")
    ids = [row["task_id"] for row in observed["cases"]]
    gold_ids = [task["task_id"] for task in benchmark["primary_tasks"]]
    if observed["product_sha"] != PRODUCT_SHA or len(ids) != 36 or len(set(ids)) != 36 or set(ids) != set(gold_ids):
        raise RuntimeError("Saved V22 product/task identity mismatch")
    if len(observed["resume_probes"]) != 4:
        raise RuntimeError("Saved V22 resume count mismatch")
    if any(row.get("technical_error") or not row.get("raw_run") for row in observed["cases"]):
        raise RuntimeError("Saved V22 primary output contains a technical error or missing run")
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", PRODUCT_SHA, "HEAD", "--", "backend", "frontend"],
        cwd=ROOT, text=True,
    ).strip()
    uncommitted = subprocess.check_output(
        ["git", "status", "--porcelain", "--", "backend", "frontend"], cwd=ROOT, text=True
    ).strip()
    if changed or uncommitted:
        raise RuntimeError("V22 product code changed after freeze")
    return observed, benchmark


def prepare(original: Path) -> None:
    observed, benchmark = verify(original)
    rows = {row["task_id"]: row for row in observed["cases"]}
    source_hash = hashlib.sha256(OBSERVED.read_bytes()).hexdigest()
    target = HERE / "raw" / "v22_agent"
    target.mkdir(parents=True, exist_ok=True)
    for task in benchmark["primary_tasks"]:
        task_id = task["task_id"]
        saved = rows[task_id]
        run = saved["raw_run"]
        answer = run.get("final_answer") or run.get("clarification_question") or ""
        if not answer.strip() or answer != saved.get("answer"):
            raise RuntimeError(f"Saved answer missing or mismatched: {task_id}")
        record = {
            "task_id": task_id,
            "system": "v22_agent",
            "response_status": "completed",
            "technical_failure": False,
            "answer_text": answer,
            "latency_seconds": saved["latency_seconds"],
            "run": run,
            "source_observed_sha256": source_hash,
        }
        path = target / f"{task_id}.json"
        if path.exists():
            if read_json(path) != record:
                raise RuntimeError(f"Existing normalized record differs; refusing overwrite: {task_id}")
            continue
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if len(list(target.glob("*.json"))) != 36:
        raise RuntimeError("Normalized V22 raw record count is not 36")
    print(f"prepared 36 saved V22 answers; observed_sha256={source_hash}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path, required=True)
    prepare(parser.parse_args().original)
