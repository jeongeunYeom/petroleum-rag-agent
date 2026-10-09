from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from prepare_semantic_review import REVIEW_COLUMNS
from run_external_baseline import ProviderResponse, Prompt, _request_json, load_json


ALLOWED_FAILURES = {
    "generation_omission", "engineering_error", "safe_refusal", "figure_failure",
    "numeric_failure", "citation_failure", "partial_answer", "other",
}


def judge(item: dict[str, Any], *, model: str, timeout: float) -> dict[str, Any]:
    rubric = item["atomic_rubric"]
    claim_count = len(rubric["required_claims"])
    system = """You are a strict, model-neutral petroleum-engineering benchmark grader.
Judge only semantic support in the answer against the supplied atomic rubric. Do not reward verbosity.
A claim is satisfied only when the answer states its engineering meaning correctly. Mark contradictions and
unsupported factual inventions. A concise uncertainty statement is a safe refusal only when it does not also
make unsupported claims. Return JSON only. You do not know which system produced the answer."""
    user = json.dumps(
        {
            "question": item["question"],
            "answer": item["answer"],
            "rubric": rubric,
            "output_requirements": {
                "claim_results": f"array of exactly {claim_count} booleans",
                "contradiction_present": "boolean",
                "false_premise_recognized": "boolean",
                "false_premise_corrected": "boolean",
                "numeric_correct": "boolean",
                "citation_correct": "boolean",
                "figure_correct": "boolean",
                "axis_correct": "boolean",
                "series_correct": "boolean",
                "figure_element_correct": "boolean",
                "figure_interpretation_correct": "boolean",
                "safe_refusal": "boolean",
                "hallucination_present": "boolean",
                "failure_attribution": "array using generation_omission, engineering_error, safe_refusal, figure_failure, numeric_failure, citation_failure, partial_answer, other",
                "reviewer_notes": "one short sentence",
            },
        },
        ensure_ascii=False,
    )
    schema = {
        "type": "object",
        "properties": {
            "claim_results": {
                "type": "array", "items": {"type": "boolean"},
                "minItems": claim_count, "maxItems": claim_count,
            },
            **{
                name: {"type": "boolean"}
                for name in (
                    "contradiction_present", "false_premise_recognized", "false_premise_corrected",
                    "numeric_correct", "citation_correct", "figure_correct", "axis_correct",
                    "series_correct", "figure_element_correct", "figure_interpretation_correct",
                    "safe_refusal", "hallucination_present",
                )
            },
            "failure_attribution": {"type": "array", "items": {"type": "string"}},
            "reviewer_notes": {"type": "string"},
        },
        "required": [
            "claim_results", "contradiction_present", "false_premise_recognized",
            "false_premise_corrected", "numeric_correct", "citation_correct", "figure_correct",
            "axis_correct", "series_correct", "figure_element_correct",
            "figure_interpretation_correct", "safe_refusal", "hallucination_present",
            "failure_attribution", "reviewer_notes",
        ],
    }
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0, "seed": 20261002, "num_predict": 500},
    }
    request = __import__("urllib.request").request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    payload = _request_json(request, timeout=timeout)
    response = ProviderResponse(payload["message"]["content"])
    result = json.loads(response.answer)
    claims = result.get("claim_results", [])
    if len(claims) != claim_count or not all(isinstance(value, bool) for value in claims):
        raise ValueError(f"{item['anonymous_answer_id']}: invalid claim_results")
    return result


def bool_cell(value: Any) -> str:
    return "1" if bool(value) else "0"


def to_row(item: dict[str, Any], result: dict[str, Any]) -> dict[str, str]:
    rubric = item["atomic_rubric"]
    claims = result["claim_results"]
    contradiction = bool(result.get("contradiction_present"))
    refusal = bool(result.get("safe_refusal"))
    overall = 2 if all(claims) and not contradiction and not refusal else 1 if any(claims) and not refusal else 0
    failures = [value for value in result.get("failure_attribution", []) if value in ALLOWED_FAILURES]
    row = {column: "" for column in REVIEW_COLUMNS}
    row.update(
        anonymous_answer_id=item["anonymous_answer_id"],
        question_id=item["question_id"],
        evaluation_condition=item["condition"],
        contradiction_present=bool_cell(contradiction),
        safe_refusal=bool_cell(refusal),
        hallucination_present=bool_cell(result.get("hallucination_present")),
        overall_score_0_1_2=str(overall),
        failure_attribution=";".join(failures),
        reviewer_notes=str(result.get("reviewer_notes", ""))[:500],
    )
    for index, value in enumerate(claims, start=1):
        row[f"claim_{index}"] = bool_cell(value)
    if rubric["false_premise_required"]:
        row["false_premise_recognized"] = bool_cell(result.get("false_premise_recognized"))
        row["false_premise_corrected"] = bool_cell(result.get("false_premise_corrected"))
    if rubric["numeric_criterion"]:
        row["numeric_correct"] = bool_cell(result.get("numeric_correct"))
    if rubric["citation_criterion"]:
        row["citation_correct"] = bool_cell(result.get("citation_correct"))
    figure = rubric["figure_criterion"]
    if figure:
        row["figure_correct"] = bool_cell(result.get("figure_correct"))
        if figure["axis_claim_ids"]:
            row["axis_correct"] = bool_cell(result.get("axis_correct"))
        if figure["series_claim_ids"]:
            row["series_correct"] = bool_cell(result.get("series_correct"))
        if figure["figure_element_claim_ids"]:
            row["figure_element_correct"] = bool_cell(result.get("figure_element_correct"))
        if figure["engineering_interpretation_claim_ids"]:
            row["figure_interpretation_correct"] = bool_cell(result.get("figure_interpretation_correct"))
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a blind external-baseline packet with one local AI reviewer.")
    parser.add_argument("--packet", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="gemma4:latest")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    packet = load_json(Path(args.packet))
    selected = packet["items"][: args.limit] if args.limit else packet["items"]
    rows: list[dict[str, str]] = []
    for index, item in enumerate(selected, start=1):
        try:
            rows.append(to_row(item, judge(item, model=args.model, timeout=args.timeout)))
        except Exception as exc:
            print(f"review failed for {item['anonymous_answer_id']}: {exc}", file=sys.stderr)
            return 2
        if index % 10 == 0:
            print(f"reviewed={index}/{len(selected)}", flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"output={output.resolve()}")
    print(f"reviewed={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
