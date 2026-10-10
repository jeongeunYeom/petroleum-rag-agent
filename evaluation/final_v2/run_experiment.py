"""Run frozen v2 phases sequentially; never overwrite successful raw responses."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BENCHMARK = ROOT / "evaluation/final_benchmark_v2.json"
MANIFEST = ROOT / "evaluation/final_benchmark_v2_manifest.json"
API = "http://127.0.0.1:8001/api"
MODELS = {"qwen": "qwen3:8b", "openai": "gpt-5.4-mini-2026-03-17",
          "reviewer": "gpt-5.4-2026-03-05"}
PHASES = ("agent", "qwen", "openai", "same-qwen", "same-openai")
TERMINAL = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def load_benchmark() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    actual = hashlib.sha256(BENCHMARK.read_bytes()).hexdigest()
    if actual != manifest["benchmark_sha256"]:
        raise RuntimeError("Frozen v2 benchmark hash mismatch")
    frozen = subprocess.check_output(
        ["git", "show", f"{manifest['freeze_commit']}:evaluation/final_benchmark_v2.json"], cwd=ROOT)
    if hashlib.sha256(frozen).hexdigest() != actual:
        raise RuntimeError("Working benchmark differs from freeze commit")
    changed_product = subprocess.check_output(
        ["git", "diff", "--name-only", manifest["evaluated_product_sha"], "HEAD"], cwd=ROOT,
        text=True).splitlines()
    if any(path.startswith(("backend/", "frontend/")) for path in changed_product):
        raise RuntimeError("Product code differs from evaluated SHA")
    working_product = subprocess.check_output(
        ["git", "status", "--porcelain", "--", "backend", "frontend"], cwd=ROOT,
        text=True)
    if working_product.strip():
        raise RuntimeError("Uncommitted product code changes present")
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    if len(benchmark["tasks"]) != manifest["task_count"]:
        raise RuntimeError("Task count mismatch")
    return benchmark


def request_json(url: str, body: dict | None = None, *, headers: dict | None = None,
                 timeout: int = 240) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Provider URLs and error bodies may contain credentials; record only status.
        raise RuntimeError(f"HTTP {exc.code} from endpoint") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Endpoint unavailable: {type(exc.reason).__name__}") from None


def write_once(path: Path, value: dict) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def preflight_server() -> dict:
    checks = request_json(f"{API}/system/checklist", timeout=30)
    if (not checks.get("ok") or checks.get("knowledge_base", {}).get("chunks") != 18976
            or checks.get("knowledge_base", {}).get("documents") != 12
            or checks.get("checks", {}).get("text_model", {}).get("model") != MODELS["qwen"]):
        raise RuntimeError("Agent backend/model/Chroma preflight failed")
    mode = request_json(f"{API}/research/evidence", {
        "query": "reservoir pressure", "use_external": False, "evidence_only": True,
        "model": MODELS["qwen"]}, timeout=90)
    if mode.get("retrieval_mode") != "hybrid" or mode.get("web_sources"):
        raise RuntimeError("Agent retrieval mode or web-off preflight failed")
    return {"backend": "ok", "documents": 12, "chunks": 18976,
            "retrieval_mode": mode["retrieval_mode"], "model": MODELS["qwen"]}


def wait_run(run_id: str, *, max_seconds: int = 600) -> dict:
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        state = request_json(f"{API}/research/goal-runs/{run_id}", timeout=45)
        if state.get("run_status") in TERMINAL:
            return state
        time.sleep(1)
    raise TimeoutError(f"Agent run exceeded {max_seconds} seconds; run_id={run_id}")


def run_agent(task: dict) -> dict:
    started = time.perf_counter()
    initial = request_json(f"{API}/research/goal-runs/from-message",
                           {"message": task["question"], "model": MODELS["qwen"]}, timeout=60)
    run_id = initial["run_id"]
    first = wait_run(run_id)
    resumed = None
    if first.get("run_status") == "waiting_for_user_input" and task.get("continuation"):
        request_json(f"{API}/research/goal-runs/{run_id}/resume",
                     {"message": task["continuation"]}, timeout=60)
        resumed = wait_run(run_id)
    return {"task_id": task["task_id"], "model_id": MODELS["qwen"], "run_id": run_id,
            "initial_response": first, "resume_response": resumed,
            "response": resumed or first, "same_run_resume": bool(resumed and resumed.get("run_id") == run_id),
            "wall_seconds": round(time.perf_counter() - started, 3)}


def captured_evidence(task_id: str) -> list[dict]:
    source = HERE / "raw/agent" / f"{task_id}.json"
    if not source.is_file():
        raise RuntimeError(f"Agent raw response missing for {task_id}")
    run = json.loads(source.read_text(encoding="utf-8")).get("response") or {}
    result = [{"evidence_id": item.get("evidence_id"), "document": item.get("document"),
               "page": item.get("page"), "chunk_id": item.get("chunk_id"), "kind": "KB",
               "excerpt": item.get("excerpt", "")}
              for item in run.get("internal_sources", [])]
    result.extend({"evidence_id": item.get("evidence_id"), "document": item.get("document"),
                   "page": item.get("page"), "image_path": item.get("image_path"), "kind": "FIG",
                   "excerpt": item.get("source_note") or item.get("excerpt", "")}
                  for item in run.get("figures", []))
    return result


def prompts(task: dict, same_evidence: bool) -> tuple[str, str, list[dict]]:
    system = ("Answer the petroleum-engineering request in the user's language. Be concise and "
              "state uncertainty. No tools, Python, retrieval or web access. Do not invent formulas, "
              "measurements or citations. Explicitly correct a false premise. If essential input "
              "is absent, ask for it. Cite evidence IDs only when evidence is supplied.")
    evidence = captured_evidence(task["task_id"]) if same_evidence else []
    user = task["question"]
    if same_evidence:
        system += (" Use only supplied KB/FIG text and the user's values for sourced engineering "
                   "claims. Cite supporting IDs in square brackets. No other evidence is available.")
        user += "\n\n=== Captured Agent KB/FIG text evidence ===\n" + json.dumps(evidence, ensure_ascii=False)
    return system, user, evidence


def call_qwen(system: str, turns: list[dict]) -> dict:
    payload = request_json("http://127.0.0.1:11434/api/chat", {
        "model": MODELS["qwen"], "messages": [{"role": "system", "content": system}, *turns],
        "stream": False, "think": False,
        "options": {"temperature": 0, "seed": 42, "num_ctx": 16384,
                    "num_predict": 1200}}, timeout=300)
    return {"answer": payload.get("message", {}).get("content", "").strip(),
            "model_id": payload.get("model"), "input_tokens": payload.get("prompt_eval_count"),
            "output_tokens": payload.get("eval_count"), "provider_payload": payload}


def call_openai(system: str, turns: list[dict]) -> dict:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY absent")
    payload = request_json("https://api.openai.com/v1/responses", {
        "model": MODELS["openai"], "instructions": system,
        "input": [{"role": turn["role"], "content": turn["content"]} for turn in turns],
        "reasoning": {"effort": "low"}, "max_output_tokens": 1800,
        "tools": [], "store": False},
        headers={"Authorization": "Bearer " + key}, timeout=300)
    answer = payload.get("output_text") or "".join(
        part.get("text", "") for output in payload.get("output", [])
        for part in output.get("content", []) if part.get("type") == "output_text")
    return {"answer": answer.strip(), "model_id": payload.get("model"),
            "input_tokens": payload.get("usage", {}).get("input_tokens"),
            "output_tokens": payload.get("usage", {}).get("output_tokens"),
            "response_id": payload.get("id"), "provider_payload": payload}


def run_baseline(task: dict, provider: str, same_evidence: bool) -> dict:
    system, user, evidence = prompts(task, same_evidence)
    caller = call_qwen if provider == "qwen" else call_openai
    started = time.perf_counter()
    first = caller(system, [{"role": "user", "content": user}])
    final = first
    if task.get("continuation"):
        final = caller(system, [{"role": "user", "content": user},
                                {"role": "assistant", "content": first["answer"]},
                                {"role": "user", "content": task["continuation"]}])
    return {"task_id": task["task_id"], "provider": provider,
            "track": "same_evidence" if same_evidence else "closed_book",
            "question": task["question"], "continuation": task.get("continuation"),
            "system_prompt": system, "user_prompt": user, "evidence": evidence,
            "initial_answer": first["answer"], **final,
            "wall_seconds": round(time.perf_counter() - started, 3)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=PHASES)
    args = parser.parse_args()
    benchmark = load_benchmark()
    invalid_path = HERE / "invalid_tasks.json"
    invalid = {row["task_id"] for row in json.loads(invalid_path.read_text(encoding="utf-8"))["invalid"]} if invalid_path.exists() else set()
    same = args.phase.startswith("same-")
    provider = args.phase.removeprefix("same-")
    if provider == "agent":
        print("PREFLIGHT " + json.dumps(preflight_server()), flush=True)
    outdir = HERE / (f"same_evidence/{provider}" if same else f"raw/{provider}")
    print(f"PHASE={args.phase} TASKS={len(benchmark['tasks'])} MODEL={MODELS['qwen' if provider=='agent' else provider]}", flush=True)
    for index, task in enumerate(benchmark["tasks"], 1):
        task_id = task["task_id"]
        if task_id in invalid:
            print(f"{index:02d}/60 {task_id} INVALID SKIP", flush=True)
            continue
        path = outdir / f"{task_id}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("error"):
                raise RuntimeError(f"Existing error needs audit before retry: {path}")
            print(f"{index:02d}/60 {task_id} EXISTING", flush=True)
            continue
        started = time.perf_counter()
        try:
            result = run_agent(task) if provider == "agent" else run_baseline(task, provider, same)
        except Exception as exc:
            result = {"task_id": task_id, "track": args.phase,
                      "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                      "wall_seconds": round(time.perf_counter() - started, 3)}
        write_once(path, result)
        print(f"{index:02d}/60 {task_id} {result.get('error','OK')} {result['wall_seconds']:.1f}s", flush=True)
        if result.get("error"):
            print("STOP: inspect provider or infrastructure error; no silent retry", flush=True)
            sys.exit(2)
        if provider == "openai":
            time.sleep(2)


if __name__ == "__main__":
    main()
