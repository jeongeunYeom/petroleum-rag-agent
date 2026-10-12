"""Offline checks: exact frozen assets and no scoring-semantic drift."""

from __future__ import annotations

from copy import deepcopy

from common import ROOT, assert_frozen, old_json, read_json
from score_reeval import score_new


def test_frozen_assets_and_task_count() -> None:
    assert_frozen()
    tasks = read_json(ROOT / "benchmark.json")["tasks"]
    assert len(tasks) == 24
    assert sum(task["category"] in {"direct_calculation", "user_formula", "kb_formula"}
               for task in tasks) == 10


def test_new_score_path_reproduces_every_old_v18_row() -> None:
    tasks = read_json(ROOT / "benchmark.json")["tasks"]
    old_rows = old_json("scored_rows.json")
    fields = ("goal_success", "claim_coverage", "claim_scores", "hallucination_free",
              "unnecessary_refusal", "unnecessary_refusal_basis", "citation_semantic_support",
              "relevant_evidence_retrieved", "numeric", "diagnostics")
    for task, expected in zip(tasks, old_rows, strict=True):
        task_id = task["task_id"]
        judge = deepcopy(old_json(f"raw/judge/{task_id}.json"))
        judge["anonymous_labels"] = {label: "v20_1_agent" if system == "v18_agent" else system
                                     for label, system in judge["anonymous_labels"].items()}
        raw = old_json(f"raw/v18_agent/{task_id}.json")
        actual = score_new(task, judge, raw)
        for field in fields:
            assert actual[field] == expected["v18_agent"][field], (task_id, field)
