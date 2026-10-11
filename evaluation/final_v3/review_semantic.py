"""Blinded task input for a single local semantic adjudicator."""

from __future__ import annotations

import hashlib
import json
import random

from score_deterministic import TRACKS


INSTRUCTIONS = """You are one independent AI-assisted semantic reviewer, not a human reviewer.
Judge five anonymized petroleum-engineering answers against one frozen task. Do not infer
system identity or repair answers. The final answer is scored; on clarification tasks,
also judge whether the first answer requested the missing information.

Return JSON only: {"scores":{"A":{...},"B":{...},...}}. Every score object must have:
- claim_verdicts: one boolean per expected claim, in the supplied order. True only
  when the answer accurately conveys the claim. A refusal is not a correct positive claim.
- partial_or_better: at least one substantive requested part is correct.
- unsupported_claim_count: count invented, source-incompatible, or unjustified specific
  engineering assertions. A closed-book answer is not automatically unsupported.
- hallucination: fabricated factual, numeric, formula, source, or engineering assertion.
  Missing citation by itself is not hallucination.
- engineering_contradiction_count: count wrong engineering relations.
- numeric_accuracy: boolean or null if no numeric gold. Match values to their named
  outputs; mere appearance of an input number is not sufficient.
- unit_accuracy: boolean or null if no expected unit. Units must attach to the
  corresponding output. Dimensionless values need no unit.
- formula_accuracy: boolean or null when a formula is requested or supplied.
- false_premise_handled: boolean or null. True requires explicit rejection of the
  erroneous premise, the corrected relation, and a supporting citation when evidence
  is provided. Never score agreement with a false premise as successful.
- safe_refusal_correct: boolean or null; applicable to unsupported tasks.
- citation_semantic_support: a FRACTION between 0.0 and 1.0, or null if the answer
  cites no KB/FIG IDs. Divide supported cited IDs by all cited IDs. Never return a
  raw count: if 2 of 4 citations support their claims, output 0.5, NOT 2. If every
  citation supports its claim, output 1.0. Do not rely on document/page similarity.
- note: concise evidence-based reason; no private chain-of-thought.

Frozen gold source spans are answer keys, not evidence available to the systems.
If an answer is empty, all claim verdicts are false and partial_or_better is false.
No Markdown."""


def answer_for(track: str, task_id: str) -> dict:
    payload = json.loads((TRACKS[track] / f"{task_id}.json").read_text(encoding="utf-8"))
    if track == "agent":
        response = payload.get("response") or {}
        initial = payload.get("initial_response") or {}
        evidence = [{
            "evidence_id": item.get("evidence_id"), "document": item.get("document"),
            "page": item.get("page"), "excerpt": item.get("excerpt") or item.get("source_note") or "",
        } for item in [*response.get("internal_sources", []), *response.get("figures", [])]]
        return {"answer": response.get("final_answer", ""),
                "initial_answer": initial.get("clarification_question") or initial.get("final_answer") or "",
                "evidence": evidence}
    return {"answer": payload.get("answer", ""), "initial_answer": payload.get("initial_answer", ""),
            "evidence": payload.get("evidence", [])}


def review_input(task: dict, catalog: dict) -> tuple[dict, dict[str, str]]:
    tracks = list(TRACKS)
    random.Random(int(hashlib.sha256(task["task_id"].encode()).hexdigest()[:8], 16)).shuffle(tracks)
    mapping = {chr(65 + index): track for index, track in enumerate(tracks)}
    item = {
        "question": task["question"], "category": task["category"],
        "expected_claims": task["expected_claims"],
        "required_numeric_result": task.get("required_numeric_result"),
        "expected_after_resume": task.get("expected_after_resume"),
        "expected_units": task.get("expected_units"),
        "expected_formula": task.get("expected_formula") or task.get("user_formula"),
        "tolerance": task.get("tolerance") or task.get("resume_tolerance"),
        "gold_source_spans": [catalog[key] for key in task["expected_source_ids"]],
        "answers": {label: answer_for(track, task["task_id"]) for label, track in mapping.items()},
    }
    if task.get("continuation"):
        item["user_continuation_after_clarification"] = task["continuation"]
    return item, mapping
