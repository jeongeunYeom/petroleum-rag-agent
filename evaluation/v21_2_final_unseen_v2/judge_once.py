"""One blinded semantic adjudication call for all systems on each task."""

from __future__ import annotations

import json
import os
import random
import re
import time
from uuid import uuid4

import requests

from common import HERE, frozen_assets, load, now, save


MODEL = "gpt-5.4-2026-03-05"
SYSTEMS = ["qwen_closed_book","v21_2_agent","gpt_reference"]
CITATION = re.compile(r"\[(?:KB|FIG|WEB)\d+\]")


def response_text(payload: dict) -> str:
    return "\n".join(part.get("text","") for output in payload.get("output",[])
                     for part in output.get("content",[]) if part.get("type")=="output_text").strip()


def package(system: str, task_id: str) -> dict:
    row = load(f"raw/{system}/{task_id}.json")
    answer = row.get("answer","")
    citations = {label[1:-1] for label in CITATION.findall(answer)}
    cited = {}
    if system == "v21_2_agent":
        run = row.get("run") or {}
        for source in (run.get("internal_sources") or []) + (run.get("figures") or []) + (run.get("web_sources") or []):
            source_id = source.get("evidence_id") or source.get("id")
            if source_id in citations:
                cited[source_id] = {"document":source.get("document"),"page":source.get("page"),
                                    "excerpt":(source.get("excerpt") or source.get("text") or "")[:1500]}
    return {"answer":answer,"cited_source_spans":cited}


def main() -> None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Exact semantic judge unavailable: OPENAI_API_KEY missing")
    frozen_assets()
    tasks = load("benchmark.json")["primary_tasks"]
    for index, task in enumerate(tasks):
        task_id = task["task_id"]
        path = HERE / "judge" / f"{task_id}.json"
        if path.exists():
            print(f"judge {index+1}/36 {task_id}: already reserved; no retry",flush=True)
            continue
        for system in SYSTEMS:
            raw = load(f"raw/{system}/{task_id}.json")
            if raw.get("status") != "completed":
                raise RuntimeError(f"{task_id} {system}: raw completion required before judging")
        labels = {chr(ord("A")+i):system for i,system in enumerate(
            random.Random(20261013+index).sample(SYSTEMS,len(SYSTEMS)))}
        anonymous = {label:package(system,task_id) for label,system in labels.items()}
        gold = {key:task[key] for key in ("question","category","answerable","required_goals",
                                               "required_claims","forbidden_claims","gold_sources",
                                               "numeric_targets","missing_inputs")}
        prompt = (
            "Single-reviewer AI-assisted semantic adjudication. The systems are anonymous and must be "
            "scored together under the same frozen rubric. Do not infer system identity. Return ONLY a "
            "JSON object with key responses, mapping each anonymous label to: claim_scores (one 0, 0.5, "
            "or 1 per required claim in order), goal_success (semantic goals before agent-specific execution "
            "gates), hallucination_free, error_labels, unnecessary_refusal, citation_semantic_support "
            "(boolean or null), source_span_correct (boolean or null), explicit_false_premise_rejection "
            "(boolean or null), final_numeric_outputs (array of {name,value,unit}), brief_rationale (one "
            "sentence). Citation existence does not prove semantic support. A safe omission alone is not "
            "hallucination. For false premises require explicit rejection and correction. For unanswerable "
            "requests, identifying the actual missing input and asking for it is success. Check material "
            "unsupported source claims, wrong formulas, wrong values/units and fabricated provenance. "
            "Do not provide private reasoning.\n\n" +
            json.dumps({"frozen_rubric":load("rubric.json"),"gold":gold,
                        "anonymous_responses":anonymous},ensure_ascii=False)
        )
        row = {"task_id":task_id,"attempt_id":str(uuid4()),"attempt_count":1,
               "attempted_at":now(),"judge_model":MODEL,"anonymous_labels":labels,"status":"reserved"}
        save(path,row)
        started = time.monotonic()
        try:
            response = requests.post("https://api.openai.com/v1/responses",
                headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                json={"model":MODEL,"input":prompt,"temperature":0,"store":False},timeout=1200)
            row["http_status"] = response.status_code
            if not response.ok:
                row["error_body"] = response.text[:500]
            response.raise_for_status()
            payload = response.json()
            row["actual_model"] = payload.get("model")
            row["usage"] = payload.get("usage",{})
            raw_text = response_text(payload)
            row["raw_text"] = raw_text
            clean = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            row["verdict"] = json.loads(clean)
            assert set(row["verdict"]["responses"]) == set(labels)
            row["status"] = "completed"
        except Exception as error:
            row.update(status="error",error=f"{type(error).__name__}: {error}")
        row.update(finished_at=now(),latency_seconds=round(time.monotonic()-started,3))
        save(path,row)
        print(f"judge {index+1}/36 {task_id}: {row['status']} {row['latency_seconds']}s",flush=True)


if __name__ == "__main__":
    main()
