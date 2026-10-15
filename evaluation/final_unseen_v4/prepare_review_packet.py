"""Assemble immutable gold and both raw conditions for task-level semantic review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def sha(name: str) -> str:
    return hashlib.sha256((HERE / name).read_bytes()).hexdigest()


def main() -> None:
    catalog = read("v4_catalog.json")
    actual = sha("v4_catalog.json")
    if actual != (HERE / "v4_catalog.sha256").read_text(encoding="ascii").split()[0]:
        raise RuntimeError("Sealed catalog changed")
    agent = {row["id"]: row for row in read("agent_results.json")["rows"]}
    baseline = {row["id"]: row for row in read("qwen_closed_book_results.json")["rows"]}
    automatic = read("automatic_scores.json")
    aflags = {row["id"]: row for row in automatic["agent"]}
    bflags = {row["id"]: row for row in automatic["qwen_closed_book"]}
    packet = {"catalog_sha256": actual, "rubric_sha256": sha("V4_SCORING_RUBRIC.md"),
              "agent_results_sha256": sha("agent_results.json"),
              "closed_book_results_sha256": sha("qwen_closed_book_results.json"), "items": []}
    for task in catalog["tasks"]:
        task_id = task["id"]
        arow = agent[task_id]
        brow = baseline[task_id]
        packet["items"].append({
            "id": task_id, "category": task["category"], "language": task["language"],
            "domain": task["domain"], "prompt": task["prompt"], "follow_up": task["follow_up"],
            "gold": task["gold"],
            "agent": {"first_turn_status": arow.get("first_turn_status"),
                      "first_turn_clarification": arow.get("first_turn_clarification"),
                      "final_status": arow.get("final_status"),
                      "final_answer": arow.get("final_answer"),
                      "final_clarification": arow.get("final_clarification"),
                      "run_id": arow.get("run_id"), "first_turn_run_id": arow.get("first_turn_run_id"),
                      "actions": [item.get("action_type") for item in arow.get("action_history", [])],
                      "validated_computations": [item for item in arow.get("computations", [])
                                                 if item.get("validation_passed")],
                      "citations": [{"id": item.get("evidence_id"),
                                     "document": item.get("document"), "page": item.get("page"),
                                     "excerpt": item.get("excerpt")}
                                    for item in arow.get("internal_sources", [])],
                      "validation": arow.get("validation"), "error": arow.get("error"),
                      "automatic_flags": aflags[task_id]},
            "qwen_closed_book": {"first_answer": brow.get("first_answer"),
                                 "final_answer": brow.get("final_answer"),
                                 "error": brow.get("error"),
                                 "automatic_flags": bflags[task_id]},
        })
    if len(packet["items"]) != 60:
        raise RuntimeError("Expected exactly 60 review items")
    (HERE / "semantic_review_packet.json").write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(packet['items'])} paired task-level review items")


if __name__ == "__main__":
    main()
