"""Resumable, write-once v12 evaluation. Does not modify product or benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CONFIG = json.loads((HERE / "run_config.json").read_text(encoding="utf-8"))
DATASET = json.loads((HERE / "unseen_eval_v12.json").read_text(encoding="utf-8"))
TERMINAL = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def stable_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify_freeze() -> None:
    if stable_hash(HERE / "unseen_eval_v12.json") != CONFIG["dataset_sha256"]:
        raise RuntimeError("Frozen benchmark hash mismatch")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not subprocess.check_output(["git", "cat-file", "-e", f"{head}:evaluation/unseen_v12/unseen_eval_v12.json"], cwd=ROOT, stderr=subprocess.DEVNULL) == b"":
        raise RuntimeError("Dataset is not frozen in a commit")
    committed = subprocess.check_output(["git", "show", f"{head}:evaluation/unseen_v12/unseen_eval_v12.json"], cwd=ROOT)
    if hashlib.sha256(committed.replace(b"\r\n", b"\n")).hexdigest() != CONFIG["dataset_sha256"]:
        raise RuntimeError("Committed frozen dataset differs")
    if subprocess.check_output(["git", "diff", "--name-only", CONFIG["product_sha"], "--", "backend", "frontend"], cwd=ROOT).strip():
        raise RuntimeError("Product differs from pinned v12 SHA")
    if subprocess.check_output(["git", "status", "--porcelain", "--", "backend", "frontend"], cwd=ROOT).strip():
        raise RuntimeError("Uncommitted product change")


def request_json(url: str, payload: dict | None = None, *, headers: dict | None = None,
                 timeout: int = 30) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})},
                  method="POST" if payload is not None else "GET")
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        # Never print provider response bodies: they can contain user text or secrets.
        raise RuntimeError(f"HTTP {exc.code} from {url.split('/')[2]}") from None
    except URLError as exc:
        raise RuntimeError(f"Connection failure to {url.split('/')[2]}: {type(exc.reason).__name__}") from None


def write_once(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def check_backend() -> None:
    info = request_json(CONFIG["api_base"] + "/system/checklist", timeout=30)
    print("Backend checklist:", json.dumps(info, ensure_ascii=False)[:1400], flush=True)
    text = json.dumps(info, ensure_ascii=False)
    if "18976" not in text or "12" not in text or "hybrid" not in text:
        raise RuntimeError("Backend checklist does not show frozen 12-doc/18,976-chunk hybrid KB")


def run_agent(limit: int | None) -> None:
    check_backend()
    tasks = DATASET["tasks"][:limit] if limit else DATASET["tasks"]
    for index, task in enumerate(tasks, 1):
        path = HERE / "raw" / "agent" / f"{task['id']}.json"
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("result", {}).get("run_status") in TERMINAL:
                print(f"[{index}/{len(tasks)}] {task['id']} SKIP", flush=True)
                continue
            raise RuntimeError(f"Existing incomplete raw output: {path}")
        started = time.perf_counter()
        result = request_json(CONFIG["api_base"] + "/research/goal-runs/from-message",
                              {"message": task["question"], "model": CONFIG["agent_model"]}, timeout=45)
        run_id = result["run_id"]
        deadline = time.monotonic() + 480
        while result["run_status"] not in TERMINAL:
            if time.monotonic() > deadline:
                raise RuntimeError(f"Agent timeout for {task['id']} run {run_id}; raw remains on server")
            time.sleep(2)
            result = request_json(CONFIG["api_base"] + f"/research/goal-runs/{run_id}")
        wall = round(time.perf_counter() - started, 3)
        write_once(path, {"task_id": task["id"], "question": task["question"],
                          "model": CONFIG["agent_model"], "retrieval_mode": CONFIG["retrieval_mode"],
                          "web_enabled": False, "wall_seconds": wall, "result": result})
        print(f"[{index}/{len(tasks)}] {task['id']} {result['run_status']} {wall}s", flush=True)


def gold_excerpts() -> dict[str, str]:
    import chromadb
    collection = chromadb.PersistentClient(path=str(ROOT / "data" / "vector_db")).get_collection("petroleum_knowledge")
    if collection.count() != CONFIG["knowledge_base_chunks"]:
        raise RuntimeError("ChromaDB count changed")
    sources: dict[str, str] = {}
    for source_id, spec in DATASET["source_catalog"].items():
        found = collection.get(where={"$and": [{"document": spec["document"]}, {"page": spec["page"]}]},
                               include=["documents"])
        docs = found["documents"] or []
        anchor = spec["anchor"].casefold()
        match = next((doc for doc in docs if anchor in " ".join(doc.casefold().split())), None)
        if not match:
            raise RuntimeError(f"Frozen source span disappeared: {source_id}")
        pos = match.casefold().find(anchor[:24])
        sources[source_id] = match[max(0, pos - 450):pos + 950] if pos >= 0 else match[:1400]
    return sources


SYSTEM = """You are a single independent petroleum-engineering answer reviewer. Judge only the answer and cited source excerpts against the frozen expected claims and gold passages. Do not infer missing facts or reward answer-key wording alone. No tools. Return ONLY a JSON object, no chain of thought. Required keys: claim_supported (boolean array in the same order as expected_claims), material_hallucination (boolean), unsupported_claim_count (integer), engineering_contradiction_count (integer), numeric_correct (boolean or null), unit_correct (boolean or null), safe_refusal (boolean or null), false_premise_corrected (boolean or null), citation_semantic_supported (boolean or null), unnecessary_refusal (boolean), failure_note (one short factual sentence). Treat citations as semantically supported only if the actual cited agent excerpts support the answer's substantive claims, not just matching document names. For unanswerable tasks, safe_refusal requires no fabricated exact answer and a clear explanation of missing inputs."""


def review_payload(task: dict, raw: dict, excerpts: dict[str, str]) -> dict:
    result = raw["result"]
    sources = [{"evidence_id": src.get("evidence_id"), "document": src.get("document"),
                "page": src.get("page"), "excerpt": src.get("excerpt", "")[:1800]}
               for src in result.get("internal_sources", [])]
    gold = [{"source_id": sid, "document": DATASET["source_catalog"][sid]["document"],
             "page": DATASET["source_catalog"][sid]["page"], "excerpt": excerpts[sid]}
            for sid in task["source_ids"]]
    return {"task_id": task["id"], "question": task["question"],
            "answerable": task["answerable"], "expected_claims": task["expected_claims"],
            "reference_answer": task["reference_answer"],
            "expected_numeric": task.get("expected_numeric"), "expected_unit": task.get("expected_unit"),
            "gold_source_passages": gold, "agent_answer": result.get("final_answer", ""),
            "agent_run_status": result.get("run_status"), "agent_cited_excerpts": sources,
            "agent_figure_excerpts": result.get("figures", [])}


def usage_cost(usage: dict) -> float:
    return (usage.get("input_tokens", 0) * CONFIG["openai_price_per_million_input_usd"]
            + usage.get("output_tokens", 0) * CONFIG["openai_price_per_million_output_usd"]) / 1_000_000


def actual_spend() -> float:
    return sum(usage_cost(json.loads(path.read_text(encoding="utf-8")).get("usage", {}))
               for path in (HERE / "review").glob("*.json")) if (HERE / "review").exists() else 0.0


def review(limit: int | None) -> None:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set; its value is never logged")
    excerpts = gold_excerpts()
    tasks = DATASET["tasks"][:limit] if limit else DATASET["tasks"]
    for index, task in enumerate(tasks, 1):
        path = HERE / "review" / f"{task['id']}.json"
        if path.exists():
            print(f"[{index}/{len(tasks)}] {task['id']} REVIEW SKIP", flush=True)
            continue
        raw_path = HERE / "raw" / "agent" / f"{task['id']}.json"
        if not raw_path.exists():
            raise RuntimeError(f"Agent result missing: {task['id']}")
        item = review_payload(task, json.loads(raw_path.read_text(encoding="utf-8")), excerpts)
        text = json.dumps(item, ensure_ascii=False)
        # Worst-case next call is bounded by max output + conservative input characters/3.
        max_next_cost = usage_cost({"input_tokens": len(text) // 3 + len(SYSTEM) // 3 + 1000,
                                    "output_tokens": CONFIG["reviewer_max_output_tokens"]})
        if actual_spend() + max_next_cost > CONFIG["openai_spend_cap_usd"]:
            raise RuntimeError("Predeclared OpenAI spend cap would be exceeded")
        payload = {"model": CONFIG["reviewer_model"], "instructions": SYSTEM, "input": text,
                   "temperature": CONFIG["reviewer_temperature"], "reasoning": {"effort": "none"},
                   "max_output_tokens": CONFIG["reviewer_max_output_tokens"],
                   "text": {"format": {"type": "json_object"}}, "store": False}
        start = time.perf_counter()
        response = request_json("https://api.openai.com/v1/responses", payload,
                                headers={"Authorization": "Bearer " + key}, timeout=120)
        if response.get("model") != CONFIG["reviewer_model"] or response.get("status") != "completed":
            raise RuntimeError("Reviewer model/status mismatch; no fallback permitted")
        content = "".join(part.get("text", "") for output in response.get("output", [])
                          for part in output.get("content", []) if part.get("type") == "output_text")
        verdict = json.loads(content)
        required = {"claim_supported", "material_hallucination", "unsupported_claim_count",
                    "engineering_contradiction_count", "numeric_correct", "unit_correct", "safe_refusal",
                    "false_premise_corrected", "citation_semantic_supported", "unnecessary_refusal", "failure_note"}
        if not required <= verdict.keys() or len(verdict["claim_supported"]) != len(task["expected_claims"]):
            raise RuntimeError(f"Malformed reviewer output: {task['id']}")
        write_once(path, {"task_id": task["id"], "model": response["model"],
                          "response_id": response.get("id"), "usage": response.get("usage", {}),
                          "cost_usd": usage_cost(response.get("usage", {})),
                          "wall_seconds": round(time.perf_counter() - start, 3), "verdict": verdict})
        print(f"[{index}/{len(tasks)}] {task['id']} reviewed ${actual_spend():.4f}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["agent", "review", "cost-preflight"])
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    verify_freeze()
    if args.phase == "agent":
        run_agent(args.limit)
    elif args.phase == "review":
        review(args.limit)
    else:
        # Conservative 8k input + 2k output per task; cap is separately enforced on actual usage.
        estimate = 50 * usage_cost({"input_tokens": 8000,
                                     "output_tokens": CONFIG["reviewer_max_output_tokens"]})
        print(json.dumps({"model": CONFIG["reviewer_model"], "calls": 50,
                          "estimated_upper_usd_at_8k_input_2k_output": round(estimate, 4),
                          "hard_cap_usd": CONFIG["openai_spend_cap_usd"]}))


if __name__ == "__main__":
    main()
