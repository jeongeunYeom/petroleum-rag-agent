"""One local, condition-blind semantic reviewer; original judgments stay immutable."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_agentic_heldout import ROOT, _save


def _scores_schema(ids: list[str]) -> dict:
    return {"type": "object", "properties": {key: {"type": "integer", "enum": [0, 1, 2]} for key in ids}, "required": ids, "additionalProperties": False}


def _final_schema(item: dict) -> dict:
    criteria = [c["criterion_id"] for c in item["criteria"]]
    claims = [c["claim_id"] for c in item["ground_truth"]["claims"]]
    fields = {
        "criterion_scores": _scores_schema(criteria),
        "claim_results": {"type": "object", "properties": {key: {"type": "boolean"} for key in claims}, "required": claims, "additionalProperties": False},
        "hallucination": {"type": "boolean"},
        "engineering_contradiction": {"type": "boolean"},
        "evidence_grounding": {"type": "number"},
        "hypothesis_handling_correct": {"type": ["boolean", "null"]},
        "insufficient_evidence_handling_correct": {"type": ["boolean", "null"]},
        "numeric_extractions": {"type": "array", "items": {"type": "object", "properties": {
            "target_id": {"type": "string"}, "value": {"type": ["number", "null"]}, "unit": {"type": "string"}, "quote": {"type": "string"},
        }, "required": ["target_id", "value", "unit", "quote"], "additionalProperties": False}},
        "reviewer_notes": {"type": "string"},
    }
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def _process_schema(item: dict) -> dict:
    criteria = [c["criterion_id"] for c in item["criteria"]]
    fields = {
        "iteration_reviews": {"type": "array", "items": {"type": "object", "properties": {
            "iteration": {"type": "integer"},
            "criterion_scores": _scores_schema(criteria),
            "relevant_new_evidence_ids": {"type": "array", "items": {"type": "string"}},
            "engineering_error": {"type": "boolean"},
        }, "required": ["iteration", "criterion_scores", "relevant_new_evidence_ids", "engineering_error"], "additionalProperties": False}},
        "reviewer_notes": {"type": "string"},
    }
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


FINAL_SYSTEM = (
    "You are one independent, strict petroleum-engineering benchmark reviewer. The system producing the answer is hidden. "
    "Use only the fixed task, ground truth, and displayed source excerpts. For each required criterion score 0 absent/wrong, 1 partial, 2 fully correct. "
    "Check engineering meaning, not superficial keyword overlap. Mark material invented facts and contradictions. "
    "Evidence grounding is fraction 0..1 of material factual claims with actually supporting displayed citations; do not credit an unrelated citation. "
    "Hypothesis handling is null when no expected result. For contradicted targets, true requires explicit rejection and correction. "
    "Insufficient handling is null except insufficient-evidence tasks, where true requires an explicit evidence limit and no invented final result. "
    "For every numeric target extract only an actually stated final-answer number and unit, quoting the exact substring containing it; use null/empty if absent. "
    "Do not calculate the numeric pass yourself. Return JSON only."
)
PROCESS_SYSTEM = (
    "You are the same independent petroleum-engineering reviewer, but this is a separate process review. "
    "The system condition is hidden. Score each actual iteration candidate independently against the fixed criteria, 0/1/2, using only evidence available in that iteration or earlier. "
    "For each iteration, return relevant_new_evidence_ids as a subset of that iteration's evidence_added IDs that materially support a fixed criterion or correct an error. "
    "Changed query text alone is not progress. Mark engineering_error if the candidate asserts an incorrect engineering relation. "
    "Do not infer a candidate from a later iteration when scoring an earlier one. Return JSON only."
)


def review_one(item: dict, *, packet_type: str, model: str, timeout: float) -> dict:
    schema = _final_schema(item) if packet_type == "final_outcome" else _process_schema(item)
    system = FINAL_SYSTEM if packet_type == "final_outcome" else PROCESS_SYSTEM
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(item, ensure_ascii=False)}],
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0, "seed": 42, "num_predict": 1400},
    }
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    result = json.loads(payload["message"]["content"])
    if packet_type == "final_outcome":
        expected = {c["criterion_id"] for c in item["criteria"]}
        if set(result["criterion_scores"]) != expected or set(result["claim_results"]) != {c["claim_id"] for c in item["ground_truth"]["claims"]}:
            raise ValueError("Reviewer final keys mismatch")
        if not 0 <= result["evidence_grounding"] <= 1:
            raise ValueError("Reviewer grounding out of range")
    else:
        iterations = item["iterations"]
        reviews = result["iteration_reviews"]
        if len(reviews) != len(iterations):
            raise ValueError("Reviewer iteration count mismatch")
        for actual, review in zip(iterations, reviews):
            if actual["iteration"] != review["iteration"] or not set(review["relevant_new_evidence_ids"]) <= set(actual["evidence_added"]):
                raise ValueError("Reviewer process IDs mismatch")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet-type", choices=["final_outcome", "process"], required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model", default="gemma4:latest")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    packet_name = "agentic_heldout_v1_blind_review.json" if args.packet_type == "final_outcome" else "agentic_heldout_v1_process_review.json"
    packet = json.loads((ROOT / "evaluation/review" / packet_name).read_text(encoding="utf-8"))
    output = args.run_dir / ("final_review_original.json" if args.packet_type == "final_outcome" else "process_review_original.json")
    if output.exists() and not args.resume:
        raise FileExistsError(f"Original review exists: {output}; use --resume to preserve it")
    judgments = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {"packet_type": args.packet_type, "model": args.model, "items": {}}
    if judgments["model"] != args.model:
        raise ValueError("Reviewer model changed")
    key = "anonymous_answer_id" if args.packet_type == "final_outcome" else "anonymous_process_id"
    for index, item in enumerate(packet["items"], 1):
        anonymous_id = item[key]
        if anonymous_id in judgments["items"]:
            continue
        judgments["items"][anonymous_id] = review_one(item, packet_type=args.packet_type, model=args.model, timeout=args.timeout)
        _save(output, judgments)
        print(f"reviewed {index}/{len(packet['items'])} {anonymous_id}", flush=True)
    print(f"complete={len(judgments['items'])} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
