"""Descriptive development-regression audit; this is not unseen benchmark scoring."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


CITATION = re.compile(r"\[(?:KB|WEB|FIG|CALC)\d+\]")
NUMBER = re.compile(r"(?<![\w])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def numeric_match(answer: str, specs: list[dict]) -> bool | None:
    if not specs:
        return None
    numbers = [float(value.replace(",", "")) for value in NUMBER.findall(answer)]
    for spec in specs:
        if "value" in spec:
            target, tolerance = float(spec["value"]), float(spec.get("tolerance") or 0)
            if not any(abs(value - target) <= tolerance + 1e-8 for value in numbers):
                return False
        elif "min" in spec and "max" in spec:
            if not any(float(spec["min"]) <= value <= float(spec["max"]) for value in numbers):
                return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--product-sha", default="unrecorded")
    args = parser.parse_args()
    tasks = {row["question_id"]: row for row in json.loads(args.rubric.read_text(encoding="utf-8"))["tasks"]}
    previous = {row["question_id"]: row for row in json.loads(args.previous.read_text(encoding="utf-8"))}
    raw = {row["question_id"]: row for line in args.raw.read_text(encoding="utf-8").splitlines()
           if line.strip() and (row := json.loads(line))}
    rows = []
    for task_id, task in tasks.items():
        item = raw.get(task_id, {})
        response = item.get("response") or {}
        sources = response.get("internal_sources") or []
        figures = response.get("figures") or []
        computations = response.get("computations") or []
        answer = response.get("final_answer") or ""
        citation_ids = set(CITATION.findall(answer))
        available_ids = {f"[{source['evidence_id']}]" for source in [*sources, *figures,
                          *(response.get("web_sources") or [])] if source.get("evidence_id")}
        available_ids |= {f"[{calc['computation_id']}]" for calc in computations
                          if calc.get("validation_passed") and calc.get("computation_id")}
        actions = response.get("action_history") or []
        documents = str(task.get("document") or "").split("; ")
        pages = task.get("preferred_page", task.get("page"))
        pages = pages if isinstance(pages, list) else [pages]
        expected = [(normalize(document), page) for document, page in zip(documents, pages)
                    if document and page is not None]
        page_hit = bool(expected) and all(any(
            source.get("page") == page and normalize(source.get("document") or "") == document
            for source in [*sources, *figures]) for document, page in expected)
        validated = [calc for calc in computations if calc.get("validation_passed")]
        numeric = numeric_match(answer, task.get("required_values") or [])
        achieved = response.get("status") == "achieved"
        readiness = (response.get("telemetry") or {}).get("calculation_readiness") or []
        latest_readiness = readiness[-1] if readiness else {}
        criteria = response.get("criteria") or []
        errors = []
        if item.get("error"):
            errors.append("infrastructure_error")
        if task.get("answerable", True) and not sources and not figures:
            errors.append("retrieval_or_evidence_missing")
        if task.get("figure_evidence_required") and not figures:
            errors.append("figure_evidence_missing")
        requires_validated = (task.get("task_type") == "calculation" or
                              "VALIDATED" in str(task.get("required_evidence_type") or "").upper())
        if requires_validated and not validated:
            errors.append("validated_calculation_missing")
        if numeric is False:
            errors.append("required_numeric_value_missing")
        if citation_ids - available_ids:
            errors.append("unresolved_citation_id")
        if task.get("answerable", True) and not achieved and (sources or figures):
            errors.append("grounded_completion_or_reasoning_unresolved")
        if task.get("answerable", True) and not page_hit:
            errors.append("preferred_page_not_retrieved")
        if not task.get("answerable", True) and achieved:
            errors.append("unsupported_goal_marked_achieved")
        rows.append({
            "question_id": task_id, "category": task.get("task_type"), "answerable": task.get("answerable", True),
            "before_status": previous.get(task_id, {}).get("run_status"),
            "before_stop_reason": previous.get(task_id, {}).get("stop_reason"),
            "after_status": response.get("run_status"), "after_goal_status": response.get("status"),
            "after_stop_reason": response.get("stop_reason"), "elapsed_seconds": item.get("elapsed_seconds"),
            "actions": [action.get("action_type") for action in actions],
            "python_calls": response.get("python_calls_total", 0), "validated_calcs": len(validated),
            "expected_page_retrieved": page_hit, "figure_count": len(figures),
            "numeric_literal_match": numeric, "citation_ids_valid": not bool(citation_ids - available_ids),
            "citations": sorted(citation_ids), "suspected_failure_classes": errors,
            "last_calculation_readiness": latest_readiness,
            "criterion_statuses": {criterion.get("criterion_id"): criterion.get("status")
                                   for criterion in criteria},
            "top_evidence": [{"id": source.get("evidence_id"), "document": source.get("document"),
                              "page": source.get("page")} for source in sources[:5]],
            "figure_evidence": [{"id": source.get("evidence_id"), "document": source.get("document"),
                                 "page": source.get("page"), "figure_number": source.get("figure_number")}
                                for source in figures],
            "final_answer": answer,
        })
    status = Counter(row["after_goal_status"] or "missing" for row in rows)
    causes = Counter(cause for row in rows for cause in row["suspected_failure_classes"])
    category_counts = {}
    for category in sorted({row["category"] for row in rows}):
        group = [row for row in rows if row["category"] == category]
        category_counts[category] = {
            "tasks": len(group),
            "achieved_status": sum(row["after_goal_status"] == "achieved" for row in group),
            "validated_calculations": sum(row["validated_calcs"] for row in group),
            "preferred_page_retrieved": sum(row["expected_page_retrieved"] for row in group),
        }
    summary = {
        "label": "development regression, not unseen generalization evaluation",
        "product_sha": args.product_sha,
        "task_count": len(rows), "completed_rows": len(raw),
        "before_achieved_status_count": sum(row["before_status"] == "completed" and
                                            previous[row["question_id"]].get("stop_reason") == "goal_achieved"
                                            for row in rows),
        "after_goal_status_counts": dict(status),
        "python_calls": sum(row["python_calls"] for row in rows),
        "validated_calculations": sum(row["validated_calcs"] for row in rows),
        "expected_page_retrieved_count": sum(row["expected_page_retrieved"] for row in rows),
        "category_counts": category_counts,
        "stop_reason_counts": dict(Counter(row["after_stop_reason"] or "none" for row in rows)),
        "suspected_failure_counts": dict(causes),
        "semantic_accuracy_note": "Not adjudicated: literal checks and run status cannot establish answer accuracy.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "dev30_diagnostic.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Agent task-completion development regression", "",
             "This reuses the previously seen 30 tasks. It is **not** an unseen benchmark or semantic accuracy score.",
             "`Before` is the prior run status; `After` is the current agent goal status. Neither alone measures answer correctness.",
             "", f"Rows: {len(rows)}; agent achieved: {status.get('achieved', 0)}; "
             f"Python calls: {summary['python_calls']}; validated CALCs: {summary['validated_calculations']}.",
             "", "| ID | Type | Before | After | Actions | Page hit | Suspected issues |",
             "|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append("| " + " | ".join((row["question_id"], str(row["category"]),
            str(row["before_status"]), str(row["after_goal_status"]),
            "→".join(row["actions"]), "yes" if row["expected_page_retrieved"] else "no",
            ", ".join(row["suspected_failure_classes"]) or "—")) + " |")
    lines += ["", "These are triage labels only. A separate independent semantic review is required before any accuracy claim."]
    lines += ["", "## Category diagnostic", "",
              "| Category | Tasks | Achieved status | Validated CALCs | Preferred page retrieved |",
              "|---|---:|---:|---:|---:|"]
    for category, counts in category_counts.items():
        lines.append(f"| {category} | {counts['tasks']} | {counts['achieved_status']} | "
                     f"{counts['validated_calculations']} | {counts['preferred_page_retrieved']} |")
    lines += ["", "## Suspected failure classes", "",
              "These labels may overlap within a task; they are diagnostic flags, not independently adjudicated causes.", ""]
    for cause, count in causes.most_common():
        lines.append(f"- {cause}: {count}")
    (args.output_dir / "dev30_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
