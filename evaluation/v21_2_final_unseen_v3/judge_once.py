"""One blinded, exact-model semantic judgment per completed answer."""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from uuid import uuid4

from common import CONFIG, HERE, TASKS, openai_once, utc_now, write_json
from integrity_check import frozen_hashes_ok, product_changed_files


SCHEMA = {
    "type": "json_schema",
    "name": "v3_semantic_judgment",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim_scores": {"type": "array", "items": {"type": "number", "enum": [0, 0.5, 1]}},
            "all_required_goals_met": {"type": "boolean"},
            "false_premise_explicitly_corrected": {"type": "boolean"},
            "unanswerable_specific_missing_identified": {"type": "boolean"},
            "hallucination": {"type": "boolean"},
            "numeric_accuracy": {"type": "boolean"},
            "unit_accuracy": {"type": "boolean"},
            "citation_semantic_support": {"type": "boolean"},
            "unnecessary_refusal": {"type": "boolean"},
            "brief_reason": {"type": "string"},
        },
        "required": [
            "claim_scores", "all_required_goals_met", "false_premise_explicitly_corrected",
            "unanswerable_specific_missing_identified", "hallucination",
            "numeric_accuracy", "unit_accuracy", "citation_semantic_support",
            "unnecessary_refusal", "brief_reason",
        ],
    },
}


def deterministic_failure(task: dict) -> dict:
    return {
        "claim_scores": [0] * len(task["required_claims"]),
        "all_required_goals_met": False,
        "false_premise_explicitly_corrected": False,
        "unanswerable_specific_missing_identified": False,
        "hallucination": False,
        "numeric_accuracy": False,
        "unit_accuracy": False,
        "citation_semantic_support": False,
        "unnecessary_refusal": False,
        "brief_reason": "Predeclared no-response technical-failure score; no fabricated claim or refusal.",
    }


def make_prompt(task: dict, answer: str, label: str) -> str:
    gold = {
        "question": task["question"],
        "category": task["category"],
        "required_goals": task["required_goals"],
        "required_claims_in_order": task["required_claims"],
        "forbidden_claims": task["forbidden_claims"],
        "numeric_targets": task["numeric_targets"],
        "specific_missing_inputs_if_unanswerable": task["missing_inputs"],
        "allowed_source_evidence": [
            {"document": s["document"], "page": s["page"], "exact_span": s["exact_span"]}
            for s in task["gold_sources"]
        ],
        "anonymous_candidate_label": label,
        "answer": answer,
    }
    return json.dumps(gold, ensure_ascii=False)


def main() -> None:
    if not frozen_hashes_ok() or product_changed_files():
        raise RuntimeError("frozen benchmark/product integrity failed")
    systems = ["qwen_closed_book", "v21_2_agent"]
    if (HERE / "raw" / "gpt_reference").is_dir():
        systems.append("gpt_reference")
    for system in systems:
        if len(list((HERE / "raw" / system).glob("*.json"))) != 36:
            raise RuntimeError(f"raw generation incomplete for {system}")
    rng = random.Random(20261013)
    labels: dict[str, dict[str, str]] = {}
    for task in TASKS:
        order = systems.copy()
        rng.shuffle(order)
        labels[task["task_id"]] = {system: f"Candidate {chr(65 + i)}" for i, system in enumerate(order)}
    write_json(HERE / "judge" / "blinding_map.json", labels)

    completed = 0
    failed = 0
    for task in TASKS:
        order = sorted(systems, key=lambda system: labels[task["task_id"]][system])
        for system in order:
            path = HERE / "judge" / f"{task['task_id']}__{system}.json"
            if path.exists():
                print(f"judge {task['task_id']} existing; no second call", flush=True)
                continue
            raw = json.loads((HERE / "raw" / system / f"{task['task_id']}.json").read_text(encoding="utf-8"))
            record = {
                "task_id": task["task_id"],
                "system": system,
                "anonymous_label": labels[task["task_id"]][system],
                "judge_model": CONFIG["judge_model"],
                "attempt_id": str(uuid4()),
                "attempt_count": 1 if not raw.get("technical_failure") else 0,
                "reserved_at": utc_now(),
                "status": "reserved",
            }
            write_json(path, record)
            if raw.get("technical_failure"):
                record.update(status="deterministic_technical_failure", judgment=deterministic_failure(task), completed_at=utc_now())
                write_json(path, record)
                completed += 1
                print(f"judge {task['task_id']} deterministic technical failure", flush=True)
                continue
            started = time.monotonic()
            try:
                text, meta = openai_once(
                    CONFIG["judge_model"],
                    "You are a blinded single-reviewer semantic adjudicator. Judge only the anonymous answer against the exact question, atomic rubric, user-supplied inputs, and allowed source evidence. Do not infer the model or system. Score each required claim in order as 1 full, 0.5 partial, or 0 absent/wrong. Mark all_required_goals_met only if every materially required goal is answered; false-premise cases require explicit rejection and correction, unanswerable cases require naming the specific missing input. Numeric accuracy requires every critical value within tolerance and compatible units. Hallucination includes materially wrong or fabricated engineering claims, equation, quantities, units, provenance, or unwarranted certainty. A cautious but otherwise complete answer is not an unnecessary refusal. Judge source citations semantically, not just by ID. Return only the required JSON object. Do not include private reasoning.",
                    make_prompt(task, raw["answer_text"], record["anonymous_label"]),
                    judge=True,
                    response_format=SCHEMA,
                )
                judgment = json.loads(text)
                if len(judgment["claim_scores"]) != len(task["required_claims"]):
                    raise ValueError("judge claim-score count mismatched frozen rubric")
                record.update(status="completed", judgment=judgment, response_meta=meta, latency_seconds=round(time.monotonic() - started, 6), completed_at=utc_now())
                completed += 1
            except Exception as exc:
                record.update(status="judge_failure", error=f"{type(exc).__name__}: {exc}"[:1000], latency_seconds=round(time.monotonic() - started, 6), completed_at=utc_now())
                failed += 1
            write_json(path, record)
            print(f"judge {task['task_id']} {record['anonymous_label']} {record['status']} completed={completed} failed={failed}", flush=True)
    print(f"judge finished; completed_or_deterministic={completed}, failures={failed}", flush=True)


if __name__ == "__main__":
    main()
