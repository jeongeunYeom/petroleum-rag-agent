from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


REVIEW_COLUMNS = [
    "anonymous_answer_id",
    "question_id",
    "evaluation_condition",
    "claim_1",
    "claim_2",
    "claim_3",
    "claim_4",
    "contradiction_present",
    "false_premise_recognized",
    "false_premise_corrected",
    "numeric_correct",
    "citation_correct",
    "figure_correct",
    "axis_correct",
    "series_correct",
    "figure_interpretation_correct",
    "safe_refusal",
    "hallucination_present",
    "overall_score_0_1_2",
    "reviewer_notes",
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_review_artifacts(
    rubric: dict[str, Any],
    answer_payload: dict[str, Any] | list[dict[str, Any]],
    *,
    answer_id_prefix: str = "A",
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    answers = answer_payload.get("results", []) if isinstance(answer_payload, dict) else answer_payload
    answer_by_id = {row["id"]: row for row in answers}
    rubric_ids = [item["id"] for item in rubric["items"]]
    if set(answer_by_id) != set(rubric_ids):
        missing = sorted(set(rubric_ids) - set(answer_by_id))
        extra = sorted(set(answer_by_id) - set(rubric_ids))
        raise ValueError(f"Answer/rubric ID mismatch: missing={missing}, extra={extra}")

    packet_items: list[dict[str, Any]] = []
    review_rows: list[dict[str, str]] = []
    for index, item in enumerate(rubric["items"], start=1):
        answer = answer_by_id[item["id"]]
        answer_text = answer.get("final_answer", answer.get("answer", ""))
        if not isinstance(answer_text, str) or not answer_text.strip():
            raise ValueError(f"Missing answer text for {item['id']}")
        anonymous_id = f"{answer_id_prefix}{index:03d}"
        packet_items.append(
            {
                "anonymous_answer_id": anonymous_id,
                "question": item["question"],
                "answer": answer_text,
                "rubric_atomic_claims": {
                    "required_claims": item["required_claims"],
                    "false_premise_required": item["false_premise_required"],
                    "contradictions": item["contradictions"],
                    "numeric_criterion": item["numeric_criterion"],
                    "citation_criterion": item["citation_criterion"],
                    "figure_criterion": item["figure_criterion"],
                },
            }
        )
        review_rows.append(
            {
                column: (
                    anonymous_id
                    if column == "anonymous_answer_id"
                    else item["id"]
                    if column == "question_id"
                    else ""
                )
                for column in REVIEW_COLUMNS
            }
        )

    return {"schema_version": "1.0", "items": packet_items}, review_rows


def write_review_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a model-blind semantic review packet.")
    parser.add_argument("--rubric", required=True)
    parser.add_argument("--answers", required=True)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--answer-id-prefix", default="A")
    args = parser.parse_args()

    packet, rows = build_review_artifacts(
        load_json(Path(args.rubric)),
        load_json(Path(args.answers)),
        answer_id_prefix=args.answer_id_prefix,
    )
    packet_path = Path(args.packet)
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_review_csv(Path(args.template), rows)
    print(f"packet={packet_path.resolve()}")
    print(f"template={Path(args.template).resolve()}")
    print(f"answers={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
