"""Fresh synthetic contract cases; no frozen evaluation tasks or values."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import (
    CalculationContract, CalculationOutputSpec, CalculationScenario, ComputationRecord,
    CriterionEvaluation, CriterionStatus, ExpectedResultStatus, GoalCriterion,
    GoalResearchRequest, PythonExecutionTrace,
)
from app.models.research_schemas import EvidenceCounts, InternalEvidence, ResearchResponse, ResearchTiming
from app.services.calc_claim_grounding import validate_calc_claim
from app.services.calculation_contract import CalculationContractBuilder, paired_reading_contract, validate_contract
from app.services.calculation_result import CalculationResultError, validate_calculation_result
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_research_agent import GoalResearchAgent
from app.services.goal_evaluator import GoalEvaluationResult
from app.services.goal_tool_planner import AnalysisPlanSelection, ToolDecision, materialize_analysis_plan_v4
from app.services.evidence_fact_registry import EvidenceFactRegistry
from app.services.formula_source_registry import FormulaSourceRegistry
from app.services.user_fact_registry import UserFactRegistry


TOPIC = "a=37 psi, b=44 psi. Calculate the difference and mean."


def plan_and_evidence():
    evidence = UserFactRegistry.from_topic(TOPIC).evidence()
    plan = materialize_analysis_plan_v4(
        AnalysisPlanSelection(purpose="Calculate difference and mean", target_criteria=["C1"],
                              fact_refs=["USERF1", "USERF2"], formula_ref=None,
                              operation_hint="difference", expected_outputs=[], create_chart=False),
        evidence, EvidenceFactRegistry.from_evidence(evidence), FormulaSourceRegistry.from_evidence(evidence),
    )
    return plan, evidence


def contract() -> CalculationContract:
    return CalculationContract(
        contract_id="CC1", purpose="Compare two readings", target_criteria=["C1"],
        input_fact_ids=["USERF1", "USERF2"], formula_id=None, operation_type="difference_and_mean",
        scenarios=[CalculationScenario(scenario_id="pair", input_bindings={"a": "USERF1", "b": "USERF2"})],
        required_outputs=[
            CalculationOutputSpec(output_id="OUT_DIFF", name="difference", semantic_type="numeric", unit="psi",
                                  scenario_id="pair", source_fact_ids=["USERF1", "USERF2"]),
            CalculationOutputSpec(output_id="OUT_MEAN", name="mean", semantic_type="numeric", unit="psi",
                                  source_fact_ids=["USERF1", "USERF2"]),
        ],
    )


def result(**changes):
    data = {"contract_id": "CC1", "outputs": {"OUT_DIFF": {"value": 7, "unit": "psi"},
                                                 "OUT_MEAN": {"value": 40.5, "unit": "psi"}},
            "used_input_ids": ["USERF1", "USERF2"], "used_formula_id": None, "summary": "Two readings compared."}
    data.update(changes)
    return data


def test_contract_ids_scenarios_and_required_outputs():
    plan, _ = plan_and_evidence()
    assert validate_contract(contract(), plan) is None
    bad = contract().model_copy(deep=True)
    bad.input_fact_ids[0] = "USERF999"
    assert validate_contract(bad, plan) == "calculation_contract_unknown_fact"
    bad = contract().model_copy(deep=True)
    bad.formula_id = "FORMULA999"
    assert validate_contract(bad, plan) == "calculation_contract_unknown_formula"
    bad = contract().model_copy(deep=True)
    bad.required_outputs = []
    assert validate_contract(bad, plan) == "calculation_contract_no_required_outputs"


class ContractReplies:
    def __init__(self, replies):
        self.replies = list(replies)

    async def chat_structured(self, *_args, **_kwargs):
        return self.replies.pop(0)


def test_contract_parse_retry_is_bounded():
    plan, _ = plan_and_evidence()
    request = GoalResearchRequest(topic=TOPIC)
    builder = CalculationContractBuilder(ContractReplies(["bad", contract().model_dump_json()]))
    built, status, attempts = asyncio.run(builder.build(request, plan))
    assert built and status == "materialized" and attempts == 2
    built, status, attempts = asyncio.run(CalculationContractBuilder(ContractReplies(["bad", "bad"])).build(request, plan))
    assert built is None and status == "calculation_contract_parse_failed" and attempts == 2


@pytest.mark.parametrize("change,reason", [
    ({"outputs": {"OUT_DIFF": {"value": 7, "unit": "psi"}}}, "CALC_INCOMPLETE_OUTPUTS"),
    ({"outputs": {"OUT_DIFF": {"value": 7, "unit": "psi"}, "mean_value": {"value": 40.5, "unit": "psi"}}}, "CALC_INCOMPLETE_OUTPUTS"),
    ({"outputs": {"OUT_DIFF": {"value": 7}, "OUT_MEAN": {"value": 40.5, "unit": "psi"}}}, "output_unit_missing"),
    ({"outputs": {"OUT_DIFF": {"value": 7, "unit": "mD"}, "OUT_MEAN": {"value": 40.5, "unit": "psi"}}}, "output_unit_mismatch"),
    ({"used_input_ids": ["USERF1"]}, "required_input_not_used"),
    ({"used_formula_id": "FORMULA2"}, "formula_contract_mismatch"),
    ({"outputs": {"OUT_DIFF": {"value": float("nan"), "unit": "psi"}, "OUT_MEAN": {"value": 40.5, "unit": "psi"}}}, "output_type_or_value_invalid"),
])
def test_contract_result_rejects_incomplete_or_invalid(change, reason):
    with pytest.raises(CalculationResultError, match=reason):
        validate_calculation_result(result(**change), contract())


def test_complete_multi_output_and_extra_diagnostic():
    value = result()
    value["outputs"]["DIAGNOSTIC"] = {"value": 99, "unit": "psi"}
    manifest = validate_calculation_result(value, contract())
    assert set(manifest) == {"OUT_DIFF", "OUT_MEAN"}


def test_twelve_pair_contract_requires_every_difference_and_summary():
    from scripts.smoke_python_tool_v5 import CASES

    topic, goal, _ = CASES["A"]
    evidence = UserFactRegistry.from_topic(topic).evidence()
    ids = [item["evidence_id"] for item in evidence]
    assert len(ids) == 24
    plan = materialize_analysis_plan_v4(
        AnalysisPlanSelection(purpose=goal, target_criteria=["C1"], fact_refs=ids,
                              formula_ref=None, operation_hint="difference", expected_outputs=[], create_chart=False),
        evidence, EvidenceFactRegistry.from_evidence(evidence), FormulaSourceRegistry.from_evidence(evidence),
    )
    built = paired_reading_contract(GoalResearchRequest(topic=topic, goal=goal), plan)
    assert built and validate_contract(built, plan) is None
    assert len(built.required_outputs) == 16
    partial = {"contract_id": built.contract_id, "outputs": {"OUT_T1_difference": {"value": 4, "unit": "psi"}},
               "used_input_ids": ids, "used_formula_id": None}
    with pytest.raises(CalculationResultError) as failure:
        validate_calculation_result(partial, built)
    assert failure.value.reason == "CALC_INCOMPLETE_OUTPUTS"
    assert len(failure.value.missing_output_ids) == 15


def test_grouped_twelve_difference_claim_uses_shared_unit():
    from scripts.smoke_python_tool_v5 import READINGS

    ids = [f"USERF{i}" for i in range(1, 25)]
    manifest = {f"OUT_T{i}_difference": {"name": f"T{i}_difference", "value": observed - baseline,
                                             "unit": "psi", "semantic_type": "numeric",
                                             "source_fact_ids": [ids[2 * (i - 1)], ids[2 * (i - 1) + 1]]}
                for i, (baseline, observed) in enumerate(READINGS, 1)}
    manifest["OUT_max_ids"] = {"name": "max_measurement_ids", "value": ["T3", "T5", "T7", "T9", "T12"],
                               "unit": None, "semantic_type": "list", "source_fact_ids": ids}
    record = ComputationRecord(computation_id="CALC1", analysis_id="PA-001", purpose="paired",
                               validation_passed=True, output_manifest=manifest,
                               input_facts=[{"canonical_fact_id": value, "evidence_id": value} for value in ids],
                               source_input_ids=ids)
    claim = ("The observed-minus-baseline differences in psi for each measurement are as follows: "
             + ", ".join(f"T{i}={observed - baseline}.0" for i, (baseline, observed) in enumerate(READINGS, 1)) + ".")
    issues, adopted = validate_calc_claim(claim, ["CALC1", *ids],
                                          [f"OUT_T{i}_difference" for i in range(1, 13)], {"CALC1": record}, [])
    assert not issues and len(adopted) == 12


def test_four_case_specialist_manifest_requires_all_cases():
    cases = ["Alpha", "Bravo", "Cedar", "Delta"]
    contract_four = CalculationContract(
        contract_id="CC-4", purpose="Four synthetic formula cases", target_criteria=["C1"],
        input_fact_ids=[f"USERF{i}" for i in range(1, 13)], formula_id="FORMULA1", operation_type="formula",
        scenarios=[CalculationScenario(scenario_id=case, input_bindings={
            "q": f"USERF{3 * index + 1}", "pr": f"USERF{3 * index + 2}", "pwf": f"USERF{3 * index + 3}"})
            for index, case in enumerate(cases)],
        required_outputs=[CalculationOutputSpec(output_id=f"OUT_{case}", name=f"{case}_PI",
                                                semantic_type="numeric", unit="stb/d/psi", scenario_id=case,
                                                source_fact_ids=[f"USERF{3 * index + offset}" for offset in (1, 2, 3)],
                                                formula_id="FORMULA1")
                          for index, case in enumerate(cases)],
    )
    data = {"contract_id": "CC-4", "outputs": {f"OUT_{case}": {"value": index + 1.25, "unit": "stb/d/psi"}
                                                for index, case in enumerate(cases)},
            "used_input_ids": contract_four.input_fact_ids, "used_formula_id": "FORMULA1"}
    assert len(validate_calculation_result(data, contract_four)) == 4
    del data["outputs"]["OUT_Delta"]
    with pytest.raises(CalculationResultError, match="CALC_INCOMPLETE_OUTPUTS"):
        validate_calculation_result(data, contract_four)


def test_efact_specialist_subprocess_keeps_original_kb_provenance(tmp_path):
    source = {"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "fresh-v5.pdf p.2",
              "text": "P_top=3580 psi, P_bottom=3100 psi, depth=96 ft. gradient = (P_top - P_bottom)/depth."}
    evidence = [source]
    plan = materialize_analysis_plan_v4(
        AnalysisPlanSelection(purpose="Pressure gradient", target_criteria=["C1"],
                              fact_refs=["EFACT1", "EFACT2", "EFACT3"], formula_ref="FORMULA1",
                              operation_hint=None, expected_outputs=[], create_chart=False),
        evidence, EvidenceFactRegistry.from_evidence(evidence), FormulaSourceRegistry.from_evidence(evidence),
    )
    spec = CalculationContract(contract_id="CC-E", purpose="Pressure gradient", target_criteria=["C1"],
                               input_fact_ids=["EFACT1", "EFACT2", "EFACT3"], formula_id="FORMULA1",
                               operation_type="formula", scenarios=[CalculationScenario(scenario_id="profile", input_bindings={
                                   "P_top": "EFACT1", "P_bottom": "EFACT2", "depth": "EFACT3"})],
                               required_outputs=[CalculationOutputSpec(output_id="OUT_GRAD", name="gradient",
                                                                       semantic_type="numeric", unit="psi/ft",
                                                                       scenario_id="profile", source_fact_ids=["EFACT1", "EFACT2", "EFACT3"],
                                                                       formula_id="FORMULA1")])
    assert validate_contract(spec, plan) is None
    payload = {"contract_id": "CC-E", "outputs": {"OUT_GRAD": {"value": 5, "unit": "psi/ft"}},
               "used_input_ids": spec.input_fact_ids, "used_formula_id": "FORMULA1", "summary": "Gradient 5 psi/ft."}
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"),
                                  CodeReply(payload), "v5-efact")
    record, executed = asyncio.run(analysis.execute(GoalResearchRequest(topic="Calculate gradient",
                                               allow_python_execution=True, python_execution_approved=True),
                                               plan, evidence, contract=spec))
    assert executed and record and record.validation_passed and record.contract_validation_passed
    assert record.source_evidence_ids == ["KB1"] and record.formula_evidence_ids == ["KB1"]


class CodeReply:
    def __init__(self, payload):
        self.payload = payload

    async def chat_structured(self, messages, *_args, **_kwargs):
        filename = json.loads(messages[-1]["content"])["output_json"]
        code = f"import json\nwith open({filename!r}, 'w') as f:\n    json.dump({self.payload!r}, f)\n"
        return json.dumps({"code": code})


def test_incomplete_subprocess_never_promotes_calc(tmp_path):
    plan, evidence = plan_and_evidence()
    incomplete = result(outputs={"OUT_DIFF": {"value": 7, "unit": "psi"}})
    analysis = GoalPythonAnalysis(Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"),
                                  CodeReply(incomplete), "v5-incomplete")
    trace = PythonExecutionTrace()
    record, executed = asyncio.run(analysis.execute(
        GoalResearchRequest(topic=TOPIC, allow_python_execution=True, python_execution_approved=True,
                            max_python_attempts_per_call=1), plan, evidence, trace, contract(),
    ))
    assert executed and record and not record.validation_passed
    assert trace.subprocess_reached and not trace.contract_complete
    assert trace.missing_output_ids == ["OUT_MEAN"] and trace.blocked_stage == "result_validation_failed"


def test_contract_path_preserves_permission_network_and_cache_gates(tmp_path):
    plan, evidence = plan_and_evidence()
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    analysis = GoalPythonAnalysis(settings, CodeReply(result()), "v5-gates")
    denied = PythonExecutionTrace()
    record, executed = asyncio.run(analysis.execute(GoalResearchRequest(topic=TOPIC), plan, evidence, denied, contract()))
    assert record is None and not executed and denied.blocked_stage == "permission_not_approved"
    assert analysis.calls == 0
    approved = GoalResearchRequest(topic=TOPIC, allow_python_execution=True, python_execution_approved=True)
    first, executed = asyncio.run(analysis.execute(approved, plan, evidence, contract=contract()))
    assert executed and first and first.validation_passed and first.contract_validation_passed
    cached = PythonExecutionTrace()
    second, executed = asyncio.run(analysis.execute(approved, plan, evidence, cached, contract()))
    assert second is first and not executed and cached.blocked_stage == "cache_hit" and not cached.subprocess_reached

    class NetworkCode:
        async def chat_structured(self, *_args, **_kwargs):
            return json.dumps({"code": "import requests\nrequests.get('https://example.invalid')"})

    blocked = GoalPythonAnalysis(settings, NetworkCode(), "v5-network")
    trace = PythonExecutionTrace()
    unsafe, executed = asyncio.run(blocked.execute(
        approved.model_copy(update={"max_python_attempts_per_call": 1}), plan, evidence, trace, contract(),
    ))
    assert executed and unsafe and not unsafe.validation_passed
    assert trace.blocked_stage == "sandbox_validation_failed" and not trace.subprocess_reached


def computation(calc_id="CALC1", value=7, unit="psi", source="USERF1"):
    return ComputationRecord(
        computation_id=calc_id, analysis_id="PA-001", purpose="difference", validation_passed=True,
        input_facts=[{"canonical_fact_id": source, "evidence_id": source}],
        source_input_ids=[source] if source.startswith("USER") else [],
        source_evidence_ids=[source] if source.startswith("KB") else [],
        required_output_ids=["OUT_DIFF"], contract_validation_passed=True,
        output_manifest={"OUT_DIFF": {"name": "difference", "value": value, "unit": unit,
                                      "semantic_type": "numeric", "source_fact_ids": [source]}},
    )


@pytest.mark.parametrize("claim,citations,outputs,reason", [
    ("Difference is 7 psi.", ["CALC1", "USERF1"], ["OUT_DIFF"], None),
    ("Mean is 2.3 psi.", ["CALC1", "USERF1"], ["OUT_MEAN"], "calc_output_not_found"),
    ("Difference is 8 psi.", ["CALC1", "USERF1"], ["OUT_DIFF"], "calc_value_mismatch"),
    ("Difference is 7 mD.", ["CALC1", "USERF1"], ["OUT_DIFF"], "calc_unit_mismatch"),
    ("Difference is 7 psi.", ["CALC1", "KB1"], ["OUT_DIFF"], "provenance_attribution_error"),
])
def test_claim_level_grounding_and_user_provenance(claim, citations, outputs, reason):
    issues, adopted = validate_calc_claim(claim, citations, outputs, {"CALC1": computation()}, [])
    assert (reason in issues) if reason else (not issues and adopted == ["CALC1:OUT_DIFF"])


def test_multi_calc_and_original_evidence_provenance():
    records = {"CALC1": computation(), "CALC2": computation("CALC2", 9, source="KB3")}
    issues, adopted = validate_calc_claim("Difference is 9 psi.", ["CALC2", "KB3"],
                                          ["CALC2:OUT_DIFF"], records, [])
    assert not issues and adopted == ["CALC2:OUT_DIFF"]
    issues, _ = validate_calc_claim("Difference is 9 psi.", ["CALC1", "CALC2", "KB3"],
                                    ["OUT_DIFF"], records, [])
    assert issues == ["calc_output_not_found"]
    user = [{"evidence_id": "USERF1", "source_type": "user_fact", "value": 7}]
    issues, _ = validate_calc_claim("The difference is 7 psi.", ["KB1"], [], {}, user)
    assert issues == ["provenance_attribution_error"]


def test_claim_semantic_label_and_tie_list_cannot_overclaim():
    record = computation()
    record.output_manifest["OUT_TIES"] = {"name": "max_station_ids", "value": ["T3", "T8"],
                                           "unit": None, "semantic_type": "list", "source_fact_ids": ["USERF1"]}
    issues, _ = validate_calc_claim("Mean is 7 psi.", ["CALC1", "USERF1"], ["OUT_DIFF"],
                                    {"CALC1": record}, [])
    assert "calc_output_not_found" in issues
    issues, _ = validate_calc_claim("Maximum ties: T3, T8, T9.", ["CALC1", "USERF1"], ["OUT_TIES"],
                                    {"CALC1": record}, [])
    assert "calc_value_mismatch" in issues
    record.output_manifest["OUT_EXTRA"] = {"name": "extra", "value": 5, "unit": "mD",
                                            "semantic_type": "numeric", "source_fact_ids": ["USERF1"]}
    issues, _ = validate_calc_claim("7 mD and 5 psi.", ["CALC1", "USERF1"], ["OUT_DIFF", "OUT_EXTRA"],
                                    {"CALC1": record}, [])
    assert "calc_unit_mismatch" in issues


def test_persisted_records_accept_old_json():
    assert ComputationRecord.model_validate({"computation_id": "CALC1", "analysis_id": "PA-001", "purpose": "old"}).contract_id is None
    assert PythonExecutionTrace.model_validate({}).required_output_ids == []


class RecoveryResearch:
    def __init__(self, source_available=True):
        self.source_available = source_available
        self.requests = []

    async def research(self, request):
        self.requests.append(request)
        text = ("The synthetic source relation is PI = q/(pr-pwf)."
                if self.source_available and len(self.requests) > 1 else "Synthetic PI context without an equation.")
        return ResearchResponse(
            query=request.query, answer="Synthetic source", internal_sources=[InternalEvidence(
                evidence_id="KB1", document="fresh-v5.pdf", page=len(self.requests),
                chunk_id=f"fresh-{len(self.requests)}", score=1, excerpt=text,
            )], web_sources=[], figures=[], provenance=[], model=request.model, inference_used=True,
            evidence_counts=EvidenceCounts(internal=1, external=0), routing_mode="internal_only", retrieval_mode="legacy",
            timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0), validation={},
        )


class RecoveryPlanner:
    async def decide(self, request, criteria, evidence, coverage, prior):
        formulas = FormulaSourceRegistry.from_evidence(evidence)
        if not formulas.records:
            return ToolDecision(tool_needed=True, tool_type="python_calculation", reason="Need cited equation",
                                plan_status="materialization_failed", verification_failures=["required_source_unavailable"],
                                plan_summary={"purpose": "productivity index", "target_criteria": ["C1"]},
                                selected_fact_ids=["USERF1", "USERF2", "USERF3"])
        plan = materialize_analysis_plan_v4(
            AnalysisPlanSelection(purpose="Calculate PI", target_criteria=["C1"],
                                  fact_refs=["USERF1", "USERF2", "USERF3"], formula_ref="FORMULA1",
                                  operation_hint=None, expected_outputs=[], create_chart=False),
            evidence, EvidenceFactRegistry.from_evidence(evidence), formulas,
        )
        return ToolDecision(tool_needed=True, tool_type="python_calculation", reason="Need cited equation",
                            plan_status="materialized", plan=plan, selected_fact_ids=["USERF1", "USERF2", "USERF3"],
                            selected_formula_id="FORMULA1")


class RecoveryContractBuilder:
    async def build(self, request, plan):
        return CalculationContract(
            contract_id="CC-REC", purpose="PI", target_criteria=["C1"],
            input_fact_ids=["USERF1", "USERF2", "USERF3"], formula_id="FORMULA1", operation_type="formula",
            scenarios=[CalculationScenario(scenario_id="well", input_bindings={"q": "USERF1", "pr": "USERF2", "pwf": "USERF3"})],
            required_outputs=[CalculationOutputSpec(output_id="OUT_PI", name="PI", semantic_type="numeric", unit="stb/d/psi",
                                                    scenario_id="well", source_fact_ids=["USERF1", "USERF2", "USERF3"],
                                                    formula_id="FORMULA1")],
        ), "materialized", 1


class FixedEvaluator:
    async def evaluate(self, request, criteria, candidate, evidence, validation, computations=None):
        good = bool(computations and computations[0].validation_passed)
        return GoalEvaluationResult(
            criteria=[CriterionEvaluation(criterion_id="C1", status=CriterionStatus.MET if good else CriterionStatus.UNMET,
                                          reason="synthetic", supporting_evidence=["CALC1"] if good else [])],
            coverage=1.0 if good else 0.0, achieved=good, expected_result_status=ExpectedResultStatus.NOT_PROVIDED,
            gaps=[], next_research_need=None, engineering_validation_passed=True,
            engineering_contradiction_count=0, unsupported_engineering_claim_count=0,
            goal_conflicts_with_evidence=False,
        )


def test_one_internal_recovery_rebuilds_registry_and_reaches_calc(tmp_path):
    topic = "q=812 stb/d, pr=3490 psi, pwf=2940 psi"
    research = RecoveryResearch()
    payload = {"contract_id": "CC-REC", "outputs": {"OUT_PI": {"value": 812 / (3490 - 2940), "unit": "stb/d/psi"}},
               "used_input_ids": ["USERF1", "USERF2", "USERF3"], "used_formula_id": "FORMULA1", "summary": "PI computed."}
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")

    async def synthesis(*_args):
        return "PI calculated."

    agent = GoalResearchAgent(
        research, object(), evaluator=FixedEvaluator(), synthesizer=synthesis,
        tool_planner=RecoveryPlanner(), contract_builder=RecoveryContractBuilder(),
        analysis_factory=lambda run_id: GoalPythonAnalysis(settings, CodeReply(payload), run_id),
    )
    response = asyncio.run(agent.run("v5-recovery", GoalResearchRequest(
        topic=topic, success_criteria=[GoalCriterion(criterion_id="C1", description="Calculate PI")],
        allow_python_execution=True, python_execution_approved=True, max_iterations=1,
        engineering_validation=False,
    )))
    trace = response.iterations[0].python_trace
    assert trace.recovery_triggered and trace.recovery_query_count == 1
    assert len(research.requests) == 2 and research.requests[1].use_internal and not research.requests[1].use_external
    assert "812" not in research.requests[1].query and "3490" not in research.requests[1].query
    assert trace.recovery_materialization_success and trace.subprocess_reached and trace.contract_complete
    assert response.computations[0].validation_passed


def test_recovery_failure_stops_before_python_and_stays_bounded(tmp_path):
    research = RecoveryResearch(source_available=False)

    async def synthesis(*_args):
        return "No equation available."

    agent = GoalResearchAgent(research, object(), evaluator=FixedEvaluator(), synthesizer=synthesis,
                              tool_planner=RecoveryPlanner(), contract_builder=RecoveryContractBuilder())
    response = asyncio.run(agent.run("v5-recovery-miss", GoalResearchRequest(
        topic="q=812 stb/d, pr=3490 psi, pwf=2940 psi", max_iterations=2,
        success_criteria=[GoalCriterion(criterion_id="C1", description="Calculate PI")],
        allow_python_execution=True, python_execution_approved=True, engineering_validation=False,
    )))
    assert response.python_calls_total == 0 and not response.computations
    assert sum(item.python_trace.recovery_query_count for item in response.iterations) == 1
    assert response.iterations[0].python_trace.blocked_stage == "calculation_source_recovery_failed"


class SynthesisReplies:
    def __init__(self, claims):
        self.claims = list(claims)
        self.calls = 0

    async def chat_structured(self, *_args, **_kwargs):
        self.calls += 1
        return json.dumps({"claims": [self.claims.pop(0)],
                           "hypothesis_assessment": {"claim": "", "citations": []}, "limitations": []})


@pytest.mark.parametrize("repair_value,expected_grounded", [(7, True), (8, False)])
def test_bounded_synthesis_repair_or_safe_omission(repair_value, expected_grounded):
    wrong = {"claim": "Difference is 8 psi.", "citations": ["CALC1"], "output_ids": ["OUT_DIFF"]}
    repair = {"claim": f"Difference is {repair_value} psi.", "citations": ["CALC1"], "output_ids": ["OUT_DIFF"]}
    ollama = SynthesisReplies([wrong, repair])
    agent = GoalResearchAgent(object(), ollama)
    record = computation()
    evidence = [
        {"evidence_id": "CALC1", "source_type": "calculation", "locator": "PA-001", "text": "Difference 7 psi",
         "source_evidence_ids": [], "source_input_ids": ["USERF1"], "formula_evidence_ids": [],
         "output_manifest": record.output_manifest, "output_files": []},
        {"evidence_id": "USERF1", "source_type": "user_fact", "locator": "topic", "text": "a=37 psi", "value": 37},
    ]
    trace = PythonExecutionTrace()
    answer = asyncio.run(agent._synthesize(GoalResearchRequest(topic=TOPIC),
                                            [GoalCriterion(criterion_id="C1", description="Calculate difference")],
                                            evidence, [], computations=[record], python_trace=trace))
    assert ollama.calls == 2
    assert ("Difference is 7 psi." in answer) is expected_grounded
    assert trace.calc_grounding_validation_passed is expected_grounded
    if not expected_grounded:
        assert "Difference is 8 psi." not in answer and "[CALC1]" not in answer


def test_source_and_formula_citations_are_expanded_for_grounded_calc():
    record = computation(source="KB3")
    record.formula_evidence_ids = ["KB5"]
    ollama = SynthesisReplies([{"claim": "Difference is 7 psi.", "citations": ["CALC1"], "output_ids": ["OUT_DIFF"]}])
    agent = GoalResearchAgent(object(), ollama)
    evidence = [
        {"evidence_id": "CALC1", "source_type": "calculation", "locator": "PA-001", "text": "Difference 7 psi",
         "source_evidence_ids": ["KB3"], "source_input_ids": [], "formula_evidence_ids": ["KB5"],
         "output_manifest": record.output_manifest, "output_files": []},
        {"evidence_id": "KB3", "source_type": "knowledge_base", "locator": "source", "text": "a=37 psi"},
        {"evidence_id": "KB5", "source_type": "knowledge_base", "locator": "formula", "text": "difference = b - a"},
    ]
    answer = asyncio.run(agent._synthesize(GoalResearchRequest(topic=TOPIC), [], evidence, [], computations=[record]))
    assert all(f"[{value}]" in answer for value in ("CALC1", "KB3", "KB5"))


def test_unsupported_calc_limitation_is_not_forwarded_to_evaluator():
    record = computation()

    class Replies:
        async def chat_structured(self, *_args, **_kwargs):
            return json.dumps({"claims": [{"claim": "Difference is 7 psi.", "citations": ["CALC1"],
                                            "output_ids": ["OUT_DIFF"]}],
                               "hypothesis_assessment": {"claim": "", "citations": []},
                               "limitations": ["CALC1 contradicts an earlier 0.55 psi result."]})

    evidence = [
        {"evidence_id": "CALC1", "source_type": "calculation", "locator": "PA-001", "text": "Difference 7 psi",
         "source_evidence_ids": [], "source_input_ids": ["USERF1"], "formula_evidence_ids": [],
         "output_manifest": record.output_manifest, "output_files": []},
        {"evidence_id": "USERF1", "source_type": "user_fact", "locator": "topic", "text": "a=37 psi", "value": 37},
    ]
    answer = asyncio.run(GoalResearchAgent(object(), Replies())._synthesize(
        GoalResearchRequest(topic=TOPIC), [], evidence, [], computations=[record],
    ))
    assert "Difference is 7 psi." in answer and "0.55" not in answer
