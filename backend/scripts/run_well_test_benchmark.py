from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.services.benchmark_evaluator import (  # noqa: E402
    BenchmarkEvaluation,
    evaluate_benchmark_answer,
)
from app.services.benchmark_suite import (  # noqa: E402
    build_benchmark_manifest,
    materialize_benchmark_items,
)
from app.services.refusal_policy import is_safe_refusal  # noqa: E402


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 900.0,
) -> Any:
    body = None
    headers = {"Accept": "application/json"}

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        url=url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {exc.code} from {url}: {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Cannot reach {url}: {exc.reason}"
        ) from exc


def filter_items(
    items: list[dict[str, Any]],
    *,
    ids: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    selected = [
        item
        for item in items
        if not ids or str(item.get("id")) in ids
    ]
    if limit > 0:
        selected = selected[:limit]
    return selected


def find_new_agent_run(
    agent_runs_dir: Path,
    before_files: set[Path],
    *,
    benchmark_id: str,
    question: str,
    timeout_seconds: float = 10.0,
) -> tuple[Path, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        current = set(agent_runs_dir.glob("*.json"))
        candidates = sorted(
            current - before_files,
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

        for path in candidates:
            try:
                record = read_json(path)
            except (OSError, json.JSONDecodeError):
                continue

            if (
                record.get("benchmark_id") == benchmark_id
                and record.get("question") == question
            ):
                return path, record

        time.sleep(0.1)

    raise RuntimeError(
        f"Agent run JSON not found for {benchmark_id}."
    )


def safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.fmean(values)


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def completed_rows(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        row for row in results
        if row.get("infrastructure_error") is None
    ]


def rows_with_value(
    rows: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if row.get(key) is not None
    ]


def count_true(
    rows: list[dict[str, Any]],
    key: str,
) -> int:
    return sum(1 for row in rows if row.get(key) is True)


def count_false(
    rows: list[dict[str, Any]],
    key: str,
) -> int:
    return sum(1 for row in rows if row.get(key) is False)


def mean_field(
    rows: list[dict[str, Any]],
    key: str,
) -> float | None:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return safe_mean(values)


def category_summary(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(
            str(result.get("category") or "unknown"),
            [],
        ).append(result)

    summary: dict[str, Any] = {}
    for category, rows in sorted(grouped.items()):
        answer_passes = count_true(rows, "final_answer_passed")
        final_passes = count_true(rows, "final_benchmark_passed")
        summary[category] = {
            "total": len(rows),
            "answer_passed": answer_passes,
            "answer_accuracy": ratio(answer_passes, len(rows)),
            "final_passed": final_passes,
            "final_pass_rate": ratio(
                final_passes,
                len(rows),
            ),
        }
    return summary


def build_summary(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    completed = completed_rows(results)
    initial_validator_rows = rows_with_value(
        completed,
        "initial_validator_passed",
    )
    final_validator_rows = rows_with_value(
        completed,
        "final_validator_passed",
    )

    initial_benchmark_failures = [
        row
        for row in completed
        if row.get("initial_benchmark_passed") is False
    ]
    validator_detection_rows = rows_with_value(
        initial_benchmark_failures,
        "initial_validator_passed",
    )

    initially_correct = [
        row
        for row in completed
        if row.get("initial_benchmark_passed") is True
    ]
    validator_false_positive_rows = rows_with_value(
        initially_correct,
        "initial_validator_passed",
    )

    refusal_rows = [
        row
        for row in completed
        if row.get("expected_behavior") == "refuse"
    ]
    accepted_refusals = sum(
        1
        for row in refusal_rows
        if is_safe_refusal(str(row.get("final_answer") or ""))
    )

    page_rows = rows_with_value(
        completed,
        "preferred_page_hit",
    )
    document_rows = rows_with_value(
        completed,
        "expected_document_hit",
    )
    page_recall = ratio(
        count_true(page_rows, "preferred_page_hit"),
        len(page_rows),
    )
    document_recall = ratio(
        count_true(document_rows, "expected_document_hit"),
        len(document_rows),
    )

    figure_rows = [
        row for row in completed if row.get("question_type") == "figure"
    ]
    figure_retrieval_rows = rows_with_value(
        figure_rows,
        "figure_retrieval_hit",
    )
    citation_rows = rows_with_value(
        completed,
        "citation_correctness",
    )
    false_premise_rows = rows_with_value(
        completed,
        "false_premise_correction_success",
    )
    engineering_validation_rows = rows_with_value(
        completed,
        "engineering_validation_passed",
    )

    return {
        "questions_total": len(results),
        "questions_completed": len(completed),
        "infrastructure_errors": (
            len(results) - len(completed)
        ),
        "initial_answer_accuracy": ratio(
            count_true(completed, "initial_answer_passed"),
            len(completed),
        ),
        "answer_accuracy": ratio(
            count_true(completed, "final_answer_passed"),
            len(completed),
        ),
        "hallucination_rate": ratio(
            count_true(completed, "hallucination_detected"),
            len(completed),
        ),
        "citation_correctness_rate": ratio(
            count_true(citation_rows, "citation_correctness"),
            len(citation_rows),
        ),
        "engineering_contradiction_count": sum(
            int(row.get("engineering_contradiction_count") or 0)
            for row in completed
        ),
        "unsupported_engineering_claim_count": sum(
            int(row.get("unsupported_engineering_claim_count") or 0)
            for row in completed
        ),
        "average_engineering_contradiction_count": mean_field(
            completed,
            "engineering_contradiction_count",
        ),
        "average_unsupported_engineering_claim_count": mean_field(
            completed,
            "unsupported_engineering_claim_count",
        ),
        "false_premise_correction_success_rate": ratio(
            count_true(
                false_premise_rows,
                "false_premise_correction_success",
            ),
            len(false_premise_rows),
        ),
        "engineering_validation_pass_rate": ratio(
            count_true(
                engineering_validation_rows,
                "engineering_validation_passed",
            ),
            len(engineering_validation_rows),
        ),
        "average_repair_attempts": mean_field(
            completed,
            "repair_attempts",
        ),
        "initial_benchmark_pass_rate": ratio(
            count_true(completed, "initial_benchmark_passed"),
            len(completed),
        ),
        "final_benchmark_pass_rate": ratio(
            count_true(completed, "final_benchmark_passed"),
            len(completed),
        ),
        "initial_validator_pass_rate": ratio(
            count_true(initial_validator_rows, "initial_validator_passed"),
            len(initial_validator_rows),
        ),
        "final_validator_pass_rate": ratio(
            count_true(final_validator_rows, "final_validator_passed"),
            len(final_validator_rows),
        ),
        "rewrite_success_rate": ratio(
            count_true(
                initial_benchmark_failures,
                "final_benchmark_passed",
            ),
            len(initial_benchmark_failures),
        ),
        "validator_detection_rate": ratio(
            count_false(
                validator_detection_rows,
                "initial_validator_passed",
            ),
            len(validator_detection_rows),
        ),
        "validator_false_positive_rate": ratio(
            count_false(
                validator_false_positive_rows,
                "initial_validator_passed",
            ),
            len(validator_false_positive_rows),
        ),
        "exact_refusal_rate": ratio(
            accepted_refusals,
            len(refusal_rows),
        ),
        "safe_refusal_rate": ratio(
            accepted_refusals,
            len(refusal_rows),
        ),
        "preferred_page_hit_rate": page_recall,
        "expected_document_hit_rate": document_recall,
        "retrieval_document_recall_at_k": document_recall,
        "retrieval_page_recall_at_k": page_recall,
        "figure_answer_accuracy": ratio(
            count_true(figure_rows, "final_answer_passed"),
            len(figure_rows),
        ),
        "figure_retrieval_accuracy": ratio(
            count_true(figure_retrieval_rows, "figure_retrieval_hit"),
            len(figure_retrieval_rows),
        ),
        "average_attempts": mean_field(completed, "attempts"),
        "average_retrieval_seconds": mean_field(
            completed,
            "retrieval_seconds",
        ),
        "average_generation_seconds": mean_field(
            completed,
            "generation_seconds",
        ),
        "average_total_seconds": mean_field(completed, "total_seconds"),
        "category_metrics": category_summary(completed),
    }


def csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_csv(
    path: Path,
    results: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    columns = [
        "id",
        "category",
        "question_type",
        "concept_group",
        "condition",
        "mode",
        "retrieval_mode",
        "model",
        "expected_behavior",
        "initial_behavior_passed",
        "final_behavior_passed",
        "initial_answer_passed",
        "final_answer_passed",
        "hallucination_detected",
        "initial_validator_passed",
        "final_validator_passed",
        "initial_benchmark_passed",
        "final_benchmark_passed",
        "rewrite_success",
        "attempts",
        "repair_attempts",
        "final_status",
        "expected_document_hit",
        "preferred_page_hit",
        "figure_retrieval_hit",
        "figure_count",
        "source_pages",
        "retrieval_seconds",
        "reasoning_seconds",
        "generation_seconds",
        "total_seconds",
        "internal_source_count",
        "external_source_count",
        "retrieved_web_urls",
        "citation_correctness",
        "unsupported_claim_count",
        "engineering_contradiction_count",
        "false_premise_detected",
        "false_premise_correction_success",
        "unsupported_engineering_claim_count",
        "engineering_validation_passed",
        "agent_citation_correctness",
        "agent_engineering_contradiction_count",
        "agent_false_premise_detected",
        "agent_false_premise_correction_success",
        "agent_unsupported_engineering_claim_count",
        "agent_engineering_validation_passed",
        "benchmark_evaluation_source",
        "citation_evaluation_source",
        "initial_required_failures",
        "initial_forbidden_hits",
        "final_required_failures",
        "final_forbidden_hits",
        "infrastructure_error",
        "question",
        "final_answer",
        "agent_run_file",
    ]

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            extrasaction="ignore",
        )
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    key: csv_value(result.get(key))
                    for key in columns
                }
            )


def reevaluate_saved_benchmark(
    saved_path: Path,
    *,
    benchmark_fallback: Path | None = None,
    run_id: str | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """Re-run only deterministic evaluation over a saved benchmark payload."""
    saved_path = saved_path.resolve()
    payload = read_json(saved_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RuntimeError("Saved benchmark JSON must contain a results list.")

    benchmark_value = str(payload.get("benchmark_file") or "").strip()
    benchmark_path = Path(benchmark_value) if benchmark_value else Path()
    if not benchmark_path.is_file() and benchmark_fallback is not None:
        benchmark_path = benchmark_fallback.resolve()
    if not benchmark_path.is_file():
        raise RuntimeError("Benchmark definition file was not found for re-evaluation.")

    raw_items = read_json(benchmark_path)
    if not isinstance(raw_items, list):
        raise RuntimeError("Benchmark JSON must contain a list.")
    items = materialize_benchmark_items(raw_items)
    items_by_id = {str(item["id"]): item for item in items}

    results: list[dict[str, Any]] = []
    for saved_row in payload["results"]:
        row = dict(saved_row)
        item_id = str(row.get("id") or "")
        item = items_by_id.get(item_id)
        if item is None:
            raise RuntimeError(f"Benchmark item not found for saved row: {item_id}")
        initial_answer = str(row.get("initial_answer") or row.get("final_answer") or "")
        final_answer = str(row.get("final_answer") or "")
        sources = row.get("sources") or []

        row.setdefault(
            "agent_engineering_contradiction_count",
            row.get("engineering_contradiction_count"),
        )
        row.setdefault(
            "agent_unsupported_engineering_claim_count",
            row.get("unsupported_engineering_claim_count"),
        )
        row.setdefault(
            "agent_false_premise_detected",
            row.get("false_premise_detected"),
        )
        row.setdefault(
            "agent_false_premise_correction_success",
            row.get("false_premise_correction_success"),
        )
        row.setdefault(
            "agent_engineering_validation_passed",
            row.get("engineering_validation_passed"),
        )
        row.setdefault("agent_citation_correctness", row.get("citation_correctness"))
        row["citation_evaluation_source"] = "saved_agent_validation"

        initial = evaluate_benchmark_answer(item, initial_answer, sources=sources)
        final = evaluate_benchmark_answer(item, final_answer, sources=sources)
        row.update(benchmark_evaluation_fields(initial, final))
        row["reevaluated"] = True
        results.append(row)

    reevaluation_run_id = run_id or utc_run_id()
    original_condition = str(payload.get("condition") or "").strip()
    output = {
        **payload,
        "run_id": reevaluation_run_id,
        "original_run_id": payload.get("run_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "condition": f"{original_condition}-reevaluated".strip("-"),
        "benchmark_file": str(benchmark_path),
        "reevaluated_from": str(saved_path),
        "question_count": len(results),
        "summary": build_summary(results),
        "results": results,
    }
    stem = f"{saved_path.stem}_reevaluated_{reevaluation_run_id}"
    json_path = saved_path.with_name(f"{stem}.json")
    csv_path = saved_path.with_name(f"{stem}.csv")
    write_json(json_path, output)
    write_csv(csv_path, results)
    return json_path, csv_path, output


def print_rate(label: str, value: float | None) -> None:
    if value is None:
        print(f"{label}=n/a")
    else:
        print(f"{label}={value:.3f}")


def benchmark_evaluation_fields(
    initial: BenchmarkEvaluation,
    final: BenchmarkEvaluation,
) -> dict[str, Any]:
    """Return row fields derived from one benchmark evaluator only."""
    engineering_passed = bool(
        final.engineering_contradiction_count == 0
        and final.unsupported_engineering_claim_count == 0
        and final.false_premise_correction_success is not False
    )
    return {
        "initial_behavior_passed": initial.behavior_passed,
        "final_behavior_passed": final.behavior_passed,
        "initial_answer_passed": initial.answer_passed,
        "final_answer_passed": final.answer_passed,
        "hallucination_detected": final.hallucination_detected,
        "initial_benchmark_passed": initial.passed,
        "final_benchmark_passed": final.passed,
        "rewrite_success": not initial.passed and final.passed,
        "expected_document_hit": final.expected_document_hit,
        "preferred_page_hit": final.preferred_page_hit,
        "engineering_contradiction_count": (
            final.engineering_contradiction_count
        ),
        "false_premise_detected": final.false_premise_detected,
        "false_premise_correction_success": (
            final.false_premise_correction_success
        ),
        "unsupported_engineering_claim_count": (
            final.unsupported_engineering_claim_count
        ),
        "engineering_validation_passed": engineering_passed,
        "initial_required_failures": initial.required_failures,
        "initial_forbidden_hits": initial.forbidden_hits,
        "final_required_failures": final.required_failures,
        "final_forbidden_hits": final.forbidden_hits,
        "initial_benchmark_evaluation": initial.to_dict(),
        "final_benchmark_evaluation": final.to_dict(),
        "benchmark_evaluation_source": "benchmark_evaluator",
    }


def figure_retrieval_hit(
    item: dict[str, Any],
    figures: list[dict[str, Any]],
) -> bool | None:
    if item.get("question_type") != "figure":
        return None
    if not figures:
        return False
    preferred_pages = {
        int(page) for page in (item.get("preferred_pages") or [])
    }
    if not preferred_pages:
        return True
    figure_pages: set[int] = set()
    for figure in figures:
        try:
            figure_pages.add(int(figure.get("page")))
        except (TypeError, ValueError):
            continue
    return bool(preferred_pages.intersection(figure_pages))


def direct_ollama_answer(
    ollama_url: str,
    *,
    model: str,
    question: str,
    timeout: float,
) -> tuple[str, float]:
    started = time.perf_counter()
    response = http_json(
        "POST",
        f"{ollama_url.rstrip('/')}/api/chat",
        payload={
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": question}],
        },
        timeout=timeout,
    )
    answer = str((response.get("message") or {}).get("content") or "")
    return answer, time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the deterministic Well Test agent benchmark "
            "against the local FastAPI backend."
        )
    )
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8000/api",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://127.0.0.1:11434",
    )
    parser.add_argument(
        "--benchmark",
        default=str(
            PROJECT_ROOT
            / "evaluation"
            / "well_test_agent_benchmark.json"
        ),
    )
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument(
        "--mode",
        choices=("rag", "research", "ollama-direct"),
        default="rag",
    )
    parser.add_argument(
        "--retrieval-mode",
        choices=("legacy", "hybrid", "hybrid_rerank"),
        default="",
        help="research 응답의 RETRIEVAL_MODE를 검증하고 결과에 기록합니다.",
    )
    parser.add_argument(
        "--condition",
        default="",
        help="논문 비교표에 표시할 실험 조건 이름.",
    )
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument(
        "--use-external",
        action="store_true",
        help="research mode에서 DDGS 외부 검색도 사용합니다.",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--ids",
        default="",
        help="Comma-separated benchmark IDs.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.5,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
    )
    parser.add_argument(
        "--fail-on-benchmark-failure",
        action="store_true",
    )
    parser.add_argument(
        "--reevaluate",
        default="",
        help=(
            "Re-evaluate a saved benchmark JSON without backend, retrieval, "
            "or Ollama calls."
        ),
    )
    args = parser.parse_args()
    if args.reevaluate:
        json_path, csv_path, payload = reevaluate_saved_benchmark(
            Path(args.reevaluate),
            benchmark_fallback=Path(args.benchmark),
        )
        print("BENCHMARK_REEVALUATED=True")
        print(f"json={json_path}")
        print(f"csv={csv_path}")
        for label in (
            "answer_accuracy",
            "hallucination_rate",
            "citation_correctness_rate",
            "exact_refusal_rate",
            "final_benchmark_pass_rate",
        ):
            print_rate(label, payload["summary"].get(label))
        return 0
    if args.retrieval_mode and args.mode != "research":
        parser.error("--retrieval-mode requires --mode research")

    benchmark_path = Path(args.benchmark).resolve()
    raw_benchmark_items = read_json(benchmark_path)
    if not isinstance(raw_benchmark_items, list):
        raise RuntimeError(
            "Benchmark JSON must contain a list."
        )
    benchmark_items = materialize_benchmark_items(raw_benchmark_items)
    benchmark_manifest = build_benchmark_manifest(benchmark_items)

    requested_ids = {
        item.strip()
        for item in args.ids.split(",")
        if item.strip()
    }
    items = filter_items(
        benchmark_items,
        ids=requested_ids,
        limit=args.limit,
    )
    if not items:
        raise RuntimeError(
            "No benchmark questions were selected."
        )

    print(f"benchmark={benchmark_path}")
    print(f"mode={args.mode}")
    if args.retrieval_mode:
        print(f"retrieval_mode={args.retrieval_mode}")
    print(f"model={args.model}")
    print(f"questions={len(items)}")
    print(
        "question_types="
        f"{benchmark_manifest['question_type_counts']}"
    )

    for item in items:
        print(
            f"  {item['id']} "
            f"[{item.get('category', 'unknown')}] "
            f"{item['question']}"
        )

    if args.dry_run:
        print("DRY_RUN=True")
        return 0

    api_base = args.api_url.rstrip("/")
    if args.mode in {"rag", "research"}:
        health = http_json(
            "GET",
            f"{api_base}/health",
            timeout=30.0,
        )
        print(
            "backend_status="
            f"{health.get('status', 'unknown')}"
        )
    else:
        tags = http_json(
            "GET",
            f"{args.ollama_url.rstrip('/')}/api/tags",
            timeout=30.0,
        )
        installed = {
            str(model.get("name") or "")
            for model in (tags.get("models") or [])
        }
        if args.model not in installed:
            raise RuntimeError(
                f"Ollama model is not installed: {args.model}"
            )
        print("ollama_status=ok")

    settings = get_settings()
    agent_runs_dir = Path(settings.agent_runs_dir)
    evaluation_dir = Path(settings.evaluation_dir)
    agent_runs_dir.mkdir(parents=True, exist_ok=True)
    evaluation_dir.mkdir(parents=True, exist_ok=True)

    run_id = utc_run_id()
    results: list[dict[str, Any]] = []
    overall_started = time.perf_counter()

    for index, item in enumerate(items, start=1):
        item_id = str(item["id"])
        question = str(item["question"])
        print(
            f"\n[{index}/{len(items)}] "
            f"{item_id}: {question}"
        )

        before_files = set(
            agent_runs_dir.glob("*.json")
        )
        if args.mode == "research":
            request_payload: dict[str, Any] = {
                "query": question,
                "model": args.model,
                "use_internal": True,
                "use_external": args.use_external,
            }
            if args.top_k is not None:
                request_payload["internal_top_k"] = args.top_k
                request_payload["external_top_k"] = args.top_k
        else:
            request_payload = {
                "question": question,
                "model": args.model,
                "benchmark_id": item_id,
            }
            if args.top_k is not None:
                request_payload["top_k"] = args.top_k

        result: dict[str, Any] = {
            "id": item_id,
            "category": item.get("category"),
            "question_type": item.get("question_type"),
            "concept_group": item.get("concept_group"),
            "question": question,
            "condition": args.condition or f"{args.model}-{args.mode}",
            "mode": args.mode,
            "retrieval_mode": args.retrieval_mode or None,
            "model": args.model,
            "expected_behavior": item.get(
                "expected_behavior"
            ),
            "infrastructure_error": None,
        }
        repair_attempts = 0
        api_engineering_contradictions: int | None = None
        api_unsupported_engineering: int | None = None
        api_false_premise_detected: bool | None = None
        api_false_premise_corrected: bool | None = None
        api_engineering_validation_passed: bool | None = None

        try:
            if args.mode == "rag":
                response = http_json(
                    "POST",
                    f"{api_base}/chat",
                    payload=request_payload,
                    timeout=args.timeout,
                )
                run_path, record = find_new_agent_run(
                    agent_runs_dir,
                    before_files,
                    benchmark_id=item_id,
                    question=question,
                )
                attempts = record.get("attempts") or []
                initial_answer = (
                    str(attempts[0].get("answer") or "")
                    if attempts
                    else ""
                )
                final_answer = str(response.get("answer") or "")
                sources = record.get("retrieved_sources") or []
                figures = [
                    figure
                    for figure in (response.get("figures") or [])
                    if isinstance(figure, dict)
                ]
                retrieval_seconds = float(
                    record.get("retrieval_elapsed_seconds") or 0.0
                )
                generation_seconds = sum(
                    float(attempt.get("elapsed_seconds") or 0.0)
                    for attempt in attempts
                )
                total_seconds = float(
                    record.get("total_elapsed_seconds") or 0.0
                )
                initial_validator_passed = (
                    attempts[0].get("validation_passed")
                    if attempts
                    else None
                )
                final_validator_passed = record.get("final_passed")
                final_status = record.get("final_status")
                agent_run_file = str(run_path)
                reasoning_seconds = generation_seconds
                internal_source_count = len(sources)
                external_source_count = 0
                retrieved_web_urls = []
                citation_correctness = None
                unsupported_claim_count = None
                repair_attempts = max(len(attempts) - 1, 0)
                api_engineering_validation_passed = (
                    bool(final_validator_passed)
                    if final_validator_passed is not None
                    else None
                )
            elif args.mode == "research":
                response = http_json(
                    "POST",
                    f"{api_base}/research/evidence",
                    payload=request_payload,
                    timeout=args.timeout,
                )
                retrieval_mode = str(response.get("retrieval_mode") or "").strip()
                if retrieval_mode not in {"legacy", "hybrid", "hybrid_rerank"}:
                    raise RuntimeError(
                        "Research response did not contain a valid retrieval_mode."
                    )
                if args.retrieval_mode and retrieval_mode != args.retrieval_mode:
                    raise RuntimeError(
                        "Backend retrieval mode mismatch: "
                        f"expected {args.retrieval_mode}, got {retrieval_mode}"
                    )
                final_answer = str(response.get("answer") or "")
                initial_answer = final_answer
                sources = response.get("internal_sources") or []
                figures = response.get("figures") or []
                attempts = [{"answer": final_answer}]
                timing = response.get("timing") or {}
                retrieval_seconds = float(timing.get("retrieval_seconds") or 0.0)
                reasoning_seconds = float(timing.get("reasoning_seconds") or 0.0)
                generation_seconds = reasoning_seconds
                total_seconds = float(timing.get("elapsed_seconds") or 0.0)
                initial_validator_passed = None
                final_validator_passed = None
                final_status = "completed"
                agent_run_file = "data/agent_runs/research"
                counts = response.get("evidence_counts") or {}
                internal_source_count = int(counts.get("internal") or 0)
                external_source_count = int(counts.get("external") or 0)
                retrieved_web_urls = [
                    str(source.get("url") or "")
                    for source in (response.get("web_sources") or [])
                ]
                validation = response.get("validation") or {}
                repair_attempts = int(validation.get("repair_attempts") or 0)
                api_engineering_contradictions = int(
                    validation.get("engineering_contradiction_count") or 0
                )
                api_unsupported_engineering = int(
                    validation.get("unsupported_engineering_claim_count") or 0
                )
                api_false_premise_detected = bool(
                    validation.get("false_premise_detected")
                )
                api_false_premise_corrected = (
                    bool(validation.get("false_premise_corrected"))
                    if api_false_premise_detected
                    else None
                )
                api_engineering_validation_passed = bool(
                    validation.get("engineering_validation_passed")
                )
                unsupported_claim_count = int(
                    validation.get("unsupported_claim_count") or 0
                )
                citation_correctness = (
                    not bool(validation.get("invalid_citations"))
                    and unsupported_claim_count == 0
                    and int(
                        validation.get("engineering_contradiction_count") or 0
                    ) == 0
                    and int(
                        validation.get("unsupported_engineering_claim_count") or 0
                    ) == 0
                    and not (
                        validation.get("false_premise_detected")
                        and not validation.get("false_premise_corrected")
                    )
                    and bool(validation.get("valid_citations"))
                )
            else:
                final_answer, generation_seconds = direct_ollama_answer(
                    args.ollama_url,
                    model=args.model,
                    question=question,
                    timeout=args.timeout,
                )
                initial_answer = final_answer
                sources = []
                figures = []
                attempts = [{"answer": final_answer}]
                retrieval_seconds = 0.0
                reasoning_seconds = generation_seconds
                total_seconds = generation_seconds
                initial_validator_passed = None
                final_validator_passed = None
                final_status = "completed"
                agent_run_file = ""
                internal_source_count = 0
                external_source_count = 0
                retrieved_web_urls = []
                citation_correctness = None
                unsupported_claim_count = None

            initial_evaluation = (
                evaluate_benchmark_answer(
                    item,
                    initial_answer,
                    sources=sources,
                )
            )
            final_evaluation = (
                evaluate_benchmark_answer(
                    item,
                    final_answer,
                    sources=sources,
                )
            )

            result.update(
                {
                    "initial_answer": initial_answer,
                    "final_answer": final_answer,
                    "sources": sources,
                    "source_pages": (
                        final_evaluation.source_pages
                    ),
                    "initial_validator_passed": (
                        initial_validator_passed
                    ),
                    "final_validator_passed": (
                        final_validator_passed
                    ),
                    "initial_answer_passed": (
                        initial_evaluation.answer_passed
                    ),
                    "final_answer_passed": (
                        final_evaluation.answer_passed
                    ),
                    "hallucination_detected": (
                        final_evaluation.hallucination_detected
                    ),
                    "initial_benchmark_passed": (
                        initial_evaluation.passed
                    ),
                    "final_benchmark_passed": (
                        final_evaluation.passed
                    ),
                    "rewrite_success": (
                        not initial_evaluation.passed
                        and final_evaluation.passed
                    ),
                    "attempts": len(attempts),
                    "repair_attempts": repair_attempts,
                    "final_status": final_status,
                    "expected_document_hit": (
                        final_evaluation
                        .expected_document_hit
                    ),
                    "preferred_page_hit": (
                        final_evaluation
                        .preferred_page_hit
                    ),
                    "figure_retrieval_hit": figure_retrieval_hit(
                        item,
                        figures,
                    ),
                    "figure_count": len(figures),
                    "retrieval_seconds": retrieval_seconds,
                    "reasoning_seconds": reasoning_seconds,
                    "generation_seconds": generation_seconds,
                    "total_seconds": total_seconds,
                    "internal_source_count": internal_source_count,
                    "external_source_count": external_source_count,
                    "retrieved_web_urls": retrieved_web_urls,
                    "citation_correctness": citation_correctness,
                    "agent_citation_correctness": citation_correctness,
                    "citation_evaluation_source": (
                        "agent_validation"
                        if citation_correctness is not None
                        else None
                    ),
                    "unsupported_claim_count": unsupported_claim_count,
                    "agent_engineering_contradiction_count": (
                        api_engineering_contradictions
                    ),
                    "agent_false_premise_detected": api_false_premise_detected,
                    "agent_false_premise_correction_success": (
                        api_false_premise_corrected
                    ),
                    "agent_unsupported_engineering_claim_count": (
                        api_unsupported_engineering
                    ),
                    "agent_engineering_validation_passed": (
                        api_engineering_validation_passed
                    ),
                    "retrieval_mode": (
                        retrieval_mode
                        if args.mode == "research"
                        else None
                    ),
                    "initial_required_failures": (
                        initial_evaluation
                        .required_failures
                    ),
                    "initial_forbidden_hits": (
                        initial_evaluation
                        .forbidden_hits
                    ),
                    "final_required_failures": (
                        final_evaluation
                        .required_failures
                    ),
                    "final_forbidden_hits": (
                        final_evaluation
                        .forbidden_hits
                    ),
                    "agent_run_file": agent_run_file,
                }
            )
            result.update(
                benchmark_evaluation_fields(
                    initial_evaluation,
                    final_evaluation,
                )
            )

            print(
                "  initial="
                f"{initial_evaluation.passed} "
                "final="
                f"{final_evaluation.passed} "
                f"attempts={len(attempts)} "
                "preferred_page="
                f"{final_evaluation.preferred_page_hit}"
            )
        except Exception as exc:
            result.update(
                {
                    "infrastructure_error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                    "initial_validator_passed": None,
                    "final_validator_passed": None,
                    "initial_answer_passed": None,
                    "final_answer_passed": None,
                    "hallucination_detected": None,
                    "initial_benchmark_passed": None,
                    "final_benchmark_passed": None,
                    "rewrite_success": False,
                    "attempts": 0,
                    "repair_attempts": 0,
                    "final_status": "infrastructure_error",
                    "expected_document_hit": None,
                    "preferred_page_hit": None,
                    "figure_retrieval_hit": None,
                    "figure_count": 0,
                    "source_pages": [],
                    "retrieval_seconds": 0.0,
                    "reasoning_seconds": 0.0,
                    "generation_seconds": 0.0,
                    "total_seconds": 0.0,
                    "internal_source_count": 0,
                    "external_source_count": 0,
                    "retrieved_web_urls": [],
                    "citation_correctness": None,
                    "unsupported_claim_count": None,
                    "engineering_contradiction_count": None,
                    "false_premise_detected": None,
                    "false_premise_correction_success": None,
                    "unsupported_engineering_claim_count": None,
                    "engineering_validation_passed": None,
                    "initial_required_failures": [],
                    "initial_forbidden_hits": [],
                    "final_required_failures": [],
                    "final_forbidden_hits": [],
                    "final_answer": "",
                    "agent_run_file": "",
                }
            )
            print(
                "  ERROR: "
                f"{result['infrastructure_error']}"
            )

        results.append(result)

        if args.pause_seconds > 0:
            time.sleep(args.pause_seconds)

    observed_retrieval_modes = sorted(
        {
            str(result["retrieval_mode"])
            for result in results
            if result.get("retrieval_mode")
            and result.get("infrastructure_error") is None
        }
    )
    if len(observed_retrieval_modes) > 1:
        raise RuntimeError("One benchmark run returned multiple retrieval modes.")
    run_retrieval_mode = (
        observed_retrieval_modes[0]
        if observed_retrieval_modes
        else args.retrieval_mode or None
    )
    run_condition = args.condition or f"{args.model}-{args.mode}"
    if args.mode == "research" and run_retrieval_mode:
        run_condition = f"{run_condition}-{run_retrieval_mode}"
    for result in results:
        result["condition"] = run_condition

    summary = build_summary(results)
    elapsed = time.perf_counter() - overall_started

    payload = {
        "benchmark_name": "well_test_agent_benchmark",
        "benchmark_file": str(benchmark_path),
        "run_id": run_id,
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "condition": run_condition,
        "mode": args.mode,
        "retrieval_mode": run_retrieval_mode,
        "model": args.model,
        "api_url": api_base,
        "ollama_url": args.ollama_url.rstrip("/"),
        "question_count": len(items),
        "benchmark_manifest": benchmark_manifest,
        "wall_clock_seconds": elapsed,
        "summary": summary,
        "results": results,
    }

    json_path = (
        evaluation_dir
        / f"well_test_benchmark_{run_id}.json"
    )
    csv_path = (
        evaluation_dir
        / f"well_test_benchmark_{run_id}.csv"
    )
    latest_json_path = (
        evaluation_dir
        / "well_test_benchmark_latest.json"
    )
    latest_csv_path = (
        evaluation_dir
        / "well_test_benchmark_latest.csv"
    )

    write_json(json_path, payload)
    write_json(latest_json_path, payload)
    write_csv(csv_path, results)
    write_csv(latest_csv_path, results)

    print("\nBENCHMARK_COMPLETED=True")
    print(f"json={json_path}")
    print(f"csv={csv_path}")
    print_rate(
        "answer_accuracy",
        summary["answer_accuracy"],
    )
    print_rate(
        "hallucination_rate",
        summary["hallucination_rate"],
    )
    print_rate(
        "initial_benchmark_pass_rate",
        summary["initial_benchmark_pass_rate"],
    )
    print_rate(
        "final_benchmark_pass_rate",
        summary["final_benchmark_pass_rate"],
    )
    print_rate(
        "rewrite_success_rate",
        summary["rewrite_success_rate"],
    )
    print_rate(
        "validator_detection_rate",
        summary["validator_detection_rate"],
    )
    print_rate(
        "exact_refusal_rate",
        summary["exact_refusal_rate"],
    )
    print_rate(
        "preferred_page_hit_rate",
        summary["preferred_page_hit_rate"],
    )
    print(
        "average_attempts="
        f"{summary['average_attempts'] or 0.0:.3f}"
    )

    has_infrastructure_error = (
        summary["infrastructure_errors"] > 0
    )
    failure_field = (
        "final_answer_passed"
        if args.mode == "ollama-direct"
        else "final_benchmark_passed"
    )
    has_benchmark_failure = any(
        row.get(failure_field) is False for row in results
    )

    if has_infrastructure_error:
        return 2
    if (
        args.fail_on_benchmark_failure
        and has_benchmark_failure
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
