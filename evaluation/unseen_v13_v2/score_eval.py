"""Pre-registered deterministic guards plus single-reviewer semantic scoring."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re
import statistics
import subprocess

from run_eval import CONFIG, DATASET, HERE, frozen_hash, verify_freeze


CALC = {"direct_calculation", "user_formula_calculation", "kb_formula_calculation"}


def pct(flags: list[bool]) -> float | None:
    return round(100 * sum(flags) / len(flags), 2) if flags else None


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def numbers_match(task: dict, answer: str) -> bool:
    values = [float(token.replace(",", "")) for token in re.findall(
        r"(?<![\w])[-+]?\d[\d,]*(?:\.\d+)?(?![\w])", answer)]
    percents = [float(token.replace(",", "")) for token in re.findall(
        r"([-+]?\d[\d,]*(?:\.\d+)?)\s*%", answer)]
    tolerance = float(task.get("tolerance", 0.01))
    return all(any(abs(number-float(expected)) <= tolerance for number in values)
               or (0 <= float(expected) <= 1 and any(
                   abs(number/100-float(expected)) <= tolerance for number in percents))
               for expected in task.get("expected_numeric", {}).values())


def generic_abstention(answer: str) -> bool:
    return (len(answer.strip()) < 170 and not re.search(r"\[(?:KB|FIG|WEB)\d+\]", answer, re.I)
            and bool(re.search(r"\b(?:evidence|sources?|insufficient|cannot)\b|자료|근거|부족|못", answer, re.I))
            and bool(re.search(r"\b(?:not|no|cannot|insufficient)\b|못|않|부족|불충분", answer, re.I)))


def names_missing_inputs(answer: str) -> bool:
    return bool(re.search(r"\b(?:without|need|require|missing|provide|lack)\w*\b|필요|부족|제공|알려", answer, re.I))


def rejects_premise(answer: str) -> bool:
    return bool(re.search(r"\b(?:no|incorrect|false|wrong|reversed?|not correct)\b|아니|틀렸|잘못|반대|동의하지|맞지 않|옳지 않", answer, re.I))


def names_specific_missing_inputs(answer: str) -> bool:
    """A stock 'missing input/unit/operation' notice is not a specific clarification."""
    return names_missing_inputs(answer) and bool(re.search(
        r"\b(?:geometry|volume|area|thickness|saturation|pressure|rate|permeability|density|"
        r"contact|length|diameter|fluid|completion|heterogeneity|aquifer|temperature|"
        r"flow|reservoir|annulus|casing)\b|부피|면적|두께|포화도|압력|유량|투과도|밀도|"
        r"길이|직경|온도|저류층|환상공간|케이싱|불균질", answer, re.I))


def source_checks(task: dict, result: dict) -> dict:
    sources = result.get("internal_sources", [])
    gold = [DATASET["source_catalog"][sid] for sid in task["source_ids"]]
    docs = [any(src.get("document") == item["document"] for src in sources) for item in gold]
    pages = [any(src.get("document") == item["document"] and src.get("page") == item["page"]
                 for src in sources) for item in gold]
    answer = result.get("final_answer") or ""
    citations = re.findall(r"\[((?:KB|WEB|FIG)\d+)\]", answer, re.I)
    known = {src.get("evidence_id") for src in sources + result.get("web_sources", [])
             + result.get("figures", [])}
    return {"citation_ids": citations, "citation_id_correct": bool(citations) and all(
        citation in known for citation in citations),
        "document_recall": sum(docs)/len(docs) if docs else None,
        "page_recall": sum(pages)/len(pages) if pages else None,
        "gold_document_hit": all(docs) if docs else None,
        "gold_page_hit": all(pages) if pages else None}


def formula_source_correct(task: dict, result: dict, calculations: list[dict]) -> bool | None:
    if task["category"] != "kb_formula_calculation":
        return None
    expected = {(DATASET["source_catalog"][sid]["document"],
                 DATASET["source_catalog"][sid]["page"]) for sid in task["source_ids"]}
    retrieved = {src.get("evidence_id"): src
                 for src in result.get("internal_sources", [])}
    for comp in calculations:
        ids = comp.get("formula_source_ids") or comp.get("formula_evidence_ids") or []
        ids = list(ids) + ([comp.get("formula_source_id")] if comp.get("formula_source_id") else [])
        for identifier in ids:
            source = retrieved.get(identifier)
            if source is None or (source.get("document"), source.get("page")) not in expected:
                continue
            excerpt = " ".join(source.get("excerpt", "").casefold().split())
            if any(" ".join(DATASET["source_catalog"][sid]["anchor"].casefold().split()) in excerpt
                   for sid in task["source_ids"]):
                return True
    return False


def score_row(task: dict, raw: dict, review: dict) -> dict:
    result, verdict = raw["result"], review["verdict"]
    answer = result.get("final_answer") or result.get("clarification_question") or ""
    claims = list(verdict["claim_supported"])
    if len(claims) != len(task["expected_claims"]):
        raise ValueError(f"Changed claim count: {task['id']}")
    if task["answerable"] and generic_abstention(answer):
        claims = [False] * len(claims)
    if not task["answerable"] and not names_specific_missing_inputs(answer):
        # The first safety claim may hold, but generic refusal cannot satisfy the missing-input claim.
        claims[1:] = [False] * max(0, len(claims)-1)
    checks = source_checks(task, result)
    sourced = task["answerable"] and bool(task["source_ids"])
    citation_semantic = verdict["citation_semantic_supported"] is True
    grounded_citation = checks["citation_id_correct"] and citation_semantic
    citation_good = not sourced or grounded_citation
    calculations = [item for item in result.get("computations", []) if item.get("validation_passed")
                    and item.get("contract_validation_passed")]
    calc_task = task["category"] in CALC
    numeric_good = (verdict["numeric_correct"] is True and numbers_match(task, answer)) if calc_task else None
    unit_good = (verdict["unit_correct"] is True) if calc_task else None
    bound = (verdict["operand_binding_correct"] is True and any(
        item.get("used_input_ids") or item.get("bound_variables") or item.get("input_fact_ids")
        for item in calculations)) if calc_task else None
    formula_good = formula_source_correct(task, result, calculations)
    hallucination = bool(verdict["material_hallucination"] or verdict["engineering_contradiction_count"])
    premise_good = (verdict["false_premise_corrected"] is True and rejects_premise(answer)
                    and grounded_citation)
    safe = (verdict["safe_refusal"] is True and names_specific_missing_inputs(answer)
            and not verdict["material_hallucination"])
    if task["answerable"]:
        success = (all(claims) and not hallucination and not verdict["unnecessary_refusal"]
                   and citation_good and result.get("status") == "achieved"
                   and (task["category"] != "false_premise" or premise_good)
                   and (not calc_task or (numeric_good and unit_good and bound and bool(calculations)
                                          and formula_good is not False)))
    else:
        success = safe and not bool(re.search(r"\b(?:exactly|정확히)\s+\d", answer, re.I))
    failures = []
    if task["answerable"]:
        if sourced and not checks["gold_document_hit"]:
            failures.append("retrieval")
        elif sourced and not checks["gold_page_hit"]:
            failures.append("retrieval")
        if sourced and not citation_good:
            failures.append("citation_grounding")
        if calc_task:
            if not calculations:
                actions = [str(row.get("action") or row.get("action_type") or "").upper()
                           for row in result.get("action_history", [])]
                failures.append("calculation_execution" if any(
                    action in {"CALCULATE", "SIMULATE"} for action in actions) else "routing")
            if not bound:
                failures.append("extraction_binding")
            if formula_good is False:
                failures.append("formula_selection")
            if not numeric_good or not unit_good:
                failures.append("verification")
        if task["category"] == "false_premise" and not premise_good:
            failures.append("false_premise")
        if not all(claims) or verdict["unnecessary_refusal"]:
            failures.append("verification")
        if result.get("status") != "achieved":
            failures.append("verification")
    elif not safe:
        failures.append("unanswerable_handling")
    if verdict["unsupported_claim_count"] or hallucination:
        failures.append("unsupported_extra_claim")
    return {"id": task["id"], "category": task["category"], "difficulty": task["difficulty"],
            "answerable": task["answerable"], "question": task["question"],
            "run_id": result.get("run_id"), "run_status": result.get("run_status"),
            "goal_status": result.get("status"), "answer": answer, "goal_success": bool(success),
            "exact_accuracy": bool(all(claims) and not hallucination
                                   and (not calc_task or (numeric_good and unit_good))
                                   and (task["answerable"] or safe)),
            "partial_or_better": any(claims), "claim_coverage": sum(claims)/len(claims),
            "claim_count": len(claims), "hallucination": hallucination,
            "unsupported_claim_count": verdict["unsupported_claim_count"],
            "engineering_contradiction_count": verdict["engineering_contradiction_count"],
            "document_recall": checks["document_recall"], "page_recall": checks["page_recall"],
            "citation_id_correct": checks["citation_id_correct"] if sourced else None,
            "citation_semantic_supported": grounded_citation if sourced else None,
            "reviewer_semantic_judgment": citation_semantic if sourced else None,
            "numeric_correct": numeric_good, "unit_correct": unit_good,
            "validated_calc": bool(calculations) if calc_task else None,
            "operand_binding_correct": bound, "formula_source_correct": formula_good,
            "false_premise_corrected": premise_good if task["category"] == "false_premise" else None,
            "safe_unanswerable": safe if not task["answerable"] else None,
            "python_calls": result.get("python_calls_total", 0), "timing": result.get("timing", {}),
            "latency_seconds": raw["wall_seconds"], "failure_labels": sorted(set(failures)),
            "reviewer_note": verdict["failure_note"], "review_cost_usd": review["estimated_cost_usd"]}


def summary(rows: list[dict]) -> dict:
    calc = [row for row in rows if row["category"] in CALC]
    sourced = [row for row in rows if row["answerable"] and row["document_recall"] is not None]
    false = [row for row in rows if row["category"] == "false_premise"]
    unanswered = [row for row in rows if not row["answerable"]]
    return {"n": len(rows), "source_answerable_n": len(sourced), "calculation_n": len(calc),
            "false_premise_n": len(false), "unanswerable_n": len(unanswered),
            "goal_success_pct": pct([r["goal_success"] for r in rows]),
            "exact_accuracy_pct": pct([r["exact_accuracy"] for r in rows]),
            "partial_or_better_pct": pct([r["partial_or_better"] for r in rows]),
            "claim_coverage_pct": round(100*sum(r["claim_coverage"]*r["claim_count"] for r in rows)
                                        / max(1, sum(r["claim_count"] for r in rows)), 2),
            "hallucination_pct": pct([r["hallucination"] for r in rows]),
            "unsupported_claims_total": sum(r["unsupported_claim_count"] for r in rows),
            "document_recall_at_k_pct": round(100*statistics.mean(r["document_recall"] for r in sourced), 2)
                                      if sourced else None,
            "page_recall_at_k_pct": round(100*statistics.mean(r["page_recall"] for r in sourced), 2)
                                  if sourced else None,
            "citation_id_correctness_pct": pct([r["citation_id_correct"] for r in sourced]),
            "citation_semantic_support_pct": pct([r["citation_semantic_supported"] for r in sourced]),
            "numeric_accuracy_pct": pct([r["numeric_correct"] for r in calc]),
            "unit_accuracy_pct": pct([r["unit_correct"] for r in calc]),
            "validated_calc_pct": pct([r["validated_calc"] for r in calc]),
            "operand_binding_pct": pct([r["operand_binding_correct"] for r in calc]),
            "kb_formula_source_correctness_pct": pct([r["formula_source_correct"] for r in calc
                                                       if r["category"] == "kb_formula_calculation"]),
            "false_premise_handling_pct": pct([r["false_premise_corrected"] for r in false]),
            "unanswerable_safe_handling_pct": pct([r["safe_unanswerable"] for r in unanswered]),
            "mean_latency_seconds": round(statistics.mean(r["latency_seconds"] for r in rows), 3)
                                    if rows else None,
            "median_latency_seconds": median([r["latency_seconds"] for r in rows]),
            "review_cost_usd": round(sum(r["review_cost_usd"] for r in rows), 4)}


def decision(metrics: dict, failures: Counter) -> str:
    if (metrics["goal_success_pct"] < 50 or metrics["hallucination_pct"] > 20
            or failures["unanswerable_handling"] >= 3 or failures["calculation_execution"] >= 3):
        return "FAIL"
    if (metrics["goal_success_pct"] >= 70 and metrics["hallucination_pct"] <= 10
            and (metrics["citation_semantic_support_pct"] or 0) >= 80
            and (metrics["unanswerable_safe_handling_pct"] or 0) >= 80):
        return "PASS"
    return "BORDERLINE"


def main() -> None:
    verify_freeze()
    rows = []
    for task in DATASET["tasks"]:
        raw = HERE / "raw" / "agent" / f"{task['id']}.json"
        review = HERE / "review" / f"{task['id']}.json"
        if not raw.exists() or not review.exists():
            raise RuntimeError(f"Incomplete task or reviewer result: {task['id']}")
        rows.append(score_row(task, json.loads(raw.read_text(encoding="utf-8")),
                              json.loads(review.read_text(encoding="utf-8"))))
    overall = summary(rows)
    groups = defaultdict(list)
    for row in rows:
        groups[f"category:{row['category']}"].append(row)
        groups[f"difficulty:{row['difficulty']}"].append(row)
    slices = {name: summary(items) for name, items in sorted(groups.items())}
    failure_counts = Counter(label for row in rows if not row["goal_success"]
                             for label in row["failure_labels"])
    verdict = decision(overall, failure_counts)
    freeze_commit = subprocess.check_output(["git", "log", "-1", "--format=%H", "--",
                                              "evaluation/unseen_v13_v2/benchmark.json"],
                                             cwd=HERE.parents[1], text=True).strip()
    metrics = {"product_sha": CONFIG["product_sha"], "freeze_commit": freeze_commit,
               "dataset_sha256": frozen_hash(HERE / "benchmark.json"), "reviewer_model": CONFIG["reviewer_model"],
               "decision": verdict, "overall": overall, "slices": slices,
               "failure_labels": dict(failure_counts)}
    (HERE / "summary_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2)+"\n",
                                                 encoding="utf-8")
    (HERE / "raw_evaluation.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2)+"\n",
                                                encoding="utf-8")
    with (HERE / "raw_evaluation.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        keys = [key for key in rows[0] if key != "timing"]
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "; ".join(map(str, value)) if isinstance(value, list) else value
                             for key, value in row.items() if key != "timing"})
    reviews = [json.loads((HERE / "review" / f"{task['id']}.json").read_text(encoding="utf-8"))
               for task in DATASET["tasks"]]
    usage = {"model": CONFIG["reviewer_model"], "reviewer_response_calls": len(reviews),
             "no_cost_model_lookup_calls": 2, "total_openai_http_requests": len(reviews)+2,
             "input_tokens": sum(row["usage"].get("input_tokens", 0) for row in reviews),
             "output_tokens": sum(row["usage"].get("output_tokens", 0) for row in reviews),
             "estimated_cost_usd": overall["review_cost_usd"],
             "hard_cap_usd": CONFIG["openai_spend_cap_usd"],
             "cost_basis": "usage tokens times official on-demand rates; billing invoice not independently verified"}
    (HERE / "usage.json").write_text(json.dumps(usage, indent=2)+"\n", encoding="utf-8")
    lines = ["# v13 independent unseen evaluation v2", "",
             f"Tested product commit: {CONFIG['product_sha']}",
             "Product modified during evaluation: NO",
             "Dataset frozen before execution: YES",
             "Prior unseen questions used for tuning: NO",
             f"OpenAI reviewer: {CONFIG['reviewer_model']}",
             "main merge: NO", "",
             f"Dataset: {len(rows)} tasks, SHA256 `{CONFIG['dataset_sha256']}`, freeze commit `{freeze_commit}`.",
             "Local Agent: qwen3:8b; hybrid; existing Chroma 12 documents/18,976 chunks; web OFF.",
             "The requested underscore reviewer ID was unavailable (HTTP 404); the official dotted snapshot with the same date was fixed for the whole run.",
             "Single-reviewer AI-assisted semantic adjudication; no human review claim.",
             f"Pre-registered decision: **{verdict}**.", "", "## Overall metrics", "",
             "| Metric | Value |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in overall.items()]
    lines += ["", "## Reviewer API usage and cost", "",
              f"- Fixed Responses calls: {usage['reviewer_response_calls']}; no-cost model lookups: {usage['no_cost_model_lookup_calls']}; total OpenAI HTTP requests: {usage['total_openai_http_requests']}.",
              f"- Input tokens: {usage['input_tokens']:,}; output tokens: {usage['output_tokens']:,}; estimated on-demand cost: ${usage['estimated_cost_usd']:.4f} versus $2.00 hard cap.",
              "- Cost is computed from returned usage and [official GPT-5.4 Mini pricing](https://developers.openai.com/api/docs/models/gpt-5.4-mini), not independently reconciled to a billing invoice.", ""]
    lines += ["", "## Category and difficulty", "",
              "| Slice | n | Strict success % | Exact accuracy % | Hallucination % |",
              "|---|---:|---:|---:|---:|"]
    lines += [f"| {name} | {item['n']} | {item['goal_success_pct']} | {item['exact_accuracy_pct']} | {item['hallucination_pct']} |"
              for name, item in slices.items()]
    lines += ["", "## Failure patterns (non-exclusive labels)", "",
              f"- Retrieval was marked in {failure_counts['retrieval']} failed tasks. Document recall was {overall['document_recall_at_k_pct']}%, but exact-page recall was only {overall['page_recall_at_k_pct']}%; this is a source-location gap, not proof that original PDFs lost content.",
              f"- Citation grounding was marked in {failure_counts['citation_grounding']} failures. Only {overall['citation_id_correctness_pct']}% of source-dependent answerable tasks used valid citation IDs, and {overall['citation_semantic_support_pct']}% met both ID and semantic-support checks.",
              f"- Calculation: direct {sum(r['goal_success'] for r in rows if r['category']=='direct_calculation')}/5, user-formula {sum(r['goal_success'] for r in rows if r['category']=='user_formula_calculation')}/5, KB-formula {sum(r['goal_success'] for r in rows if r['category']=='kb_formula_calculation')}/5. Validated CALC was {overall['validated_calc_pct']}% across 15 calculation tasks. Routing/binding and formula selection were marked in {failure_counts['routing']}/{failure_counts['extraction_binding']}/{failure_counts['formula_selection']} failed tasks, respectively.",
              f"- False-premise correction succeeded in {sum(r['false_premise_corrected'] is True for r in rows if r['category']=='false_premise')}/4; specific safe handling succeeded in {sum(r['safe_unanswerable'] is True for r in rows if not r['answerable'])}/4.",
              f"- {overall['unsupported_claims_total']} unsupported claims and {sum(r['hallucination'] for r in rows)} material-hallucination/contradiction task flags were recorded. The {failure_counts['verification']} verification labels overlap other failure types and are not a separate root-cause count.", ""]
    lines += ["", "## Failed tasks and pre-registered failure types", "",
              "| ID | Category | Failure types | Reviewer observation |", "|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['category']} | {', '.join(r['failure_labels'])} | {r['reviewer_note'].replace('|', '/')} |"
              for r in rows if not r["goal_success"]]
    lines += ["", "## Interpretation", "",
              "Calculations require the right final number and unit, validated contract-complete CALC, and correct operand binding; KB formula tasks additionally require formula-source provenance on the gold page.",
              "A source citation counts only if its ID exists in the run and the fixed reviewer finds semantic support in the cited excerpt.",
              "One AI reviewer can make semantic mistakes. The sealed benchmark and raw outputs are retained for later independent human inspection, not post-hoc retuning.",
              "For example, the FP04 reviewer flagged the cited electric-submersible-pump detail as unsupported even though its quoted excerpt mentions that detail; this possible reviewer false positive was not post-hoc overridden.",
              "This dataset differs from v12 unseen; no paired score-improvement claim is made.", "",
              "## Next step", "",
              {"PASS": "Proceed to a separately designed poster benchmark and external ChatGPT comparison.",
               "BORDERLINE": "Consider an additional independent verification set before making external claims.",
               "FAIL": "Preserve this sealed result and start a separate development cycle; do not hotfix against these questions."}[verdict], ""]
    (HERE / "final_report.md").write_text("\n".join(lines), encoding="utf-8")
    analysis = ["# v13 unseen v2 failure analysis", "",
                "Counts are non-exclusive and calculated only over failed strict-goal tasks.", "",
                *[f"- {name}: {count}" for name, count in failure_counts.most_common()], "",
                "## Representative observed patterns", "",
                "- SF01: a source-based definition ended in generic evidence refusal rather than a grounded answer.",
                "- DC02: both pressure operands were supplied, but the Agent requested their order and no validated CALC was produced.",
                "- KF03: the KB relationship was not adopted, so no validated formula-source chain or final numeric claim was produced.",
                "- UF05: validated user-formula result 2.4 was printed with psi even though the supplied index was dimensionless.",
                "- UA04: a generic input/unit/operation notice did not name the flow or geometry data needed for breakthrough time.",
                "- FP04: a possible reviewer false positive about cited ESP detail is retained unchanged for independent audit.", "",
                "No source reindex, benchmark rewrite, product hotfix, or v12 score comparison was performed.", ""]
    (HERE / "failure_analysis.md").write_text("\n".join(analysis), encoding="utf-8")
    print(json.dumps({"decision": verdict, **overall}, ensure_ascii=False))


if __name__ == "__main__":
    main()
