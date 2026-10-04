"""Build condition-blind final and separate process packets from a complete run."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_agentic_heldout import BENCHMARK, CONDITIONS, MANIFEST, ROOT, _save, sha256


def _evidence(response: dict) -> list[dict]:
    return [
        {"evidence_id": item["evidence_id"], "document": item["document"], "page": item.get("page"), "chunk_id": item.get("chunk_id"), "excerpt": item.get("excerpt", "")[:700]}
        for item in response.get("internal_sources", [])
    ] + [
        {"evidence_id": item["evidence_id"], "document": item["document"], "page": item.get("page"), "figure_number": item.get("figure_number"), "image_path": item.get("image_path"), "title": item.get("title"), "excerpt": item.get("excerpt", "")[:700], "source_note": item.get("source_note", "")[:700], "related_page_text": item.get("related_page_text", "")[:700]}
        for item in response.get("figures", [])
    ]


def _task_packet(task: dict, catalog: dict) -> dict:
    gt = task["ground_truth"]
    return {
        "task_id": task["task_id"],
        "topic": task["topic"],
        "goal": task["goal"],
        "expected_result": task["expected_result"],
        "criteria": task["success_criteria"],
        "ground_truth": {
            "claims": [{**claim, "sources": [catalog[s] for s in claim["source_ids"]]} for claim in gt["claims"]],
            "numeric_targets": gt["numeric_targets"],
            "goal_feasibility": gt["goal_feasibility"],
            "expected_hypothesis_status": gt["expected_hypothesis_status"],
        },
    }


def prepare(benchmark: dict, raws: dict[str, dict]) -> tuple[dict, dict, dict]:
    tasks = benchmark["tasks"]
    expected_ids = {t["task_id"] for t in tasks}
    for condition in CONDITIONS:
        raw = raws[condition]
        ids = [row["task_id"] for row in raw["results"]]
        if raw.get("complete") is not True or len(ids) != len(tasks) or set(ids) != expected_ids:
            raise ValueError(f"{condition}: incomplete or duplicate run")
    shuffled = [(task, condition) for task in tasks for condition in CONDITIONS]
    random.Random(42).shuffle(shuffled)
    by_condition = {condition: {row["task_id"]: row for row in raws[condition]["results"]} for condition in CONDITIONS}
    final_items = []
    process_items = []
    mapping = {"final": {}, "process": {}}
    for task, condition in shuffled:
        row = by_condition[condition][task["task_id"]]
        response = row["response"]
        task_info = _task_packet(task, benchmark["source_catalog"])
        final_id = f"AR-{len(final_items) + 1:03d}"
        final_items.append({**task_info, "anonymous_answer_id": final_id, "candidate_final_answer": response.get("answer", response.get("final_answer", "")), "candidate_evidence_citations": _evidence(response)})
        mapping["final"][final_id] = {"task_id": task["task_id"], "condition": condition}
        if condition != "single_shot":
            process_id = f"AP-{len(process_items) + 1:03d}"
            process_items.append({**task_info, "anonymous_process_id": process_id, "iterations": [
                {"iteration": it["iteration"], "candidate_answer": it["candidate_answer"], "evidence_added": it["evidence_added"]}
                for it in response.get("iterations", [])
            ], "candidate_evidence_citations": _evidence(response)})
            mapping["process"][process_id] = {"task_id": task["task_id"], "condition": condition}
    return (
        {"benchmark_id": benchmark["benchmark_id"], "packet_type": "final_outcome", "items": final_items},
        {"benchmark_id": benchmark["benchmark_id"], "packet_type": "process", "items": process_items},
        mapping,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if sha256(BENCHMARK) != manifest["benchmark_sha256"]:
        raise ValueError("Frozen benchmark changed")
    raws = {condition: json.loads((args.run_dir / f"{condition}.json").read_text(encoding="utf-8")) for condition in CONDITIONS}
    for raw in raws.values():
        if raw["benchmark_sha256"] != manifest["benchmark_sha256"]:
            raise ValueError("Raw run does not match frozen benchmark")
    final, process, mapping = prepare(benchmark, raws)
    review = ROOT / "evaluation/review"
    _save(review / "agentic_heldout_v1_blind_review.json", final)
    _save(review / "agentic_heldout_v1_process_review.json", process)
    _save(args.run_dir / "blind_review_map.json", mapping)
    print(f"final={len(final['items'])} process={len(process['items'])} map={args.run_dir / 'blind_review_map.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
