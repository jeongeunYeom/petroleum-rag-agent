"""Record immutable-asset and raw-run hashes outside the self-referential manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "evaluation/review"
FREEZE_SHA = "213231fd5c4f6bc29cefebd37f98fc9656c488cb"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(run_dir: Path) -> dict:
    manifest_path = ROOT / "evaluation/python_tool_heldout_v4r1_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for label, relative in {
        "benchmark": "evaluation/python_tool_heldout_v4r1.json",
        "rubric": "evaluation/python_tool_heldout_v4r1_rubric.json",
        "source_catalog": "evaluation/python_tool_heldout_v4r1_source_catalog.json",
        "source_exclusions": "evaluation/python_tool_heldout_v4r1_source_exclusions.json",
        "preflight": "evaluation/review/python_tool_heldout_v4r1_preflight.json",
        "reference_calculator": "evaluation/reference/python_tool_heldout_v4r1_ground_truth.py",
    }.items():
        if digest(ROOT / relative) != manifest[label + "_sha256"]:
            raise ValueError(f"Frozen {label} hash changed")
    raw = {name: run_dir / f"{name}.json" for name in ("python_off", "python_on")}
    payloads = {name: json.loads(path.read_text(encoding="utf-8")) for name, path in raw.items()}
    if any(not data.get("complete") or len(data.get("results", [])) != 12 for data in payloads.values()):
        raise ValueError("Run is incomplete")
    if len({data["run_id"] for data in payloads.values()}) != 1:
        raise ValueError("OFF/ON run IDs differ")
    freeze = subprocess.check_output(["git", "rev-parse", FREEZE_SHA], cwd=ROOT, text=True).strip()
    if freeze != FREEZE_SHA:
        raise ValueError("Freeze commit unavailable")
    return {
        "benchmark_id": manifest["benchmark_id"], "run_id": payloads["python_off"]["run_id"],
        "product_code_sha": manifest["product_code_sha"], "freeze_commit_sha": FREEZE_SHA,
        "manifest_sha256": digest(manifest_path),
        "benchmark_sha256": manifest["benchmark_sha256"],
        "rubric_sha256": manifest["rubric_sha256"],
        "source_catalog_sha256": manifest["source_catalog_sha256"],
        "source_exclusions_sha256": manifest["source_exclusions_sha256"],
        "preflight_sha256": manifest["preflight_sha256"],
        "reference_calculator_sha256": manifest["reference_calculator_sha256"],
        "raw_sha256": {name: digest(path) for name, path in raw.items()},
        "raw_paths": {name: str(path.resolve()) for name, path in raw.items()},
        "execution_order": ["python_off", "python_on"],
        "conditions": manifest["conditions"], "model_settings": manifest["model_settings"],
        "kb": manifest["kb"], "full_ab_runs": 1, "partial_reruns": 0,
        "openai_api_used": False, "gemini_api_used": False,
        "product_code_changed": False, "previous_heldout_changed": False,
        "previous_heldout_rerun": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    path = REVIEW / "python_tool_heldout_v4r1_run_provenance.json"
    if path.exists():
        raise FileExistsError(path)
    data = record(args.run_dir)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
