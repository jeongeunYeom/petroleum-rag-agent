"""Single-reviewer AI-assisted semantic adjudication, after deterministic grading.

One independently selected reviewer model scores anonymized system answers for
each frozen task. API failures or parse failures are recorded, never imputed.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import time

from run_experiment import HERE, MODELS, load_benchmark, request_json, write_once
from score_deterministic import TRACKS


PROMPT_VERSION = "final-v1-reviewer-1"
INSTRUCTIONS = """You are the single independent AI-assisted semantic reviewer for a fixed
petroleum-engineering benchmark. This is not human review. Judge ONLY the seven
anonymized answers against the supplied expected claims, numeric gold, source spans,
question, and evidence. Do not infer system identity. Do not repair answers.

For every answer return:
- exact_correct (boolean): all material requested parts correct; no critical omission.
- partial_or_better (boolean): at least one substantive correct requested part.
- claim_coverage (0..1): fraction of expected claims accurately conveyed.
- unsupported_claim_count (integer): unsupported *specific* engineering assertions.
  A closed-book answer is NOT automatically unsupported solely because no source
  was provided; only count a clearly invented, source-incompatible, or unjustified
  specific assertion. Do not penalize uncertainty or a cautious statement.
- hallucination (boolean): at least one fabricated factual, numerical, formula,
  source, or engineering assertion; missing citations alone do not qualify.
- engineering_contradiction_count (integer): explicit engineering relations contrary
  to expected claims or cited evidence.
- safe_refusal_correct (boolean or null): applicable only to unsupported_formula.
- false_premise_handled (boolean or null): applicable only to false_premise;
  requires explicit rejection and corrected relation, not vague hedging.
- formula_accuracy (boolean or null): applicable to calculations or explicit models.
- numeric_accuracy (boolean or null): applicable when numeric gold is supplied;
  check the correct output-to-value association, not mere presence of an input number.
- citation_semantic_support (number 0..1 or null): among actual citations in the
  answer, fraction whose *specific cited evidence excerpt* supports the adjacent
  engineering claim. Null if no citations or no evidence supplied. Citation ID
  existence is independently checked, so here evaluate meaning, not formatting.
- note: brief reason, no chain-of-thought.

Keep all named keys in every score object, using JSON null for non-applicable
fields. Be conservative about unsupported or contradictory statements. For missing answers,
score exact_correct=false, partial_or_better=false, claim_coverage=0, and leave
non-applicable fields null. Return only a JSON object with key 'scores' containing
one object per anonymous answer label. No Markdown or extra text."""


def answer_for(track: str, task_id: str) -> tuple[str, list[dict]]:
    path = TRACKS[track] / f"{task_id}.json"
    if not path.exists():
        return "", []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("error"):
        return "", []
    if track == "agent":
        response = payload.get("response") or {}
        evidence = [
            {"evidence_id": row.get("evidence_id"), "document": row.get("document"),
             "page": row.get("page"), "excerpt": row.get("excerpt", "")}
            for row in [*response.get("internal_sources", []), *response.get("figures", [])]
        ]
        return response.get("final_answer", ""), evidence
    return payload.get("answer", ""), payload.get("evidence", [])


def reviewer_input(task: dict, catalog: dict) -> tuple[dict, dict[str, str]]:
    tracks = list(TRACKS)
    random.Random(int(hashlib.sha256(task["task_id"].encode()).hexdigest()[:8], 16)).shuffle(tracks)
    mapping = {chr(65 + index): track for index, track in enumerate(tracks)}
    answers = {}
    for label, track in mapping.items():
        answer, evidence = answer_for(track, task["task_id"])
        answers[label] = {"answer": answer, "evidence": evidence}
    payload = {
        "task_id": task["task_id"], "question": task["question"],
        "category": task["category"], "expected_claims": task["expected_claims"],
        "required_numeric_result": task.get("required_numeric_result"),
        "expected_after_resume": task.get("expected_after_resume"),
        "tolerance": task.get("tolerance") or task.get("resume_tolerance"),
        "gold_source_spans": [catalog[key] for key in task["expected_source_ids"]],
        "answers": answers,
    }
    return payload, mapping


def review_one(task: dict, catalog: dict) -> dict:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY absent")
    item, mapping = reviewer_input(task, catalog)
    started = time.perf_counter()
    payload = request_json(
        "https://api.openai.com/v1/responses",
        {"model": MODELS["reviewer"], "instructions": INSTRUCTIONS,
         "input": json.dumps(item, ensure_ascii=False),
         "reasoning": {"effort": "low"}, "max_output_tokens": 5000,
         "tools": [], "store": False},
        headers={"Authorization": "Bearer " + key}, timeout=300,
    )
    text = payload.get("output_text") or "".join(
        part.get("text", "") for output in payload.get("output", [])
        for part in output.get("content", []) if part.get("type") == "output_text")
    result = {"task_id": task["task_id"], "prompt_version": PROMPT_VERSION,
              "reviewer_model_id": payload.get("model"),
              "reviewer_response_id": payload.get("id"),
              "wall_seconds": round(time.perf_counter() - started, 3),
              "mapping": mapping, "raw_review": text,
              "usage": payload.get("usage", {}), "provider_payload": payload}
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        parsed = json.loads(cleaned)
        scores = parsed["scores"]
        if set(scores) != set(mapping):
            raise ValueError("review labels incomplete")
        for record in scores.values():
            required_keys = {"exact_correct", "partial_or_better", "claim_coverage",
                             "unsupported_claim_count", "hallucination",
                             "engineering_contradiction_count", "safe_refusal_correct",
                             "false_premise_handled", "formula_accuracy", "numeric_accuracy",
                             "citation_semantic_support", "note"}
            if not required_keys.issubset(record):
                raise ValueError("review fields incomplete")
            if not isinstance(record.get("exact_correct"), bool) or not isinstance(record.get("partial_or_better"), bool):
                raise ValueError("review boolean fields malformed")
            coverage = record.get("claim_coverage")
            if not isinstance(coverage, (int, float)) or not 0 <= coverage <= 1:
                raise ValueError("review claim coverage malformed")
            for name in ("unsupported_claim_count", "engineering_contradiction_count"):
                if not isinstance(record.get(name), int) or record[name] < 0:
                    raise ValueError(f"review {name} malformed")
            if not isinstance(record.get("hallucination"), bool):
                raise ValueError("review hallucination malformed")
        result["scores_by_track"] = {mapping[label]: scores[label] for label in mapping}
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        result["parse_error"] = type(exc).__name__
    return result


def main() -> None:
    benchmark = load_benchmark()
    deterministic = HERE / "metrics/deterministic_rows.json"
    if not deterministic.exists():
        raise RuntimeError("Run deterministic scoring before semantic review")
    rows = json.loads(deterministic.read_text(encoding="utf-8"))
    if len(rows) != len(benchmark["tasks"]) * len(TRACKS):
        raise RuntimeError("Deterministic rows incomplete")
    for index, task in enumerate(benchmark["tasks"], 1):
        path = HERE / "review" / f"{task['task_id']}.json"
        if path.exists():
            print(f"{index:02d}/50 {task['task_id']} EXISTING", flush=True)
            continue
        try:
            result = review_one(task, benchmark["source_catalog"])
            if result.get("parse_error"):
                first_attempt = {"response_id": result.get("reviewer_response_id"),
                                 "raw_review": result.get("raw_review"),
                                 "parse_error": result["parse_error"]}
                result = review_one(task, benchmark["source_catalog"])
                result["parse_retry_count"] = 1
                result["first_parse_attempt"] = first_attempt
        except Exception as exc:
            result = {"task_id": task["task_id"], "prompt_version": PROMPT_VERSION,
                      "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        write_once(path, result)
        print(f"{index:02d}/50 {task['task_id']} "
              f"{result.get('error', result.get('parse_error', 'OK'))}", flush=True)
        if result.get("error"):
            print("BLOCKED semantic reviewer; no further calls", flush=True)
            sys.exit(2)


if __name__ == "__main__":
    main()
