"""Single-reviewer AI-assisted semantic adjudication for frozen v2 outputs."""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import time

from run_experiment import HERE, MODELS, load_benchmark, request_json, write_once
from score_deterministic import TRACKS


PROMPT_VERSION = "final-v2-reviewer-1"
INSTRUCTIONS = """You are one independent AI-assisted semantic reviewer, not a human reviewer.
Judge five anonymized petroleum-engineering answers against one frozen task. Do not infer
system identity or repair answers. Evaluate the final answer; for a clarification task,
also evaluate whether its first answer requested the missing information.

Return JSON only: {"scores":{"A":{...},"B":{...},...}}. Each score object MUST have:
- claim_verdicts: boolean list in exactly the supplied expected_claims order. True only
  when the final answer accurately conveys that claim. An explicit refusal does not
  satisfy a substantive positive claim.
- partial_or_better: boolean, at least one substantive requested part correct.
- unsupported_claim_count: nonnegative integer of unsupported specific engineering
  assertions; no-source closed-book is NOT automatically unsupported. Count clearly
  invented, source-incompatible, or unjustified specific assertions.
- hallucination: boolean for a fabricated factual, numeric, formula, source, or
  engineering assertion. Missing citation alone is not hallucination.
- engineering_contradiction_count: nonnegative integer of wrong engineering relations.
- numeric_accuracy: boolean or null; use null only when no numeric gold. Associate
  each expected output with its value; mere appearance of an input number is not enough.
- unit_accuracy: boolean or null, units must attach to corresponding output; dimensionless
  output is acceptable without a unit.
- formula_accuracy: boolean or null when a formula is requested or supplied.
- false_premise_handled: boolean or null. True requires explicit rejection of the
  erroneous premise, correct statement, and supporting citation when supplied evidence
  is available.
- safe_refusal_correct: boolean or null; applicable to unsupported-formula tasks.
- citation_semantic_support: 0..1 or null. Of actual cited IDs, fraction whose exact
  supplied excerpt supports the adjacent claim. Do not judge only document/page similarity.
- note: concise evidence-based reason, no private chain-of-thought.

Be strict but fair. Source gold spans are answer keys, not evidence available to models.
No citations in an answer means citation_semantic_support=null. Do not infer missing
facts from background knowledge for citation support. If an answer is empty, all claim
verdicts false and partial_or_better false. No Markdown."""


def answer_for(track: str, task_id: str) -> dict:
    source = TRACKS[track] / f"{task_id}.json"
    if not source.exists():
        return {"answer": "", "initial_answer": "", "evidence": []}
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("error"):
        return {"answer": "", "initial_answer": "", "evidence": []}
    if track == "agent":
        response = payload.get("response") or {}
        initial = payload.get("initial_response") or {}
        evidence = [{"evidence_id": item.get("evidence_id"), "document": item.get("document"),
                     "page": item.get("page"), "excerpt": item.get("excerpt") or item.get("source_note") or ""}
                    for item in [*response.get("internal_sources", []), *response.get("figures", [])]]
        return {"answer": response.get("final_answer", ""),
                "initial_answer": initial.get("clarification_question") or initial.get("final_answer") or "",
                "evidence": evidence}
    return {"answer": payload.get("answer", ""),
            "initial_answer": payload.get("initial_answer", ""),
            "evidence": payload.get("evidence", [])}


def review_input(task: dict, catalog: dict) -> tuple[dict, dict[str, str]]:
    tracks = list(TRACKS)
    random.Random(int(hashlib.sha256(task["task_id"].encode()).hexdigest()[:8], 16)).shuffle(tracks)
    mapping = {chr(65 + index): track for index, track in enumerate(tracks)}
    item = {"question": task["question"], "category": task["category"],
            "expected_claims": task["expected_claims"],
            "required_numeric_result": task.get("required_numeric_result"),
            "expected_after_resume": task.get("expected_after_resume"),
            "expected_units": task.get("expected_units"),
            "expected_formula": task.get("expected_formula") or task.get("user_formula"),
            "tolerance": task.get("tolerance") or task.get("resume_tolerance"),
            "gold_source_spans": [catalog[key] for key in task["expected_source_ids"]],
            "answers": {label: answer_for(track, task["task_id"]) for label, track in mapping.items()}}
    return item, mapping


def review_one(task: dict, catalog: dict) -> dict:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY absent")
    item, mapping = review_input(task, catalog)
    started = time.perf_counter()
    payload = request_json("https://api.openai.com/v1/responses", {
        "model": MODELS["reviewer"], "instructions": INSTRUCTIONS,
        "input": json.dumps(item, ensure_ascii=False), "reasoning": {"effort": "low"},
        "max_output_tokens": 6500, "tools": [], "store": False},
        headers={"Authorization": "Bearer " + key}, timeout=300)
    raw = payload.get("output_text") or "".join(
        part.get("text", "") for output in payload.get("output", [])
        for part in output.get("content", []) if part.get("type") == "output_text")
    result = {"task_id": task["task_id"], "prompt_version": PROMPT_VERSION,
              "reviewer_model_id": payload.get("model"), "reviewer_response_id": payload.get("id"),
              "wall_seconds": round(time.perf_counter() - started, 3), "mapping": mapping,
              "raw_review": raw, "usage": payload.get("usage", {}), "provider_payload": payload}
    try:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        scores = json.loads(clean)["scores"]
        if set(scores) != set(mapping):
            raise ValueError("Answer labels incomplete")
        required = {"claim_verdicts", "partial_or_better", "unsupported_claim_count",
                    "hallucination", "engineering_contradiction_count", "numeric_accuracy",
                    "unit_accuracy", "formula_accuracy", "false_premise_handled",
                    "safe_refusal_correct", "citation_semantic_support", "note"}
        for row in scores.values():
            if not required.issubset(row):
                raise ValueError("Review fields incomplete")
            if len(row["claim_verdicts"]) != len(task["expected_claims"]) or not all(type(x) is bool for x in row["claim_verdicts"]):
                raise ValueError("Claim verdicts malformed")
            if type(row["partial_or_better"]) is not bool or type(row["hallucination"]) is not bool:
                raise ValueError("Boolean fields malformed")
            for name in ("unsupported_claim_count", "engineering_contradiction_count"):
                if type(row[name]) is not int or row[name] < 0:
                    raise ValueError(name + " malformed")
            support = row["citation_semantic_support"]
            if support is not None and (not isinstance(support, (float, int)) or not 0 <= support <= 1):
                raise ValueError("Citation support malformed")
        result["scores_by_track"] = {mapping[label]: row for label, row in scores.items()}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result["parse_error"] = type(exc).__name__
    return result


def main() -> None:
    benchmark = load_benchmark()
    rows_file = HERE / "metrics/deterministic_rows.json"
    if not rows_file.exists():
        raise RuntimeError("Run deterministic scoring before semantic review")
    rows = json.loads(rows_file.read_text(encoding="utf-8"))
    if len(rows) != len(benchmark["tasks"]) * len(TRACKS) or not all(row["available"] for row in rows if row["valid"]):
        raise RuntimeError("Valid-task deterministic rows incomplete")
    invalid_file = HERE / "invalid_tasks.json"
    invalid = {row["task_id"] for row in json.loads(invalid_file.read_text(encoding="utf-8")).get("invalid", [])} if invalid_file.exists() else set()
    for index, task in enumerate(benchmark["tasks"], 1):
        task_id = task["task_id"]
        if task_id in invalid:
            print(f"{index:02d}/60 {task_id} INVALID SKIP", flush=True)
            continue
        path = HERE / "review" / f"{task_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("parse_error") or existing.get("error"):
                retry_path = HERE / "review/retries" / f"{task_id}.json"
                if retry_path.exists():
                    retry = json.loads(retry_path.read_text(encoding="utf-8"))
                    if retry.get("parse_error") or retry.get("error"):
                        raise RuntimeError(f"Reviewer retry already failed; preserve both records: {retry_path}")
                    print(f"{index:02d}/60 {task_id} RETRY EXISTING", flush=True)
                    continue
                print(f"{index:02d}/60 {task_id} cooldown-completed single retry", flush=True)
                try:
                    retry = review_one(task, benchmark["source_catalog"])
                except Exception as exc:
                    retry = {"task_id": task_id, "prompt_version": PROMPT_VERSION,
                             "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
                write_once(retry_path, retry)
                if retry.get("parse_error") or retry.get("error"):
                    raise RuntimeError(f"Reviewer retry failed; preserve both records: {retry_path}")
                time.sleep(12)
                continue
            print(f"{index:02d}/60 {task_id} EXISTING", flush=True)
            continue
        try:
            result = review_one(task, benchmark["source_catalog"])
        except Exception as exc:
            result = {"task_id": task_id, "prompt_version": PROMPT_VERSION,
                      "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        write_once(path, result)
        print(f"{index:02d}/60 {task_id} {result.get('error') or result.get('parse_error') or 'OK'}", flush=True)
        if result.get("error") or result.get("parse_error"):
            print("STOP: review error; no silent retry", flush=True)
            sys.exit(2)
        time.sleep(12)


if __name__ == "__main__":
    main()
