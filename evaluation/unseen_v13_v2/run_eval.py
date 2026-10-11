"""Write-once, resumable v13 unseen evaluation; never edits product or gold data."""

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
DATASET = json.loads((HERE / "benchmark.json").read_text(encoding="utf-8"))
TERMINAL = {"completed", "stopped", "failed", "canceled", "waiting_for_user_input"}


def frozen_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify_freeze() -> None:
    expected = CONFIG["dataset_sha256"]
    if frozen_hash(HERE / "benchmark.json") != expected:
        raise RuntimeError("Frozen dataset hash mismatch")
    committed = subprocess.check_output(
        ["git", "show", "HEAD:evaluation/unseen_v13_v2/benchmark.json"], cwd=ROOT
    )
    if hashlib.sha256(committed.replace(b"\r\n", b"\n")).hexdigest() != expected:
        raise RuntimeError("Dataset is not frozen in HEAD")
    if subprocess.check_output(["git", "diff", "--name-only", CONFIG["product_sha"], "--",
                                "backend", "frontend"], cwd=ROOT).strip():
        raise RuntimeError("Product code differs from pinned v13")
    if subprocess.check_output(["git", "status", "--porcelain", "--", "backend", "frontend"],
                               cwd=ROOT).strip():
        raise RuntimeError("Uncommitted product change")


def request_json(url: str, payload: dict | None = None, headers: dict | None = None,
                 timeout: int = 30) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = Request(url, data=body, method="POST" if body is not None else "GET",
                  headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"HTTP {error.code} from {url.split('/')[2]}") from None
    except URLError as error:
        raise RuntimeError(f"Connection failure to {url.split('/')[2]}: {type(error.reason).__name__}") from None


def write_once(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def check_backend() -> None:
    checklist = request_json(CONFIG["api_base"] + "/system/checklist")
    if checklist.get("knowledge_base") != {"documents": 12, "chunks": 18976}:
        raise RuntimeError("Backend is not attached to the frozen 12-doc/18,976-chunk KB")
    probe = request_json(CONFIG["api_base"] + "/research/evidence",
                         {"query": "aquifer pressure support", "use_internal": True,
                          "use_external": False, "evidence_only": True,
                          "model": CONFIG["agent_model"]}, timeout=180)
    if probe.get("retrieval_mode") != CONFIG["retrieval_mode"]:
        raise RuntimeError("Backend retrieval mode is not hybrid")
    models = request_json("http://127.0.0.1:11434/api/tags")
    if CONFIG["agent_model"] not in [item.get("name") for item in models.get("models", [])]:
        raise RuntimeError("Pinned local Qwen model is unavailable")
    print("Preflight: KB 12/18976, hybrid, qwen3:8b, web off", flush=True)


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
            raise RuntimeError(f"Incomplete checkpoint: {path}")
        started = time.perf_counter()
        result = request_json(CONFIG["api_base"] + "/research/goal-runs/from-message",
                              {"message": task["question"], "model": CONFIG["agent_model"]}, timeout=45)
        run_id = result["run_id"]
        deadline = time.monotonic() + 600
        while result.get("run_status") not in TERMINAL:
            if time.monotonic() > deadline:
                raise RuntimeError(f"Agent timeout for {task['id']} run {run_id}; server run retained")
            time.sleep(2)
            result = request_json(CONFIG["api_base"] + f"/research/goal-runs/{run_id}")
        write_once(path, {"task_id": task["id"], "question": task["question"],
                          "model": CONFIG["agent_model"], "retrieval_mode": CONFIG["retrieval_mode"],
                          "web_enabled": False, "wall_seconds": round(time.perf_counter()-started, 3),
                          "result": result})
        print(f"[{index}/{len(tasks)}] {task['id']} {result['run_status']} ",
              f"{round(time.perf_counter()-started, 1)}s", flush=True)


def gold_excerpts() -> dict[str, str]:
    import chromadb
    db = ROOT / "data" / "vector_db"
    if not (db / "chroma.sqlite3").exists():
        raise RuntimeError("Existing DB missing")
    collection = chromadb.PersistentClient(path=str(db)).get_collection("petroleum_knowledge")
    if collection.count() != CONFIG["knowledge_base_chunks"]:
        raise RuntimeError("Chroma count changed")
    excerpts = {}
    for sid, spec in DATASET["source_catalog"].items():
        found = collection.get(where={"$and": [{"document": spec["document"]},
                                                 {"page": spec["page"]}]}, include=["documents"])
        anchor = " ".join(spec["anchor"].casefold().split())
        match = next((doc for doc in found["documents"] if anchor in " ".join(doc.casefold().split())), None)
        if match is None:
            raise RuntimeError(f"Frozen source span vanished: {sid}")
        location = match.casefold().find(spec["anchor"][:20].casefold())
        excerpts[sid] = match[max(0, location-400):location+1100] if location >= 0 else match[:1500]
    return excerpts


REVIEW_SYSTEM = """You are one independent petroleum-engineering semantic reviewer. Judge the visible answer against frozen expected claims, gold source excerpts, cited source excerpts, and calculation records. Do not reward answer-key wording unless it appears correctly in the answer. Do not infer missing facts. A correct number without correct operand binding is not a correct calculation. No tools or private reasoning output. Return only the required JSON object. Cite semantic support only when the cited excerpt really supports the substantive claim. An unanswerable safe response must avoid fabrication and specify missing inputs."""
REVIEW_PROPERTIES = {
    "claim_supported": {"type": "array", "items": {"type": "boolean"}},
    "material_hallucination": {"type": "boolean"},
    "unsupported_claim_count": {"type": "integer"},
    "engineering_contradiction_count": {"type": "integer"},
    "numeric_correct": {"type": ["boolean", "null"]},
    "unit_correct": {"type": ["boolean", "null"]},
    "operand_binding_correct": {"type": ["boolean", "null"]},
    "safe_refusal": {"type": ["boolean", "null"]},
    "false_premise_corrected": {"type": ["boolean", "null"]},
    "citation_semantic_supported": {"type": ["boolean", "null"]},
    "unnecessary_refusal": {"type": "boolean"},
    "failure_note": {"type": "string"},
}


def review_case(task: dict, raw: dict, gold: dict[str, str]) -> dict:
    result = raw["result"]
    sources = [{"id": s.get("evidence_id"), "document": s.get("document"),
                "page": s.get("page"), "excerpt": s.get("excerpt", "")[:1300]}
               for s in result.get("internal_sources", [])]
    calculations = [{key: comp.get(key) for key in (
        "computation_id", "purpose", "formula_source_ids", "input_fact_ids", "bound_variables",
        "normalized_formula", "units", "output", "validation_passed", "contract_validation_passed",
        "used_input_ids", "summary")}
        for comp in result.get("computations", [])]
    return {"task_id": task["id"], "question": task["question"],
            "expected_claims": task["expected_claims"], "reference_answer": task["reference_answer"],
            "answerable": task["answerable"], "expected_numeric": task.get("expected_numeric"),
            "expected_unit": task.get("expected_unit"),
            "gold_passages": [{"source_id": sid, **DATASET["source_catalog"][sid], "excerpt": gold[sid]}
                              for sid in task["source_ids"]],
            "visible_answer": result.get("final_answer") or result.get("clarification_question") or "",
            "run_status": result.get("run_status"), "cited_sources": sources,
            "figures": result.get("figures", []), "calculations": calculations}


def usage_cost(usage: dict) -> float:
    return (usage.get("input_tokens", 0) * CONFIG["openai_price_per_million_input_usd"]
            + usage.get("output_tokens", 0) * CONFIG["openai_price_per_million_output_usd"]) / 1_000_000


def actual_spend() -> float:
    return sum(usage_cost(json.loads(path.read_text(encoding="utf-8")).get("usage", {}))
               for path in (HERE / "review").glob("*.json")) if (HERE / "review").exists() else 0.0


def review(limit: int | None) -> None:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY missing; value is never logged")
    gold = gold_excerpts()
    tasks = DATASET["tasks"][:limit] if limit else DATASET["tasks"]
    for index, task in enumerate(tasks, 1):
        path = HERE / "review" / f"{task['id']}.json"
        if path.exists():
            print(f"[{index}/{len(tasks)}] {task['id']} REVIEW SKIP", flush=True)
            continue
        raw_path = HERE / "raw" / "agent" / f"{task['id']}.json"
        if not raw_path.exists():
            raise RuntimeError(f"Agent result missing: {task['id']}")
        case = review_case(task, json.loads(raw_path.read_text(encoding="utf-8")), gold)
        prompt = (f"Return JSON with exactly {len(task['expected_claims'])} claim_supported booleans, "
                  "in frozen claim order. Case: " + json.dumps(case, ensure_ascii=False))
        worst_case = usage_cost({"input_tokens": (len(prompt)+len(REVIEW_SYSTEM))//3 + 1000,
                                 "output_tokens": CONFIG["reviewer_max_output_tokens"]})
        if actual_spend() + worst_case > CONFIG["openai_spend_cap_usd"]:
            raise RuntimeError("Pre-registered OpenAI hard cap would be exceeded")
        payload = {"model": CONFIG["reviewer_model"], "instructions": REVIEW_SYSTEM,
                   "input": prompt, "temperature": 0, "reasoning": {"effort": "none"},
                   "max_output_tokens": CONFIG["reviewer_max_output_tokens"],
                   "text": {"format": {"type": "json_schema", "name": "unseen_v13_review",
                                       "strict": True, "schema": {"type": "object",
                                                                   "properties": REVIEW_PROPERTIES,
                                                                   "required": list(REVIEW_PROPERTIES),
                                                                   "additionalProperties": False}}},
                   "store": False}
        started = time.perf_counter()
        response = request_json("https://api.openai.com/v1/responses", payload,
                                headers={"Authorization": "Bearer " + key}, timeout=120)
        if response.get("model") != CONFIG["reviewer_model"] or response.get("status") != "completed":
            raise RuntimeError("Reviewer model/status mismatch; fallback disabled")
        content = "".join(part.get("text", "") for output in response.get("output", [])
                          for part in output.get("content", []) if part.get("type") == "output_text")
        verdict = json.loads(content)
        if set(verdict) != set(REVIEW_PROPERTIES) or len(verdict["claim_supported"]) != len(task["expected_claims"]):
            raise RuntimeError(f"Malformed reviewer verdict for {task['id']}")
        write_once(path, {"task_id": task["id"], "model": response["model"],
                          "response_id": response.get("id"), "usage": response.get("usage", {}),
                          "estimated_cost_usd": usage_cost(response.get("usage", {})),
                          "wall_seconds": round(time.perf_counter()-started, 3), "verdict": verdict})
        print(f"[{index}/{len(tasks)}] {task['id']} reviewed; saved cost ${actual_spend():.4f}", flush=True)


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
        estimate = len(DATASET["tasks"]) * usage_cost({"input_tokens": 8000,
            "output_tokens": CONFIG["reviewer_max_output_tokens"]})
        print(json.dumps({"model": CONFIG["reviewer_model"], "calls": len(DATASET["tasks"]),
                          "estimated_upper_usd": round(estimate, 4),
                          "hard_cap_usd": CONFIG["openai_spend_cap_usd"]}))


if __name__ == "__main__":
    main()
