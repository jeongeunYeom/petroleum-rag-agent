"""Diagnostic agreement only; incomplete OpenAI reviews never enter final scores."""

from __future__ import annotations

import json
from pathlib import Path

from run_experiment import HERE


def main() -> None:
    comparisons = {"claim_verdicts": [], "hallucination": [], "numeric_accuracy": [],
                   "citation_full_support": [], "citation_support_abs_difference": []}
    tasks = []
    for source in sorted((HERE / "review").glob("*.json")):
        openai = json.loads(source.read_text(encoding="utf-8"))
        if "scores_by_track" not in openai:
            continue
        folder = "clarification_context" if source.stem.startswith("C") else "local_gemma_schema"
        local_path = HERE / "review" / folder / source.name
        if not local_path.exists():
            continue
        local = json.loads(local_path.read_text(encoding="utf-8"))
        if "scores_by_track" not in local:
            continue
        tasks.append(source.stem)
        for track, left in openai["scores_by_track"].items():
            right = local["scores_by_track"][track]
            comparisons["claim_verdicts"].append(left["claim_verdicts"] == right["claim_verdicts"])
            comparisons["hallucination"].append(left["hallucination"] == right["hallucination"])
            if left["numeric_accuracy"] is not None and right["numeric_accuracy"] is not None:
                comparisons["numeric_accuracy"].append(left["numeric_accuracy"] == right["numeric_accuracy"])
            a, b = left["citation_semantic_support"], right["citation_semantic_support"]
            if a is not None and b is not None:
                comparisons["citation_full_support"].append((a == 1) == (b == 1))
                comparisons["citation_support_abs_difference"].append(abs(a - b))
    summary = {"purpose": "diagnostic inter-model reviewer agreement; OpenAI partial reviews excluded from final metrics",
               "overlap_tasks": len(tasks), "overlap_system_rows": len(comparisons["claim_verdicts"]),
               "metrics": {name: {"n": len(values), "mean": round(sum(values) / len(values), 4) if values else None}
                           for name, values in comparisons.items()}}
    target = HERE / "review/reviewer_agreement_audit.json"
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
