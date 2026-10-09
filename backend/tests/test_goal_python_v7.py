"""New synthetic intent fixtures; no frozen held-out task or source is reused."""

from __future__ import annotations

import asyncio
import math

from app.core.config import Settings
from app.models.goal_research_schemas import (CriterionEvaluation, CriterionStatus, ExpectedResultStatus,
    GoalCriterion, GoalResearchRequest, PythonExecutionTrace)
from app.models.research_schemas import EvidenceCounts, ResearchResponse, ResearchTiming
from app.services.calculation_assumption_guard import preflight_calculation_code
from app.services.calculation_contract import validate_contract
from app.services.calculation_contract_skeleton import build_contract_skeleton, skeleton_diff
from app.services.calculation_request_ir import parse_request_ir, resolve_request_ir, validate_ir
from app.services.calculation_requirements import augment_plan_with_bindings, build_requirement_graph, required_recovery_gain
from app.services.formula_resolver import FormulaIntent, resolve_formula
from app.services.generic_calculation_registry import generic_code, tie_leaders, tie_ranking
from app.services.goal_tool_planner import InputFact, PythonAnalysisPlan
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_research_agent import GoalResearchAgent
from app.services.goal_tool_planner import ToolDecision
from app.services.goal_evaluator import GoalEvaluationResult
from app.services.goal_planner import GoalPlanner
from app.services.formula_source_registry import FormulaSourceRegistry
from app.services.required_outputs import checklist_from_ir
from app.services.user_fact_registry import UserFactRegistry


CRITERIA = [GoalCriterion(criterion_id="C1", description="Provide the requested calculations")]


def request(topic: str, goal: str) -> GoalResearchRequest:
    return GoalResearchRequest(topic=topic, goal=goal, success_criteria=CRITERIA)


def plan_from_topic(topic: str) -> tuple[PythonAnalysisPlan, list[dict]]:
    sources = UserFactRegistry.from_topic(topic).evidence()
    facts = [InputFact(name=item["name"], value=item["value"], unit=item["unit"],
                       evidence_id=item["evidence_id"], canonical_fact_id=item["evidence_id"],
                       source_excerpt=item["source_span"], source_type="user_fact") for item in sources]
    return PythonAnalysisPlan(purpose="Synthetic calculation", target_criteria=["C1"], input_facts=facts), sources


def test_request_ir_scenarios_statistics_and_mixed_relation():
    topic = "A_value=13 psi, B_value=17 psi, C_value=21 psi, D_value=29 psi."
    ir = parse_request_ir(request(topic, "For each case A-D report result in psi, mean, maximum and descending ranking."), CRITERIA)
    assert not validate_ir(ir)
    assert [item.scenario_id for item in ir.scenarios] == list("ABCD")
    assert ir.computation_class == "generic_statistics"
    assert len(ir.requested_outputs) == 4 + 4
    assert {item.semantic_name for item in ir.requested_outputs} >= {"mean", "maximum", "ranking", "leader_ids"}
    stats = parse_request_ir(request(topic, "Find median, population standard deviation and range."), CRITERIA)
    assert {"median", "std_population", "range"}.issubset(stats.requested_operation_types)
    assert "std_unspecified" not in stats.requested_operation_types
    mixed = parse_request_ir(request(topic, "Calculate K using the cited equation for each case A-D in dimensionless, then mean and ranking."), CRITERIA)
    assert mixed.computation_class == "mixed" and mixed.specialist_relation_required
    named = parse_request_ir(request(topic, "Calculate pore volume using the cited equation in bbl."), CRITERIA)
    assert "PV" in named.target_concepts and named.requested_outputs[0].semantic_name == "pore_volume"


def test_dimensionless_aggregate_does_not_inherit_input_unit():
    req = request("A_value=12 psi, B_value=18 psi.",
                  "For each case A-B report result in psi, mean and coefficient of variation.")
    ir = parse_request_ir(req, CRITERIA)
    checklist = checklist_from_ir(ir)
    assert not validate_ir(ir)
    assert next(item.requested_unit for item in checklist if item.semantic_name == "mean") == "psi"
    assert next(item.requested_unit for item in checklist if item.semantic_name == "coefficient_of_variation") == "percent"


def test_generic_user_facts_need_no_kb_formula_and_have_source_ids():
    topic = "A_value=13 psi, B_value=17 psi, C_value=21 psi, D_value=29 psi."
    ir = parse_request_ir(request(topic, "For each case A-D report result in psi, mean, maximum and ranking."), CRITERIA)
    plan, evidence = plan_from_topic(topic)
    graph = build_requirement_graph(plan, evidence)
    checklist = checklist_from_ir(ir)
    contract = build_contract_skeleton(ir, checklist, plan, graph)
    assert graph.source_complete and graph.formula_id is None
    assert validate_contract(contract, plan, graph, checklist) is None
    assert all(item.source_fact_ids for item in contract.required_outputs)
    assert set(next(item for item in contract.required_outputs if item.name == "mean").source_fact_ids) == set(contract.input_fact_ids)
    code = generic_code(plan, contract, "synthetic.json")
    assert code and not preflight_calculation_code(code, contract.input_fact_ids, {0.0, 1.0, 100.0, 4.0})
    mutated = contract.model_copy(deep=True)
    mutated.required_outputs.pop()
    assert skeleton_diff(contract, mutated) == ["required_outputs"]


def test_scenario_prefix_does_not_treat_case_as_scenario_c():
    topic = "case_A_value=11 psi, case_B_value=23 psi, case_C_value=37 psi."
    ir = parse_request_ir(request(topic, "For each case A-C report result in psi, mean and ranking."), CRITERIA)
    plan, evidence = plan_from_topic(topic)
    contract = build_contract_skeleton(ir, checklist_from_ir(ir), plan, build_requirement_graph(plan, evidence))
    assert {item.scenario_id: len(item.input_bindings) for item in contract.scenarios} == {"A": 1, "B": 1, "C": 1}
    assert generic_code(plan, contract, "synthetic.json")


def test_formula_resolution_rejects_extra_variables_and_accepts_equivalent_source():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": "Z = X / Y"},
                {"evidence_id": "KB2", "source_type": "knowledge_base", "text": "Z = X / Y / W / R"}]
    intent = FormulaIntent(desired_output_names=("Z",), concept_terms=("index",),
                           available_input_semantics=("case_A_X", "case_A_Y"))
    resolved = resolve_formula(evidence, intent)
    assert resolved.record and resolved.record.source_id == "KB1"
    assert any(item["reason"] == "excess_unavailable_variables" for item in resolved.candidates)
    equivalent = resolve_formula([evidence[0], {**evidence[0], "evidence_id": "KB3"}], intent)
    assert equivalent.record and equivalent.reason == "resolved"
    ambiguous = resolve_formula([evidence[0], {"evidence_id": "KB4", "source_type": "knowledge_base",
                                                   "text": "Z = X * Y"}], intent)
    assert ambiguous.record is None and ambiguous.reason == "formula_selection_ambiguous"


def test_binding_structured_alias_and_cross_scenario_guard():
    topic = "case_A_dimensionless_time=14 days, case_A_dimensionless_storage=7 days, case_B_dimensionless_time=22 days, case_B_dimensionless_storage=11 days."
    plan, sources = plan_from_topic(topic)
    formula = {"evidence_id": "KB1", "source_type": "knowledge_base", "text": "pD = tD / CD"}
    graph = build_requirement_graph(plan, [formula, *sources], formula_id="FORMULA1", formula_required=True)
    assert graph.source_complete and graph.bound_variable_count == 4
    assert set(graph.scenario_bindings) == {"case_A", "case_B"}
    assert set(graph.scenario_bindings["case_A"].values()).isdisjoint(graph.scenario_bindings["case_B"].values())
    assert all(item.binding_confidence in {"deterministic_alias", "scenario_match"} for item in graph.formula_variables)
    wrong = resolve_formula([{"evidence_id": "KB9", "source_type": "knowledge_base", "text": "pD = t / CD"}],
        FormulaIntent(desired_output_names=("pD",), concept_terms=(), available_input_semantics=("tD", "CD")))
    assert wrong.record is not None  # Candidate may be retrieved, but t must remain unbound.
    bad_graph = build_requirement_graph(plan, [{"evidence_id": "KB9", "source_type": "knowledge_base", "text": "pD = t / CD"}, *sources],
        formula_id="FORMULA1", formula_required=True)
    assert not bad_graph.source_complete and any(value.endswith(":t") for value in bad_graph.missing_variables)


def test_tie_policy_does_not_choose_false_sole_leader():
    assert tie_leaders({"A": 0.3, "B": 0.30000000000000004, "C": 0.19}) == ["A", "B"]
    assert tie_ranking({"A": 0.3, "B": 0.30000000000000004, "C": 0.19}) == ["A=B", "C"]
    assert math.isclose(0.3, 0.30000000000000004)


def test_generic_fast_path_reaches_existing_sandbox_and_validated_calc(tmp_path):
    topic = "A_value=13 psi, B_value=17 psi, C_value=21 psi, D_value=29 psi."
    req = request(topic, "For each case A-D report result in psi, mean, maximum and ranking.")
    req.allow_python_execution = req.python_execution_approved = True
    ir = parse_request_ir(req, CRITERIA)
    plan, evidence = plan_from_topic(topic)
    graph = build_requirement_graph(plan, evidence)
    checklist = checklist_from_ir(ir)
    contract = build_contract_skeleton(ir, checklist, plan, graph)
    trace = PythonExecutionTrace(requirement_graph=graph.model_dump(mode="json"), source_complete=True,
                                 calculation_contract_schema_version=3)
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    analysis = GoalPythonAnalysis(settings, object(), "v7-generic-synthetic")
    record, executed = asyncio.run(analysis.execute(req, plan, evidence, trace=trace, contract=contract))
    assert executed and record and record.validation_passed and record.contract_validation_passed
    assert trace.subprocess_reached and trace.assumption_guard_passed
    assert record.output_manifest["OUT_mean"]["value"] == 20
    assert record.output_manifest["OUT_leader_ids"]["value"] == ["D"]


def test_specialist_multi_scenario_and_aggregate_contract_runs_in_sandbox(tmp_path):
    topic = "case_A_X=26 psi, case_A_Y=13 psi, case_B_X=45 psi, case_B_Y=15 psi."
    req = request(topic, "For each case A-B calculate Z using the cited equation in dimensionless, then mean, maximum and ranking.")
    req.allow_python_execution = req.python_execution_approved = True
    ir = parse_request_ir(req, CRITERIA)
    plan, users = plan_from_topic(topic)
    kb = {"evidence_id": "KB1", "source_type": "knowledge_base", "text": "Z = X / Y"}
    evidence = [kb, *users]
    formula = FormulaSourceRegistry.from_evidence(evidence).records[0]
    plan.formula, plan.formula_source_id = formula.expression_candidate, formula.formula_id
    plan.formula_source_span, plan.supporting_evidence_ids = formula.raw_span, [formula.source_id]
    graph = build_requirement_graph(plan, evidence, formula_id=formula.formula_id, formula_required=True)
    assert graph.source_complete and graph.bound_variable_count == 4
    augment_plan_with_bindings(plan, graph, evidence)
    plan.formula_bindings = graph.scenario_bindings
    checklist = checklist_from_ir(ir)
    contract = build_contract_skeleton(ir, checklist, plan, graph)
    assert validate_contract(contract, plan, graph, checklist) is None
    trace = PythonExecutionTrace(requirement_graph=graph.model_dump(mode="json"), source_complete=True,
                                 calculation_contract_schema_version=3)
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    analysis = GoalPythonAnalysis(settings, object(), "v7-specialist-synthetic")
    record, executed = asyncio.run(analysis.execute(req, plan, evidence, trace=trace, contract=contract))
    assert executed and record and record.validation_passed and trace.subprocess_reached
    assert record.output_manifest["OUT_case_A_Z"]["value"] == 2
    assert record.output_manifest["OUT_case_B_Z"]["value"] == 3
    assert record.output_manifest["OUT_mean"]["value"] == 2.5
    assert record.output_manifest["OUT_leader_ids"]["value"] == ["case_B"]


def test_agent_generic_ir_precedes_evidence_contract_and_no_recovery(tmp_path):
    topic = "A_value=13 psi, B_value=17 psi, C_value=21 psi, D_value=29 psi."
    req = request(topic, "For each case A-D report result in psi, mean, maximum and ranking.")
    req.allow_python_execution = req.python_execution_approved = True
    req.max_iterations = 1

    class Research:
        calls = 0
        async def research(self, query):
            self.calls += 1
            return ResearchResponse(query=query.query, answer="", internal_sources=[], web_sources=[], figures=[],
                provenance=[], model=query.model, inference_used=False, evidence_counts=EvidenceCounts(internal=0, external=0),
                routing_mode="internal_only", retrieval_mode="legacy",
                timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0), validation={})

    class Planner:
        async def decide(self, *args):
            return ToolDecision(tool_needed=True, tool_type="python_calculation", reason="Calculation requested")

    class Evaluator:
        async def evaluate(self, *args, **kwargs):
            return GoalEvaluationResult(criteria=[CriterionEvaluation(criterion_id="C1", status=CriterionStatus.MET,
                reason="verified", supporting_evidence=[])], coverage=1, achieved=True,
                expected_result_status=ExpectedResultStatus.NOT_PROVIDED, gaps=[], next_research_need=None,
                engineering_validation_passed=True, engineering_contradiction_count=0,
                unsupported_engineering_claim_count=0, goal_conflicts_with_evidence=False)

    async def synth(*args):
        return "Synthetic validated calculation."

    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    research = Research()
    agent = GoalResearchAgent(research, object(), planner=GoalPlanner(object()), evaluator=Evaluator(),
        tool_planner=Planner(), synthesizer=synth,
        analysis_factory=lambda run_id: GoalPythonAnalysis(settings, object(), run_id))
    result = asyncio.run(agent.run("v7-agent-synthetic", req))
    trace = result.iterations[0].python_trace
    assert trace.request_ir and trace.generic_fast_path and trace.initial_readiness_snapshot
    assert trace.required_output_checklist and trace.contract_skeleton
    assert trace.source_complete and not trace.recovery_triggered and research.calls == 1
    assert trace.subprocess_reached and result.computations[0].validation_passed


def test_generic_linear_regression_is_source_bound_and_unit_typed(tmp_path):
    topic = "x1=2 days, y1=7 psi, x2=5 days, y2=16 psi, x3=9 days, y3=28 psi."
    req = request(topic, "Perform linear regression and report slope and intercept.")
    req.allow_python_execution = req.python_execution_approved = True
    ir = parse_request_ir(req, CRITERIA)
    assert ir.computation_class == "generic_statistics"
    plan, evidence = plan_from_topic(topic)
    graph = build_requirement_graph(plan, evidence)
    contract = build_contract_skeleton(ir, checklist_from_ir(ir), plan, graph)
    assert validate_contract(contract, plan, graph, checklist_from_ir(ir)) is None
    assert next(item.unit for item in contract.required_outputs if item.name == "slope") == "psi/days"
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    trace = PythonExecutionTrace(requirement_graph=graph.model_dump(mode="json"), source_complete=True,
                                 calculation_contract_schema_version=3)
    record, executed = asyncio.run(GoalPythonAnalysis(settings, object(), "v7-regression-synthetic").execute(
        req, plan, evidence, trace=trace, contract=contract))
    assert executed and record and record.validation_passed
    assert math.isclose(record.output_manifest["OUT_slope"]["value"], 3)
    assert math.isclose(record.output_manifest["OUT_intercept"]["value"], 1)


def test_recovery_requires_new_formula_or_fact_not_just_another_passage():
    plan, users = plan_from_topic("X=47 psi, Y=18 psi.")
    before = build_requirement_graph(plan, users, formula_required=True)
    formula = {"evidence_id": "KB7", "source_type": "knowledge_base", "text": "Z = X - Y"}
    after = build_requirement_graph(plan, [*users, formula], formula_id="FORMULA1", formula_required=True)
    assert required_recovery_gain(before, after, ["KB7"]) == ["formula_source"]
    assert not required_recovery_gain(after, after, ["KB8"])

    partial, one_user = plan_from_topic("X=47 psi.")
    missing = build_requirement_graph(partial, [*one_user, formula], formula_id="FORMULA1", formula_required=True)
    numeric = {"evidence_id": "KB8", "source_type": "knowledge_base", "text": "Y is 18 psi."}
    completed = build_requirement_graph(partial, [*one_user, formula, numeric], formula_id="FORMULA1", formula_required=True)
    assert not missing.source_complete and completed.source_complete
    assert required_recovery_gain(missing, completed, ["KB8"]) == ["default:Y"]


def test_unspecified_standard_deviation_is_not_guessed():
    req = request("A_value=12 psi, B_value=18 psi.", "Calculate standard deviation.")
    ir = parse_request_ir(req, CRITERIA)
    assert "standard_deviation_convention_ambiguous" in validate_ir(ir)
    unresolved = asyncio.run(resolve_request_ir(req, CRITERIA, object()))
    assert unresolved and "standard_deviation_convention_ambiguous" in validate_ir(unresolved)


def test_formula_explicit_unit_conflict_is_rejected():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base", "text": "Z = X / Y. Z (psi) is the output."}]
    intent = FormulaIntent(desired_output_names=("Z",), concept_terms=(),
                           available_input_semantics=("X", "Y"), expected_unit_family="dimensionless")
    resolution = resolve_formula(evidence, intent)
    assert resolution.record is None and resolution.candidates[0]["reason"] == "unit_mismatch"
