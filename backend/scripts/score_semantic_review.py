from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUBRIC = PROJECT_ROOT / "evaluation" / "petroleum_agent_heldout_v1_semantic_rubric.json"
VALID_CONDITIONS = {"closed_book", "same_evidence", "figure", "petroleum_agent"}
VALID_FAILURES = {
    "retrieval_failure",
    "generation_omission",
    "engineering_error",
    "safe_refusal",
    "figure_failure",
    "numeric_failure",
    "citation_failure",
    "partial_answer",
    "other",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_bool(value: str, field: str, question_id: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"{question_id}: {field} must be 1/0 or true/false")


def ratio(numerator: int | float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_review(
    rubric: dict[str, Any],
    rows: list[dict[str, str]],
    *,
    evaluation_condition: str | None = None,
    strict_answer_accuracy: float | None = None,
    strict_pass_by_id: dict[str, bool] | None = None,
) -> dict[str, Any]:
    rubric_by_id = {item["id"]: item for item in rubric["items"]}
    row_by_id = {row["question_id"]: row for row in rows}
    if len(row_by_id) != len(rows):
        raise ValueError("Duplicate question_id in review CSV")
    if set(row_by_id) != set(rubric_by_id):
        missing = sorted(set(rubric_by_id) - set(row_by_id))
        extra = sorted(set(row_by_id) - set(rubric_by_id))
        raise ValueError(f"Review/rubric ID mismatch: missing={missing}, extra={extra}")
    anonymous_ids = [row["anonymous_answer_id"] for row in rows]
    if len(set(anonymous_ids)) != len(anonymous_ids):
        raise ValueError("Duplicate anonymous_answer_id in review CSV")

    conditions = {row.get("evaluation_condition", "").strip() for row in rows} - {""}
    condition = evaluation_condition or (next(iter(conditions)) if len(conditions) == 1 else None)
    if condition not in VALID_CONDITIONS:
        raise ValueError(f"evaluation_condition must be one of {sorted(VALID_CONDITIONS)}")

    exact = partial = satisfied_claims = total_claims = 0
    false_total = false_recognized = false_corrected = 0
    numeric_total = numeric_correct = 0
    citation_total = citation_correct = 0
    figure_total = figure_correct = 0
    axis_total = axis_correct = 0
    series_total = series_correct = 0
    element_total = element_correct = 0
    interpretation_total = interpretation_correct = 0
    safe_refusals = contradictions = hallucinations = 0
    evaluated: list[dict[str, Any]] = []
    failure_counts: dict[str, int] = {}

    for question_id, item in rubric_by_id.items():
        row = row_by_id[question_id]
        claim_values = [
            parse_bool(row[f"claim_{index}"], f"claim_{index}", question_id)
            for index in range(1, len(item["required_claims"]) + 1)
        ]
        satisfied_claims += sum(claim_values)
        total_claims += len(claim_values)

        try:
            overall = int(row["overall_score_0_1_2"])
        except ValueError as exc:
            raise ValueError(f"{question_id}: overall_score_0_1_2 must be 0, 1, or 2") from exc
        if overall not in {0, 1, 2}:
            raise ValueError(f"{question_id}: overall_score_0_1_2 must be 0, 1, or 2")
        contradiction = parse_bool(row["contradiction_present"], "contradiction_present", question_id)
        safe_refusal = parse_bool(row["safe_refusal"], "safe_refusal", question_id)
        hallucination = parse_bool(row["hallucination_present"], "hallucination_present", question_id)
        if safe_refusal and (overall != 0 or hallucination):
            raise ValueError(f"{question_id}: safe refusal requires score 0 and hallucination=false")
        if overall == 2 and (not all(claim_values) or contradiction or safe_refusal):
            raise ValueError(f"{question_id}: score 2 requires full claim coverage and no contradiction/refusal")
        exact += overall == 2
        partial += overall >= 1
        contradictions += contradiction
        safe_refusals += safe_refusal
        hallucinations += hallucination
        failures = {
            value.strip()
            for value in row.get("failure_attribution", "").split(";")
            if value.strip()
        }
        unknown_failures = failures - VALID_FAILURES
        if unknown_failures:
            raise ValueError(f"{question_id}: unknown failure attribution {sorted(unknown_failures)}")
        for failure in failures:
            failure_counts[failure] = failure_counts.get(failure, 0) + 1
        evaluated.append(
            {
                "id": question_id,
                "domain": item["domain"],
                "task_type": item["task_type"],
                "score": overall,
                "coverage": sum(claim_values) / len(claim_values),
                "hallucination": hallucination,
                "contradiction": contradiction,
                "safe_refusal": safe_refusal,
            }
        )

        if item["false_premise_required"]:
            recognized = parse_bool(row["false_premise_recognized"], "false_premise_recognized", question_id)
            corrected = parse_bool(row["false_premise_corrected"], "false_premise_corrected", question_id)
            if corrected and not recognized:
                raise ValueError(f"{question_id}: corrected false premise must also be recognized")
            false_total += 1
            false_recognized += recognized
            false_corrected += corrected

        if item["numeric_criterion"]:
            numeric_total += 1
            numeric_correct += parse_bool(row["numeric_correct"], "numeric_correct", question_id)
        if item["citation_criterion"]:
            citation_total += 1
            citation_correct += parse_bool(row["citation_correct"], "citation_correct", question_id)
        if item["figure_criterion"]:
            figure_total += 1
            figure_correct += parse_bool(row["figure_correct"], "figure_correct", question_id)
            figure = item["figure_criterion"]
            if figure["axis_claim_ids"]:
                axis_total += 1
                axis_correct += parse_bool(row["axis_correct"], "axis_correct", question_id)
            if figure["series_claim_ids"]:
                series_total += 1
                series_correct += parse_bool(row["series_correct"], "series_correct", question_id)
            if figure["figure_element_claim_ids"]:
                element_total += 1
                element_correct += parse_bool(
                    row["figure_element_correct"], "figure_element_correct", question_id
                )
            if figure["engineering_interpretation_claim_ids"]:
                interpretation_total += 1
                interpretation_correct += parse_bool(
                    row["figure_interpretation_correct"], "figure_interpretation_correct", question_id
                )

    def breakdown(field: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for value in sorted({row[field] for row in evaluated}):
            subset = [row for row in evaluated if row[field] == value]
            count = len(subset)
            result[value] = {
                "questions": count,
                "semantic_exact_accuracy": ratio(sum(row["score"] == 2 for row in subset), count),
                "semantic_partial_or_better": ratio(sum(row["score"] >= 1 for row in subset), count),
                "mean_claim_coverage": ratio(sum(row["coverage"] for row in subset), count),
                "hallucination_rate": ratio(sum(row["hallucination"] for row in subset), count),
                "safe_refusal_rate": ratio(sum(row["safe_refusal"] for row in subset), count),
            }
        return result

    strict_groups: dict[str, list[str]] = {}
    if strict_pass_by_id is not None:
        if set(strict_pass_by_id) != set(rubric_by_id):
            raise ValueError("Strict-result IDs do not match rubric IDs")
        strict_groups = {
            "strict_pass_semantic_pass": [row["id"] for row in evaluated if strict_pass_by_id[row["id"]] and row["score"] == 2],
            "strict_fail_semantic_pass": [row["id"] for row in evaluated if not strict_pass_by_id[row["id"]] and row["score"] == 2],
            "strict_fail_semantic_fail": [row["id"] for row in evaluated if not strict_pass_by_id[row["id"]] and row["score"] < 2],
        }

    total = len(rows)
    return {
        "schema_version": "1.0",
        "evaluation_condition": condition,
        "questions_reviewed": total,
        "strict_answer_accuracy": strict_answer_accuracy,
        "semantic_answer_accuracy": ratio(exact, total),
        "semantic_exact_accuracy": ratio(exact, total),
        "semantic_partial_or_better": ratio(partial, total),
        "mean_claim_coverage": ratio(satisfied_claims, total_claims),
        "false_premise_total": false_total,
        "false_premise_recognition_rate": ratio(false_recognized, false_total),
        "false_premise_correction_rate": ratio(false_corrected, false_total),
        "numeric_accuracy": ratio(numeric_correct, numeric_total),
        "figure_semantic_accuracy": ratio(figure_correct, figure_total),
        "axis_accuracy": ratio(axis_correct, axis_total),
        "series_accuracy": ratio(series_correct, series_total),
        "figure_element_accuracy": ratio(element_correct, element_total),
        "figure_interpretation_accuracy": ratio(interpretation_correct, interpretation_total),
        "citation_accuracy": ratio(citation_correct, citation_total),
        "safe_refusal_rate": ratio(safe_refusals, total),
        "engineering_contradiction_rate": ratio(contradictions, total),
        "hallucination_rate": ratio(hallucinations, total),
        "domain_metrics": breakdown("domain"),
        "task_type_metrics": breakdown("task_type"),
        "failure_attribution_counts": dict(sorted(failure_counts.items())),
        "strict_semantic_groups": strict_groups,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate a completed model-neutral semantic review CSV.")
    parser.add_argument("--review", required=True)
    parser.add_argument("--rubric", default=str(DEFAULT_RUBRIC))
    parser.add_argument("--evaluation-condition", choices=sorted(VALID_CONDITIONS))
    parser.add_argument("--strict-result")
    parser.add_argument("--output")
    args = parser.parse_args()

    with Path(args.review).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    strict_accuracy = None
    strict_pass_by_id = None
    if args.strict_result:
        strict_payload = load_json(Path(args.strict_result))
        strict_accuracy = strict_payload["summary"]["answer_accuracy"]
        strict_pass_by_id = {
            row["id"]: bool(row["final_benchmark_passed"])
            for row in strict_payload["results"]
        }
    result = score_review(
        load_json(Path(args.rubric)),
        rows,
        evaluation_condition=args.evaluation_condition,
        strict_answer_accuracy=strict_accuracy,
        strict_pass_by_id=strict_pass_by_id,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
