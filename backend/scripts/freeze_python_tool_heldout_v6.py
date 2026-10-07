"""Create a hash manifest only after both independent preflight gates pass."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend/scripts"))
from preflight_python_tool_heldout_v6 import BASE, PREFIX, PRODUCT_SHA, digest, load  # noqa: E402

FILES = {
    "author_spec": BASE / f"{PREFIX}_spec.json",
    "author_script": ROOT / "backend/scripts/author_python_tool_heldout_v6.py",
    "benchmark": BASE / f"{PREFIX}.json",
    "rubric": BASE / f"{PREFIX}_rubric.json",
    "source_catalog": BASE / f"{PREFIX}_source_catalog.json",
    "source_exclusions": BASE / f"{PREFIX}_source_exclusions.json",
    "reference_calculator": BASE / "reference" / f"{PREFIX}_ground_truth.py",
    "reference_outputs": BASE / "reference" / f"{PREFIX}_reference_outputs.json",
    "policy": BASE / "PYTHON_TOOL_HELDOUT_V6_POLICY.md",
    "preflight": BASE / "review" / f"{PREFIX}_preflight.json",
    "gt_consistency": BASE / "review" / f"{PREFIX}_gt_consistency.json",
    "freeze_script": ROOT / "backend/scripts/freeze_python_tool_heldout_v6.py",
}


def frozen_manifest() -> dict:
    if not all(p.is_file() for p in FILES.values()):
        raise FileNotFoundError("At least one required freeze asset is absent")
    preflight = load(FILES["preflight"])
    gt = load(FILES["gt_consistency"])
    if (preflight["status"] != "PASS" or gt["status"] != "PASS" or gt["conflict_count"] != 0 or
            preflight["errors"] or any(preflight["calls"].values()) or
            preflight["hashes"]["benchmark_draft_sha256"] != digest(FILES["benchmark"])):
        raise ValueError("Freeze blocked: preflight or GT integrity failed")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != PRODUCT_SHA:
        raise ValueError(f"Freeze must start at the unmodified product SHA, got {head}")
    benchmark = load(FILES["benchmark"])
    if benchmark["product_code_sha"] != PRODUCT_SHA:
        raise ValueError("Benchmark product SHA differs")
    return {
        "benchmark_id": PREFIX, "product_code_sha": PRODUCT_SHA,
        **{label + "_sha256": digest(p) for label, p in FILES.items()},
        "preflight_status": "PASS", "gt_consistency_status": "PASS",
        "preflight_llm_calls": 0, "gt_conflicts": 0,
        "task_count": preflight["task_count"],
        "python_need_count": preflight["python_need_count"],
        "required_stratum_count": preflight["required_stratum_count"],
        "domain_count": preflight["domain_count"],
        "expected_user_facts": preflight["representability"]["user"]["expected"],
        "expected_evidence_facts": preflight["representability"]["evidence"]["expected"],
        "expected_formulas": preflight["representability"]["formula"]["expected"],
        "expected_required_outputs": preflight["required_canonical_targets"],
        "kb": {"data_dir": r"D:\petroleum-rag-agent\data", "collection": "petroleum_knowledge",
               "chunks": 18976, "documents": 12, "retrieval_mode": "legacy"},
        "model_settings": {"research_model": "qwen3:8b", "review_model": "gemma4:latest",
                           "temperature": 0, "seed": 42, "use_internal": True, "use_external": False,
                           "engineering_validation": True, "internal_top_k": 5, "external_top_k": 5,
                           "max_iterations": 4, "no_progress_patience": 2,
                           "max_python_calls": 4, "max_python_attempts_per_call": 2},
        "conditions": [{"name": "python_off", "allow_python_execution": False, "python_execution_approved": False},
                       {"name": "python_on", "allow_python_execution": True, "python_execution_approved": True}],
        "run_policy": "one complete OFF 12 then ON 12; no selective reruns; product failures scored",
        "freeze_commit_sha": None,
    }


def main() -> None:
    manifest = frozen_manifest()
    p = BASE / f"{PREFIX}_manifest.json"
    if p.exists():
        raise FileExistsError("Manifest already exists; frozen benchmark cannot be regenerated")
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Freeze manifest prepared with {len(FILES)} asset hashes; commit it before any Agent run")


if __name__ == "__main__":
    main()
