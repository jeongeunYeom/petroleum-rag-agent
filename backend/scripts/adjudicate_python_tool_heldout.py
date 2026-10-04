"""Post-hoc, itemized manual QA of all 20 rows; never overwrite original scores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_python_tool_heldout import BENCHMARK, MANIFEST, ROOT, _save, sha256  # noqa: E402
from scripts.score_python_tool_heldout import aggregate, write_csv  # noqa: E402


ADJUDICATION = ROOT / "evaluation/review/python_tool_heldout_v1_strict_adjudication_v1_1.json"


def strict_rows(run_dir: Path) -> tuple[list[dict], dict]:
    source = json.loads((run_dir.parents[2] / "python_tool_heldout_v1_comparison.json").read_text(encoding="utf-8"))
    decisions = json.loads(ADJUDICATION.read_text(encoding="utf-8"))["task_decisions"]
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    tasks = {task["task_id"]: task for task in benchmark["tasks"]}
    raw = {condition: json.loads((run_dir / f"{condition}.json").read_text(encoding="utf-8"))["results"]
           for condition in ("python_off", "python_on")}
    if set(decisions) != set(tasks) or len(source["rows"]) != 20:
        raise ValueError("Adjudication must cover all ten tasks and twenty rows")
    for index, task in enumerate(benchmark["tasks"]):
        left, right = raw["python_off"][index]["response"], raw["python_on"][index]["response"]
        if left["final_answer"] != right["final_answer"]:
            raise ValueError(f"Paired answers differ: {task['task_id']}; task-level adjudication invalid")
        if [(s["chunk_id"], s["page"]) for s in left["internal_sources"]] != [(s["chunk_id"], s["page"]) for s in right["internal_sources"]]:
            raise ValueError(f"Paired evidence differs: {task['task_id']}; task-level adjudication invalid")
    rows = []
    for original in source["rows"]:
        row = dict(original)
        task = tasks[row["task_id"]]
        decision = decisions[row["task_id"]]
        expected_criteria = {c["criterion_id"] for c in task["success_criteria"]}
        if set(decision["criterion_passed"]) != expected_criteria:
            raise ValueError(f"Missing criterion: {row['task_id']}")
        expected_targets = {target["name"] for target in task["ground_truth"]["numeric_targets"]}
        if not set(decision["unit_supported_targets"]) <= expected_targets:
            raise ValueError(f"Unknown unit target: {row['task_id']}")
        for target in task["ground_truth"]["numeric_targets"]:
            if row["final_numeric_targets"][target["name"]]["passed"] and target["name"] not in decision["unit_supported_targets"]:
                raise ValueError(f"Manual unit audit contradicts a passed numeric target: {row['task_id']}")
        row["criteria_passed"] = decision["criterion_passed"]
        row["external_coverage"] = sum(decision["criterion_passed"].values()) / len(expected_criteria)
        row["hallucination"] = decision["hallucination"]
        row["engineering_contradiction"] = decision["engineering_contradiction"]
        row["goal_success"] = all(decision["criterion_passed"].values()) and not decision["engineering_contradiction"]
        row["unit_supported_targets"] = decision["unit_supported_targets"]
        row["unit_accuracy"] = len(decision["unit_supported_targets"]) / len(expected_targets) if expected_targets else None
        row["adjudication_reason"] = decision["reason"]
        if row["python_expected"] == "required" and not row["goal_success"]:
            if row["condition"] == "python_off":
                row["failure_attribution"] = "python_disabled_baseline"
            elif not row["tool_selected"]:
                row["failure_attribution"] = "tool_not_selected"
            else:
                matching = next(r for r in raw["python_on"] if r["task_id"] == row["task_id"])
                stages = [it.get("python_trace", {}).get("blocked_stage") for it in matching["response"]["iterations"] if it.get("python_trace")]
                row["failure_attribution"] = "input_fact_failure" if "input_fact_verification_failed" in stages else "other"
        rows.append(row)
    summary = aggregate(benchmark["tasks"], rows)
    for category in ("overall", "required"):
        for condition in ("python_off", "python_on"):
            relevant = [r for r in rows if r["condition"] == condition and
                        (category == "overall" or r["python_expected"] == "required")]
            total = sum(r["numeric_total"] for r in relevant)
            summary[category][condition]["unit_accuracy"] = sum(len(r["unit_supported_targets"]) for r in relevant) / total if total else None
    stages = ("tool_selected", "plan_present", "permission_passed", "facts_verified", "call_boundary_reached",
              "code_generated", "sandbox_validation_passed", "subprocess_reached", "result_validation_passed")
    required_on = [r for r in rows if r["condition"] == "python_on" and r["python_expected"] == "required"]
    summary["funnel"] = {stage: sum(all(r[earlier] for earlier in stages[:index+1]) for r in required_on)
                         for index, stage in enumerate(stages)}
    summary["reviewer_qa"] = {"original_method": "single AI-assisted semantic reviewer",
                              "manual_qa_rows": 20, "paired_answer_and_source_identical_count": 10,
                              "original_review_preserved": True, "numeric_deterministic_authoritative": True}
    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--tables-only", action="store_true", help="Export strict poster/funnel tables from the saved adjudication")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if sha256(BENCHMARK) != manifest["benchmark_sha256"]:
        raise ValueError("Frozen benchmark changed")
    output = args.run_dir.parents[2]
    json_path = output / "python_tool_heldout_v1_comparison_strict_v1_1.json"
    csv_path = output / "python_tool_heldout_v1_comparison_strict_v1_1.csv"
    if args.tables_only:
        saved = json.loads(json_path.read_text(encoding="utf-8"))
        rows, summary = saved["rows"], saved["summary"]
        poster = output / "python_tool_heldout_v1_poster_strict_v1_1.csv"
        funnel = output / "python_tool_heldout_v1_funnel_strict_v1_1.csv"
        if poster.exists() or funnel.exists():
            raise FileExistsError("Strict poster/funnel tables already exist")
        write_csv(poster, [{"metric": metric, "python_off": summary["overall"]["python_off"][metric],
                            "python_on": summary["overall"]["python_on"][metric]}
                           for metric in summary["overall"]["python_off"]])
        stages = ("tool_selected", "plan_present", "permission_passed", "facts_verified",
                  "call_boundary_reached", "code_generated", "sandbox_validation_passed",
                  "subprocess_reached", "result_validation_passed")
        funnel_rows = []
        for row in rows:
            if row["condition"] != "python_on":
                continue
            item = {"task_id": row["task_id"], "python_expected": row["python_expected"]}
            for index, stage in enumerate(stages):
                item[stage] = all(row[earlier] for earlier in stages[:index+1])
            item["blocked_stage"] = row["failure_attribution"] or row["blocked_stage"]
            item["calc_id"] = row["calc_id"]
            funnel_rows.append(item)
        write_csv(funnel, funnel_rows)
        print(f"strict_poster={poster}\nstrict_funnel={funnel}")
        return 0
    rows, summary = strict_rows(args.run_dir)
    if json_path.exists() or csv_path.exists():
        raise FileExistsError("Strict adjudication output already exists; original QA result is immutable")
    _save(json_path, {"summary": summary, "rows": rows, "run_dir": str(args.run_dir),
                      "adjudication_source": str(ADJUDICATION)})
    write_csv(csv_path, rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
