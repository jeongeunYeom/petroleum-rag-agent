from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from prepare_semantic_review import REVIEW_COLUMNS
from run_external_baseline import RUBRIC_PATH, build_anonymous_review, load_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a model-blind review packet and separate answer key.")
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--answer-id-prefix", default="EXT")
    args = parser.parse_args()

    packet, key = build_anonymous_review(
        [load_json(Path(path)) for path in args.runs],
        load_json(RUBRIC_PATH),
        answer_id_prefix=args.answer_id_prefix,
    )
    packet_path, key_path, template_path = map(Path, (args.packet, args.key, args.template))
    for path in (packet_path, key_path, template_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    key_path.write_text(json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with template_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for item in packet["items"]:
            row = {column: "" for column in REVIEW_COLUMNS}
            row.update(
                anonymous_answer_id=item["anonymous_answer_id"],
                question_id=item["question_id"],
                evaluation_condition=item["condition"],
            )
            writer.writerow(row)
    print(f"packet={packet_path.resolve()}")
    print(f"key={key_path.resolve()}")
    print(f"template={template_path.resolve()}")
    print(f"answers={len(packet['items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
