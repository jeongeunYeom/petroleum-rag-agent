"""Attest the frozen assets and the first complete raw paired run."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
from run_python_tool_heldout_v6 import load_frozen  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def record(run_dir: Path) -> dict:
    benchmark, manifest = load_frozen()
    raw = {name: run_dir / f"{name}.json" for name in ("python_off", "python_on")}
    payloads = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in raw.items()}
    expected = [task["task_id"] for task in benchmark["tasks"]]
    if any(not payload.get("complete") or [row["task_id"] for row in payload.get("results", [])] != expected
           for payload in payloads.values()) or len({payload["run_id"] for payload in payloads.values()}) != 1:
        raise ValueError("Only a complete, frozen 12+12 pair can be attested")
    return {"benchmark_id": manifest["benchmark_id"], "run_id": payloads["python_off"]["run_id"],
            "product_code_sha": manifest["product_code_sha"], "freeze_commit_sha": manifest["freeze_commit_sha"],
            "manifest_sha256": digest(ROOT / "evaluation/python_tool_heldout_v6_manifest.json"),
            "frozen_sha256": {key: value for key, value in manifest.items() if key.endswith("_sha256")},
            "raw_sha256": {name: digest(path) for name, path in raw.items()},
            "raw_paths": {name: str(path.resolve()) for name, path in raw.items()},
            "execution_order": ["python_off", "python_on"], "conditions": manifest["conditions"],
            "model_settings": manifest["model_settings"], "kb": manifest["kb"],
            "full_ab_runs": 1, "partial_reruns": 0, "openai_api_used": False, "gemini_api_used": False,
            "product_code_changed": False, "previous_heldout_changed": False,
            "previous_heldout_rerun": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    target = ROOT / "evaluation/review/python_tool_heldout_v6_run_provenance.json"
    if target.exists():
        raise FileExistsError(target)
    target.write_text(json.dumps(record(args.run_dir), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
