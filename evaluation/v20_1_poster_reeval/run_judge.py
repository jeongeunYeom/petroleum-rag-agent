"""One blinded frozen-policy judge call per task; old scores remain immutable."""

from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime, timezone

import requests

from common import JUDGE_MODEL, ROOT, assert_frozen, old_json, read_json, save_json


TASKS = read_json(ROOT / "benchmark.json")["tasks"]
SYSTEMS = ["qwen_closed_book", "v18_agent", "v20_1_agent", "gpt_reference"]
CITATION = re.compile(r"\[(?:KB|FIG)\d+\]")


def answer_package(system: str, task_id: str) -> dict:
    row = (read_json(ROOT / "raw" / system / f"{task_id}.json") if system == "v20_1_agent"
           else old_json(f"raw/{system}/{task_id}.json"))
    answer = row.get("answer", "")
    sources = {}
    retrieved = []
    if system.endswith("_agent"):
        run = row.get("run") or {}
        cited = set(CITATION.findall(answer))
        for source in (run.get("internal_sources") or []) + (run.get("figures") or []):
            source_id = source.get("evidence_id")
            if len(retrieved) < 20:
                retrieved.append({"id": source_id, "document": source.get("document"),
                                  "page": source.get("page"), "excerpt": source.get("excerpt", "")[:700]})
            if f"[{source_id}]" in cited:
                sources[source_id] = {"document": source.get("document"), "page": source.get("page"),
                                      "excerpt": source.get("excerpt", "")[:1600]}
    return {"answer": answer, "cited_source_spans": sources, "retrieved_source_spans": retrieved}


def response_text(payload: dict) -> str:
    return "\n".join(part.get("text", "") for output in payload.get("output", [])
                     for part in output.get("content", []) if part.get("type") == "output_text").strip()


def main() -> None:
    assert_frozen()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    for index, task in enumerate(TASKS):
        task_id = task["task_id"]
        path = ROOT / "raw" / "judge" / f"{task_id}.json"
        if path.exists():
            print(f"judge {index+1}/24 {task_id}: already attempted; skip", flush=True)
            continue
        raw_path = ROOT / "raw" / "v20_1_agent" / f"{task_id}.json"
        if not raw_path.exists():
            raise RuntimeError(f"{task_id}: product raw output missing")
        raw = read_json(raw_path)
        if raw.get("status") != "completed" or raw.get("attempt_count") != 1 or not raw.get("run"):
            raise RuntimeError(f"{task_id}: product run incomplete; no judge call")
        systems = SYSTEMS.copy()
        random.Random(20261012 + index).shuffle(systems)
        labels = {chr(ord("A") + i): system for i, system in enumerate(systems)}
        responses = {label: answer_package(system, task_id) for label, system in labels.items()}
        gold = {key: task.get(key) for key in (
            "question", "category", "answerable", "required_claims", "gold_answer_summary",
            "reasoning_rubric", "supporting_spans", "numeric_gold", "accepted_units",
            "false_premise_correction", "required_missing_inputs",
        ) if task.get(key) is not None}
        prompt = (
            "Single-reviewer AI-assisted semantic adjudication. Evaluate every anonymous response "
            "against the SAME frozen rubric. Do not infer system identity. Citation presence alone "
            "does not prove a claim; check cited span semantics. Score each required claim as exactly "
            "1, 0.5, or 0. Mark goal_success only if all material requirements are met. Mark "
            "hallucination_free false only for a materially false or invented factual statement, "
            "not mere omission. For false premises require explicit rejection and correction. "
            "For insufficient inputs, a precise clarification can be success. For a numerical "
            "task, report the stated final numerical outputs but leave tolerance/unit comparison "
            "to deterministic scoring. Use only these error labels when applicable: "
            "fabricated_fact, unsupported_claim, incorrect_refusal, omission, wrong_calculation, "
            "wrong_unit, wrong_formula, wrong_formula_provenance. Return ONLY JSON with key 'responses'; each anonymous label "
            "maps to {claim_scores: number[], goal_success: boolean, hallucination_free: boolean, "
            "error_labels: string[], unnecessary_refusal: boolean, citation_semantic_support: "
            "boolean|null, relevant_evidence_retrieved: boolean|null, "
            "final_numeric_outputs: [{name:string,value:number,unit:string}], "
            "brief_rationale: string}. No chain-of-thought.\n\n"
            + json.dumps({"frozen_gold": gold, "anonymous_responses": responses}, ensure_ascii=False)
        )
        row = {"task_id": task_id, "attempt_count": 1,
               "attempted_at": datetime.now(timezone.utc).isoformat(),
               "judge_model": JUDGE_MODEL, "anonymous_labels": labels, "status": "attempted"}
        save_json(path, row)  # reserve before the sole model call
        started = time.perf_counter()
        try:
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": JUDGE_MODEL, "input": prompt, "temperature": 0, "store": False}, timeout=900,
            )
            row["http_status"] = response.status_code
            if not response.ok:
                row["error_body"] = response.text[:1000]
            response.raise_for_status()
            payload = response.json()
            row["response_id"] = payload.get("id")
            row["actual_model"] = payload.get("model")
            row["usage"] = payload.get("usage", {})
            row["raw_text"] = response_text(payload)
            row["verdict"] = json.loads(row["raw_text"].removeprefix("```json").removesuffix("```").strip())
            row["status"] = "completed"
        except Exception as error:
            row["status"] = "error"
            row["error"] = f"{type(error).__name__}: {error}"
        row["latency_seconds"] = round(time.perf_counter() - started, 3)
        row["finished_at"] = datetime.now(timezone.utc).isoformat()
        save_json(path, row)
        print(f"judge {index+1}/24 {task_id}: {row['status']} ({row['latency_seconds']}s)", flush=True)


if __name__ == "__main__":
    main()
