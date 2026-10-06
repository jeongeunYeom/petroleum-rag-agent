"""Freeze only an unchanged PASS preflight and zero-conflict GT audit."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from preflight_python_tool_heldout_v4r1 import (  # noqa: E402
    AUDIT, BASE, BENCHMARK, CATALOG, EXCLUSIONS, MANIFEST, REFERENCE,
    REFERENCE_OUTPUTS, REPORT, can_freeze, digest,
)

RUBRIC = BASE / "python_tool_heldout_v4r1_rubric.json"
POLICY = BASE / "PYTHON_TOOL_HELDOUT_V4R1_POLICY.md"


def verify_freeze_gate(report: dict, consistency: dict, current_hashes: dict[str, str]) -> None:
    if not can_freeze(report, consistency):
        raise ValueError("Input and GT consistency preflight must both PASS before freeze")
    for label in ("benchmark_draft", "source_catalog", "source_exclusions",
                  "reference_calculator", "reference_outputs"):
        if report["hashes"][label + "_sha256"] != current_hashes[label]:
            raise ValueError(f"Audited {label} changed after preflight")
    if consistency["reference_calculator_sha256"] != current_hashes["reference_calculator"]:
        raise ValueError("GT audit calculator changed")
    if consistency["reference_outputs_sha256"] != current_hashes["reference_outputs"]:
        raise ValueError("GT audit reference outputs changed")


def build_manifest(report: dict, consistency: dict) -> dict:
    files = {
        "benchmark_draft": BENCHMARK, "source_catalog": CATALOG, "source_exclusions": EXCLUSIONS,
        "reference_calculator": REFERENCE, "reference_outputs": REFERENCE_OUTPUTS,
        "rubric": RUBRIC, "policy": POLICY, "preflight": REPORT, "gt_consistency": AUDIT,
    }
    hashes = {label: digest(path) for label, path in files.items()}
    verify_freeze_gate(report, consistency, hashes)
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    tasks = benchmark["tasks"]
    return {
        "benchmark_id": "python_tool_heldout_v4r1",
        "product_code_sha": "2646be1e5439cd689fdd236e064e2f9b64255274",
        "benchmark_sha256": hashes["benchmark_draft"],
        "source_catalog_sha256": hashes["source_catalog"],
        "source_exclusions_sha256": hashes["source_exclusions"],
        "reference_calculator_sha256": hashes["reference_calculator"],
        "reference_outputs_sha256": hashes["reference_outputs"],
        "rubric_sha256": hashes["rubric"], "policy_sha256": hashes["policy"],
        "preflight_sha256": hashes["preflight"], "gt_consistency_sha256": hashes["gt_consistency"],
        "preflight_status": "PASS", "gt_consistency_status": "PASS",
        "preflight_llm_calls": 0, "gt_conflicts": 0,
        "task_count": 12, "python_need_count": dict(Counter(task["python_expected"] for task in tasks)),
        "required_stratum_count": dict(Counter(task["evaluation_stratum"] for task in tasks if task["python_expected"] == "required")),
        "domain_count": dict(Counter(task["domain"] for task in tasks)),
        "expected_user_facts": report["summary"]["expected_user"],
        "expected_evidence_facts": report["summary"]["expected_evidence"],
        "expected_formulas": report["summary"]["expected_formula"],
        "expected_required_outputs": report["summary"]["required_outputs"],
        "kb": {"data_dir": r"D:\petroleum-rag-agent\data", "collection": "petroleum_knowledge",
               "chunks": 18976, "documents": 12, "retrieval_mode": "legacy"},
        "model_settings": {
            "research_model": "qwen3:8b", "review_model": "gemma4:latest", "temperature": 0, "seed": 42,
            "use_internal": True, "use_external": False, "engineering_validation": True,
            "internal_top_k": 5, "external_top_k": 5,
            "max_iterations": 4, "no_progress_patience": 2,
            "max_python_calls": 4, "max_python_attempts_per_call": 2,
        },
        "conditions": [
            {"name": "python_off", "allow_python_execution": False, "python_execution_approved": False},
            {"name": "python_on", "allow_python_execution": True, "python_execution_approved": True},
        ],
        "run_policy": "one complete OFF 12 then ON 12; no selective reruns; product failures retained",
        "freeze_commit_sha": "recorded_externally_in_run_provenance",
        "manifest_sha256": "recorded_externally_in_run_provenance",
    }


def main() -> int:
    if MANIFEST.exists():
        raise FileExistsError("v4r1 already frozen")
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    consistency = json.loads(AUDIT.read_text(encoding="utf-8"))
    manifest = build_manifest(report, consistency)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("FROZEN ASSETS", manifest["benchmark_id"], manifest["benchmark_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
