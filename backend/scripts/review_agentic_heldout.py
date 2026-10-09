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


def _final_schema(item: dict, *, strict: bool = False) -> dict:
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
    if strict:
        fields["criterion_quotes"] = {"type": "object", "properties": {key: {"type": "string"} for key in criteria}, "required": criteria, "additionalProperties": False}
        fields["contradiction_quote"] = {"type": "string"}
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def _process_schema(item: dict) -> dict:
    criteria = [c["criterion_id"] for c in item["criteria"]]
    fields = {
        "iteration_reviews": {"type": "array", "minItems": len(item["iterations"]), "maxItems": len(item["iterations"]), "items": {"type": "object", "properties": {
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
STRICT_FINAL_SYSTEM = FINAL_SYSTEM + (
    " This is a corrected, quote-grounded review of the same frozen benchmark, not a new benchmark. "
    "Assess ONLY candidate_final_answer, not the target facts printed in criteria or ground_truth. "
    "For EACH criterion give an exact verbatim criterion_quote from candidate_final_answer supporting your score; "
    "for score 0 use an empty string, and never award 2 if any required component is absent from the answer. "
    "A correct formula without the required numerical result is at most partial. "
    "Read the ENTIRE answer for contradictions, including after a correct sentence. If it later says radial flow has pressure and derivative overlapping at unit slope, mark engineering_contradiction true and false-premise handling false. "
    "Supply contradiction_quote verbatim when an engineering contradiction exists, otherwise empty. "
    "When the task asks for an unknowable reserves value but allows a calculable OOIP, giving OOIP while explicitly refusing unique reserves is correct insufficient-evidence handling."
)
PROCESS_SYSTEM = (
    "You are the same independent petroleum-engineering reviewer, but this is a separate process review. "
    "The system condition is hidden. Score each actual iteration candidate independently against the fixed criteria, 0/1/2, using only evidence available in that iteration or earlier. "
    "For each iteration, return relevant_new_evidence_ids as a subset of that iteration's evidence_added IDs that materially support a fixed criterion or correct an error. "
    "Changed query text alone is not progress. Mark engineering_error if the candidate asserts an incorrect engineering relation. "
    "Do not infer a candidate from a later iteration when scoring an earlier one. Return JSON only."
)


def review_one(item: dict, *, packet_type: str, model: str, timeout: float, invalid_log: Path | None = None, strict: bool = False) -> dict:
    schema = _final_schema(item, strict=strict) if packet_type == "final_outcome" else _process_schema(item)
    system = STRICT_FINAL_SYSTEM if strict else (FINAL_SYSTEM if packet_type == "final_outcome" else PROCESS_SYSTEM)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(item, ensure_ascii=False)}]
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0, "seed": 42, "num_predict": 1400},
    }
    for attempt in range(3):
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        raw = payload["message"]["content"]
        try:
            result = json.loads(raw)
            if packet_type == "final_outcome":
                expected = {c["criterion_id"] for c in item["criteria"]}
                if set(result["criterion_scores"]) != expected or set(result["claim_results"]) != {c["claim_id"] for c in item["ground_truth"]["claims"]}:
                    raise ValueError("Reviewer final keys mismatch")
                if not 0 <= result["evidence_grounding"] <= 1:
                    raise ValueError("Reviewer grounding out of range")
                if strict:
                    answer = item["candidate_final_answer"]
                    gated = []
                    for criterion_id, score in result["criterion_scores"].items():
                        quote = result["criterion_quotes"][criterion_id]
                        if score and (not quote or quote not in answer):
                            result["criterion_scores"][criterion_id] = 0
                            result["criterion_quotes"][criterion_id] = ""
                            gated.append(criterion_id)
                    contradiction_quote = result["contradiction_quote"]
                    if result["engineering_contradiction"] and (not contradiction_quote or contradiction_quote not in answer):
                        result["contradiction_quote"] = ""
                        gated.append("contradiction_quote_missing")
                    result["quote_gated_criteria"] = gated
                    if gated and invalid_log is not None:
                        with invalid_log.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps({"item_id": item["anonymous_answer_id"], "attempt": attempt + 1, "error": "Quote gate: " + ", ".join(gated), "raw": raw}, ensure_ascii=False) + "\n")
            else:
                iterations = item["iterations"]
                reviews = result["iteration_reviews"]
                if len(reviews) != len(iterations):
                    raise ValueError(f"Reviewer iteration count mismatch: expected {len(iterations)}, got {len(reviews)}")
                for actual, review in zip(iterations, reviews):
                    if actual["iteration"] != review["iteration"]:
                        raise ValueError(f"Reviewer process iteration mismatch: expected {actual['iteration']}, got {review['iteration']}")
            return result
        except (ValueError, KeyError, TypeError) as exc:
            if invalid_log is not None:
                with invalid_log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"item_id": item.get("anonymous_process_id", item.get("anonymous_answer_id")), "attempt": attempt + 1, "error": str(exc), "raw": raw}, ensure_ascii=False) + "\n")
            if attempt == 2:
                raise
            messages.extend([
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"Your previous JSON is invalid: {exc}. Return the complete schema again. For iteration i, relevant_new_evidence_ids must ONLY use that same iteration's evidence_added IDs; use [] when none qualify."},
            ])
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet-type", choices=["final_outcome", "process"], required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model", default="gemma4:latest")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--strict-final-review", action="store_true")
    args = parser.parse_args()
    if args.strict_final_review and args.packet_type != "final_outcome":
        parser.error("--strict-final-review requires --packet-type final_outcome")
    packet_name = "agentic_heldout_v1_blind_review.json" if args.packet_type == "final_outcome" else "agentic_heldout_v1_process_review.json"
    packet = json.loads((ROOT / "evaluation/review" / packet_name).read_text(encoding="utf-8"))
    output = args.run_dir / ("final_review_strict_v1_1.json" if args.strict_final_review else ("final_review_original.json" if args.packet_type == "final_outcome" else "process_review_original.json"))
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
        judgments["items"][anonymous_id] = review_one(item, packet_type=args.packet_type, model=args.model, timeout=args.timeout, invalid_log=args.run_dir / "review_invalid_attempts.jsonl", strict=args.strict_final_review)
        _save(output, judgments)
        print(f"reviewed {index}/{len(packet['items'])} {anonymous_id}", flush=True)
    print(f"complete={len(judgments['items'])} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
