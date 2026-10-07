"""Fresh synthetic-source, real local qwen3:8b development smoke (never held-out)."""

from __future__ import annotations

import asyncio
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.config import Settings
from app.models.goal_research_schemas import GoalCriterion, GoalResearchRequest, CalculationContract
from app.models.research_schemas import EvidenceCounts, InternalEvidence, ResearchResponse, ResearchTiming
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_research_agent import GoalResearchAgent
from app.services.ollama import OllamaClient
from app.services.final_response_guard import leaked_text


CASES = {
    "S1": ("case_A_value=11.3 psi, case_B_value=23.7 psi, case_C_value=34.1 psi, case_D_value=46.9 psi, "
           "case_E_value=57.2 psi, case_F_value=69.4 psi, case_G_value=74.8 psi, case_H_value=86.6 psi.",
           "For each case A-H report result in psi, then mean, median, population standard deviation, range, "
           "coefficient of variation, maximum and descending ranking.", ["Synthetic measurement set only; no specialist equation." ]),
    "S2": ("case_A_X=27 m, case_A_Y=16 m, case_B_X=39 m, case_B_Y=24 m, case_C_X=53 m, case_C_Y=18 m.",
           "For each case A-C calculate Z using the cited equation in m.", ["Synthetic engineering relation: Z = X + Y."]),
    "S3": ("X=42 m, Y=19 m, W=17 m.", "Calculate Z using the cited nested equations in dimensionless.",
           ["Synthetic nested equations: Q = X + Y. Z = Q / W."]),
    "S4": ("Use the two measurements in the cited synthetic note.",
           "Calculate Z using the cited equation in psi.",
           ["Well M: X is 31 psi.\nWell M: Y is 14 psi.\nZ = X - Y."]),
    "S5": ("X=36 m, Y=22 m.", "Calculate Z using the cited equation in m.",
           ["The first synthetic note names Z but omits the relation.", "An independent synthetic passage states Z = X + Y."]),
    "S6": ("X=44 psi. Use source-backed Y.", "Calculate Z using the cited equation in psi.",
           ["Synthetic relation Z = X - Y; the Y measurement is elsewhere.", "The missing synthetic measurement Y is 12 psi."]),
    "S7": ("case_A_X=33 m, case_A_Y=21 m, case_B_X=54 m, case_B_Y=27 m, case_C_X=75 m, case_C_Y=25 m.",
           "For each case A-C calculate Z using the cited equation in dimensionless, then report mean, maximum and ranking.",
           ["Synthetic relation Z = X / Y."]),
    "N1": ("X=28 m, Y=16 m.", "Calculate Z using the cited equation in m without inventing variables.",
           ["This synthetic relation has extra unavailable variables: Z = X + Y + W + R."]),
    "N2": ("X=41 m, Y=17 m.", "Calculate Z using the cited equation in m; do not guess if methods conflict.",
           ["Synthetic alternative one: Z = X + Y.\nSynthetic alternative two: Z = X - Y."]),
    "N3": ("X=38 m, Y=29 m.", "Calculate Z using a cited specialist equation in m; do not invent the equation.",
           ["The synthetic note contains no equation for Z."]),
    "N4": ("case_A_X=52 m, case_A_Y=23 m, case_B_X=68 m, case_B_Y=34 m.",
           "For each case A-B calculate Z using the cited equation in m, then report mean and ranking.",
           ["Synthetic relation Z = X + Y."]),
}


class SyntheticResearch:
    def __init__(self, passages: list[str]):
        self.passages = passages
        self.calls = 0

    async def research(self, request):
        index = min(self.calls, len(self.passages) - 1)
        self.calls += 1
        return ResearchResponse(query=request.query, answer="Synthetic source", internal_sources=[InternalEvidence(
            evidence_id="KB1", document="v7-synthetic-development.pdf", page=self.calls,
            chunk_id=f"synthetic-v7-{self.calls}", score=1.0, excerpt=self.passages[index])],
            web_sources=[], figures=[], provenance=[], model=request.model, inference_used=True,
            evidence_counts=EvidenceCounts(internal=1, external=0), routing_mode="internal_only",
            retrieval_mode="legacy", timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0),
            validation={})


class MutatingContractBuilder:
    """N4 models an LLM dropping a required output after the deterministic skeleton."""
    async def build(self, request, plan):
        return CalculationContract(contract_id="CC-MUTATED", purpose=plan.purpose,
            target_criteria=plan.target_criteria, input_fact_ids=[fact.canonical_fact_id or fact.evidence_id for fact in plan.input_facts],
            formula_id=plan.formula_source_id, operation_type="source_formula", scenarios=[], required_outputs=[]), "materialized", 1


async def run_case(case_id: str, root: Path) -> dict:
    topic, goal, passages = CASES[case_id]
    settings = Settings(data_dir=root / case_id / "data", agent_workspace_dir=root / case_id / "workspace")
    ollama = OllamaClient(settings)
    research = SyntheticResearch(passages)
    agent = GoalResearchAgent(research, ollama,
        contract_builder=MutatingContractBuilder() if case_id == "N4" else None,
        analysis_factory=lambda run_id: GoalPythonAnalysis(settings, ollama, run_id))
    req = GoalResearchRequest(topic=topic, goal=goal, success_criteria=[GoalCriterion(criterion_id="C1", description=goal)],
        model="qwen3:8b", temperature=0, seed=42, max_iterations=1, allow_python_execution=True,
        python_execution_approved=True, engineering_validation=False, use_external=False)
    response = await agent.run(f"v7-synthetic-{case_id}", req)
    trace = response.iterations[0].python_trace
    report = {"case": case_id, "computation_class": trace.computation_class,
        "ir_valid": bool(trace.request_ir), "ir_outputs": [item["semantic_name"] for item in trace.required_output_checklist],
        "checklist_outputs": [item["semantic_name"] for item in trace.required_output_checklist],
        "checklist_complete": bool(trace.request_ir) and len(trace.required_output_checklist) == len(trace.request_ir["requested_outputs"]),
        "formula_candidates": trace.formula_candidates, "resolved_formula": trace.resolved_formula_id,
        "binding_complete": trace.required_variable_count == trace.bound_variable_count and not trace.missing_variables,
        "initial_readiness": trace.initial_readiness_snapshot, "recovery_rounds": trace.recovery_rounds,
        "recovery_snapshots": trace.recovery_snapshots, "post_readiness": trace.source_complete,
        "contract_skeleton": trace.contract_skeleton, "contract_final": trace.contract_final,
        "contract_complete": bool(trace.contract_final) and not trace.contract_skeleton_diff,
        "contract_diff": trace.contract_skeleton_diff, "subprocess": trace.subprocess_reached,
        "validated_calc": any(item.validation_passed for item in response.computations),
        "grounding": trace.calc_grounding_validation_passed, "blocked_stage": trace.blocked_stage,
        "assumption_failures": trace.assumption_guard_failures, "research_calls": research.calls,
        "instruction_leakage": leaked_text(response.final_answer),
        "answer": response.final_answer, "error": response.error}
    print(json.dumps(report, ensure_ascii=True), flush=True)
    return report


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if any(case not in CASES for case in args.cases):
        parser.error("unknown synthetic case")
    with TemporaryDirectory(prefix="petroleum-v7-development-") as directory:
        reports = []
        for case_id in (args.cases or list(CASES)):
            try:
                reports.append(await run_case(case_id, Path(directory)))
            except Exception as exc:
                report = {"case": case_id, "exception": type(exc).__name__, "error": str(exc)[:500]}
                reports.append(report)
                print(json.dumps(report, ensure_ascii=True), flush=True)
        summary = {"ir_valid": sum(bool(row.get("ir_valid")) for row in reports if row["case"].startswith("S")),
            "checklist_complete": sum(bool(row.get("checklist_complete")) for row in reports if row["case"].startswith("S")),
            "source_complete": sum(bool(row.get("post_readiness")) for row in reports if row["case"].startswith("S")),
            "contract_complete": sum(bool(row.get("contract_complete")) for row in reports if row["case"].startswith("S")),
            "subprocess": sum(bool(row.get("subprocess")) for row in reports if row["case"].startswith("S")),
            "validated_calc": sum(bool(row.get("validated_calc")) for row in reports if row["case"].startswith("S")),
            "grounded": sum(row.get("grounding") is True for row in reports if row["case"].startswith("S")),
            "recovery_to_calc": sum(bool(row.get("validated_calc")) and any(round_["required_gain"] for round_ in row.get("recovery_rounds", []))
                                    for row in reports if row["case"].startswith("S")),
            "negative_subprocess": sum(bool(row.get("subprocess")) for row in reports if row["case"].startswith("N")),
            "instruction_leakage": sum(bool(row.get("instruction_leakage")) for row in reports)}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({"cases": reports, "summary": summary}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"summary": summary}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
