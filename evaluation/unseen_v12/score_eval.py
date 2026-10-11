"""Deterministic-plus-single-reviewer scoring of the frozen v12 evaluation."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import statistics
import subprocess
from datetime import datetime, timezone

from run_eval import CONFIG, DATASET, HERE, stable_hash, verify_freeze


def rate(values: list[bool]) -> float | None:
    return round(100 * sum(values) / len(values), 2) if values else None


def average(values: list[float]) -> float | None:
    return round(statistics.mean(values), 3) if values else None


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    x = (len(data) - 1) * fraction
    lo, hi = int(x), min(int(x) + 1, len(data) - 1)
    return round(data[lo] + (data[hi] - data[lo]) * (x - lo), 3)


def action_list(result: dict) -> list[str]:
    return [str(item.get("action") or item.get("action_type") or "").upper()
            for item in result.get("action_history", [])]


def numeric_values_present(task: dict, answer: str) -> bool:
    expected = task.get("expected_numeric") or {}
    numbers = [float(value.replace(",", "")) for value in
               re.findall(r"(?<![\w])[-+]?\d[\d,]*(?:\.\d+)?(?![\w])", answer)]
    percents = [float(value.replace(",", "")) for value in
                re.findall(r"([-+]?\d[\d,]*(?:\.\d+)?)\s*%", answer)]
    tolerance = float(task.get("tolerance", .01))
    return all(any(abs(number - float(value)) <= tolerance for number in numbers)
               or (0 <= float(value) <= 1 and any(abs(number / 100 - float(value)) <= tolerance
                                                      for number in percents))
               for value in expected.values())


def generic_abstention(answer: str) -> bool:
    """Product boilerplate cannot count as an expected engineering claim."""
    text = answer.strip()
    return (len(text) < 160 and not re.search(r"\[(?:KB|FIG|WEB)\d+\]", text, re.I)
            and bool(re.search(r"\b(?:evidence|sources?)\b|자료|근거", text, re.I))
            and bool(re.search(r"\b(?:not|no|cannot|insufficient)\b|못|않|부족|불충분", text, re.I)))


def names_missing_inputs(answer: str) -> bool:
    return (not generic_abstention(answer)
            and bool(re.search(r"\b(?:without|need|require|missing|provide|lack)\w*\b|필요|부족|제공|알려", answer, re.I)))


def explicitly_rejects_premise(answer: str) -> bool:
    return bool(re.search(r"\b(?:no|incorrect|false|wrong|reversed?|not correct)\b|아니|틀렸|잘못|반대", answer, re.I))


def source_checks(task: dict, result: dict) -> dict:
    retrieved = result.get("internal_sources", [])
    cited = re.findall(r"\[((?:KB|FIG|WEB)\d+)\]", result.get("final_answer", ""), re.I)
    known = {src.get("evidence_id") for src in retrieved}
    known |= {src.get("evidence_id") for src in result.get("figures", [])}
    known |= {src.get("evidence_id") for src in result.get("web_sources", [])}
    source_specs = [DATASET["source_catalog"][sid] for sid in task["source_ids"]]
    doc_hits = [any(src.get("document") == spec["document"] for src in retrieved)
                for spec in source_specs]
    page_hits = [any(src.get("document") == spec["document"] and src.get("page") == spec["page"]
                     for src in retrieved) for spec in source_specs]
    return {"cited_ids": cited, "citation_id_correct": bool(cited) and all(cid in known for cid in cited),
            "document_recall": sum(doc_hits) / len(doc_hits) if doc_hits else None,
            "page_recall": sum(page_hits) / len(page_hits) if page_hits else None,
            "gold_document_hit": any(doc_hits), "gold_page_hit": any(page_hits)}


def score_row(task: dict, raw: dict, review: dict) -> dict:
    result, verdict = raw["result"], review["verdict"]
    visible_answer = result.get("final_answer") or result.get("clarification_question") or ""
    source = source_checks(task, result)
    claims = list(verdict["claim_supported"])
    if len(claims) != len(task["expected_claims"]):
        raise ValueError(f"Claim count changed for {task['id']}")
    guard_flags = []
    if generic_abstention(visible_answer):
        if task["answerable"]:
            claims = [False] * len(claims)
        guard_flags.append("generic_abstention_not_claim_support")
    safe_refusal = (verdict["safe_refusal"] is True and names_missing_inputs(visible_answer))
    if not task["answerable"] and not safe_refusal:
        if len(claims) > 1:
            claims[1] = False
        guard_flags.append("missing_input_explanation_absent")
    premise_corrected = (verdict["false_premise_corrected"] is True
                         and explicitly_rejects_premise(visible_answer))
    if task["category"] == "false_premise" and verdict["false_premise_corrected"] and not premise_corrected:
        guard_flags.append("explicit_premise_rejection_absent")
    validated = [item for item in result.get("computations", []) if item.get("validation_passed")]
    numeric = task["category"] == "calculation"
    numeric_correct = verdict["numeric_correct"] is True and numeric_values_present(task, visible_answer)
    unsupported_count = 0 if generic_abstention(visible_answer) else verdict["unsupported_claim_count"]
    sourced = bool(task["source_ids"])
    citation_valid = (not sourced or (source["citation_id_correct"]
                                      and verdict["citation_semantic_supported"] is True))
    hallucination = bool(verdict["material_hallucination"] or verdict["engineering_contradiction_count"])
    if task["answerable"]:
        success = (all(claims) and not hallucination and not verdict["unnecessary_refusal"]
                   and citation_valid and result.get("status") == "achieved"
                   and (task["category"] != "false_premise" or premise_corrected)
                   and (not numeric or (numeric_correct
                                        and verdict["unit_correct"] is True and bool(validated))))
    else:
        success = (safe_refusal and not hallucination
                   and not bool(re.search(r"\b(?:exactly|정확히)\s+\d", visible_answer, re.I)))
    failures = []
    if task["answerable"]:
        if sourced and not source["gold_document_hit"]:
            failures.append("retrieval_document_miss")
        elif sourced and not source["gold_page_hit"]:
            failures.append("retrieval_page_miss")
        if sourced and not citation_valid:
            failures.append("citation_missing_or_semantically_unsupported")
        if source["gold_page_hit"] and not all(claims):
            failures.append("relevant_evidence_but_answer_incomplete")
        if not all(claims):
            failures.append("claim_coverage")
        if numeric and not validated:
            failures.append("missing_validated_CALC")
        if numeric and not numeric_correct:
            failures.append("wrong_numeric_result")
        if numeric and verdict["unit_correct"] is not True:
            failures.append("wrong_or_missing_unit")
        if verdict["unnecessary_refusal"] or result.get("run_status") == "waiting_for_user_input":
            failures.append("unnecessary_refusal_or_clarification")
        if result.get("status") != "achieved":
            failures.append("goal_not_achieved")
        if task["category"] == "false_premise" and not premise_corrected:
            failures.append("false_premise_not_explicitly_corrected")
    elif not safe_refusal:
        failures.append("unanswerable_fabrication_or_no_safe_response")
    if hallucination:
        failures.append("hallucination_or_engineering_contradiction")
    if unsupported_count:
        failures.append("unsupported_claim")
    if failures and task["category"] == "multi_source":
        failures.append("multi_hop_synthesis_failure")
    if failures and task["category"] == "terminology_confusion":
        failures.append("terminology_confusion")
    return {"id": task["id"], "category": task["category"], "difficulty": task["difficulty"],
            "claim_total": len(claims), "source_count": len(task["source_ids"]),
            "answerable": task["answerable"], "question": task["question"],
            "reference_answer": task["reference_answer"], "agent_answer": visible_answer,
            "run_id": result.get("run_id"), "run_status": result.get("run_status"),
            "goal_status": result.get("status"), "goal_success": bool(success),
            "exact_accuracy": bool(all(claims) and not hallucination
                                   and (task["answerable"] or safe_refusal)),
            "partial_or_better": any(claims), "claim_coverage": sum(bool(x) for x in claims) / len(claims),
            "hallucination": hallucination,
            "unsupported_claim_count": unsupported_count,
            "reviewer_raw_unsupported_claim_count": verdict["unsupported_claim_count"],
            "engineering_contradiction_count": verdict["engineering_contradiction_count"],
            "numeric_correct": numeric_correct if numeric else None,
            "unit_correct": verdict["unit_correct"] if numeric else None,
            "safe_refusal": safe_refusal if not task["answerable"] else None,
            "false_premise_corrected": premise_corrected if task["category"] == "false_premise" else None,
            "citation_semantic_supported": verdict["citation_semantic_supported"] if sourced else None,
            "validated_calc": bool(validated), "python_calls": result.get("python_calls_total", 0),
            "actions": action_list(result), "timing": result.get("timing", {}),
            "latency_seconds": raw["wall_seconds"], "review_cost_usd": review["cost_usd"],
            "review_note": verdict["failure_note"], "failure_labels": failures,
            "adjudication_guard_flags": guard_flags,
            "retrieved_context": [{"id": src.get("evidence_id"), "document": src.get("document"),
                                   "page": src.get("page"), "excerpt": src.get("excerpt", "")[:400]}
                                  for src in result.get("internal_sources", [])[:5]],
            **source}


def summarize(rows: list[dict]) -> dict:
    sourced = [r for r in rows if r["answerable"] and r["source_count"]]
    numeric = [r for r in rows if r["category"] == "calculation"]
    unanswerable = [r for r in rows if not r["answerable"]]
    false_premise = [r for r in rows if r["category"] == "false_premise"]
    guard_counts = Counter(flag for r in rows for flag in r["adjudication_guard_flags"])
    document_recall = [r["document_recall"] for r in rows if r["document_recall"] is not None]
    page_recall = [r["page_recall"] for r in rows if r["page_recall"] is not None]
    return {"n": len(rows), "invalid_tasks": 0, "infrastructure_errors": 0,
            "goal_success_pct": rate([r["goal_success"] for r in rows]),
            "run_status_counts": dict(Counter(r["run_status"] for r in rows)),
            "exact_accuracy_pct": rate([r["exact_accuracy"] for r in rows]),
            "partial_or_better_pct": rate([r["partial_or_better"] for r in rows]),
            "claim_coverage_pct": round(100 * sum(r["claim_coverage"] * r["claim_total"] for r in rows)
                                        / max(1, sum(r["claim_total"] for r in rows)), 2),
            "hallucination_pct": rate([r["hallucination"] for r in rows]),
            "unsupported_claims_total": sum(r["unsupported_claim_count"] for r in rows),
            "engineering_contradictions_total": sum(r["engineering_contradiction_count"] for r in rows),
            "numeric_accuracy_pct": rate([r["numeric_correct"] is True for r in numeric]),
            "unit_accuracy_pct": rate([r["unit_correct"] is True for r in numeric]),
            "validated_calc_pct": rate([r["validated_calc"] for r in numeric]),
            "safe_refusal_pct": rate([r["safe_refusal"] is True for r in unanswerable]),
            "false_premise_handling_pct": rate([r["false_premise_corrected"] is True for r in false_premise]),
            "adjudication_guard_counts": dict(guard_counts),
            "citation_id_correctness_pct": rate([r["citation_id_correct"] for r in sourced]),
            "citation_semantic_support_pct": rate([r["citation_semantic_supported"] is True for r in sourced]),
            "document_recall_at_k_pct": round(100 * statistics.mean(document_recall), 2) if document_recall else None,
            "page_recall_at_k_pct": round(100 * statistics.mean(page_recall), 2) if page_recall else None,
            "mean_latency_seconds": average([r["latency_seconds"] for r in rows]),
            "median_latency_seconds": round(statistics.median(r["latency_seconds"] for r in rows), 3) if rows else None,
            "p95_latency_seconds": percentile([r["latency_seconds"] for r in rows], .95),
            "average_retrieval_seconds": average([r["timing"].get("retrieval_seconds", 0) for r in rows]),
            "average_llm_generation_seconds": average([r["timing"].get("llm_generation_seconds", 0) for r in rows]),
            "average_python_seconds": average([r["timing"].get("python_seconds", 0) for r in rows]),
            "average_verification_seconds": average([r["timing"].get("verification_seconds", 0) for r in rows]),
            "average_synthesis_seconds": average([r["timing"].get("synthesis_seconds", 0) for r in rows]),
            "review_cost_usd": round(sum(r["review_cost_usd"] for r in rows), 4)}


def render_report(rows: list[dict], summary: dict, slices: dict, verdict: str) -> str:
    failures = Counter(label for row in rows for label in row["failure_labels"])
    lines = ["# v12 independent unseen evaluation", "",
             "Tested version: v12",
             "Dataset: new `unseen_eval_v12.json` (50 frozen tasks)",
             f"OpenAI model: `{CONFIG['reviewer_model']}`",
             "v12 modification during evaluation: NO",
             "main merge: NO", "",
             f"- Frozen product: `{CONFIG['product_sha']}`; benchmark SHA256: `{CONFIG['dataset_sha256']}`",
             f"- Evaluation: {len(rows)} new tasks; local `{CONFIG['agent_model']}` + hybrid Chroma (12 documents / 18,976 chunks), web off.",
             f"- Reviewer: `{CONFIG['reviewer_model']}`; single-reviewer AI-assisted semantic adjudication. No human review claim.",
             f"- Verdict: **{verdict}** under pre-registered thresholds in `EVALUATION_POLICY.md`.", "",
             "## 요약", "",
             f"- 엄격한 목표 달성 {summary['goal_success_pct']}%, 계산 정확도 {summary['numeric_accuracy_pct']}%, 잘못된 전제 교정 {summary['false_premise_handling_pct']}%로 사전 정의한 기준에 미달했다.",
             f"- 문서/페이지 검색 재현율은 {summary['document_recall_at_k_pct']}% / {summary['page_recall_at_k_pct']}%였지만, 인용 의미 지지는 {summary['citation_semantic_support_pct']}%였다. 검색 이후의 실행·판단 실패를 분리해서 보아야 한다.",
             f"- 답변 불가 5문항 중 구체적으로 필요한 입력을 설명한 비율은 {summary['safe_refusal_pct']}%였다. 막연한 안전 거절은 성공으로 처리하지 않았다.", "",
             "## Overall", "", "| Metric | Value |", "|---|---:|"]
    for key, value in summary.items():
        lines.append(f"| {key} | {value} |")
    lines += ["", "## Decision basis", "",
              f"Pre-registered PASS thresholds: goal success ≥70%, material hallucination ≤10%, citation semantic support ≥80%, safe handling of unanswerables ≥80%. Observed: {summary['goal_success_pct']}%, {summary['hallucination_pct']}%, {summary['citation_semantic_support_pct']}%, {summary['safe_refusal_pct']}%, respectively.",
              "Most frequent failure labels: " + ", ".join(f"{name} ({count})" for name, count in failures.most_common(5)) + ".", ""]
    lines += ["", "## Category / difficulty / answerability", "",
              "| Slice | n | Goal success % | Claim coverage % | Hallucination % | Median s |", "|---|---:|---:|---:|---:|---:|"]
    for name, metric in slices.items():
        lines.append(f"| {name} | {metric['n']} | {metric['goal_success_pct']} | {metric['claim_coverage_pct']} | {metric['hallucination_pct']} | {metric['median_latency_seconds']} |")
    lines += ["", "## Failure cases", "",
              "| ID | Category | Cause labels | Agent status | Reviewer observation |", "|---|---|---|---|---|"]
    for r in rows:
        if r["goal_success"]:
            continue
        lines.append(f"| {r['id']} | {r['category']} | {', '.join(r['failure_labels'])} | {r['goal_status']} | {r['review_note'].replace('|', '/')} |")
    lines += ["", "## Interpretation / limitations", "",
              "- Retrieval recall is computed against pre-frozen gold document/page metadata, not mere citation existence.",
              "- Stage timings come from product telemetry and can overlap; do not sum them to estimate end-to-end latency.",
              "- Strict goal success requires product achieved status, claim correctness, citation semantic support, and validated CALC for calculation tasks.",
              "- One AI reviewer can misjudge semantics; selected failures merit expert audit before external claims.",
              "- The reviewer occasionally credited gold passages even when the product showed only a generic abstention. Deterministic guard rules enforce the pre-registered requirement that the answer itself contain claims and name missing inputs. Original reviewer outputs are retained unchanged.",
              "- This unseen set differs from prior versions and must not be represented as a paired v11/v12 gain.",
              "- Source selection and hand-authored reference claims can carry errors; post-freeze corrections are prohibited and any errors should be marked INVALID.", "",
              "## Recommended next step", "",
              "Have a domain expert inspect the listed failures and gold spans, then design a separate future development set. Do not change this frozen run or merge v12 to main from this evaluation.", ""]
    return "\n".join(line.rstrip() for line in "\n".join(lines).splitlines()) + "\n"


def failure_analysis(rows: list[dict]) -> str:
    failed = [r for r in rows if not r["goal_success"]]
    selected = failed[:2]
    seen_categories = {r["category"] for r in selected}
    for row in failed:
        if row["category"] not in seen_categories:
            selected.append(row)
            seen_categories.add(row["category"])
    for label in ("retrieval_document_miss", "relevant_evidence_but_answer_incomplete",
                  "hallucination_or_engineering_contradiction", "missing_validated_CALC",
                  "unnecessary_refusal_or_clarification"):
        match = next((r for r in failed if label in r["failure_labels"] and r not in selected), None)
        if match:
            selected.append(match)
    lines = ["# v12 unseen failure analysis", "",
             f"Failed strict-goal tasks: {len(failed)} / {len(rows)}. Full raw records are in `raw/agent/` and `review/`.", ""]
    for r in selected:
        context = "\n".join(f"- {s['id']} {s['document']} p.{s['page']}: {s['excerpt']}"
                            for s in r["retrieved_context"]) or "- No KB context retrieved."
        lines += [f"## {r['id']} — {r['category']}", "", f"Question: {r['question']}", "",
                  f"Expected: {r['reference_answer']}", "", "Retrieved context:", context, "",
                  f"Model answer: {r['agent_answer'] or '(empty)'}", "",
                  f"Failure type: {', '.join(r['failure_labels'])}", "",
                  f"Reviewer observation: {r['review_note']}", ""]
    lines += ["## Recommendations (not implemented)", "",
              "Review the classified failures and independently verify gold evidence before any future product changes. Do not retune v12 on this frozen set.", ""]
    return "\n".join(line.rstrip() for line in "\n".join(lines).splitlines()) + "\n"


def main() -> None:
    verify_freeze()
    rows = []
    for task in DATASET["tasks"]:
        raw_file = HERE / "raw" / "agent" / f"{task['id']}.json"
        review_file = HERE / "review" / f"{task['id']}.json"
        if not raw_file.exists() or not review_file.exists():
            raise RuntimeError(f"Missing result or review for {task['id']}")
        rows.append(score_row(task, json.loads(raw_file.read_text(encoding="utf-8")),
                              json.loads(review_file.read_text(encoding="utf-8"))))
    summary = summarize(rows)
    groups = defaultdict(list)
    for row in rows:
        for label in (f"category:{row['category']}", f"difficulty:{row['difficulty']}",
                      f"answerability:{row['answerable']}"):
            groups[label].append(row)
    slices = {name: summarize(items) for name, items in sorted(groups.items())}
    systemic = Counter(label for row in rows for label in row["failure_labels"])
    if summary["goal_success_pct"] < 50 or summary["hallucination_pct"] > 20 or any(
            systemic[label] >= 3 for label in ("unanswerable_fabrication_or_no_safe_response", "missing_validated_CALC")):
        verdict = "FAIL"
    elif (summary["goal_success_pct"] >= 70 and summary["hallucination_pct"] <= 10
          and (summary["citation_semantic_support_pct"] or 0) >= 80
          and (summary["safe_refusal_pct"] or 0) >= 80):
        verdict = "PASS"
    else:
        verdict = "BORDERLINE"
    for name, data in (("raw_evaluation.json", rows), ("summary_metrics.json", {
            "overall": summary, "slices": slices, "decision": verdict,
            "failure_label_counts": dict(systemic), "dataset_sha256": stable_hash(HERE / "unseen_eval_v12.json"),
            "review_model": CONFIG["reviewer_model"]})):
        (HERE / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (HERE / "raw_evaluation.csv").open("w", newline="", encoding="utf-8-sig") as file:
        keys = [key for key in rows[0] if key not in {"timing", "actions", "cited_ids"}]
        writer = csv.DictWriter(file, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "; ".join(map(str, value)) if isinstance(value, list) else value
                             for key, value in row.items()})
    (HERE / "UNSEEN_EVAL_V12_REPORT.md").write_text(render_report(rows, summary, slices, verdict), encoding="utf-8")
    (HERE / "failure_analysis.md").write_text(failure_analysis(rows), encoding="utf-8")
    reviews = [json.loads((HERE / "review" / f"{task['id']}.json").read_text(encoding="utf-8"))
               for task in DATASET["tasks"]]
    freeze_commit = subprocess.check_output(["git", "log", "-1", "--format=%H", "--",
                                             "evaluation/unseen_v12/unseen_eval_v12.json"],
                                            cwd=HERE.parents[1], text=True).strip()
    (HERE / "usage.json").write_text(json.dumps({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "openai_model": CONFIG["reviewer_model"], "scored_calls": len(reviews),
        "discarded_completed_pilot_calls": 3, "rejected_http_400_pilot_requests": 1,
        "total_attempted_requests": len(reviews) + 4,
        "input_tokens": sum(r["usage"].get("input_tokens", 0) for r in reviews),
        "output_tokens": sum(r["usage"].get("output_tokens", 0) for r in reviews),
        "actual_cost_usd": summary["review_cost_usd"],
        "cost_note": "Saved-response cost is a lower bound; three discarded pilot responses lack retained token usage.",
        "conservative_cost_upper_usd": round(summary["review_cost_usd"] + 3 * .015, 4),
        "freeze_commit": freeze_commit,
        "product_sha": CONFIG["product_sha"],
        "dataset_sha256": CONFIG["dataset_sha256"],
        "agent_model": CONFIG["agent_model"], "retrieval_mode": CONFIG["retrieval_mode"],
        "retrieval_top_k": 5, "reranker": False, "web": False,
        "agent_seed": None, "agent_temperature": None,
        "reviewer_temperature": CONFIG["reviewer_temperature"],
        "spend_cap_usd": CONFIG["openai_spend_cap_usd"]}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": verdict, **summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
