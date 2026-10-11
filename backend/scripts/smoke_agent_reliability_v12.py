"""Local-only development E2E; synthetic prompts are not a final benchmark."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.research_routes import cached_research_agent
from app.core.config import get_settings
from app.models.goal_research_schemas import GoalRunStatus
from app.services.goal_execution_agent import GoalExecutionAgent
from app.services.goal_message_parser import GoalMessageRequest, parse_goal_message
from app.services.ollama import OllamaClient
from app.services.user_fact_registry import UserFactRegistry
from scripts.v12_acceptance import ExpectedRun, assess


CASES = [
    ("D01", "Direct", "A=6, B=10, C=14. Compute the mean from these readings.", None,
     ExpectedRun("direct_calc", "none", ("calculate", "verify", "synthesize"), output=10)),
    ("D02", "Direct", "A=9, B=17, C=25. Find the median of the supplied values.", None,
     ExpectedRun("direct_calc", "none", ("calculate", "verify", "synthesize"), output=17)),
    ("D03", "Direct", "X=12, Y=18, Z=21. Calculate the sum.", None,
     ExpectedRun("direct_calc", "none", ("calculate", "verify", "synthesize"), output=51)),
    ("D04", "Direct", "rate=240 stb/d. Convert this to stb/h.", None,
     ExpectedRun("direct_calc", "none", ("calculate", "verify", "synthesize"), output=10, unit="stb/h")),
    ("D05", "Direct", "mass=45 mg, volume=9 L. Calculate mass concentration.", None,
     ExpectedRun("direct_calc", "none", ("calculate", "verify", "synthesize"), output=5, unit="mg/L")),
    ("D06", "Direct", "diameter=6 in, length=120 ft. Calculate cylinder volume in ft3.", None,
     ExpectedRun("direct_calc", "none", ("calculate", "verify", "synthesize"), output=23.5619449, unit="ft3")),
    ("D07", "Direct", "펌프 전력은 각각 10, 20, 30 kW이고 모두 2시간 가동했다. 소비 에너지를 계산해줘.", None,
     ExpectedRun("direct_calc", "none", ("calculate", "verify", "synthesize"), output=120, unit="kWh")),
    ("D08", "Direct", "첫 구간은 90 stb/d로 1시간, 둘째는 120 stb/d로 2시간. 시간 가중 평균을 계산해줘.", None,
     ExpectedRun("direct_calc", "none", ("calculate", "verify", "synthesize"), output=110, unit="stb/d")),
    ("K01", "KB formula", "SG=0.83인 원유의 API도를 내부 교재에 나온 식을 확인하고 계산해줘.", None,
     ExpectedRun("kb_formula_calc", "kb_formula", ("retrieve", "calculate", "verify", "synthesize"), output=141.5/.83-131.5, unit="°API")),
    ("K02", "KB formula", "SG=0.91일 때 내부 자료의 API=141.5/SG-131.5 관계식으로 API gravity를 구해줘.", None,
     ExpectedRun("kb_formula_calc", "kb_formula", ("retrieve", "calculate", "verify", "synthesize"), output=141.5/.91-131.5, unit="°API")),
    ("K03", "KB formula", "Po=2700 psi, Pw=2500 psi. 내부 교재의 Pc=Po-Pw 관계를 확인하고 모세관압을 계산해줘.", None,
     ExpectedRun("kb_formula_calc", "kb_formula", ("retrieve", "calculate", "verify", "synthesize"), output=200)),
    ("K04", "KB formula", "Po=3100 psi, Pw=2850 psi. 문서에서 Pc=Po-Pw 식을 찾아 Pc 값을 산출해줘.", None,
     ExpectedRun("kb_formula_calc", "kb_formula", ("retrieve", "calculate", "verify", "synthesize"), output=250)),
    ("K05", "KB formula", "qt=170 stb/d, qw=45 stb/d. 내부 자료에 나온 qo=qt-qw 식으로 qo를 계산해줘.", None,
     ExpectedRun("kb_formula_calc", "kb_formula", ("retrieve", "calculate", "verify", "synthesize"), output=125)),
    ("K06", "KB formula", "qt=250 stb/d, qw=80 stb/d. 교재의 qo=qt-qw 관계를 확인하고 오일 유량을 구해줘.", None,
     ExpectedRun("kb_formula_calc", "kb_formula", ("retrieve", "calculate", "verify", "synthesize"), output=170)),
    ("K07", "KB formula", "Psc=100 psi, Pd=200 psi, Pb=300 psi, Pa=400 psi. 교재의 네 성분 Pt=Psc+Pd+Pb+Pa 식으로 계산해줘.", None,
     ExpectedRun("kb_formula_calc", "kb_formula", ("retrieve", "calculate", "verify", "synthesize"), output=1000)),
    ("K08", "KB formula", "Psc=110 psi, Pd=220 psi, Pb=330 psi, Pa=440 psi. 내부 자료의 네 성분 Pt=Psc+Pd+Pb+Pa 관계식을 확인하고 총압을 구해줘.", None,
     ExpectedRun("kb_formula_calc", "kb_formula", ("retrieve", "calculate", "verify", "synthesize"), output=1100)),
    ("U01", "User formula", "a=7, b=4. 내가 정의한 result=a*b+2로 계산해줘.", None,
     ExpectedRun("user_formula_calc", "user_formula", ("calculate", "verify", "synthesize"), output=30)),
    ("U02", "User formula", "a=19, b=8. Use my formula result=a-b to calculate result.", None,
     ExpectedRun("user_formula_calc", "user_formula", ("calculate", "verify", "synthesize"), output=11)),
    ("U03", "User formula", "x=3, y=5. score=x*x+y. Calculate score with my equation.", None,
     ExpectedRun("user_formula_calc", "user_formula", ("calculate", "verify", "synthesize"), output=14)),
    ("U04", "User formula", "a=8, b=2. output=a/b+1. 내가 준 식으로 output 값을 구해줘.", None,
     ExpectedRun("user_formula_calc", "user_formula", ("calculate", "verify", "synthesize"), output=5)),
    ("S01", "Simulation", "c=3. score=c*x. x=1부터 5까지 1 간격으로 변화시키고 최적값을 계산해줘.", None,
     ExpectedRun("user_formula_simulation", "user_formula", ("simulate", "analyze", "verify", "synthesize"), output=15)),
    ("S02", "Simulation", "b=2. score=b*x+1. Sweep x from 1 to 4 step 1 and find the best case.", None,
     ExpectedRun("user_formula_simulation", "user_formula", ("simulate", "analyze", "verify", "synthesize"), output=9)),
    ("S03", "Simulation", "k=4. index=k*x. x를 2부터 6까지 2씩 바꾸고 최적 조건을 찾아줘.", None,
     ExpectedRun("user_formula_simulation", "user_formula", ("simulate", "analyze", "verify", "synthesize"), output=24)),
    ("P01", "Premise", "압력 상승 시험에서는 shut-in 후 압력 기록이 필요 없다는 전제가 맞나? 내부 근거로 확인해줘.", None, None),
    ("P02", "Premise", "이수 밀도가 변해도 정수압에는 영향이 없다는 말이 옳은가? 교재를 확인해줘.", None, None),
    ("Q01", "Knowledge QA", "모세관압과 물 포화도의 관계를 내부 자료로 설명해줘.", None, None),
    ("Q02", "Knowledge QA", "저류층 투과도와 유체 유동 능력의 관계를 교재 근거로 설명해줘.", None, None),
    ("R01", "Resume", "a=4. result=a*b. 내가 준 식으로 result를 계산해줘.", "b=5.",
     ExpectedRun("user_formula_calc", "user_formula", ("calculate", "verify", "synthesize"), output=20, resume=True)),
    ("R02", "Resume", "score=c*x. x=1부터 5까지 1 간격으로 최적값을 계산해줘.", "c=4.",
     ExpectedRun("user_formula_simulation", "user_formula", ("simulate", "analyze", "verify", "synthesize"), output=20, resume=True)),
    ("R03", "Resume", "score=k*x. x from 2 to 6 step 2. Find the best case.", "k=3.",
     ExpectedRun("user_formula_simulation", "user_formula", ("simulate", "analyze", "verify", "synthesize"), output=18, resume=True)),
]

EXPECTED_FACTS = {
    "D01": (("A", 6, ""), ("B", 10, ""), ("C", 14, "")),
    "D02": (("A", 9, ""), ("B", 17, ""), ("C", 25, "")),
    "D03": (("X", 12, ""), ("Y", 18, ""), ("Z", 21, "")),
    "D04": (("rate", 240, "stb/d"),),
    "D05": (("mass", 45, "mg"), ("volume", 9, "L")),
    "D06": (("diameter", 6, "in"), ("length", 120, "ft")),
    "D07": (("pump_1_power", 10, "kW"), ("pump_2_power", 20, "kW"),
            ("pump_3_power", 30, "kW"), ("shared_duration", 2, "h")),
    "D08": (("segment_1_rate", 90, "stb/d"), ("segment_1_duration", 1, "h"),
            ("segment_2_rate", 120, "stb/d"), ("segment_2_duration", 2, "h")),
    "K01": (("SG", .83, ""),), "K02": (("SG", .91, ""),),
    "K03": (("Po", 2700, "psi"), ("Pw", 2500, "psi")),
    "K04": (("Po", 3100, "psi"), ("Pw", 2850, "psi")),
    "K05": (("qt", 170, "stb/d"), ("qw", 45, "stb/d")),
    "K06": (("qt", 250, "stb/d"), ("qw", 80, "stb/d")),
    "K07": (("psc", 100, "psi"), ("Pd", 200, "psi"), ("Pb", 300, "psi"), ("Pa", 400, "psi")),
    "K08": (("psc", 110, "psi"), ("Pd", 220, "psi"), ("Pb", 330, "psi"), ("Pa", 440, "psi")),
    "U01": (("a", 7, ""), ("b", 4, "")), "U02": (("a", 19, ""), ("b", 8, "")),
    "U03": (("x", 3, ""), ("y", 5, "")), "U04": (("a", 8, ""), ("b", 2, "")),
    "S01": (("c", 3, ""), ("x", 1, "")), "S02": (("b", 2, ""),),
    "S03": (("k", 4, ""),), "R01": (("a", 4, ""), ("b", 5, "")),
    "R02": (("x", 1, ""), ("c", 4, "")), "R03": (("k", 3, ""),),
}
EXPECTED_OPERATIONS = {"D01": "mean", "D02": "median", "D03": "sum",
                       "D04": "unit_conversion", "D05": "concentration_mass_per_volume",
                       "D06": "cylinder_volume", "D07": "power_times_duration",
                       "D08": "weighted_average_by_duration"}
EXPECTED_MISSING = {"R01": ("b",), "R02": ("c",), "R03": ("k",)}


def _observed(result, expected: ExpectedRun, prompt: str, reply: str | None, initial=None) -> dict:
    valid = [row for row in result.computations if row.validation_passed]
    numeric = next((float(row["value"]) for calc in valid for row in calc.output_manifest.values()
                    if isinstance(row.get("value"), (int, float)) and expected.output is not None and
                    abs(float(row["value"]) - expected.output) <= max(.01, abs(expected.output) * 1e-5)), None)
    unit = next((str(row.get("unit") or "") for calc in valid for row in calc.output_manifest.values()
                 if isinstance(row.get("value"), (int, float)) and numeric is not None and
                 abs(float(row["value"]) - numeric) < 1e-8), "")
    users = UserFactRegistry.from_messages([prompt, *([reply] if reply else [])])
    evidence = [{"evidence_id": item.evidence_id, "source_type": "knowledge_base", "text": item.excerpt}
                for item in result.internal_sources]
    evidence.extend(users.evidence())
    known = {row["evidence_id"] for row in evidence}
    for calc in valid:
        for fact in calc.input_facts:
            fact_id = str(fact.get("evidence_id") or "")
            if fact_id and fact_id not in known:
                evidence.append({"evidence_id": fact_id, "source_type": "user_fact",
                                 "text": f"{fact.get('name')}={fact.get('value')} {fact.get('unit') or ''}"})
                known.add(fact_id)
        for source_id in calc.formula_source_ids:
            if source_id.startswith("USERF"):
                if source_id not in known:
                    evidence.append({"evidence_id": source_id, "source_type": "user_fact",
                                     "text": calc.source_formula or ""})
                    known.add(source_id)
                else:
                    source = next(row for row in evidence if row["evidence_id"] == source_id)
                    if calc.source_formula and calc.source_formula not in source["text"]:
                        source["text"] += "\n" + calc.source_formula
    provenance = bool(valid) and all(GoalExecutionAgent._provenance_complete(
        calc, evidence, prompt + " " + (reply or "")) for calc in valid)
    binding = bool(valid) and all(calc.bound_variables and
                                  set(calc.bound_variables.values()) <= set(calc.input_fact_ids)
                                  for calc in valid)
    actions = [row["action_type"] for row in result.action_history]
    before_facts = {row.name for row in UserFactRegistry.from_topic(prompt).records}
    after_facts = {row.name for row in users.records}
    initial_missing = set(initial.required_inputs if initial else [])
    return {"intent": result.telemetry.get("intent_route"),
            "source_requirement": result.telemetry.get("source_requirement"),
            "facts": sorted(after_facts),
            "fact_values": {row.name: (row.value, row.canonical_unit) for row in users.records},
            "actions": actions,
            "operation": (result.telemetry.get("calculation") or {}).get("requested_operation_family"),
            "binding_pass": binding, "required_inputs": list(initial_missing),
            "calc_validated": bool(valid), "numeric": numeric, "unit": unit,
            "provenance_complete": provenance, "answer": result.final_answer,
            "run_status": result.run_status.value, "status": result.status.value,
            "stop_reason": result.stop_reason.value if result.stop_reason else None,
            "initial_waiting": bool(initial and initial.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT),
            "missing_variable_pass": bool(initial_missing),
            "same_run": bool(initial and result.run_id == initial.run_id),
            "prior_facts_kept": before_facts <= after_facts,
            "followup_facts_merged": bool(reply and after_facts - before_facts)}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    selected = [row for row in CASES if not args.cases or row[0] in args.cases]
    if args.cases and len(selected) != len(args.cases):
        parser.error("unknown case id")
    settings = get_settings()
    if settings.retrieval_mode != "hybrid" or not (settings.vector_db_dir / "chroma.sqlite3").is_file():
        raise RuntimeError("Connect the existing Chroma DB with RETRIEVAL_MODE=hybrid")
    research = cached_research_agent()
    if research.vector_store.count() != 18976:
        raise RuntimeError("Existing 18,976-chunk collection required")
    metadata = research.vector_store.collection.get(include=["metadatas"])["metadatas"]
    if len({item.get("document") for item in metadata if item and item.get("document")}) != 12:
        raise RuntimeError("Existing 12-document KB required")
    agent = GoalExecutionAgent(research, OllamaClient(settings))
    rows = []
    for case_id, category, prompt, reply, expected in selected:
        if expected and case_id in EXPECTED_FACTS:
            expected = replace(expected, facts=tuple(row[0] for row in EXPECTED_FACTS[case_id]),
                               fact_values=EXPECTED_FACTS[case_id],
                               operation=EXPECTED_OPERATIONS.get(case_id),
                               missing_variables=EXPECTED_MISSING.get(case_id, ()))
        started = time.perf_counter()
        try:
            request = parse_goal_message(GoalMessageRequest(message=prompt, model="qwen3:8b"))
            request = request.model_copy(update={"use_external": False, "max_iterations": 8,
                                         "max_python_calls": 2, "max_retrieval_actions": 2,
                                         "temperature": 0, "seed": 42})
            result = await agent.run(f"DEV-V12-{case_id}", request)
            initial = result if reply else None
            if reply and result.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT:
                checkpoint = dict(result.resume_checkpoint)
                checkpoint["user_replies"] = [reply]
                result = await agent.run(result.run_id, request, resume_state=checkpoint,
                                         resume_result=result)
            observed = _observed(result, expected, prompt, reply, initial) if expected else {}
            if expected:
                checks = assess(observed, expected)
            else:
                cited = bool(re.search(r"\[(?:KB|FIG)\d+\]", result.final_answer))
                passed = (result.status.value == "achieved" and cited and
                          result.validation.get("citation_semantic_passed") is True)
                checks = {"overall_pass": passed, "failure_stage": "" if passed else "finalization_or_citation"}
            row = {"case_id": case_id, "category": category, "prompt": prompt, "reply": reply,
                   **observed, **checks, "run_id": result.run_id,
                   "intent": result.telemetry.get("intent_route"),
                   "source_requirement": result.telemetry.get("source_requirement"),
                   "actions": [item["action_type"] for item in result.action_history],
                   "answer": result.final_answer, "status": result.status.value,
                   "run_status": result.run_status.value,
                   "stop_reason": result.stop_reason.value if result.stop_reason else None,
                   "validation": result.validation,
                   "seconds": round(time.perf_counter() - started, 3),
                   "python_calls": result.python_calls_total, "validated_calcs": len([c for c in result.computations if c.validation_passed]),
                   "required_inputs": initial.required_inputs if initial else [],
                   "criteria": [item.model_dump(mode="json") for item in result.criteria],
                   "frozen_criteria": [item.model_dump(mode="json") for item in result.frozen_criteria],
                   "computation_sources": [{"formula_source_ids": item.formula_source_ids,
                                            "input_fact_ids": item.input_fact_ids,
                                            "source_formula": item.source_formula,
                                            "bound_variables": item.bound_variables,
                                            "required_output_ids": item.required_output_ids}
                                           for item in result.computations],
                   "telemetry": result.telemetry}
        except Exception as exc:
            row = {"case_id": case_id, "category": category, "prompt": prompt, "reply": reply,
                   "overall_pass": False, "failure_stage": "exception",
                   "error": type(exc).__name__ + ": " + str(exc),
                   "seconds": round(time.perf_counter() - started, 3)}
        rows.append(row)
        print(json.dumps({key: row.get(key) for key in ("case_id", "category", "overall_pass",
                                               "failure_stage", "intent", "actions", "status", "seconds", "error")
                          if key in row}, ensure_ascii=True), flush=True)
        if args.debug and not row.get("overall_pass"):
            print(json.dumps({key: row.get(key) for key in ("answer", "criteria", "frozen_criteria", "computation_sources",
                                                       "validation", "status", "actions",
                                                       "required_inputs", "stop_reason", "provenance_complete")},
                             ensure_ascii=True), flush=True)
    root = Path(__file__).resolve().parents[2] / "evaluation" / "review"
    root.mkdir(parents=True, exist_ok=True)
    complete = not args.cases
    if complete:
        payload = {"label": "DEVELOPMENT LIVE SMOKE ONLY — NOT UNSEEN OR FINAL BENCHMARK",
                   "model": "qwen3:8b", "retrieval_mode": "hybrid", "documents": 12, "chunks": 18976,
                   "web": False, "OpenAI API calls": 0, "case_count": len(rows),
                   "passed": sum(row.get("overall_pass") is True for row in rows), "cases": rows}
        (root / "agent_reliability_v12_dev_smoke.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        columns = ["case_id", "category", "expected_intent", "actual_intent",
                   "expected_source_requirement", "actual_source_requirement", "fact_pass", "unit_pass",
                   "operation_pass", "formula_retrieval_pass", "formula_selection_pass", "binding_pass",
                   "calc_executed", "calc_validated", "provenance_complete", "numeric_pass",
                   "unit_output_pass", "final_answer_adopted", "run_completed", "goal_achieved",
                   "overall_pass", "failure_stage"]
        with (root / "agent_reliability_v12_acceptance_matrix.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row, case in zip(rows, selected):
                expected = case[4]
                writer.writerow({"case_id": row["case_id"], "category": row["category"],
                    "expected_intent": expected.intent if expected else "premise_check/knowledge_qa",
                    "actual_intent": row.get("intent"),
                    "expected_source_requirement": expected.source_requirement if expected else "none",
                    "actual_source_requirement": row.get("source_requirement"),
                    "fact_pass": row.get("fact_pass"), "unit_pass": row.get("unit_pass"),
                    "operation_pass": row.get("operation_pass"),
                    "formula_retrieval_pass": "retrieve" in row.get("actions", []) if case[1] == "KB formula" else "",
                    "formula_selection_pass": bool(row.get("telemetry", {}).get("formula", {}).get("selected_formula_id")) if case[1] == "KB formula" else "",
                    "binding_pass": row.get("binding_pass"), "calc_executed": row.get("python_calls", 0) > 0,
                    "calc_validated": row.get("calc_validated"), "provenance_complete": row.get("provenance_complete"),
                    "numeric_pass": row.get("numeric_pass"), "unit_output_pass": row.get("unit_pass"),
                    "final_answer_adopted": row.get("final_answer_adopted"),
                    "run_completed": row.get("run_completed"), "goal_achieved": row.get("goal_achieved"),
                    "overall_pass": row["overall_pass"], "failure_stage": row.get("failure_stage")})


if __name__ == "__main__":
    asyncio.run(main())
