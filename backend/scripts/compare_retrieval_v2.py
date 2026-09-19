from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings, get_settings  # noqa: E402
from app.services.benchmark_evaluator import evaluate_benchmark_answer  # noqa: E402
from app.services.benchmark_suite import materialize_benchmark_items  # noqa: E402
from app.services.hybrid_vector_store import HybridVectorStore  # noqa: E402
from app.services.ollama import OllamaClient  # noqa: E402
from app.services.qa import QAService  # noqa: E402
from app.services.vector_store import VectorStore  # noqa: E402


class DenseOnlyVectorStore(VectorStore):
    """Dense-only baseline that keeps QAService's hybrid_search interface."""

    def hybrid_search(
        self,
        question: str,
        top_k: int,
        score_threshold: float,
        prefer_metadata: dict[str, Any] | None = None,
        keyword_weight: float = 0.45,
    ) -> list[dict[str, Any]]:
        del keyword_weight
        candidate_k = max(top_k * 3, top_k)
        hits = self.search(question, candidate_k)
        output: list[dict[str, Any]] = []
        for hit in hits:
            distance = hit.get("distance")
            score = (
                max(0.0, 1.0 - float(distance))
                if distance is not None
                else float(hit.get("score") or 0.0)
            )
            score = min(
                1.0,
                score
                + self._metadata_boost(
                    hit.get("metadata") or {},
                    prefer_metadata,
                ),
            )
            if score < score_threshold:
                continue
            updated = dict(hit)
            updated["vector_score"] = score
            updated["keyword_score"] = 0.0
            updated["score"] = score
            output.append(updated)
        output.sort(
            key=lambda item: float(item.get("score") or 0.0),
            reverse=True,
        )
        return output[:top_k]


def read_items(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Benchmark JSON must contain a list.")
    return materialize_benchmark_items(raw)


def source_payloads(response: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for source in response.sources:
        if hasattr(source, "model_dump"):
            payloads.append(source.model_dump())
        else:
            payloads.append(source.dict())
    return payloads


def make_condition(
    name: str,
    base_settings: Settings,
) -> tuple[Settings, VectorStore]:
    if name == "dense":
        settings = replace(base_settings, reranker_enabled=False)
        return settings, DenseOnlyVectorStore(settings)
    if name == "hybrid":
        settings = replace(base_settings, reranker_enabled=False)
        return settings, HybridVectorStore(settings)
    if name == "hybrid_rerank":
        settings = replace(base_settings, reranker_enabled=True)
        return settings, HybridVectorStore(settings)
    raise ValueError(f"Unknown condition: {name}")


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    passed = sum(bool(row["passed"]) for row in rows)
    answer_passed = sum(bool(row["answer_passed"]) for row in rows)
    hallucinations = sum(bool(row["hallucination_detected"]) for row in rows)

    refusal_rows = [
        row for row in rows if row["expected_behavior"] == "refuse"
    ]
    correct_refusals = sum(
        bool(row["behavior_passed"]) for row in refusal_rows
    )

    document_rows = [
        row for row in rows if row["expected_document_hit"] is not None
    ]
    document_hits = sum(
        bool(row["expected_document_hit"]) for row in document_rows
    )

    page_rows = [
        row for row in rows if row["preferred_page_hit"] is not None
    ]
    page_hits = sum(
        bool(row["preferred_page_hit"]) for row in page_rows
    )

    figure_rows = [
        row for row in rows if row["question_type"] == "figure"
    ]
    figure_passed = sum(bool(row["passed"]) for row in figure_rows)

    elapsed_values = [float(row["elapsed_seconds"]) for row in rows]
    retrieval_values = [
        float(row.get("retrieval_elapsed_seconds") or 0.0)
        for row in rows
    ]

    return {
        "questions": count,
        "pass_rate": ratio(passed, count),
        "answer_accuracy": ratio(answer_passed, count),
        "hallucination_rate": ratio(hallucinations, count),
        "correct_refusal_rate": ratio(correct_refusals, len(refusal_rows)),
        "expected_document_recall": ratio(document_hits, len(document_rows)),
        "preferred_page_recall": ratio(page_hits, len(page_rows)),
        "figure_pass_rate": ratio(figure_passed, len(figure_rows)),
        "average_elapsed_seconds": (
            sum(elapsed_values) / len(elapsed_values) if elapsed_values else 0.0
        ),
        "average_retrieval_seconds": (
            sum(retrieval_values) / len(retrieval_values)
            if retrieval_values
            else 0.0
        ),
    }


async def run_condition(
    *,
    condition: str,
    items: list[dict[str, Any]],
    base_settings: Settings,
    model: str,
    top_k: int | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings, store = make_condition(condition, base_settings)
    service = QAService(settings, store, OllamaClient(settings))
    rows: list[dict[str, Any]] = []

    for index, item in enumerate(items, start=1):
        benchmark_id = str(item["id"])
        question = str(item["question"])
        started = time.perf_counter()
        try:
            response = await service.answer(
                question,
                top_k=top_k,
                model=model,
                benchmark_id=f"{condition}:{benchmark_id}",
            )
            elapsed = time.perf_counter() - started
            sources = source_payloads(response)
            evaluation = evaluate_benchmark_answer(
                item,
                response.answer,
                sources=sources,
            )
            row = {
                "condition": condition,
                "id": benchmark_id,
                "concept_group": item.get("concept_group"),
                "question_type": item.get("question_type"),
                "category": item.get("category"),
                "expected_behavior": item.get("expected_behavior"),
                "question": question,
                "answer": response.answer,
                "sources": sources,
                "elapsed_seconds": elapsed,
                "retrieval_elapsed_seconds": float(
                    getattr(response, "retrieval_elapsed_seconds", 0.0) or 0.0
                ),
                **evaluation.to_dict(),
                "error": None,
            }
        except Exception as exc:
            elapsed = time.perf_counter() - started
            row = {
                "condition": condition,
                "id": benchmark_id,
                "concept_group": item.get("concept_group"),
                "question_type": item.get("question_type"),
                "category": item.get("category"),
                "expected_behavior": item.get("expected_behavior"),
                "question": question,
                "answer": "",
                "sources": [],
                "elapsed_seconds": elapsed,
                "retrieval_elapsed_seconds": 0.0,
                "passed": False,
                "answer_passed": False,
                "hallucination_detected": False,
                "behavior_passed": False,
                "expected_document_hit": None,
                "preferred_page_hit": None,
                "required_failures": [],
                "forbidden_hits": [],
                "source_pages": [],
                "source_documents": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
        rows.append(row)
        status = "PASS" if row["passed"] else "FAIL"
        print(
            f"[{condition}] {index:02d}/{len(items):02d} "
            f"{benchmark_id} {status} {elapsed:.2f}s"
        )

    summary = summarize(rows)
    summary["condition"] = condition
    if isinstance(store, HybridVectorStore):
        summary["reranker_requested"] = condition == "hybrid_rerank"
        summary["reranker_load_error"] = (
            str(store._reranker_error) if store._reranker_error else None
        )
    else:
        summary["reranker_requested"] = False
        summary["reranker_load_error"] = None
    return rows, summary


def write_outputs(
    output_dir: Path,
    payload: dict[str, Any],
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"retrieval_v2_compare_{stamp}.json"
    csv_path = output_dir / f"retrieval_v2_compare_{stamp}.csv"
    summary_path = output_dir / f"retrieval_v2_compare_{stamp}_summary.csv"

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    rows = payload["rows"]
    fieldnames = [
        "condition",
        "id",
        "concept_group",
        "question_type",
        "category",
        "expected_behavior",
        "passed",
        "answer_passed",
        "hallucination_detected",
        "behavior_passed",
        "expected_document_hit",
        "preferred_page_hit",
        "elapsed_seconds",
        "retrieval_elapsed_seconds",
        "error",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})

    summary_rows = payload["summaries"]
    summary_fields = list(summary_rows[0].keys()) if summary_rows else []
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summary_rows)

    return json_path, csv_path, summary_path


async def async_main(args: argparse.Namespace) -> int:
    base_settings = get_settings()
    benchmark_path = Path(args.benchmark).resolve()
    items = read_items(benchmark_path)
    if args.limit > 0:
        items = items[: args.limit]

    conditions = args.conditions
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for condition in conditions:
        rows, summary = await run_condition(
            condition=condition,
            items=items,
            base_settings=base_settings,
            model=args.model,
            top_k=args.top_k,
        )
        all_rows.extend(rows)
        summaries.append(summary)

    payload = {
        "benchmark": str(benchmark_path),
        "model": args.model,
        "top_k": args.top_k,
        "conditions": conditions,
        "summaries": summaries,
        "rows": all_rows,
    }
    output_dir = Path(args.output_dir).resolve()
    json_path, csv_path, summary_path = write_outputs(output_dir, payload)

    print("\n=== Retrieval v2 comparison ===")
    for summary in summaries:
        print(
            f"{summary['condition']}: "
            f"pass={summary['pass_rate']:.3f} "
            f"answer={summary['answer_accuracy']:.3f} "
            f"hallucination={summary['hallucination_rate']:.3f} "
            f"doc_recall={summary['expected_document_recall']:.3f} "
            f"page_recall={summary['preferred_page_recall']:.3f} "
            f"avg={summary['average_elapsed_seconds']:.2f}s"
        )
    print(f"JSON: {json_path}")
    print(f"CSV: {csv_path}")
    print(f"Summary CSV: {summary_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare dense-only, dense+BM25, and dense+BM25+reranker "
            "on the Well Test benchmark."
        )
    )
    parser.add_argument(
        "--benchmark",
        default=str(PROJECT_ROOT / "evaluation" / "well_test_agent_benchmark.json"),
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "data" / "evaluation"),
    )
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=["dense", "hybrid", "hybrid_rerank"],
        default=["dense", "hybrid", "hybrid_rerank"],
    )
    return parser.parse_args()


def main() -> int:
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
