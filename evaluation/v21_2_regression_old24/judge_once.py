"""One blinded observed-set review per task; no product retry or tuning."""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import time
from datetime import datetime, timezone

import requests

from run_once import BENCHMARK_REF, BENCHMARK_SHA256, HERE, REPO, PRODUCT_SHA, save


MODEL = "gpt-5.4-2026-03-05"
OLD_COMMIT = "e59c2959231c7997c2ab883a66708e91c14962e3"
V20_ROOT = REPO.parent / "petroleum-rag-agent-v20-1-reeval" / "evaluation" / "v20_1_poster_reeval"
SYSTEMS = ["qwen_closed_book", "v18_agent", "v20_1_agent", "v21_2_agent", "gpt_reference"]
CITATION = re.compile(r"\[(?:KB|FIG)\d+\]")


def read_old(system: str, task_id: str) -> dict:
    if system == "v21_2_agent":
        return json.loads((HERE / "raw" / f"{task_id}.json").read_text(encoding="utf-8"))
    if system == "v20_1_agent":
        return json.loads((V20_ROOT / "raw" / system / f"{task_id}.json").read_text(encoding="utf-8"))
    blob = subprocess.check_output(["git", "show", f"{OLD_COMMIT}:evaluation/v18_poster_final/"
                                    f"raw/{system}/{task_id}.json"], cwd=REPO)
    return json.loads(blob)


def package(system: str, task_id: str) -> dict:
    row = read_old(system, task_id)
    answer = row.get("answer", "")
    run = row.get("run") or {}
    cited = set(CITATION.findall(answer))
    sources, retrieved = {}, []
    if system.endswith("_agent"):
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
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY unavailable; observed semantic metrics cannot be scored")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip() != PRODUCT_SHA:
        raise RuntimeError("product differs from freeze SHA")
    blob = subprocess.check_output(["git", "show", BENCHMARK_REF], cwd=REPO)
    if __import__("hashlib").sha256(blob).hexdigest() != BENCHMARK_SHA256:
        raise RuntimeError("observed task bytes differ from frozen reference")
    for index, task in enumerate(json.loads(blob)["tasks"]):
        task_id = task["task_id"]
        path = HERE / "judge" / f"{task_id}.json"
        if path.exists():
            print(f"judge {index+1}/24 {task_id}: already attempted; skip", flush=True)
            continue
        if not (HERE / "raw" / f"{task_id}.json").exists():
            raise RuntimeError(f"{task_id}: product raw result missing")
        labels = {chr(ord("A") + i): system for i, system in enumerate(
            random.Random(20261012 + index).sample(SYSTEMS, len(SYSTEMS)))}
        gold = {key: task.get(key) for key in (
            "question", "category", "answerable", "required_claims", "gold_answer_summary",
            "reasoning_rubric", "supporting_spans", "numeric_gold", "accepted_units",
            "false_premise_correction", "required_missing_inputs") if task.get(key) is not None}
        responses = {label: package(system, task_id) for label, system in labels.items()}
        prompt = (
            "Single-reviewer AI-assisted semantic adjudication. Evaluate every anonymous response "
            "against the SAME frozen rubric. Do not infer system identity. Citation presence alone "
            "does not prove a claim; check cited span semantics. Score each required claim as exactly "
            "1, 0.5, or 0. Mark goal_success only if all material requirements are met. Mark "
            "hallucination_free false only for a materially false or invented factual statement, "
            "not mere omission. For false premises require explicit rejection and correction. For "
            "insufficient inputs, a precise clarification can be success. For a numerical task, "
            "report the stated final numerical outputs but leave tolerance/unit comparison to "
            "deterministic scoring. Use only these error labels when applicable: fabricated_fact, "
            "unsupported_claim, incorrect_refusal, omission, wrong_calculation, wrong_unit, "
            "wrong_formula, wrong_formula_provenance. Return ONLY JSON with key 'responses'; each "
            "anonymous label maps to {claim_scores: number[], goal_success: boolean, "
            "hallucination_free: boolean, error_labels: string[], unnecessary_refusal: boolean, "
            "citation_semantic_support: boolean|null, relevant_evidence_retrieved: boolean|null, "
            "final_numeric_outputs: [{name:string,value:number,unit:string}], brief_rationale: string}. "
            "No chain-of-thought.\n\n" +
            json.dumps({"frozen_gold": gold, "anonymous_responses": responses}, ensure_ascii=False))
        row = {"task_id": task_id, "product_sha": PRODUCT_SHA, "attempt_count": 1,
               "attempted_at": datetime.now(timezone.utc).isoformat(),
               "judge_model": MODEL, "anonymous_labels": labels, "status": "attempted"}
        save(path, row)
        started = time.monotonic()
        try:
            response = requests.post("https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": MODEL, "input": prompt, "temperature": 0, "store": False}, timeout=900)
            row["http_status"] = response.status_code
            if not response.ok:
                row["error_body"] = response.text[:1000]
            response.raise_for_status()
            payload = response.json()
            row["actual_model"] = payload.get("model")
            row["usage"] = payload.get("usage", {})
            row["raw_text"] = response_text(payload)
            row["verdict"] = json.loads(row["raw_text"].removeprefix("```json").removesuffix("```").strip())
            row["status"] = "completed"
        except Exception as error:
            row.update(status="error", error=f"{type(error).__name__}: {error}")
        row["latency_seconds"] = round(time.monotonic() - started, 3)
        row["finished_at"] = datetime.now(timezone.utc).isoformat()
        save(path, row)
        print(f"judge {index+1}/24 {task_id}: {row['status']} {row['latency_seconds']}s", flush=True)


if __name__ == "__main__":
    main()
