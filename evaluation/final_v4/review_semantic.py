"""Blinded inputs and one independent AI-assisted semantic adjudicator."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
import time
import urllib.request
import urllib.error

from score_deterministic import TRACKS
from run_experiment import HERE, load_benchmark, write_once

REVIEWER_MODEL = "gpt-6-astra"


INSTRUCTIONS = """You are one independent AI-assisted semantic reviewer, not a human reviewer.
Judge five anonymized petroleum-engineering answers against one frozen task. Do not infer
system identity or repair answers. The final answer is scored; on clarification tasks,
also judge whether the first answer requested the missing information.

Return JSON only: {"scores":{"A":{...},"B":{...},...}}. Every score object must have:
- claim_verdicts: one boolean per expected claim, in the supplied order. True only
  when the answer accurately conveys the claim. A refusal is not a correct positive claim.
- partial_or_better: at least one substantive requested part is correct.
- unsupported_claim_count: count invented, source-incompatible, or unjustified specific
  engineering assertions. A closed-book answer is not automatically unsupported.
- hallucination: fabricated factual, numeric, formula, source, or engineering assertion.
  Missing citation by itself is not hallucination.
- engineering_contradiction_count: count wrong engineering relations.
- numeric_accuracy: boolean or null if no numeric gold. Match values to their named
  outputs; mere appearance of an input number is not sufficient.
- unit_accuracy: boolean or null if no expected unit. Units must attach to the
  corresponding output. Dimensionless values need no unit.
- formula_accuracy: boolean or null when a formula is requested or supplied.
- false_premise_handled: boolean or null. True requires explicit rejection of the
  erroneous premise, the corrected relation, and a supporting citation when evidence
  is provided. Never score agreement with a false premise as successful.
- safe_refusal_correct: boolean or null; applicable to unsupported tasks.
- citation_semantic_support: a FRACTION between 0.0 and 1.0, or null if the answer
  cites no KB/FIG IDs. Divide supported cited IDs by all cited IDs. Never return a
  raw count: if 2 of 4 citations support their claims, output 0.5, NOT 2. If every
  citation supports its claim, output 1.0. Do not rely on document/page similarity.
- note: concise evidence-based reason; no private chain-of-thought.

For clarification tasks, evaluate the initial question/clarification and final answer
together; a correct request for missing input should not be marked absent merely
because the final answer no longer repeats it.
Frozen gold source spans are answer keys, not evidence available to the systems.
If an answer is empty, all claim verdicts are false and partial_or_better is false.
No Markdown."""


def answer_for(track: str, task_id: str) -> dict:
    payload = json.loads((TRACKS[track] / f"{task_id}.json").read_text(encoding="utf-8"))
    if track == "agent":
        response = payload.get("response") or {}
        initial = payload.get("initial_response") or {}
        evidence = [{
            "evidence_id": item.get("evidence_id"), "document": item.get("document"),
            "page": item.get("page"), "excerpt": (item.get("excerpt") or item.get("source_note") or "")[:1600],
        } for item in [*response.get("internal_sources", []), *response.get("figures", [])]]
        return {"answer": response.get("final_answer", ""),
                "initial_answer": initial.get("clarification_question") or initial.get("final_answer") or "",
                "evidence": evidence}
    evidence = [{**item, "excerpt": str(item.get("excerpt") or "")[:1600]}
                for item in payload.get("evidence", [])]
    return {"answer": payload.get("answer", ""), "initial_answer": payload.get("initial_answer", ""),
            "evidence": evidence}


def review_input(task: dict, catalog: dict) -> tuple[dict, dict[str, str]]:
    tracks = list(TRACKS)
    random.Random(int(hashlib.sha256(task["task_id"].encode()).hexdigest()[:8], 16)).shuffle(tracks)
    mapping = {chr(65 + index): track for index, track in enumerate(tracks)}
    item = {
        "question": task["question"], "category": task["category"],
        "expected_claims": task["expected_claims"],
        "required_numeric_result": task.get("required_numeric_result"),
        "expected_after_resume": task.get("expected_after_resume"),
        "expected_units": task.get("expected_units"),
        "expected_formula": task.get("expected_formula") or task.get("user_formula"),
        "tolerance": task.get("tolerance") or task.get("resume_tolerance"),
        "gold_source_spans": [catalog[key] for key in task["expected_source_ids"]],
        "answers": {label: answer_for(track, task["task_id"]) for label, track in mapping.items()},
    }
    if task.get("continuation"):
        item["user_continuation_after_clarification"] = task["continuation"]
    return item, mapping


def extract_text(payload: dict) -> str:
    return payload.get("output_text") or "".join(
        part.get("text", "") for output in payload.get("output", [])
        for part in output.get("content", []) if part.get("type") == "output_text")


def call_reviewer(item: dict) -> tuple[dict, dict]:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY absent")
    body = {"model": REVIEWER_MODEL, "instructions": INSTRUCTIONS,
            "input": [{"role": "user", "content": json.dumps(item, ensure_ascii=False)}],
            "reasoning": {"effort": "low"}, "max_output_tokens": 6000,
            "tools": [], "store": False,
            "text": {"format": {"type": "json_object"}}}
    request = urllib.request.Request("https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=360) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Reviewer provider returned HTTP {exc.code}") from None
    scores = json.loads(extract_text(payload))
    if set(scores.get("scores", {})) != set(item["answers"]):
        raise ValueError("Reviewer label set mismatch")
    required = {"claim_verdicts", "partial_or_better", "unsupported_claim_count", "hallucination",
                "engineering_contradiction_count", "numeric_accuracy", "unit_accuracy", "formula_accuracy",
                "false_premise_handled", "safe_refusal_correct", "citation_semantic_support", "note"}
    for label, score in scores["scores"].items():
        if not required.issubset(score) or len(score["claim_verdicts"]) != len(item["expected_claims"]):
            raise ValueError(f"Reviewer schema/claim count mismatch: {label}")
        fraction = score["citation_semantic_support"]
        if fraction is not None and not (0 <= float(fraction) <= 1):
            raise ValueError(f"Reviewer citation fraction out of range: {label}")
    meta = {"reviewer_model_id": payload.get("model"), "response_id": payload.get("id"),
            "usage": payload.get("usage")}
    return scores["scores"], meta


def main() -> None:
    benchmark = load_benchmark()
    invalid_path = HERE / "invalid_tasks.json"
    invalid = {row["task_id"] for row in json.loads(invalid_path.read_text(encoding="utf-8")).get("invalid", [])} if invalid_path.exists() else set()
    outdir = HERE / "review/independent_openai"
    for index, task in enumerate(benchmark["tasks"], 1):
        task_id = task["task_id"]
        if task_id in invalid:
            continue
        path = outdir / f"{task_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("error"):
                raise RuntimeError(f"Review error requires inspection: {path}")
            print(f"{index:02d}/60 {task_id} EXISTING", flush=True)
            continue
        item, mapping = review_input(task, benchmark["source_catalog"])
        started = time.perf_counter()
        try:
            scores, meta = call_reviewer(item)
            result = {"task_id": task_id, **meta,
                      "scores_by_track": {mapping[label]: score for label, score in scores.items()},
                      "anonymized_label_map": mapping,
                      "wall_seconds": round(time.perf_counter() - started, 3)}
        except Exception as exc:
            result = {"task_id": task_id, "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                      "wall_seconds": round(time.perf_counter() - started, 3)}
        write_once(path, result)
        print(f"{index:02d}/60 {task_id} {result.get('error', 'OK')} {result['wall_seconds']:.1f}s", flush=True)
        if result.get("error"):
            raise RuntimeError("Review stopped; inspect recorded error before any retry")
        time.sleep(2)


if __name__ == "__main__":
    main()
