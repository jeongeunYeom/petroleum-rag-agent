"""Read-only similarity audit against historical evaluation questions."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from difflib import SequenceMatcher
from pathlib import Path


QUESTION_KEYS = {"question", "prompt", "query", "user_message", "raw_user_query"}


def historical_questions(root: Path) -> list[tuple[str, str]]:
    found: dict[str, str] = {}

    def walk(value: object, path: Path) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in QUESTION_KEYS and isinstance(item, str) and len(item) > 15:
                    found.setdefault(item, str(path))
                elif isinstance(item, (dict, list)):
                    walk(item, path)
        elif isinstance(value, list):
            for item in value:
                walk(item, path)

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".csv"}:
            continue
        if path.stat().st_size > 8_000_000:
            continue
        try:
            if path.suffix.lower() == ".json":
                walk(json.loads(path.read_text(encoding="utf-8")), path)
            else:
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        walk(row, path)
        except (OSError, UnicodeError, ValueError, csv.Error):
            continue
    return [(text, source) for text, source in found.items()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical-root", type=Path, required=True)
    parser.add_argument("--rubric", type=Path, default=Path(__file__).with_name("rubric.json"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("dedup_audit.json"))
    args = parser.parse_args()
    questions = json.loads(args.rubric.read_text(encoding="utf-8"))["tasks"]
    historical = historical_questions(args.historical_root)
    git_assets = [
        ("evaluation/final-benchmark-v1", "evaluation/final_benchmark_v1.json"),
        ("evaluation/final-benchmark-v2", "evaluation/final_benchmark_v2.json"),
        ("evaluation/final-benchmark-v3", "evaluation/final_benchmark_v3.json"),
        ("evaluation/final-benchmark-v4", "evaluation/final_benchmark_v4.json"),
        ("eval/v23-final-unseen-v4", "evaluation/final_unseen_v4/v4_catalog.json"),
    ]

    def add_git_questions(value: object, source: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in QUESTION_KEYS and isinstance(item, str) and len(item) > 15:
                    historical.append((item, source))
                elif isinstance(item, (dict, list)):
                    add_git_questions(item, source)
        elif isinstance(value, list):
            for item in value:
                add_git_questions(item, source)

    for ref, path in git_assets:
        result = subprocess.run(
            ["git", "show", f"{ref}:{path}"], capture_output=True, check=False
        )
        if result.returncode == 0:
            add_git_questions(json.loads(result.stdout), f"git:{ref}:{path}")
    historical = list({text: (text, source) for text, source in historical}.values())
    corpus = [task["question"] for task in questions] + [text for text, _ in historical]

    from sklearn.feature_extraction.text import TfidfVectorizer

    vectors = TfidfVectorizer(analyzer="char", ngram_range=(2, 5)).fit_transform(corpus)
    similarities = vectors[: len(questions)] @ vectors[len(questions) :].T
    results = []
    for index, task in enumerate(questions):
        scores = similarities.getrow(index).toarray()[0]
        nearest = int(scores.argmax()) if len(scores) else 0
        prior_text, prior_source = historical[nearest]
        results.append(
            {
                "question_id": task["question_id"],
                "nearest_tfidf_char_similarity": round(float(scores[nearest]), 4),
                "nearest_sequence_similarity": round(
                    SequenceMatcher(None, task["question"], prior_text).ratio(), 4
                ),
                "nearest_historical_question": prior_text,
                "historical_file": prior_source if prior_source.startswith("git:") else str(Path(prior_source).relative_to(args.historical_root)),
            }
        )
    payload = {
        "audit_method": "character 2-5gram TF-IDF and SequenceMatcher; manual review required for cross-language semantic duplicates",
        "historical_unique_questions": len(historical),
        "new_questions": len(questions),
        "results": results,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in sorted(results, key=lambda item: -item["nearest_tfidf_char_similarity"]):
        print(row["question_id"], row["nearest_tfidf_char_similarity"], row["nearest_historical_question"][:110])


if __name__ == "__main__":
    main()
