"""Fixed, single-reviewer semantic scoring for both systems; no rubric edits."""

from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request
from pathlib import Path


REVIEWER_MODEL = "gemma4:latest"
SYSTEM = """You are a strict independent evaluator, not a petroleum-answer generator.
Use the frozen gold rubric to evaluate the answer. Judge required claims semantically, including
Korean/English equivalents. A correct number without the required unit is incomplete. A wrong
formula operator, radical, exponent, or variable is incorrect. Do not trust an Agent's self-status.
Separate answer truth from grounding: evidence_support means the supplied ACTUAL evidence
supports that gold claim; citation_support means the evidence ID CITED alongside that answer
claim really supports it. No evidence means false, even if the answer is true. A validated
computation can support an arithmetic claim only when its inputs and formula match the claim.
For figure tasks, inspect the supplied image only when present; never infer visual detail from
document title alone. For unanswerable tasks, a safe non-invented refusal is correct.
An unsupported_new_claim is a material invented/false/private factual assertion, NOT merely an
uncited but correct general statement. Mark a refusal even if it adds unrelated text.
Return a single JSON object only with: claim_checks (list of objects with index, answer_present,
answer_correct, evidence_support, citation_support), refusal (bool), explicit_premise_correction (bool),
unsupported_new_claims (nonnegative integer), numeric_and_units_correct (bool or null),
equation_correct (bool or null), figure_correct (bool or null), calculation_correct (bool or null),
task_completed (bool), brief_reason (one short sentence). Do not add private reasoning."""


def load_jsonl(path: Path) -> dict[str, dict]:
    return {row["question_id"]: row for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() for row in [json.loads(line)]}


def make_evidence(response: dict) -> tuple[list[dict], list[str]]:
    blocks = []
    images = []
    for item in response.get("internal_sources", [])[:10]:
        blocks.append({"id": item.get("evidence_id"), "document": item.get("document"),
                       "page": item.get("page"), "excerpt": (item.get("excerpt") or "")[:850]})
    for item in response.get("figures", [])[:5]:
        blocks.append({"id": item.get("evidence_id"), "document": item.get("document"),
                       "page": item.get("page"), "figure_number": item.get("figure_number"),
                       "excerpt": (item.get("excerpt") or "")[:850],
                       "source_note": (item.get("source_note") or "")[:850]})
        image_path = item.get("image_path")
        if image_path and Path(image_path).is_file():
            images.append(image_path)
    for item in response.get("computations", [])[:5]:
        blocks.append({"id": item.get("computation_id"), "formula": item.get("formula"),
                       "summary": item.get("summary"), "validation_passed": item.get("validation_passed"),
                       "source_evidence_ids": item.get("source_evidence_ids"),
                       "input_facts": item.get("input_facts")})
    return blocks, images


def review(task: dict, system: str, row: dict) -> tuple[dict, float]:
    if system == "agent":
        response = row.get("response") or {}
        answer = response.get("final_answer", "")
        evidence, image_paths = make_evidence(response)
    else:
        answer = row.get("answer", "")
        evidence, image_paths = [], []
    gold = {key: task.get(key) for key in (
        "question_id", "question", "answerable", "expected_behavior", "required_claims",
        "required_values", "expected_units", "acceptable_equation", "forbidden_claims",
        "required_evidence_type", "task_type", "required_visual_claim")}
    user = "FROZEN GOLD:\n" + json.dumps(gold, ensure_ascii=False) + "\n\nANSWER:\n" + answer
    user += "\n\nACTUAL EVIDENCE:\n" + json.dumps(evidence, ensure_ascii=False)
    payload = {"model": REVIEWER_MODEL,
               "messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": user,
                             **({"images": [base64.b64encode(Path(path).read_bytes()).decode("ascii")
                                            for path in image_paths[:2]]} if image_paths else {})}],
               "stream": False, "think": False, "format": "json",
               "options": {"temperature": 0, "seed": 17, "num_predict": 1400}}
    request = urllib.request.Request("http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    start = time.monotonic()
    with urllib.request.urlopen(request, timeout=210) as response:
        result = json.loads(response.read().decode("utf-8"))
    raw = result["message"]["content"]
    return {"parsed": json.loads(raw), "raw": raw, "eval_count": result.get("eval_count")}, time.monotonic() - start


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rubric", type=Path, default=Path(__file__).with_name("rubric.json"))
    parser.add_argument("--agent", type=Path, default=Path(__file__).with_name("agent_raw.jsonl"))
    parser.add_argument("--baseline", type=Path, default=Path(__file__).with_name("baseline_raw.jsonl"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("semantic_review_raw.jsonl"))
    args = parser.parse_args()
    tasks = json.loads(args.rubric.read_text(encoding="utf-8"))["tasks"]
    inputs = {"agent": load_jsonl(args.agent), "baseline": load_jsonl(args.baseline)}
    done = set()
    if args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if "review" in row:
                    done.add((row["system"], row["question_id"]))
    for task in tasks:
        for system in ("agent", "baseline"):
            key = (system, task["question_id"])
            if key in done:
                continue
            row = {"system": system, "question_id": task["question_id"],
                   "reviewer_model": REVIEWER_MODEL}
            try:
                row["review"], row["elapsed_seconds"] = review(task, system, inputs[system][task["question_id"]])
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
            with args.output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(system, task["question_id"], "OK" if "review" in row else "ERROR", flush=True)


if __name__ == "__main__":
    main()
