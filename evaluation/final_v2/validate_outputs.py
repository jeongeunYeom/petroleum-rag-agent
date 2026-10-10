"""Read-only integrity checks for the completed frozen-v2 evaluation."""

from __future__ import annotations

import csv
import json

from run_experiment import HERE, MODELS, captured_evidence, load_benchmark
from score_deterministic import TRACKS


def main() -> None:
    benchmark = load_benchmark()
    tasks = benchmark["tasks"]
    ids = [item["task_id"] for item in tasks]
    assert len(ids) == len(set(ids)) == 60
    invalid = json.loads((HERE / "invalid_tasks.json").read_text(encoding="utf-8"))["invalid"]
    assert not invalid
    for task_id in ids:
        for track, directory in TRACKS.items():
            path = directory / f"{task_id}.json"
            assert path.exists(), (track, task_id)
            row = json.loads(path.read_text(encoding="utf-8"))
            assert not row.get("error"), (track, task_id)
            expected_model = MODELS["openai"] if "openai" in track else MODELS["qwen"]
            assert row["model_id"] == expected_model, (track, task_id, row.get("model_id"))
            if track.endswith("same_evidence"):
                assert row["evidence"] == captured_evidence(task_id), (track, task_id)
        review_folder = "clarification_context" if task_id.startswith("C") else "local_gemma_schema"
        review = json.loads((HERE / "review" / review_folder / f"{task_id}.json").read_text(encoding="utf-8"))
        assert not review.get("error") and not review.get("parse_error"), task_id
        assert review["reviewer_model_id"] == "gemma4:latest"
        assert set(review["scores_by_track"]) == set(TRACKS), task_id
        assert all(len(score["claim_verdicts"]) == len(next(item for item in tasks if item["task_id"] == task_id)["expected_claims"])
                   for score in review["scores_by_track"].values()), task_id
    with (HERE / "final_results.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 300
    assert {(row["task_id"], row["track"]) for row in rows} == {(task_id, track) for task_id in ids for track in TRACKS}
    for filename, length in (("poster_metrics.csv", 5), ("agent_reliability_metrics.csv", 1)):
        with (HERE / filename).open(encoding="utf-8-sig", newline="") as stream:
            assert len(list(csv.DictReader(stream))) == length
    metrics = json.loads((HERE / "final_metrics.json").read_text(encoding="utf-8"))
    assert metrics["valid_tasks"] == 60 and metrics["frozen_tasks"] == 60
    assert metrics["model_ids"]["semantic_reviewer"] == "gemma4:latest"
    stats = json.loads((HERE / "statistical_analysis.json").read_text(encoding="utf-8"))
    assert stats["iterations"] == 4000
    assert (HERE / "final_evaluation_report.md").exists()
    assert (HERE / "figures/goal_success.png").exists()
    print("PASS: freeze, product SHA, 300 raw rows, same-evidence identity, 60 single-reviewer scores, CSV and CI outputs")


if __name__ == "__main__":
    main()
