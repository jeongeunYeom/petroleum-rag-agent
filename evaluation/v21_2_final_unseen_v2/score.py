"""Apply the frozen rubric to one-shot raw/judge outputs and write final artifacts."""

from __future__ import annotations

import csv
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from common import HERE, load, save
from integrity_check import verify


SYSTEMS = ["qwen_closed_book","v21_2_agent","gpt_reference"]
LABELS = {"qwen_closed_book":"qwen3:8b Closed-book","v21_2_agent":"V21.2 Agent",
          "gpt_reference":"GPT Reference"}
CITATION = re.compile(r"\[(?:KB|FIG|WEB)\d+\]")


def unit_matches(expected: str, observed: str, equivalents: dict) -> bool:
    valid = {value.casefold().replace(" ","") for value in equivalents.get(expected,[expected])}
    return (observed or "").casefold().replace(" ","") in valid


def numeric_correct(task: dict, verdict: dict, equivalents: dict) -> bool | None:
    targets = task["numeric_targets"]
    if not targets:
        return None
    actuals = verdict.get("final_numeric_outputs") or []
    for target in targets:
        expected = float(target["expected_value"])
        tolerance = max(target["absolute_tolerance"], target["relative_tolerance"]*abs(expected))
        if not any(isinstance(output,dict) and isinstance(output.get("value"),(int,float))
                   and math.isclose(float(output["value"]),expected,abs_tol=tolerance,rel_tol=0)
                   and unit_matches(target["expected_unit"],str(output.get("unit") or ""),equivalents)
                   for output in actuals):
            return False
    return True


def actions(run: dict) -> list[str]:
    return [str(item.get("action_type") or item.get("action") or "").upper()
            for item in run.get("action_history") or []]


def retrieve_then_calculate(run: dict) -> bool:
    sequence = actions(run)
    return any(any("RETRIEVE" in earlier for earlier in sequence[:index])
               for index,action in enumerate(sequence) if "CALCULATE" in action)


def normalized(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def formula_source_correct(task: dict, run: dict) -> bool:
    if task["category"] != "kb_formula":
        return False
    gold = task["formula_source"]
    target_formula = normalized(gold["exact_formula_span"])
    sources = {source.get("evidence_id"):source for source in run.get("internal_sources") or []}
    for comp in run.get("computations") or []:
        if not comp.get("validation_passed"):
            continue
        source_ids = set(comp.get("formula_source_ids") or [])
        if comp.get("formula_source_id"):
            source_ids.add(comp["formula_source_id"])
        raw = normalized(comp.get("raw_formula_span") or comp.get("source_equation") or comp.get("source_formula") or "")
        if len(raw) < 7:
            continue
        for source_id in source_ids:
            source = sources.get(source_id) or {}
            if source.get("document") != gold["document"] or source.get("page") != gold["page"]:
                continue
            excerpt = normalized(source.get("excerpt") or "")
            if not excerpt:
                continue
            if (target_formula in excerpt or raw in excerpt) and (raw in target_formula or target_formula in raw or raw in excerpt):
                return True
    return False


def provenance_complete(run: dict, *, kb_formula: bool) -> bool:
    for comp in run.get("computations") or []:
        if not (comp.get("validation_passed") and comp.get("contract_validation_passed")):
            continue
        required = [comp.get("input_fact_ids"),comp.get("bound_variables"),
                    comp.get("normalized_formula"),comp.get("execution_hash"),comp.get("output")]
        if kb_formula:
            required.append(comp.get("formula_source_ids") or comp.get("formula_source_id"))
        if all(required):
            return True
    return False


def source_retrieved(task: dict, run: dict) -> bool:
    formula = task["formula_source"]
    if not formula.get("required"):
        return False
    return any(s.get("document") == formula["document"] and s.get("page") == formula["page"]
               for s in run.get("internal_sources") or [])


def percentile(sorted_values: list[float], fraction: float) -> float:
    position = (len(sorted_values)-1)*fraction
    lo = math.floor(position)
    hi = math.ceil(position)
    return sorted_values[lo] + (sorted_values[hi]-sorted_values[lo])*(position-lo)


def bootstrap_difference(pairs: list[tuple[float,float]]) -> dict:
    rng = random.Random(20261013)
    differences = []
    n = len(pairs)
    for _ in range(10000):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        differences.append(sum(a-b for a,b in sample)/n)
    differences.sort()
    estimate = sum(a-b for a,b in pairs)/n
    return {"difference":estimate,"ci_low":percentile(differences,0.025),
            "ci_high":percentile(differences,0.975),"paired_n":n,
            "superiority_established":percentile(differences,0.025)>0}


def summarize(rows: list[dict]) -> dict:
    assert len(rows) == 36
    numeric = [r for r in rows if r["numeric_correct"] is not None]
    assert len(numeric) == 16
    latencies = sorted(float(r["latency_seconds"]) for r in rows)
    return {"goal_success":sum(r["goal_success"] for r in rows)/36,
            "claim_coverage":sum(r["claim_coverage"] for r in rows)/36,
            "hallucination_free":sum(r["hallucination_free"] for r in rows)/36,
            "numerical_accuracy":sum(r["numeric_correct"] for r in numeric)/16,
            "latency_mean_seconds":statistics.mean(latencies),
            "latency_median_seconds":statistics.median(latencies),
            "latency_p95_seconds":percentile(latencies,0.95)}


def resume_metrics(probes: list[dict]) -> dict:
    rows = []
    for probe in probes:
        path = HERE / "resume" / f"{probe['probe_id']}.json"
        if not path.exists():
            rows.append({"probe_id":probe["probe_id"],"completed":False})
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        first = raw.get("turn_1_run") or {}
        final = raw.get("final_run") or {}
        answer = final.get("final_answer") or ""
        expected = float(probe["expected_value"])
        numbers = [float(n.replace(",","")) for n in re.findall(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?",answer)]
        correct = any(math.isclose(x,expected,rel_tol=0.001,abs_tol=0.02) for x in numbers)
        computations = final.get("computations") or []
        item = {"probe_id":probe["probe_id"],"turn_1_correct_waiting":first.get("run_status")=="waiting_for_user_input",
                "same_run_preserved":bool(raw.get("run_id") and first.get("run_id")==raw["run_id"] and final.get("run_id")==raw["run_id"]),
                "supplied_fact_bound":bool(computations and any(c.get("bound_variables") for c in computations)),
                "repeated_clarification":final.get("run_status")=="waiting_for_user_input",
                "final_completion":str(final.get("status","")).lower()=="achieved" and correct,
                "validated_calculation":any(c.get("validation_passed") for c in computations),
                "completed":raw.get("status")=="completed"}
        rows.append(item)
    return {"rows":rows,"turn_1_waiting":sum(r.get("turn_1_correct_waiting",False) for r in rows),
            "same_run":sum(r.get("same_run_preserved",False) for r in rows),
            "fact_bound":sum(r.get("supplied_fact_bound",False) for r in rows),
            "repeated_clarification":sum(r.get("repeated_clarification",False) for r in rows),
            "final_completion":sum(r.get("final_completion",False) for r in rows),
            "validated_calculation":sum(r.get("validated_calculation",False) for r in rows)}


def score() -> dict:
    integrity = verify(post=True)
    tasks = load("benchmark.json")["primary_tasks"]
    rubric = load("rubric.json")
    equivalent = rubric["numeric_unit_equivalences"]
    by_system: dict[str,list[dict]] = defaultdict(list)
    scored = []
    for task in tasks:
        judge = load(f"judge/{task['task_id']}.json")
        assert judge["status"] == "completed" and judge["actual_model"] == rubric["judge_model"]
        labels = judge["anonymous_labels"]
        verdicts = judge["verdict"]["responses"]
        for label,system in labels.items():
            verdict = verdicts[label]
            raw = load(f"raw/{system}/{task['task_id']}.json")
            claim_scores = verdict["claim_scores"]
            assert len(claim_scores) == len(task["required_claims"])
            assert all(value in (0,0.5,1) for value in claim_scores)
            num = numeric_correct(task,verdict,equivalent)
            run = raw.get("run") or {}
            cite = verdict.get("citation_semantic_support")
            formula_correct = formula_source_correct(task,run) if system == "v21_2_agent" else None
            complete = provenance_complete(run,kb_formula=task["category"]=="kb_formula") if system == "v21_2_agent" else None
            sem_goal = bool(verdict["goal_success"] and all(x == 1 for x in claim_scores))
            goal = sem_goal and (num is not False)
            if system == "v21_2_agent":
                goal = goal and str(run.get("status","")).lower()=="achieved"
                if task["citation_required_for_agent"]:
                    goal = goal and cite is True and bool(CITATION.search(raw.get("answer", "")))
                if task["category"] == "kb_formula":
                    goal = goal and formula_correct and complete and retrieve_then_calculate(run)
                elif task["numeric_targets"]:
                    goal = goal and complete and any(c.get("validation_passed") for c in run.get("computations") or [])
            elif task["category"] == "kb_formula":
                # Closed-book systems cannot satisfy the frozen, source-backed calculation chain.
                goal = False
            if task["category"] == "false_premise":
                goal = goal and verdict.get("explicit_false_premise_rejection") is True
            hall = bool(verdict["hallucination_free"])
            if num is False and verdict.get("final_numeric_outputs"):
                hall = False
            row = {"task_id":task["task_id"],"category":task["category"],"domain":task["domain"],
                   "question_language":task["question_language"],"multi_goal":task["multi_goal"],
                   "system":system,"goal_success":bool(goal),"claim_coverage":sum(claim_scores)/len(claim_scores),
                   "hallucination_free":hall,"numeric_correct":num,
                   "citation_semantic_support":cite,"source_span_correct":verdict.get("source_span_correct"),
                   "unnecessary_refusal":bool(verdict.get("unnecessary_refusal")),
                   "formula_source_correct":formula_correct,"calculation_provenance_complete":complete,
                   "formula_source_retrieved":source_retrieved(task,run) if system=="v21_2_agent" else None,
                   "retrieve_then_calculate":retrieve_then_calculate(run) if system=="v21_2_agent" else None,
                   "calculation_executed":bool(run.get("python_calls_total",0)) if system=="v21_2_agent" else None,
                   "calculation_validated":any(c.get("validation_passed") for c in run.get("computations") or []) if system=="v21_2_agent" else None,
                   "numeric_operand_complete":any(c.get("input_fact_ids") and c.get("bound_variables") for c in run.get("computations") or []) if system=="v21_2_agent" else None,
                   "action_sequence":actions(run) if system=="v21_2_agent" else [],
                   "run_status":run.get("run_status") if system=="v21_2_agent" else None,
                   "product_status":run.get("status") if system=="v21_2_agent" else None,
                   "latency_seconds":raw["latency_seconds"],"error_labels":verdict.get("error_labels") or [],
                   "judge_rationale":verdict.get("brief_rationale","")}
            by_system[system].append(row)
            scored.append(row)

    metrics = {"FINALIZED":True,"integrity":integrity,"systems":{s:summarize(by_system[s]) for s in SYSTEMS},
               "category_goal_success":{s:{category:sum(r["goal_success"] for r in rows if r["category"]==category)/sum(r["category"]==category for r in rows)
                                             for category in sorted({r["category"] for r in rows})} for s,rows in by_system.items()},
               "resume":resume_metrics(load("benchmark.json")["resume_probes"])}
    agent = by_system["v21_2_agent"]
    agent_numeric = [r for r in agent if r["numeric_correct"] is not None]
    agent_kb = [r for r in agent if r["category"]=="kb_formula"]
    metrics["agent_diagnostics"] = {
        "calculation_executed_16":sum(r["calculation_executed"] for r in agent_numeric),
        "calculation_validated_16":sum(r["calculation_validated"] for r in agent_numeric),
        "numeric_correct_16":sum(r["numeric_correct"] for r in agent_numeric),
        "numeric_operand_complete_16":sum(r["numeric_operand_complete"] for r in agent_numeric),
        "kb_formula_retrieved_6":sum(r["formula_source_retrieved"] for r in agent_kb),
        "kb_correct_formula_span_6":sum(r["formula_source_correct"] for r in agent_kb),
        "kb_retrieve_calculate_6":sum(r["retrieve_then_calculate"] for r in agent_kb),
        "kb_numeric_correct_6":sum(r["numeric_correct"] for r in agent_kb),
        "unnecessary_refusals":sum(r["unnecessary_refusal"] for r in agent if r["category"]!="unanswerable"),
        "cross_language_success_12":sum(r["goal_success"] for r in agent if r["question_language"]=="ko"),
        "multi_goal_success_6":sum(r["goal_success"] for r in agent if r["multi_goal"]),
        "citation_semantic_support_count":sum(r["citation_semantic_support"] is True for r in agent if r["category"] in {"knowledge_qa","multi_claim_reasoning","kb_formula","false_premise"}),
    }
    for comparator in ("qwen_closed_book","gpt_reference"):
        metrics[f"paired_agent_minus_{comparator}"] = {}
        other = {r["task_id"]:r for r in by_system[comparator]}
        for metric in ("goal_success","claim_coverage","hallucination_free","numeric_correct"):
            selected = [r for r in agent if metric!="numeric_correct" or r[metric] is not None]
            pairs = [(float(r[metric]),float(other[r["task_id"]][metric])) for r in selected]
            metrics[f"paired_agent_minus_{comparator}"][metric] = bootstrap_difference(pairs)

    save(HERE / "scored_rows.json",{"rows":scored})
    save(HERE / "metrics.json",metrics)
    columns = ["task_id","category","domain","question_language","multi_goal","system","goal_success",
               "claim_coverage","hallucination_free","numeric_correct","citation_semantic_support",
               "source_span_correct","unnecessary_refusal","formula_source_correct","calculation_provenance_complete",
               "formula_source_retrieved","retrieve_then_calculate","calculation_executed","calculation_validated",
               "numeric_operand_complete","run_status","product_status","latency_seconds","error_labels","action_sequence"]
    with (HERE / "results.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=columns,extrasaction="ignore")
        writer.writeheader()
        for row in scored:
            writer.writerow({**row,"error_labels":";".join(row["error_labels"]),
                             "action_sequence":" > ".join(row["action_sequence"])})

    def pct(value: float) -> str:
        return f"{100*value:.1f}%"
    poster = ["# V21.2 final unseen poster metrics", "", "| Metric | qwen3:8b Closed-book | V21.2 Agent | GPT Reference |",
              "|---|---:|---:|---:|"]
    names = {"goal_success":"Goal Success","claim_coverage":"Claim Coverage",
             "hallucination_free":"Hallucination-free","numerical_accuracy":"Numerical Accuracy"}
    for key,label in names.items():
        poster.append(f"| {label} | {pct(metrics['systems']['qwen_closed_book'][key])} | {pct(metrics['systems']['v21_2_agent'][key])} | {pct(metrics['systems']['gpt_reference'][key])} |")
    poster.extend(["","## V21.2 − qwen3:8b paired differences (95% percentile CI)","",
                   "| Metric | Difference | 95% CI | Interpretation |","|---|---:|---:|---|"])
    for key,label in (("goal_success","Goal Success"),("claim_coverage","Claim Coverage"),
                      ("hallucination_free","Hallucination-free"),("numeric_correct","Numerical Accuracy")):
        p = metrics["paired_agent_minus_qwen_closed_book"][key]
        interpretation = "positive CI excludes zero" if p["superiority_established"] else "descriptive difference; superiority not established"
        poster.append(f"| {label} | {pct(p['difference'])} | [{pct(p['ci_low'])}, {pct(p['ci_high'])}] | {interpretation} |")
    poster.extend(["","## Goal Success by category","",
                   "| Category | n | qwen3:8b | V21.2 | GPT reference |","|---|---:|---:|---:|---:|"])
    for category in sorted({r["category"] for r in agent}):
        n = sum(r["category"]==category for r in agent)
        poster.append(f"| {category} | {n} | {pct(metrics['category_goal_success']['qwen_closed_book'][category])} | {pct(metrics['category_goal_success']['v21_2_agent'][category])} | {pct(metrics['category_goal_success']['gpt_reference'][category])} |")
    (HERE / "poster_metrics.md").write_text("\n".join(poster)+"\n",encoding="utf-8")

    failed = [f"{r['task_id']} ({r['category']})" for r in agent if not r["goal_success"]]
    report = ["# V21.2 final unseen evaluation", "",
              "V21.2 was evaluated once on a newly authored benchmark that was frozen after the V21.2 product freeze and before any evaluated product run. The product was not modified after benchmark creation or after execution began.","",
              f"Product SHA: `f5182b8ae2907452e1c53373055e66c5182c9b90`. Benchmark freeze commit: `{load('freeze_receipt.json')['benchmark_freeze_commit']}`.",
              "Primary benchmark: 36 tasks, including 16 numerical tasks and 12 Korean questions grounded in English sources. Four resume probes are separate and never enter primary denominators.",
              "Source candidates were sampled with seed 20261013 by document from the frozen 12-document/18,976-chunk KB before writing questions. Prior development/observed document-page pairs were mechanically excluded. Each authored question, numeric target, unit, source locator, literal formula span, and novelty score was validated before the freeze commit. The single AI judge is not a human reviewer and may make semantic scoring errors.","",
              "## Headline metrics","",*poster[2:8],"",
              "## Diagnostics","",f"Agent calculation executed/validated/numeric correct: {metrics['agent_diagnostics']['calculation_executed_16']}/{metrics['agent_diagnostics']['calculation_validated_16']}/{metrics['agent_diagnostics']['numeric_correct_16']} of 16.",
              f"KB formula retrieved/correct span/retrieve→calculate/numeric correct: {metrics['agent_diagnostics']['kb_formula_retrieved_6']}/{metrics['agent_diagnostics']['kb_correct_formula_span_6']}/{metrics['agent_diagnostics']['kb_retrieve_calculate_6']}/{metrics['agent_diagnostics']['kb_numeric_correct_6']} of 6.",
              f"Unnecessary refusals: {metrics['agent_diagnostics']['unnecessary_refusals']}. Korean-source success: {metrics['agent_diagnostics']['cross_language_success_12']}/12. Multi-goal success: {metrics['agent_diagnostics']['multi_goal_success_6']}/6. Resume completion: {metrics['resume']['final_completion']}/4.","",
              "## Latency","", "| System | Mean (s) | Median (s) | P95 (s) |","|---|---:|---:|---:|"]
    for system in SYSTEMS:
        m = metrics["systems"][system]
        report.append(f"| {LABELS[system]} | {m['latency_mean_seconds']:.2f} | {m['latency_median_seconds']:.2f} | {m['latency_p95_seconds']:.2f} |")
    report.extend(["","## Paired confidence intervals","",*poster[10:18],"",
                   "A 95% CI containing zero is a descriptive difference; superiority is not established.","",
                   "## Unsuccessful V21.2 tasks (after scoring)","",", ".join(failed) if failed else "None.","",
                   "## Resume probe outcomes","", "| Probe | Turn 1 waiting | Same run | Input bound | Repeated clarification | Final completion | Validated calculation |",
                   "|---|---:|---:|---:|---:|---:|---:|"])
    for r in metrics["resume"]["rows"]:
        report.append("| " + " | ".join([r["probe_id"]]+[str(r.get(k)) for k in ("turn_1_correct_waiting","same_run_preserved","supplied_fact_bound","repeated_clarification","final_completion","validated_calculation")]) + " |")
    report.extend(["","## Interpretation and limits","",
                   "This is a one-shot, independent benchmark. It must not be pooled with the observed older 24-task set. The 36-task primary set is small, and each task's gold sources come from one fixed local KB; the result does not estimate performance on arbitrary field data. Semantic outcomes depend on one blinded AI reviewer, not human adjudication. The four resume cases are diagnostic only. All values and conclusion language should be interpreted with the paired confidence intervals above.","",
                   "## Integrity","",f"FINALIZED={metrics['FINALIZED']}. Frozen benchmark/rubric, application code, and KB file hashes matched before and after model execution. Raw 36×3 and judge 36 counts passed."])
    (HERE / "FINAL_REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    return metrics


if __name__ == "__main__":
    result = score()
    print(json.dumps({"FINALIZED":result["FINALIZED"],"systems":result["systems"],
                      "agent_diagnostics":result["agent_diagnostics"],"resume":result["resume"]},ensure_ascii=False,indent=2))
