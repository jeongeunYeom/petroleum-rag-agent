"""Shared immutable-evaluation IO and integrity helpers."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PRODUCT_SHA = "f5182b8ae2907452e1c53373055e66c5182c9b90"
TERMINAL = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def save(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding="utf-8")
    pending.replace(path)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=REPO)


def frozen_assets() -> None:
    receipt = load("freeze_receipt.json")
    assert receipt["evaluated_product_sha"] == PRODUCT_SHA
    commit = receipt["benchmark_freeze_commit"]
    assert git("rev-parse", commit).decode().strip() == commit
    for filename, digest in receipt["sha256"].items():
        assert sha((HERE / filename).read_bytes()) == digest, f"working file changed: {filename}"
    for filename, digest in receipt["git_blob_sha256"].items():
        blob = git("show", f"{commit}:evaluation/v21_2_final_unseen_v2/{filename}")
        assert sha(blob) == digest, f"freeze blob mismatch: {filename}"
    assert (HERE / "benchmark.sha256").read_text(encoding="ascii").strip() == receipt["sha256"]["benchmark.json"]


def frozen_product() -> None:
    committed = git("diff", "--name-only", PRODUCT_SHA, "HEAD", "--", "backend", "frontend")
    assert not committed.strip(), "application files differ from product SHA"
    dirty = git("status", "--porcelain", "--", "backend", "frontend")
    assert not dirty.strip(), "application working tree differs from product SHA"
