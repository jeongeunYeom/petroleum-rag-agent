"""Read-only KB/product snapshots and one-shot evaluation integrity gates."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PRODUCT_SHA = "f5182b8ae2907452e1c53373055e66c5182c9b90"
KB_ROOTS = (Path(r"D:\petroleum-rag-agent\data\vector_db"), Path(r"D:\petroleum-rag-agent\data\raw"))
SYSTEMS = ("qwen_closed_book", "v21_2_agent")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def kb_snapshot() -> dict:
    files = []
    for root in KB_ROOTS:
        if not root.is_dir():
            raise RuntimeError(f"KB root missing: {root}")
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            files.append({"path": str(path.relative_to(root.parent)), "bytes": path.stat().st_size, "sha256": sha256(path)})
    return {"file_count": len(files), "files": files}


def product_changed_files() -> list[str]:
    args = ["git", "diff", "--name-only", PRODUCT_SHA, "--", ".", ":(exclude)evaluation/v21_2_final_unseen_v3"]
    committed = subprocess.check_output(args, cwd=REPO, text=True).splitlines()
    staged_or_worktree = subprocess.check_output(
        ["git", "diff", "--name-only", "HEAD", "--", ".", ":(exclude)evaluation/v21_2_final_unseen_v3"],
        cwd=REPO, text=True,
    ).splitlines()
    return sorted(set(committed + staged_or_worktree))


def frozen_hashes_ok() -> bool:
    receipt = json.loads((HERE / "freeze_receipt.json").read_text(encoding="utf-8"))
    return all(sha256(HERE / name) == expected for name, expected in receipt["sha256"].items())


def records(system: str) -> list[dict]:
    root = HERE / "raw" / system
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(root.glob("*.json"))] if root.exists() else []


def main(stage: str) -> None:
    if stage == "snapshot-before":
        write_json(HERE / "kb_snapshot_before.json", kb_snapshot())
        print({"KB_files_hashed": json.loads((HERE / "kb_snapshot_before.json").read_text())["file_count"]})
        return
    benchmark = json.loads((HERE / "benchmark.json").read_text(encoding="utf-8"))
    task_ids = {t["task_id"] for t in benchmark["primary_tasks"]}
    summary = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "product_sha": PRODUCT_SHA,
        "product_changed_files": product_changed_files(),
        "benchmark_rubric_hashes_match_receipt": frozen_hashes_ok(),
        "kb_matches_before": kb_snapshot() == json.loads((HERE / "kb_snapshot_before.json").read_text(encoding="utf-8")),
        "primary_task_count": len(task_ids),
        "attempts": {},
        "judge_coverage": None,
    }
    assert len(task_ids) == 36 and not summary["product_changed_files"]
    assert summary["benchmark_rubric_hashes_match_receipt"] and summary["kb_matches_before"]
    if stage == "post":
        summary["attempts"] = {}
        for system in SYSTEMS + (("gpt_reference",) if (HERE / "raw" / "gpt_reference").exists() else ()):
            rows = records(system)
            ids = [row.get("task_id") for row in rows]
            attempts = [row.get("attempt_id") for row in rows]
            failures = sum(row.get("technical_failure") is True for row in rows)
            summary["attempts"][system] = {
                "records": len(rows),
                "technical_failures": failures,
                "one_attempt_each": len(rows) == 36 and set(ids) == task_ids and len(set(ids)) == 36 and len(set(attempts)) == 36 and all(row.get("attempt_count") == 1 for row in rows),
                "within_systemic_threshold": failures <= 7,
            }
        scored = json.loads((HERE / "scored_rows.json").read_text(encoding="utf-8"))
        summary["judge_coverage"] = len(scored) == 36 * len(summary["attempts"])
        summary["finalized"] = (
            all(v["one_attempt_each"] for v in summary["attempts"].values())
            and all(summary["attempts"][system]["within_systemic_threshold"] for system in SYSTEMS)
            and summary["judge_coverage"]
        )
        write_json(HERE / "kb_snapshot_after.json", kb_snapshot())
        assert summary["kb_matches_before"] and all(v["one_attempt_each"] for v in summary["attempts"].values())
    write_json(HERE / f"integrity_{'pre' if stage == 'pre' else 'post'}.json", summary)
    print({k: v for k, v in summary.items() if k not in {"attempts"}})


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"snapshot-before", "pre", "post"}:
        raise SystemExit("usage: integrity_check.py snapshot-before|pre|post")
    main(sys.argv[1])
