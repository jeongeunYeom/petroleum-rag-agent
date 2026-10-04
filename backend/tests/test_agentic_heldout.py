from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scripts.run_agentic_heldout import (
    BENCHMARK,
    MANIFEST,
    RUBRIC,
    _save,
    load_and_validate,
    make_request,
    run_one,
    sha256,
)


class FakeResponse:
    def model_dump(self, **_kwargs):
        return {"answer": "fixture"}


class FakeResearchAgent:
    def __init__(self):
        self.calls = []

    async def research(self, request):
        self.calls.append(request)
        return FakeResponse()


class FakeGoalAgent:
    def __init__(self):
        self.calls = []

    async def run(self, run_id, request):
        self.calls.append((run_id, request))
        return FakeResponse()


def test_benchmark_schema_and_freeze():
    data = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert len(data["tasks"]) == 18
    assert len({t["task_id"] for t in data["tasks"]}) == 18
    assert sum(len(t["success_criteria"]) for t in data["tasks"]) == 54
    assert sha256(BENCHMARK) == manifest["benchmark_sha256"]
    assert sha256(RUBRIC) == manifest["rubric_sha256"]
    for task in data["tasks"]:
        gt = task["ground_truth"]
        covered = {cid for claim in gt["claims"] for cid in claim["criterion_ids"]}
        covered.update(n["criterion_id"] for n in gt["numeric_targets"])
        assert {c["criterion_id"] for c in task["success_criteria"]} <= covered
        assert all(n["abs_tolerance"] > 0 for n in gt["numeric_targets"])
        assert all(set(c["source_ids"]) <= data["source_catalog"].keys() for c in gt["claims"])


def test_figure_mapping_manifest():
    data = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    figures = [f for task in data["tasks"] for f in ([task["ground_truth"]["figure"]] if "figure" in task["ground_truth"] else task["ground_truth"].get("figures", []))]
    assert len(figures) == 3
    assert {(f["page"], f["figure_number"], f["image_index"]) for f in figures} == {(440, "2", 2), (441, "4", 2), (441, "5", 3)}
    assert {f["image_file"] for f in figures} == {f["image_file"] for f in manifest["figure_assets"]}
    for f in manifest["figure_assets"]:
        if Path(f["image_file"]).exists():
            assert sha256(Path(f["image_file"])) == f["sha256"]


def test_condition_permissions_web_and_single_call(tmp_path):
    data = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    settings = json.loads(MANIFEST.read_text(encoding="utf-8"))["model_settings"]
    task = data["tasks"][0]
    research = FakeResearchAgent()
    goal = FakeGoalAgent()

    async def run():
        return [await run_one(task, condition, settings, research, goal, "SYNTHETIC") for condition in ("single_shot", "goal_agent", "full_agent")]

    rows = asyncio.run(run())
    assert len(research.calls) == 1
    assert len(goal.calls) == 2
    assert all(not r["request"]["use_external"] and r["request"]["use_internal"] for r in rows)
    assert all(r["request"]["model"] == "qwen3:8b" and r["request"]["seed"] == 42 and r["request"]["temperature"] == 0 for r in rows)
    assert rows[0]["request"]["query"].count("C1:") == 1
    assert rows[1]["request"]["allow_python_execution"] is False
    assert rows[1]["request"]["python_execution_approved"] is False
    assert rows[2]["request"]["allow_python_execution"] is True
    assert rows[2]["request"]["python_execution_approved"] is True
    path = tmp_path / "synthetic.json"
    _save(path, {"complete": True, "results": rows})
    assert len(json.loads(path.read_text(encoding="utf-8"))["results"]) == 3
