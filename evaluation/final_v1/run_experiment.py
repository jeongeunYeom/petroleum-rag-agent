"""Reproducible, output-only runner for the frozen final benchmark.

Run one phase at a time. Existing per-task raw files are never overwritten.
This script does not import or modify product internals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BENCHMARK = ROOT / "evaluation/final_benchmark_v1.json"
MANIFEST = ROOT / "evaluation/final_benchmark_v1_manifest.json"
API = "http://127.0.0.1:8001/api"
MODELS = {
    "qwen": "qwen3:8b",
    "openai": "gpt-5.4-mini-2026-03-17",
    "gemini": "gemini-2.5-flash",
    "reviewer": "gpt-5.4-2026-03-05",
}
TERMINAL = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def load_benchmark() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    actual = hashlib.sha256(BENCHMARK.read_bytes()).hexdigest()
    if actual != manifest["benchmark_sha256"]:
        raise RuntimeError("Frozen benchmark SHA mismatch; no experiment was run")
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    if len(benchmark["tasks"]) != manifest["task_count"]:
        raise RuntimeError("Frozen benchmark task count mismatch")
    return benchmark


def request_json(url: str, body: dict | None = None, *, headers: dict | None = None,
                 timeout: float = 120) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not serialize URLs or exception bodies: Gemini URLs and auth errors may contain secrets.
        raise RuntimeError(f"HTTP {exc.code} from remote endpoint") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Remote endpoint unavailable: {type(exc.reason).__name__}") from None


def write_once(path: Path, payload: dict) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def wait_run(run_id: str, *, max_seconds: int = 360) -> dict:
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        value = request_json(f"{API}/research/goal-runs/{run_id}", timeout=30)
        if value.get("run_status") in TERMINAL:
            return value
        time.sleep(1)
    raise TimeoutError(f"Agent run exceeded {max_seconds} seconds; run_id={run_id}")


def run_agent(task: dict) -> dict:
    started = time.perf_counter()
    initial = request_json(
        f"{API}/research/goal-runs/from-message",
        {"message": task["question"], "model": MODELS["qwen"]},
        timeout=45,
    )
    run_id = initial["run_id"]
    first = wait_run(run_id)
    resumed = None
    final = first
    if first.get("run_status") == "waiting_for_user_input" and task.get("continuation"):
        request_json(f"{API}/research/goal-runs/{run_id}/resume",
                     {"message": task["continuation"]}, timeout=45)
        resumed = wait_run(run_id)
        final = resumed
    return {
        "task_id": task["task_id"], "model_id": MODELS["qwen"], "run_id": run_id,
        "initial_response": first, "resume_response": resumed, "response": final,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "same_run_resume": bool(resumed and resumed.get("run_id") == run_id),
    }


def evidence_for_task(task_id: str) -> list[dict]:
    path = HERE / "raw/agent" / f"{task_id}.json"
    if not path.is_file():
        raise RuntimeError(f"Agent raw response absent: {task_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    response = payload.get("response") or {}
    evidence = []
    for item in response.get("internal_sources", []):
        evidence.append({
            "evidence_id": item.get("evidence_id"), "document": item.get("document"),
            "page": item.get("page"), "chunk_id": item.get("chunk_id"),
            "kind": "KB", "excerpt": item.get("excerpt", ""),
        })
    for item in response.get("figures", []):
        evidence.append({
            "evidence_id": item.get("evidence_id"), "document": item.get("document"),
            "page": item.get("page"), "image_path": item.get("image_path"),
            "kind": "FIG", "excerpt": item.get("source_note") or item.get("excerpt", ""),
        })
    return evidence


def prompt_for(task: dict, *, same_evidence: bool) -> tuple[str, str, list[dict]]:
    system = (
        "You are answering a petroleum-engineering question in Korean. Give a concise, directly "
        "responsive answer. Do not use tools, Python, browsing, or hidden retrieval. If the "
        "question lacks essential values or a verifiable model, ask for the missing information "
        "or state that a numeric result cannot be established. Do not invent facts, equations, "
        "numbers, or citations. Correct a false premise explicitly."
    )
    evidence: list[dict] = []
    user = task["question"]
    if same_evidence:
        evidence = evidence_for_task(task["task_id"])
        system += (
            " Use only the supplied evidence and values in the question for sourced engineering "
            "claims. Cite supporting evidence IDs in square brackets. Do not add other sources. "
            "An empty evidence list means no KB support was supplied."
        )
        user += "\n\n=== Identical Agent-retrieved KB/FIG evidence ===\n"
        user += json.dumps(evidence, ensure_ascii=False)
    return system, user, evidence


def call_qwen(system: str, user: str) -> dict:
    payload = request_json(
        "http://127.0.0.1:11434/api/chat",
        {"model": MODELS["qwen"], "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
         "stream": False, "think": False,
         "options": {"temperature": 0, "seed": 42, "num_predict": 1200}},
        timeout=240,
    )
    return {"answer": payload.get("message", {}).get("content", "").strip(),
            "model_id": payload.get("model"), "input_tokens": payload.get("prompt_eval_count"),
            "output_tokens": payload.get("eval_count"), "provider_payload": payload}


def call_openai(system: str, user: str) -> dict:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY absent")
    payload = request_json(
        "https://api.openai.com/v1/responses",
        {"model": MODELS["openai"], "instructions": system, "input": user,
         "reasoning": {"effort": "low"}, "max_output_tokens": 1800,
         "tools": [], "store": False},
        headers={"Authorization": "Bearer " + key}, timeout=240,
    )
    answer = payload.get("output_text") or "".join(
        part.get("text", "") for output in payload.get("output", [])
        for part in output.get("content", []) if part.get("type") == "output_text")
    return {"answer": answer.strip(), "model_id": payload.get("model"),
            "input_tokens": payload.get("usage", {}).get("input_tokens"),
            "output_tokens": payload.get("usage", {}).get("output_tokens"),
            "response_id": payload.get("id"), "provider_payload": payload}


def call_gemini(system: str, user: str) -> dict:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY absent")
    payload = request_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODELS['gemini']}:generateContent",
        {"systemInstruction": {"parts": [{"text": system}]},
         "contents": [{"role": "user", "parts": [{"text": user}]}],
         "generationConfig": {"temperature": 0, "maxOutputTokens": 4096,
                              "thinkingConfig": {"thinkingBudget": 0}}},
        headers={"x-goog-api-key": key}, timeout=240,
    )
    answer = "".join(
        part.get("text", "") for candidate in payload.get("candidates", [])[:1]
        for part in candidate.get("content", {}).get("parts", []) if not part.get("thought"))
    usage = payload.get("usageMetadata", {})
    return {"answer": answer.strip(), "model_id": payload.get("modelVersion", MODELS["gemini"]),
            "input_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount"), "provider_payload": payload}


CALLERS = {"qwen": call_qwen, "openai": call_openai, "gemini": call_gemini}


def run_baseline(task: dict, provider: str, same_evidence: bool) -> dict:
    system, user, evidence = prompt_for(task, same_evidence=same_evidence)
    started = time.perf_counter()
    answer = CALLERS[provider](system, user)
    return {"task_id": task["task_id"], "track": "same_evidence" if same_evidence else "closed_book",
            "provider": provider, "question": task["question"],
            "system_prompt": system, "user_prompt": user, "evidence": evidence, **answer,
            "wall_seconds": round(time.perf_counter() - started, 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["agent", "qwen", "openai", "gemini",
                                          "same-qwen", "same-openai", "same-gemini"])
    args = parser.parse_args()
    benchmark = load_benchmark()
    same = args.phase.startswith("same-")
    provider = args.phase.removeprefix("same-")
    invalid = {item["task_id"] for item in json.loads(
        (HERE / "invalid_tasks.json").read_text(encoding="utf-8"))["invalid"]}
    outdir = HERE / (f"same_evidence/{provider}" if same else f"raw/{provider}")
    print(f"PHASE={args.phase} TASKS={len(benchmark['tasks'])} MODEL={MODELS['qwen' if provider=='agent' else provider]}", flush=True)
    for index, task in enumerate(benchmark["tasks"], 1):
        if same and task["task_id"] in invalid:
            print(f"{index:02d}/50 {task['task_id']} INVALID SKIP", flush=True)
            continue
        path = outdir / f"{task['task_id']}.json"
        if path.exists():
            print(f"{index:02d}/50 {task['task_id']} EXISTING", flush=True)
            continue
        started = time.perf_counter()
        try:
            result = run_agent(task) if provider == "agent" else run_baseline(task, provider, same)
        except Exception as exc:
            result = {"task_id": task["task_id"], "track": args.phase, "error":
                      f"{type(exc).__name__}: {str(exc)[:200]}",
                      "wall_seconds": round(time.perf_counter() - started, 3)}
        write_once(path, result)
        print(f"{index:02d}/50 {task['task_id']} {result.get('error','OK')} "
              f"{result.get('wall_seconds',0):.1f}s", flush=True)
        if provider in {"openai", "gemini"} and result.get("error"):
            print("BLOCKED external provider; no further calls", flush=True)
            sys.exit(2)
        if provider == "gemini" and index < len(benchmark["tasks"]):
            # Respect the observed provider rate limit; this is pacing, not a
            # content retry or benchmark/model adjustment.
            time.sleep(10)


if __name__ == "__main__":
    main()
