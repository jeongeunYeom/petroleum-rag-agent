"""Immutable V18 references and V20.1 evaluation integrity helpers."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
OLD_COMMIT = "e59c2959231c7997c2ab883a66708e91c14962e3"
OLD_PREFIX = "evaluation/v18_poster_final/"
PRODUCT_SHA = "c82ef66070695e6a13f7a6f3eb35f2714e4e5811"
BENCHMARK_SHA = "6913d38c697e00cc4601db3d53e3e4270350520600de0d9e9ac2fc25169e2b1f"
POLICY_SHA = "32da6b7220c86a1872910d159418412618a70616a0976aaf078277d388af77f9"
JUDGE_MODEL = "gpt-5.4-2026-03-05"


def old_bytes(name: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{OLD_COMMIT}:{OLD_PREFIX}{name}"], cwd=REPO)


def old_json(name: str) -> dict | list:
    return json.loads(old_bytes(name))


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def assert_frozen() -> None:
    if sha256(ROOT / "benchmark.json") != BENCHMARK_SHA:
        raise RuntimeError("frozen benchmark SHA256 changed")
    if sha256(ROOT / "POLICY.md") != POLICY_SHA:
        raise RuntimeError("frozen policy SHA256 changed")
    if hashlib.sha256(old_bytes("benchmark.json")).hexdigest() != BENCHMARK_SHA:
        raise RuntimeError("source benchmark SHA256 changed")
    if hashlib.sha256(old_bytes("POLICY.md")).hexdigest() != POLICY_SHA:
        raise RuntimeError("source policy SHA256 changed")


def kb_snapshot() -> dict:
    frozen = old_json("kb_snapshot.json")
    base = Path(frozen["persistent_directory"])
    files = {}
    for name, expected in frozen["files"].items():
        path = base / name
        size, digest = path.stat().st_size, sha256(path)
        files[name] = {"bytes": size, "sha256": digest,
                       "matches_frozen": size == expected["bytes"] and digest == expected["sha256"]}
    return {"directory": str(base), "collection": frozen["collection"], "files": files,
            "all_files_match_frozen": all(item["matches_frozen"] for item in files.values())}


def product_unchanged() -> bool:
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", PRODUCT_SHA, "--", "backend/app", "frontend"], cwd=REPO, text=True
    ).strip()
    return not bool(changed)
