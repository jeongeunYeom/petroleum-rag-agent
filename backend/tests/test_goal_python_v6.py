"""Development-only generic calculation cases; no held-out tasks or answers."""

from __future__ import annotations

import asyncio
import json

from app.core.config import Settings
from app.models.goal_research_schemas import (
    CalculationContract, CalculationOutputSpec, CalculationScenario, GoalCriterion,
    GoalResearchRequest, PythonExecutionTrace, CriterionEvaluation, CriterionStatus, ExpectedResultStatus,
)
from app.models.research_schemas import EvidenceCounts, InternalEvidence, ResearchResponse, ResearchTiming
from app.services.calculation_assumption_guard import preflight_calculation_code
from app.services.calc_claim_grounding import validate_calc_claim
from app.services.calculation_contract import validate_contract
from app.services.calculation_requirements import (
    augment_plan_with_bindings, build_requirement_graph, required_recovery_gain,
)
from app.services.final_response_guard import synthesis_has_leak, strip_synthesis_leaks
from app.services.goal_evaluator import GoalEvaluationResult
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_research_agent import GoalResearchAgent
from app.services.goal_tool_planner import InputFact, PythonAnalysisPlan, ToolDecision
from app.services.required_outputs import missing_checklist_outputs, required_output_checklist


def user(name: str, value: float, number: int, unit: str = "m") -> dict:
    return {"evidence_id": f"USERF{number}", "source_type": "user_fact", "name": name,
            "value": value, "unit": unit, "source_span": f"{name}={value} {unit}",
            "raw_value_text": str(value), "text": f"{name}={value} {unit}"}


def source(text: str, evidence_id: str = "KB1") -> dict:
    return {"evidence_id": evidence_id, "source_type": "knowledge_base", "text": text,
            "locator": "synthetic source p.1"}


def plan(formula: str = "z = x + y") -> PythonAnalysisPlan:
    return PythonAnalysisPlan(purpose="Calculate z", target_criteria=["C1"], formula=formula,
                              formula_source_id="FORMULA1", formula_source_span=formula,
                              supporting_evidence_ids=["KB1"])


def contract(ids: list[str], *, scenario: str = "case", output: str = "z") -> CalculationContract:
    return CalculationContract(contract_id="CC-GENERIC", purpose="Calculate z", target_criteria=["C1"],
        input_fact_ids=ids, formula_id="FORMULA1", operation_type="formula",
        scenarios=[CalculationScenario(scenario_id=scenario, input_bindings=dict(zip(("x", "y"), ids)))],
        required_outputs=[CalculationOutputSpec(output_id="OUT_Z", name=output, semantic_type="numeric",
            unit="m", scenario_id=scenario, source_fact_ids=ids, formula_id="FORMULA1")])


def test_a_exact_formula_binding_with_scenario_prefix():
    evidence = [source("z = x + y"), user("case_A_x", 2, 1), user("case_A_y", 3, 2)]
    graph = build_requirement_graph(plan(), evidence)
    assert graph.source_complete and graph.scenario_bindings == {"case_A": {"x": "USERF1", "y": "USERF2"}}
    assert all(item.binding_method == "scenario_exact" for item in graph.formula_variables)


def test_b_three_scenarios_never_cross_bind():
    evidence = [source("z = q + pr + pwf")]
    count = 0
    for scenario in ("well_A", "well_B", "well_C"):
        for variable in ("q", "pr", "pwf"):
            count += 1
            evidence.append(user(f"{scenario}_{variable}", count, count))
    graph = build_requirement_graph(plan("z = q + pr + pwf"), evidence)
    assert graph.source_complete and len(graph.scenario_bindings) == 3
    assert len({value for bindings in graph.scenario_bindings.values() for value in bindings.values()}) == 9


def test_c_ambiguous_alias_blocks_source_completeness():
    graph = build_requirement_graph(plan("z = q + x"),
        [source("z = q + x"), user("rate", 2, 1), user("flow_rate", 3, 2), user("x", 4, 3)])
    assert not graph.source_complete and graph.ambiguous_variables == ["default:q"]
    assert graph.formula_variables[0].bound_fact_id is None or graph.formula_variables[1].bound_fact_id is None


def test_d_missing_binding_blocks_source_completeness():
    graph = build_requirement_graph(plan("z = a + b + c + d"),
        [source("z = a + b + c + d"), *(user(name, i, i) for i, name in enumerate("abc", 1))])
    assert not graph.source_complete and "default:d" in graph.missing_variables


def test_e_formula_recovery_is_a_required_gain():
    facts = [user("x", 2, 1), user("y", 3, 2)]
    before = build_requirement_graph(plan(), facts, formula_required=True)
    after = build_requirement_graph(plan(), [*facts, source("z = x + y")], formula_required=True)
    assert not before.source_complete and after.source_complete
    assert required_recovery_gain(before, after, ["KB1"]) == ["formula_source"]


def test_f_numeric_evidence_recovery_binds_efact():
    before_sources = [source("z = x + y"), user("x", 2, 1)]
    after_sources = [*before_sources, source("y is 3 m.", "KB2")]
    before = build_requirement_graph(plan(), before_sources)
    after = build_requirement_graph(plan(), after_sources)
    assert not before.source_complete and after.source_complete
    assert required_recovery_gain(before, after, ["KB2"]) == ["default:y"]


def test_g_unrelated_recovery_source_is_no_op():
    before_sources = [source("z = x + y"), user("x", 2, 1)]
    before = build_requirement_graph(plan(), before_sources)
    after = build_requirement_graph(plan(), [*before_sources, source("thickness is 9 ft.", "KB2")])
    assert not after.source_complete and required_recovery_gain(before, after, ["KB2"]) == []


def test_h_recovery_gain_does_not_count_repeated_source():
    evidence = [source("z = x + y"), user("x", 2, 1)]
    before = build_requirement_graph(plan(), evidence)
    after = build_requirement_graph(plan(), evidence)
    assert required_recovery_gain(before, after, []) == []


def test_i_unsupported_numeric_fallback_blocked():
    assert preflight_calculation_code("dx = 1\ny = facts['USERF1']['value'] / dx", ["USERF1"]) == [
        "unsupported_numeric_assumption"]


def test_j_algebraic_one_is_allowed():
    assert preflight_calculation_code("x = facts['USERF1']['value']\ny = 1 / x", ["USERF1"]) == []


def test_unapproved_numeric_coefficient_is_blocked():
    assert preflight_calculation_code("x = facts['USERF1']['value']\ny = x * 0.37", ["USERF1"], {0.0, 1.0}) == [
        "unsupported_numeric_assumption"]


def test_k_json_literals_blocked_before_subprocess():
    assert preflight_calculation_code("x = facts['USERF1']['value']\nfoo = null", ["USERF1"]) == [
        "code_generation_invalid_literal"]


def test_l_source_complete_user_facts_reach_validated_calc(tmp_path):
    evidence = [source("z = x + y"), user("x", 2, 1), user("y", 3, 2)]
    selected = plan()
    graph = build_requirement_graph(selected, evidence)
    augment_plan_with_bindings(selected, graph, evidence)
    selected.formula_bindings = graph.scenario_bindings
    spec = contract(["USERF1", "USERF2"])
    assert validate_contract(spec, selected, graph) is None
    trace = PythonExecutionTrace(source_complete=True, requirement_graph=graph.model_dump(mode="json"),
                                 calculation_contract_schema_version=2)
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"),
                                  object(), "v6-user")
    record, executed = asyncio.run(analysis.execute(GoalResearchRequest(
        topic="x=2 m, y=3 m", allow_python_execution=True, python_execution_approved=True),
        selected, evidence, trace, spec))
    assert executed and record and record.validation_passed and trace.subprocess_reached
    assert trace.assumption_guard_passed and record.output_manifest["OUT_Z"]["value"] == 5
    issues, adopted = validate_calc_claim("z is 5 m", ["CALC1", "KB1", "USERF1", "USERF2"],
                                          ["OUT_Z"], {"CALC1": record}, evidence)
    assert issues == [] and adopted == ["CALC1:OUT_Z"]


def test_m_source_complete_evidence_facts_keep_provenance(tmp_path):
    evidence = [source("z = x + y"), source("x is 2 m.\ny is 3 m.", "KB2")]
    selected = plan()
    graph = build_requirement_graph(selected, evidence)
    augment_plan_with_bindings(selected, graph, evidence)
    selected.formula_bindings = graph.scenario_bindings
    ids = [graph.scenario_bindings["default"][name] for name in ("x", "y")]
    spec = contract(ids)
    trace = PythonExecutionTrace(source_complete=True, requirement_graph=graph.model_dump(mode="json"),
                                 calculation_contract_schema_version=2)
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"),
                                  object(), "v6-evidence")
    record, executed = asyncio.run(analysis.execute(GoalResearchRequest(
        topic="Compute z", allow_python_execution=True, python_execution_approved=True),
        selected, evidence, trace, spec))
    assert executed and record and record.validation_passed
    assert record.source_evidence_ids == ["KB2"] and record.formula_evidence_ids == ["KB1"]


def test_n_checklist_has_four_cases_mean_max_ranking():
    evidence = [source("z = x + y")]
    for number, scenario in enumerate(("A", "B", "C", "D"), 1):
        evidence.extend([user(f"well_{scenario}_x", number, number * 2 - 1),
                         user(f"well_{scenario}_y", number + 1, number * 2)])
    graph = build_requirement_graph(plan(), evidence)
    request = GoalResearchRequest(topic="Four wells", goal="Calculate each well result, mean, maximum and ranking")
    checklist = required_output_checklist(request, graph)
    assert len(checklist) == 7 and {item.semantic_name for item in checklist} == {
        "per_case", "mean", "maximum", "ranking"}


def test_o_incomplete_contract_fails_checklist():
    evidence = [source("z = x + y"), user("well_A_x", 2, 1), user("well_A_y", 3, 2),
                user("well_B_x", 4, 3), user("well_B_y", 5, 4)]
    selected = plan()
    graph = build_requirement_graph(selected, evidence)
    augment_plan_with_bindings(selected, graph, evidence)
    partial = contract(["USERF1", "USERF2"], scenario="well_A")
    partial.input_fact_ids = ["USERF1", "USERF2", "USERF3", "USERF4"]
    partial.scenarios.append(CalculationScenario(scenario_id="well_B", input_bindings={"x": "USERF3", "y": "USERF4"}))
    checklist = required_output_checklist(GoalResearchRequest(topic="Two wells", goal="Calculate each well result"), graph)
    assert missing_checklist_outputs(partial, checklist) == ["well_B:per_case"]


def test_p_internal_instruction_leak_is_removed():
    candidate = {"claims": [{"claim": "Every material claim must be cited with output_ids", "citations": ["KB1"]},
                            {"claim": "The measured result is supported.", "citations": ["KB1"]}],
                 "hypothesis_assessment": {"claim": "", "citations": []}, "limitations": ["response schema failed"]}
    assert synthesis_has_leak(candidate)
    clean = strip_synthesis_leaks(candidate)
    assert not synthesis_has_leak(clean) and len(clean["claims"]) == 1 and not clean["limitations"]


def test_q_source_incomplete_gate_prevents_python(tmp_path):
    evidence = [source("z = x + y"), user("x", 2, 1)]
    selected = plan()
    graph = build_requirement_graph(selected, evidence)
    trace = PythonExecutionTrace(source_complete=False, requirement_graph=graph.model_dump(mode="json"))
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"),
                                  object(), "v6-incomplete")
    record, executed = asyncio.run(analysis.execute(GoalResearchRequest(
        topic="x=2 m", allow_python_execution=True, python_execution_approved=True),
        selected, evidence, trace, contract(["USERF1", "USERF2"])))
    assert record is None and not executed and not trace.subprocess_reached
    assert trace.blocked_stage == "calculation_source_incomplete"


def test_r_full_contract_and_requirement_snapshots_are_json_readable():
    graph = build_requirement_graph(plan(), [source("z = x + y"), user("x", 2, 1), user("y", 3, 2)])
    spec = contract(["USERF1", "USERF2"])
    trace = PythonExecutionTrace(requirement_graph_schema_version=graph.schema_version,
        requirement_graph=graph.model_dump(mode="json"), calculation_contract_schema_version=2,
        calculation_contract=spec.model_dump(mode="json"))
    restored = PythonExecutionTrace.model_validate_json(trace.model_dump_json())
    assert restored.calculation_contract["required_outputs"][0]["unit"] == "m"
    assert restored.calculation_contract["scenarios"][0]["input_bindings"]["x"] == "USERF1"
    assert restored.requirement_graph["formula_variables"][0]["bound_fact_id"] == "USERF1"


def test_annotated_variable_unit_mismatch_blocks_binding():
    graph = build_requirement_graph(plan("z = x + y"),
        [source("x (ft) and y (ft) are the inputs. z = x + y"), user("x", 2, 1, "psi"), user("y", 3, 2, "ft")])
    assert not graph.source_complete and "default:x" in graph.unit_mismatch_variables


def test_nested_equations_bind_only_leaf_inputs():
    text = "Ta = Ka*Aa/da. Tb = Kb*Ab/db. Tap = 1/(1/Ta + 1/Tb)."
    evidence = [source(text), *[user(name, index, index) for index, name in
                                enumerate(("Ka", "Aa", "da", "Kb", "Ab", "db"), 1)]]
    selected = PythonAnalysisPlan(purpose="Calculate Tap", formula="Tap = 1/(1/Ta + 1/Tb)",
        formula_source_id="FORMULA3", formula_source_span="Tap = 1/(1/Ta + 1/Tb)", supporting_evidence_ids=["KB1"])
    graph = build_requirement_graph(selected, evidence)
    assert graph.source_complete and len(graph.dependency_formulas) == 2
    assert set(graph.scenario_bindings["default"]) == {"Ka", "Aa", "da", "Kb", "Ab", "db"}


def test_recovery_is_bounded_to_two_internal_queries():
    class Research:
        calls = 0

        async def research(self, request):
            self.calls += 1
            return ResearchResponse(query=request.query, answer="synthetic", internal_sources=[InternalEvidence(
                evidence_id="KB1", document="generic-dev.pdf", page=self.calls,
                chunk_id=f"chunk-{self.calls}", score=1.0, excerpt="z = x + y")],
                web_sources=[], figures=[], provenance=[], model=request.model, inference_used=True,
                evidence_counts=EvidenceCounts(internal=1, external=0), routing_mode="internal_only",
                retrieval_mode="legacy", timing=ResearchTiming(retrieval_seconds=0,
                    reasoning_seconds=0, elapsed_seconds=0), validation={})

    class Planner:
        calls = 0

        async def decide(self, request, criteria, evidence, coverage, prior):
            self.calls += 1
            selected = PythonAnalysisPlan(purpose="first" if self.calls == 1 else "second",
                target_criteria=["C1"], formula="z = x + y", formula_source_id="FORMULA1",
                formula_source_span="z = x + y", supporting_evidence_ids=["KB1"],
                input_facts=[InputFact(name="x", value=2, unit="m", evidence_id="USERF1",
                    source_excerpt="x=2 m", source_type="user_fact", canonical_fact_id="USERF1")])
            return ToolDecision(tool_needed=True, tool_type="python_calculation", reason="calculate",
                                plan=selected, selected_formula_id="FORMULA1", plan_summary={"purpose": selected.purpose})

    class Evaluator:
        async def evaluate(self, request, criteria, candidate, evidence, validation, computations=None):
            return GoalEvaluationResult(criteria=[CriterionEvaluation(criterion_id="C1", status=CriterionStatus.UNMET,
                reason="missing y")], coverage=0, achieved=False,
                expected_result_status=ExpectedResultStatus.NOT_PROVIDED, gaps=[], next_research_need=None,
                engineering_validation_passed=True, engineering_contradiction_count=0,
                unsupported_engineering_claim_count=0, goal_conflicts_with_evidence=False)

    async def synthesize(*_args):
        return ""

    research = Research()
    agent = GoalResearchAgent(research, object(), tool_planner=Planner(), evaluator=Evaluator(), synthesizer=synthesize)
    result = asyncio.run(agent.run("v6-recovery-budget", GoalResearchRequest(topic="x=2 m",
        goal="Calculate z from the cited equation", success_criteria=[GoalCriterion(criterion_id="C1",
        description="Calculate z")], max_iterations=1, allow_python_execution=True,
        python_execution_approved=True, engineering_validation=False)))
    trace = result.iterations[0].python_trace
    assert research.calls == 3 and trace.recovery_rounds_used == 2
    assert not trace.source_complete and not trace.subprocess_reached


def test_basic_pair_checklist_includes_unselected_user_cases():
    evidence = [user("A_baseline", 2, 1), user("A_observed", 3, 2),
                user("B_baseline", 4, 3), user("B_observed", 5, 4)]
    selected = PythonAnalysisPlan(purpose="Compare each pair", input_facts=[InputFact(
        name=item["name"], value=item["value"], unit=item["unit"], evidence_id=item["evidence_id"],
        source_excerpt=item["source_span"], source_type="user_fact", canonical_fact_id=item["evidence_id"])
        for item in evidence[:2]])
    graph = build_requirement_graph(selected, evidence, require_all_scenarios=True)
    augment_plan_with_bindings(selected, graph, evidence)
    assert graph.source_complete and set(graph.scenario_bindings) == {"A", "B"}
    assert len(selected.input_facts) == 4
    checklist = required_output_checklist(GoalResearchRequest(topic="Pairs", goal="Calculate each pair result"), graph)
    assert {item.scenario_id for item in checklist} == {"A", "B"}
