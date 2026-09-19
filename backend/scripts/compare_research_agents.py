from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BENCHMARK = PROJECT_ROOT / "evaluation" / "well_test_agent_benchmark.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "evaluation"


def load_questions(path: Path, limit: int | None) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Benchmark JSON must be a list.")
    questions = [
        {
            "id": str(item.get("id") or f"Q-{index + 1:03d}"),
            "question": str(item.get("question") or "").strip(),
        }
        for index, item in enumerate(raw)
        if isinstance(item, dict) and str(item.get("question") or "").strip()
    ]
    return questions[:limit] if limit else questions


def call_agent(
    url: str,
    question: str,
    *,
    timeout: float,
    internal_top_k: int,
    external_top_k: int,
) -> dict[str, Any]:
    payload = {
        "query": question,
        "internal_top_k": internal_top_k,
        "external_top_k": external_top_k,
        "use_internal": True,
        "use_external": True,
    }
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
        data = response.json()
        error = None
    except Exception as exc:
        data = {}
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started

    internal_sources = data.get("internal_sources") or []
    web_sources = data.get("web_sources") or []
    return {
        "elapsed_seconds": elapsed,
        "answer": str(data.get("answer") or ""),
        "internal_source_count": len(internal_sources),
        "external_source_count": len(web_sources),
        "internal_sources": internal_sources,
        "web_sources": web_sources,
        "provenance": data.get("provenance") or [],
        "model": data.get("model"),
        "error": error,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two Evidence Research Agent endpoints on identical questions."
    )
    parser.add_argument("--agent-a-url", required=True)
    parser.add_argument("--agent-b-url", required=True)
    parser.add_argument("--agent-a-name", default="current_agent")
    parser.add_argument("--agent-b-name", default="codex_agent")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--internal-top-k", type=int, default=5)
    parser.add_argument("--external-top-k", type=int, default=5)
    args = parser.parse_args()

    questions = load_questions(args.benchmark, args.limit)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    rows: list[dict[str, Any]] = []
    detail: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": str(args.benchmark),
        "agents": {
            args.agent_a_name: args.agent_a_url,
            args.agent_b_name: args.agent_b_url,
        },
        "results": [],
    }

    for index, item in enumerate(questions, start=1):
        print(f"[{index}/{len(questions)}] {item['id']} {item['question']}")
        pair: dict[str, Any] = {
            "id": item["id"],
            "question": item["question"],
            "agents": {},
        }
        for name, url in (
            (args.agent_a_name, args.agent_a_url),
            (args.agent_b_name, args.agent_b_url),
        ):
            result = call_agent(
                url,
                item["question"],
                timeout=args.timeout,
                internal_top_k=args.internal_top_k,
                external_top_k=args.external_top_k,
            )
            pair["agents"][name] = result
            rows.append(
                {
                    "question_id": item["id"],
                    "question": item["question"],
                    "agent": name,
                    "elapsed_seconds": round(result["elapsed_seconds"], 4),
                    "internal_source_count": result["internal_source_count"],
                    "external_source_count": result["external_source_count"],
                    "model": result["model"] or "",
                    "error": result["error"] or "",
                    "answer": result["answer"],
                }
            )
        detail["results"].append(pair)

    json_path = args.output_dir / f"research_agent_compare_{timestamp}.json"
    csv_path = args.output_dir / f"research_agent_compare_{timestamp}.csv"
    json_path.write_text(
        json.dumps(detail, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fieldnames = [
        "question_id",
        "question",
        "agent",
        "elapsed_seconds",
        "internal_source_count",
        "external_source_count",
        "model",
        "error",
        "answer",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved JSON: {json_path}")
    print(f"Saved CSV:  {csv_path}")


if __name__ == "__main__":
    main()
