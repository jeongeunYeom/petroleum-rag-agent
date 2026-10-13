"""Fresh synthetic v21 checks; no frozen evaluation material is loaded."""

import asyncio

import pytest

from app.models.goal_research_schemas import GoalResearchRequest, GoalRunStatus, GoalStatus
from app.services.calculation_request_ir import parse_request_ir
from app.services.calculation_requirements import formula_target_contract, rank_formula_candidates
from app.services.formula_dependency import resolve_formula_dependencies
from app.services.formula_source_registry import FormulaSourceRegistry
from app.services.goal_intent import GoalIntentKind, classify_goal_intent
from app.services.goal_action_planner import GoalActionPlanner
from app.services.goal_knowledge_retrieval import plan_query
from app.services.goal_simulation import direct_operation_operands, direct_readiness, direct_role_values
from app.services.user_fact_registry import UserFactRegistry
from test_agent_reliability_v19_dev import actions, execute, request


def intent_of(text):
    return classify_goal_intent(request(text), has_user_facts=bool(UserFactRegistry.from_topic(text).records))


@pytest.mark.parametrize("text,kind", [
    ("초기 유량은 420 stb/d이고 변경 후 유량은 525 stb/d이다. 증가율을 계산해줘.", GoalIntentKind.DIRECT_CALC),
    ("입구 압력은 3100 psi, 출구 압력은 2860 psi이다. 압력 강하량을 구해줘.", GoalIntentKind.DIRECT_CALC),
    ("주입량 800 bbl 중 620 bbl을 회수했다. 회수율을 계산해줘.", GoalIntentKind.DIRECT_CALC),
    ("A=19, B=31, C=27의 평균을 구해줘.", GoalIntentKind.DIRECT_CALC),
    ("x=7, y=9. score = x * y + 2로 계산해줘.", GoalIntentKind.USER_FORMULA_CALC),
    ("k=16 mD로 내부 교재의 투과도 관계식을 찾아 지수를 계산해줘.", GoalIntentKind.KB_FORMULA_CALC),
    ("2017년 책에서는 공극률을 어떻게 정의하는가?", GoalIntentKind.KNOWLEDGE_QA),
    ("투과도가 커지면 압력 손실이 항상 증가하는 거지?", GoalIntentKind.PREMISE_CHECK),
])
def test_request_classification(text, kind):
    assert intent_of(text).kind == kind


@pytest.mark.parametrize("text,roles", [
    ("초기 유량은 420 stb/d, 변경 후 유량은 525 stb/d", {"initial", "final"}),
    ("입구 압력은 3100 psi, 출구 압력은 2860 psi", {"inlet", "outlet"}),
    ("주입량 800 bbl 중 620 bbl을 회수했다", {"injected", "produced"}),
    ("before pressure is 120 psi and after pressure is 150 psi", {"initial", "final"}),
    ("inlet pressure is 80 psi and outlet pressure is 65 psi", {"inlet", "outlet"}),
    ("injected volume is 500 bbl and recovered volume is 375 bbl", {"injected", "produced"}),
    ("첫 번째 측정값은 10 psi, 두 번째 측정값은 14 psi", {"initial", "final"}),
    ("baseline rate is 40 stb/d, changed rate is 52 stb/d", {"initial", "final"}),
])
def test_semantic_operand_roles(text, roles):
    facts = UserFactRegistry.from_topic(text)
    assert roles <= {row.semantic_role for row in facts.records}


@pytest.mark.parametrize("text,operation,expected,unit", [
    ("초기 유량은 420 stb/d이고 변경 후 유량은 525 stb/d이다. 증가율을 계산해줘.",
     "percentage_increase", 25.0, "%"),
    ("입구 압력은 3100 psi, 출구 압력은 2860 psi이다. 압력 강하량을 구해줘.",
     "difference", 240.0, "psi"),
    ("주입량 800 bbl 중 620 bbl을 회수했다. 회수율을 계산해줘.",
     "recovery_percent", 77.5, "%"),
    ("A=19, B=31, C=27의 평균을 구해줘.", "mean", 77 / 3, None),
    ("A=19, B=31, C=27의 합계를 구해줘.", "sum", 77.0, None),
    ("초기 압력은 120 psi이고 최종 압력은 150 psi이다. 증가율을 계산해줘.",
     "percentage_increase", 25.0, "%"),
])
def test_direct_execution(tmp_path, monkeypatch, text, operation, expected, unit):
    result, _, _ = execute(tmp_path, monkeypatch, text)
    assert result.status == GoalStatus.ACHIEVED, (actions(result), result.required_inputs, result.telemetry)
    assert actions(result)[0] == "calculate"
    assert "retrieve" not in actions(result)
    assert result.computations[0].validation_passed
    output = next(row for row in result.computations[0].output_manifest.values()
                  if row["name"] == operation)
    assert output["value"] == pytest.approx(expected)
    if unit:
        assert output["unit"] == unit


@pytest.mark.parametrize("target,decoy,left,right", [
    ("Q", "P", "k", "dp"), ("J", "Q", "rate", "drawdown"),
    ("Vp", "Vs", "bulk", "phi"), ("Ek", "Q", "mass", "speed"),
    ("W", "P", "force", "length"), ("Z", "A", "n", "m"),
    ("M", "N", "density", "volume"), ("R", "S", "rise", "run"),
])
def test_source_formula_selection_by_requested_output(target, decoy, left, right):
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": f"Synthetic relations:\n{decoy} = {left} + {right}\n"
                         f"{target} = {left} * {right}\nVariables are measured locally."}]
    contract = formula_target_contract(f"Calculate {target} using {left} and {right}", [left, right], target)
    chosen, report = rank_formula_candidates(evidence, f"Calculate {target} using {left} and {right}",
                                             [left, right], target_contract=contract)
    assert chosen and chosen.lhs == target
    assert report.candidates_found >= 1


@pytest.mark.parametrize("producer,target,left,right,scale", [
    ("A", "D", "B", "C", "E"), ("X", "Y", "U", "V", "W"),
    ("F1", "F2", "T", "S", "G"), ("R1", "R2", "p", "q", "z"),
])
def test_sourced_dependency_selects_prerequisite(producer, target, left, right, scale):
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": f"Synthetic sequence:\n{producer} = {left} + {right}\n"
                         f"{target} = {producer} * {scale}\n"}]
    records = FormulaSourceRegistry.from_evidence(evidence).records
    final = next(row for row in records if row.lhs == target)
    users = UserFactRegistry.from_topic(f"{left}=3, {right}=4, {scale}=5")
    plan = resolve_formula_dependencies(final, evidence, users, [], [])
    assert plan.next_formula and plan.next_formula.lhs == producer
    assert not plan.missing_inputs and not plan.block_reason


@pytest.mark.parametrize("question,english", [
    ("시추 시 정수압 관계식을 찾아줘", "hydrostatic pressure"),
    ("지층 비저항의 정의를 설명해줘", "formation resistivity"),
    ("생산 지수를 내부 자료에서 찾아줘", "productivity index"),
    ("물 포화도와 지층 평가를 설명해줘", "water saturation"),
])
def test_bilingual_retrieval_concept(question, english):
    plan = plan_query(question)
    assert english in plan.search_text
    assert plan.domain is None or isinstance(plan.domain, str)


@pytest.mark.parametrize("target,known,missing,answer", [
    ("H", "P", "Q", "Q=11 psi"),
    ("Z", "A", "B", "B=7 psi"),
    ("K", "M", "N", "N=13 psi"),
    ("T", "U", "V", "V=17 psi"),
])
def test_missing_input_resume_same_run(tmp_path, monkeypatch, target, known, missing, answer):
    from app.core.config import Settings
    from app.services.goal_execution_agent import GoalExecutionAgent
    from test_agent_reliability_v19_dev import PassingEvaluator, SyntheticResearch, no_synthesis

    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
                        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    source = f"Measured engineering relation:\n{target} = {known} + {missing}\n"
    agent = GoalExecutionAgent(SyntheticResearch([[(3, source)]]), object(),
                               evaluator=PassingEvaluator(), synthesizer=no_synthesis)
    text = f"{known}=4 psi. Find the internal equation for {target} and calculate {target}."
    first = asyncio.run(agent.run("v21-resume", request(text)))
    assert first.run_status == GoalRunStatus.WAITING_FOR_USER_INPUT, (actions(first), first.telemetry)
    checkpoint = dict(first.resume_checkpoint)
    checkpoint["user_replies"] = [answer]
    resumed = asyncio.run(agent.run(first.run_id, request(text),
                                    resume_state=checkpoint, resume_result=first))
    assert resumed.run_id == first.run_id
    assert resumed.status == GoalStatus.ACHIEVED, (actions(resumed), resumed.required_inputs)
    assert resumed.computations and resumed.computations[-1].validation_passed
    assert resumed.telemetry["clarification_resolved"]


@pytest.mark.parametrize("text", [
    "비중 0.85", "The catalog lists 2021 as the publication year.",
    "초기 압력은 3000 psi, 생산량은 500 stb/d. 차이를 계산해줘.",
    "inlet pressure is 100 psi, outlet volume is 80 bbl; find their difference.",
    "A=3 psi, B=7 bbl. A/B 비율을 계산해줘.",
    "공극률을 설명해줘. phi=0.23",
])
def test_near_miss_does_not_invent_computation(text):
    facts = UserFactRegistry.from_topic(text)
    intent = intent_of(text)
    if "차이" in text or "difference" in text or "비율" in text:
        operations = parse_request_ir(request(text), []).requested_operation_types
        orders, missing = direct_operation_operands(text, facts, operations)
        assert missing or direct_readiness(text, facts, operations)
        assert not orders
    else:
        assert intent.kind != GoalIntentKind.DIRECT_CALC


def test_unrelated_same_variable_formula_rejected():
    evidence = [{"evidence_id": "KB1", "source_type": "knowledge_base",
                 "text": "The formation factor is discussed in this chapter.\nQ = k + h\n"}]
    chosen, _ = rank_formula_candidates(evidence, "Calculate F from k and h", ["k", "h"],
                                        target_contract=formula_target_contract("Calculate F", ["k", "h"], "F"))
    assert chosen is None


def test_formula_recovery_uses_standard_symbol_names_without_guessing_equation():
    text = "phi=0.26, Sw=0.42, Rw=0.12 ohm-m. 내부 지층평가 관계식으로 Rt를 계산해줘."
    query = GoalActionPlanner.formula_recovery_query(
        request(text), intent_of(text), ["phi", "Sw", "Rw"], {"Rw": "ohm-m"}, [], 1)
    assert "true formation resistivity" in query
    assert "formation water resistivity" in query
    assert "water saturation" in query
    assert "=" not in query.split("equation formula relation", 1)[0]


@pytest.mark.parametrize("target,left,right", [
    ("H", "P", "Q"), ("Z", "A", "B"), ("K", "M", "N"), ("T", "U", "V"),
    ("J", "R", "S"), ("W", "C", "D"), ("L", "E", "F"), ("G", "I", "O"),
    ("N1", "X", "Y"), ("B1", "D1", "E1"),
])
def test_synthetic_kb_retrieve_to_calculate(tmp_path, monkeypatch, target, left, right):
    source = f"Synthetic engineering equation:\n{target} = {left} + {right}\n"
    text = (f"{left}=14 psi, {right}=9 psi. Find the internal equation for {target} "
            f"and calculate {target}.")
    result, _, _ = execute(tmp_path, monkeypatch, text, [[(4, source)]])
    assert result.status == GoalStatus.ACHIEVED, (actions(result), result.telemetry)
    assert actions(result)[:3] == ["retrieve", "calculate", "verify"]
    assert result.computations[0].validation_passed
    assert result.computations[0].output_manifest["OUT_RESULT"]["value"] == pytest.approx(23)
    assert result.telemetry["formula_source_verified"]


@pytest.mark.parametrize("producer,target,left,right,extra", [
    ("A", "D", "B", "C", "E"), ("X", "Y", "U", "V", "W"),
    ("F1", "F2", "T", "S", "G"), ("R1", "R2", "p", "q", "z"),
])
def test_synthetic_two_calculation_chain(tmp_path, monkeypatch, producer, target, left, right, extra):
    from app.core.config import Settings
    from app.services.goal_execution_agent import GoalExecutionAgent
    from test_agent_reliability_v19_dev import PassingEvaluator, SyntheticResearch, no_synthesis

    source = f"Synthetic engineering relations:\n{producer} = {left} + {right}\n{target} = {producer} + {extra}\n"
    text = (f"{left}=3 psi, {right}=4 psi, {extra}=5 psi. Find the internal relations "
            f"and calculate {target}.")
    class NoExtraTool:
        async def chat_structured(self, *_args, **_kwargs):
            return '{"tool_needed":false,"tool_type":"none","reason":"Synthetic run"}'

    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
                        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    agent = GoalExecutionAgent(SyntheticResearch([[(4, source)]]), NoExtraTool(),
                               evaluator=PassingEvaluator(), synthesizer=no_synthesis)
    result = asyncio.run(agent.run("v21-chain", request(text)))
    assert result.status == GoalStatus.ACHIEVED, (actions(result), result.telemetry)
    assert actions(result).count("calculate") == 2
    assert result.computations[-1].output_manifest["OUT_RESULT"]["value"] == pytest.approx(12)
    assert all(row.validation_passed for row in result.computations)


def test_english_only_recovery_after_empty_bilingual_search(tmp_path, monkeypatch):
    from app.core.config import Settings
    from app.models.research_schemas import EvidenceCounts, ResearchResponse, ResearchTiming
    from app.services.goal_execution_agent import GoalExecutionAgent
    from test_agent_reliability_v19_dev import PassingEvaluator, SyntheticResearch, SyntheticSemanticSupport, no_synthesis

    class BilingualResearch(SyntheticResearch):
        async def research(self, query):
            if any("가" <= char <= "힣" for char in query.query):
                self.queries.append(query.query)
                return ResearchResponse(query=query.query, answer="", internal_sources=[], web_sources=[],
                    figures=[], provenance=[], model=query.model, inference_used=False,
                    evidence_counts=EvidenceCounts(internal=0, external=0),
                    routing_mode="internal_only", retrieval_mode="hybrid",
                    timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0, elapsed_seconds=0))
            return await super().research(query)

    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
                        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    research = BilingualResearch([[(4, "Formation resistivity describes true resistivity of the rock")]])
    research.vector_store = object()
    agent = GoalExecutionAgent(research, SyntheticSemanticSupport(),
                               evaluator=PassingEvaluator(), synthesizer=no_synthesis)
    result = asyncio.run(agent.run("bilingual", request("지층 비저항의 의미를 내부 자료에서 설명해줘.")))
    assert result.telemetry["retrieval_refinement_used"]
    assert any(query == "formation resistivity" for query in research.queries)
    assert result.internal_sources


def test_later_complete_context_replaces_pinned_clipped_formula(tmp_path, monkeypatch):
    from app.core.config import Settings
    from app.services.goal_execution_agent import GoalExecutionAgent
    from test_agent_reliability_v19_dev import PassingEvaluator, SyntheticResearch, no_synthesis

    class DistinctChunks(SyntheticResearch):
        async def research(self, query):
            response = await super().research(query)
            response.internal_sources = [source.model_copy(update={"chunk_id": f"chunk-{self.calls}"})
                                         for source in response.internal_sources]
            return response

    clipped = "F = a/fm\nwhere m is the cementation factor and a is a constant."
    complete = ("Formation factor is obtained from measured porosity.\n"
                "F = a/fm\nwhere m is the cementation factor and a is a constant.")
    monkeypatch.setattr("app.services.goal_execution_agent.get_settings",
                        lambda: Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace"))
    research = DistinctChunks([[(164, clipped)], [(164, complete)]])
    agent = GoalExecutionAgent(research, object(), evaluator=PassingEvaluator(), synthesizer=no_synthesis)
    result = asyncio.run(agent.run("v21-better-context", request(
        "phi=0.26, a=1.1, m=1.8. Find the internal formation factor relation and calculate F.")))
    assert result.status == GoalStatus.ACHIEVED, (actions(result), result.telemetry)
    assert result.telemetry["formula_pin_upgraded_with_context"]
    assert result.computations[0].normalized_formula == "f=a/phi**m"
    assert result.computations[0].validation_passed
    assert result.computations[0].output_manifest["OUT_RESULT"]["value"] == pytest.approx(1.1 / 0.26**1.8)
