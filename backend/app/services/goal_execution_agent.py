"""State-driven v8 orchestration around the existing research and calculation tools."""

from __future__ import annotations

import asyncio
import re
import time
import json
import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.models.goal_research_schemas import (
    CriterionEvaluation, CriterionStatus, ExpectedResultStatus, GoalCriterion, GoalResearchRequest,
    GoalResearchResponse, GoalRunStatus, GoalStatus, GoalStopReason,
)
from app.models.research_schemas import EvidenceCounts, ResearchRequest, ResearchResponse, ResearchTiming
from app.services.formula_source_registry import FormulaSourceRegistry, equation_ast, expression_variables, normalize_formula, source_contains_equation
from app.services.calculation_requirements import infer_dimensionless, rank_formula_candidates, select_formula_candidate
from app.services.calculation_request_ir import OPERATIONS, parse_request_ir, validate_ir
from app.services.goal_clarification import (calculation_missing, calculation_readiness, clarification_question,
                                             parse_user_simulation_spec, simulation_readiness,
                                             user_simulation_missing)
from app.services.evidence_fact_registry import EvidenceFactRegistry
from app.services.calc_claim_grounding import NUMERIC, _matches_reported_value, validate_calc_claim
from app.services.citation_semantics import ground_research_claims
from app.services.premise_grounding import PremiseAssessment, assess_premise, expand_premise_context
from app.services.goal_knowledge_retrieval import plan_query, rerank_sources
from app.services.goal_action_planner import (CALC_WORDS, ENGINEERING_TERMS, SIMULATE_WORDS,
                                              GoalActionPlanner)
from app.services.goal_intent import (FormulaOrigin, GoalIntentKind, SourceRequirement, asks_for_api_gravity_calculation,
                                      ambiguous_premise_candidate, classify_goal_intent, prefers_korean,
                                      formula_origin, user_equation,
                                      GoalIntent)
from app.services.engineering.drilling import DrillingValidator
from app.services.engineering_validator import EngineeringValidator
from app.services.goal_evaluator import GoalEvaluator
from app.services.goal_execution_state import (
    ActionRecord, DerivedFact, GoalActionType, GoalExecutionState, SimulationParameter, SimulationSpec,
)
from app.services.goal_research_agent import EvidenceAccumulator, GoalResearchAgent
from app.services.goal_tool_planner import (
    AnalysisPlanSelection, GoalToolPlanner, ToolDecision, materialize_analysis_plan_v4,
)
from app.services.goal_simulation import (direct_operation_operands, direct_readiness,
                                          run_direct_arithmetic, run_parameter_sweep,
                                          run_user_formula_calculation,
                                          user_formula_bindings)
from app.services.user_fact_registry import NUMBER, UserFactRegistry
from app.services.source_answerability import (evaluate_claim_support, grounded_answer, SupportStatus,
                                               RequiredClaim, ClaimSupport)


class _EvidenceSnapshot:
    """Feeds the v7 computation pipeline accumulated evidence, without a retrieval call."""

    def __init__(self, evidence: EvidenceAccumulator, model: str,
                 formula_source_id: str | None = None, formula_span: str | None = None,
                 retrieval_mode: str = "legacy"):
        self.evidence = evidence
        self.model = model
        self.formula_source_id = formula_source_id
        self.formula_span = formula_span
        self.retrieval_mode = retrieval_mode

    async def research(self, request: ResearchRequest) -> ResearchResponse:
        internal = self.evidence.internal
        web = self.evidence.web
        if self.formula_source_id and self.formula_span:
            # The span is copied verbatim from a retrieved passage.  This avoids
            # treating worked-example equations on the same page as alternate
            # dependencies of an already supplied input.
            internal = [item.model_copy(update={"excerpt": self.formula_span}) for item in internal
                        if item.evidence_id == self.formula_source_id]
            web = [item.model_copy(update={"passage": self.formula_span}) for item in web
                   if item.evidence_id == self.formula_source_id]
        return ResearchResponse(
            query=request.query, answer="", internal_sources=internal,
            web_sources=web, figures=self.evidence.figures if not self.formula_source_id else [], provenance=[],
            model=self.model, inference_used=False,
            evidence_counts=EvidenceCounts(internal=len(internal), external=len(web)),
            routing_mode="internal_only" if request.use_internal else "external_only",
            retrieval_mode=self.retrieval_mode, timing=ResearchTiming(retrieval_seconds=0, reasoning_seconds=0,
                                                           elapsed_seconds=0), validation={},
        )


class _V8ToolPlanner(GoalToolPlanner):
    """Repair an ID-category error without relaxing any fact or formula check."""

    async def decide(self, request: GoalResearchRequest, criteria: list[GoalCriterion],
                     evidence: list[dict[str, Any]], previous_coverage: float | None,
                     prior_evaluations: list[Any] | None = None) -> Any:
        result = await super().decide(request, criteria, evidence, previous_coverage, prior_evaluations)
        if (not result.tool_needed and request.allow_python_execution and request.python_execution_approved):
            user_ids = [str(item["evidence_id"]) for item in evidence
                        if item.get("source_type") == "user_fact" and "name" in item]
            intent = parse_request_ir(request, criteria) if user_ids else None
            if (intent and not validate_ir(intent) and not intent.specialist_relation_required
                    and intent.requested_operation_types and
                    len(user_ids) >= (1 if intent.requested_operation_types == ["result"] else 2)):
                # The existing generic contract/code path is deterministic; an
                # LLM "no tool" answer cannot veto explicit user-only arithmetic.
                return ToolDecision(tool_needed=True, tool_type="python_calculation",
                                    reason="Explicit arithmetic over supplied user facts",
                                    decision_status="selected", plan_status="generic_fast_path",
                                    selected_user_fact_ids=user_ids, selected_fact_ids=user_ids)
        if (not result.tool_needed and asks_for_api_gravity_calculation(request)
                and request.allow_python_execution and request.python_execution_approved):
            # A phrasing-sensitive LLM "none" must not veto an explicit calculation
            # when both canonical inputs and a parsed source formula are present.
            sg_facts = [item for item in evidence if item.get("source_type") == "user_fact"
                        and str(item.get("name", "")).casefold() == "sg"]
            formula = select_formula_candidate(evidence, f"{request.goal} {request.topic}", ["SG"])
            if len(sg_facts) == 1 and formula:
                selection = AnalysisPlanSelection(
                    purpose=request.goal or request.topic,
                    target_criteria=[item.description for item in criteria if item.required],
                    fact_refs=[str(sg_facts[0]["evidence_id"])], formula_ref=formula.formula_id,
                    operation_hint=None, expected_outputs=["API_gravity"], create_chart=False,
                )
                try:
                    plan = materialize_analysis_plan_v4(
                        selection, evidence, EvidenceFactRegistry.from_evidence(evidence),
                        FormulaSourceRegistry.from_evidence(evidence), allow_unbound=True)
                except ValueError:
                    pass
                else:
                    return ToolDecision(
                        tool_needed=True, tool_type="python_calculation",
                        reason="Explicit calculation with sourced formula and user SG",
                        plan=plan, decision_status="selected", plan_status="materialized",
                        plan_parsed=True, selected_fact_ids=selection.fact_refs,
                        selected_user_fact_ids=selection.fact_refs,
                        selected_formula_id=formula.formula_id,
                    )
        if (result.plan_status != "materialization_failed" or
                result.verification_failures != ["fact_id_unknown"] or
                not result.selected_formula_id or
                result.selected_formula_id not in result.selected_fact_ids or
                not result.plan_summary):
            return result
        facts = EvidenceFactRegistry.from_evidence(evidence)
        formulas = FormulaSourceRegistry.from_evidence(evidence)
        valid_facts = {str(item["evidence_id"]) for item in evidence
                       if item.get("source_type") == "user_fact" and "name" in item}
        valid_facts.update(item.fact_id for item in facts.records)
        retained = [item for item in result.selected_fact_ids if item != result.selected_formula_id]
        if not retained or not set(retained) <= valid_facts:
            return result
        summary = result.plan_summary
        selection = AnalysisPlanSelection(
            purpose=summary["purpose"], target_criteria=summary["target_criteria"],
            fact_refs=retained, formula_ref=result.selected_formula_id,
            operation_hint=summary["operation_hint"], expected_outputs=summary["expected_outputs"],
            create_chart=result.tool_type == "python_plot",
        )
        try:
            result.plan = materialize_analysis_plan_v4(selection, evidence, facts, formulas,
                                                       allow_unbound=True)
        except ValueError:
            return result
        result.selected_fact_ids = retained
        result.plan_summary["fact_refs"] = retained
        result.plan_status = "materialized"
        result.fact_materialization_status = "materialized"
        result.formula_materialization_status = "materialized"
        result.verification_failures = []
        result.verification_failures_structured = []
        return result


class GoalExecutionAgent(GoalResearchAgent):
    """One action per iteration; v7 remains available as the legacy execution mode."""

    def __init__(self, research_agent: Any, ollama: Any, *, action_planner: GoalActionPlanner | None = None,
                 **kwargs: Any):
        super().__init__(research_agent, ollama, **kwargs)
        self.action_planner = action_planner or GoalActionPlanner()
        if "tool_planner" not in kwargs:
            self.tool_planner = _V8ToolPlanner(ollama)

    @staticmethod
    def _add_time(result: GoalResearchResponse, stage: str, seconds: float) -> None:
        result.timing[stage] = round(result.timing.get(stage, 0.0) + seconds, 6)

    @staticmethod
    def _explicit_numeric_criteria(request: GoalResearchRequest,
                                   users: UserFactRegistry,
                                   simulation_spec: SimulationSpec | None) -> list[GoalCriterion]:
        """Extract only requested machine-checkable outputs, never extra hypotheses."""
        goal = request.goal or request.topic
        descriptions = []
        if asks_for_api_gravity_calculation(request):
            descriptions = (["교재의 비중-API도 변환 관계식을 근거와 함께 제시", "제공된 비중으로 API도를 계산하고 검증된 결과를 제시"]
                            if prefers_korean(request) else
                             ["Cite the source-backed specific gravity to API gravity equation",
                             "Calculate API gravity from the supplied specific gravity with a validated result"])
        elif (users.records and user_equation(f"{request.topic} {request.goal or ''}") and
              formula_origin(f"{request.topic} {request.goal or ''}") != FormulaOrigin.KB_REFERENCED):
            descriptions = (["제공된 값과 사용자 식으로 계산", "검증된 결과와 출처를 답변에 제시"]
                            if prefers_korean(request) else
                            ["Calculate from the supplied values and user equation",
                             "Present the validated result with provenance"])
        elif simulation_spec:
            descriptions.append("Report all simulated cases from the validated parameter sweep")
            for word, phrase in ((r"\bbest\b|\bmaxim|최적|최대|최댓", "Identify the best case"),
                                 (r"\bmean\b|\baverage\b|평균", "Report the mean simulated result"),
                                 (r"\brange\b|\bsensitiv|범위|민감도", "Report the sensitivity range")):
                if re.search(word, goal, re.I):
                    descriptions.append(phrase)
        elif users.records and re.search(r"공식|수식|관계식|\b(?:formula|equation|correlation)\b", goal, re.I) and re.search(
                r"계산|구해|\b(?:calculat\w*|comput\w*)\b", goal, re.I):
            descriptions.append("출처 있는 관계식과 제공된 입력으로 검증된 계산 결과를 제시" if prefers_korean(request)
                                else "Provide a validated result from a sourced equation and supplied inputs")
        elif re.search(r"중앙값|표준편차|분산|보간|사다리꼴|기하\s*평균|가중\s*평균|경과\s*시간|비례\s*(?:배분|할당)|구간별\s*(?:비용|요금)|"
                       r"단위\s*변환|시간당|원기둥\s*부피|전력|에너지|농도|차분|압력\s*변화율|감소율|순\s*변화|"
                       r"\b(?:median|deviation|variance|interpolat\w*|trapezoid|geometric\s+mean|weighted\s+average|elapsed\s+time|allocation|piecewise|convert|conversion|cylinder|energy|concentration|finite\s+difference|regression\s+slope|percent\s+decrease)\b", goal, re.I):
            requested = parse_request_ir(request, []).requested_operation_types
            descriptions.append(("제공된 값으로 요청한 " + ", ".join(requested) + " 계산을 검증하여 제시")
                                if prefers_korean(request) else
                                ("Compute and validate the requested " + ", ".join(requested) + " outputs"))
        elif users.records and re.search(r"\b(?:calculat|comput|determine|find|mean|average|sum|ratio|difference)\w*\b|계산|구해|구하|평균|합계|총합|비율|차이", goal, re.I):
            if re.search(r"\bmean\b|\baverage\b|평균", goal, re.I):
                descriptions.append("제공된 입력의 평균을 계산하여 제시" if prefers_korean(request)
                                    else "Calculate the requested mean from the supplied inputs")
            if re.search(r"\bsum\b|\btotal\b|합계|총합", goal, re.I):
                descriptions.append("제공된 입력의 합계를 계산하여 제시" if prefers_korean(request)
                                    else "Calculate the requested sum from the supplied inputs")
            if re.search(r"\bratio\b|비율", goal, re.I):
                descriptions.append("제공된 입력의 비율을 계산하여 제시" if prefers_korean(request)
                                    else "Calculate the requested ratio from the supplied inputs")
            if re.search(r"\bdifference\b|차이", goal, re.I):
                descriptions.append("제공된 입력의 차이를 계산하여 제시" if prefers_korean(request)
                                    else "Calculate the requested difference from the supplied inputs")
            if re.search(r"\b(?:rank|top|best|highest)\b|순위|최고|최적|가장\s*높", goal, re.I):
                descriptions.append("제공된 입력의 순위와 가장 높은 항목을 제시" if prefers_korean(request)
                                    else "Identify the requested ranking or top case from the supplied inputs")
            if not descriptions:
                requested = parse_request_ir(request, []).requested_operation_types
                if requested:
                    descriptions.append(("제공된 값으로 요청한 " + ", ".join(requested) + " 계산을 검증하여 제시")
                                        if prefers_korean(request) else
                                        ("Compute and validate the requested " + ", ".join(requested) + " outputs"))
        elif request.deliverables:
            descriptions.append("요청한 주제의 조사 결과를 확인 가능한 근거와 함께 제시" if prefers_korean(request)
                                else "Present the requested research with identifiable evidence")
        elif (not request.deliverables and re.search(r"설명해|\b(?:explain|describe)\b", goal, re.I)
              and not re.search(r"계산|시뮬레이션|\b(?:calculat\w*|simulat\w*)\b", goal, re.I)):
            descriptions.append("요청한 관계를 확인 가능한 근거와 함께 설명" if prefers_korean(request)
                                else "Explain the requested relationship with identifiable evidence")
        return [GoalCriterion(criterion_id=f"C{index}", description=description)
                for index, description in enumerate(descriptions, 1)]

    @staticmethod
    def _premise_criteria(request: GoalResearchRequest) -> list[GoalCriterion]:
        question = f"{request.topic}\n{request.goal or ''}"
        if not EngineeringValidator().detect_false_premises(question):
            return []
        descriptions = (["질문의 잘못된 전제를 명시적으로 반박", "올바른 공학적 관계를 설명",
                         "교정된 관계를 뒷받침하는 내부 근거를 인용"] if prefers_korean(request) else
                        ["Explicitly reject the false premise", "State the corrected engineering relation",
                         "Cite evidence supporting the correction"])
        return [GoalCriterion(criterion_id=f"C{index}", description=value)
                for index, value in enumerate(descriptions, 1)]

    @staticmethod
    def _validated_premise_criteria(evaluation: Any, criteria: list[GoalCriterion],
                                    request: GoalResearchRequest, answer: str,
                                    evidence: list[dict[str, Any]]) -> Any:
        query = f"{request.topic}\n{request.goal or ''}"
        validator = EngineeringValidator()
        detected, corrected, _ = validator.false_premise_correction(query, answer)
        cited = "\n".join(line for line in answer.splitlines()
                          if re.search(r"\[(?:KB|WEB|FIG)\d+\]", line))
        _, supported, _ = validator.false_premise_correction(query, "The premise is incorrect. " + cited)
        if not (detected and corrected and supported and evaluation.engineering_validation_passed):
            return evaluation
        source_ids = set(re.findall(r"\[((?:KB|WEB|FIG)\d+)\]", cited))
        sources = {str(item["evidence_id"]): str(item.get("text") or "") for item in evidence
                   if item.get("source_type") in {"knowledge_base", "web", "figure"}}
        if not source_ids <= sources.keys() or not source_ids:
            return evaluation
        for line in cited.splitlines():
            ids = re.findall(r"\[((?:KB|WEB|FIG)\d+)\]", line)
            if not validator.validate_claim(line, "\n".join(sources[value] for value in ids),
                                            query=query).passed:
                return evaluation
        reason = ("잘못된 전제를 바로잡고 실제 근거를 인용했습니다." if prefers_korean(request)
                  else "The false premise was corrected with cited evidence.")
        updates = [CriterionEvaluation(criterion_id=item.criterion_id, status=CriterionStatus.MET,
                                       reason=reason, supporting_evidence=sorted(source_ids))
                   for item in criteria]
        return replace(evaluation, criteria=updates, coverage=1.0, achieved=True, gaps=[])

    @staticmethod
    def _simulation_spec(request: GoalResearchRequest) -> SimulationSpec | None:
        if request.simulation_spec:
            return SimulationSpec.model_validate(request.simulation_spec)
        text = "\n".join(filter(None, (request.topic, request.goal)))
        return parse_user_simulation_spec(text)

    @staticmethod
    def _record_stop(result: GoalResearchResponse, state: GoalExecutionState,
                     reason: str) -> None:
        result.current_action = GoalActionType.STOP.value
        result.current_stage = GoalActionType.STOP.value
        record = ActionRecord(iteration=state.iteration, action_id=f"ACT-STOP-{state.iteration}",
                              action_type=GoalActionType.STOP, target_criteria=[],
                              status="completed", reason_code=reason,
                              started_at=datetime.now(timezone.utc),
                              finished_at=datetime.now(timezone.utc),
                              coverage_before=state.current_coverage,
                              coverage_after=state.current_coverage)
        state.completed_actions.append(record)
        result.action_history.append(record.model_dump(mode="json"))
        result.state_history.append(state.snapshot())

    @staticmethod
    def _safe_unavailable_answer(candidate: str, state: GoalExecutionState,
                                 reason: str = "", formula: Any = None,
                                 korean: bool = False) -> str:
        if reason == "missing_validated_formula":
            return ("요청한 계산을 뒷받침할 출처 있는 관계식과 검증된 계산 결과를 함께 확보하지 못했습니다. 값을 추측하지 않습니다."
                    if korean else "A sourced equation and validated calculation result were not both available. No value was guessed.")
        if reason == "premise_insufficient":
            return ("검색된 근거만으로 질문의 전제를 확인하거나 교정할 수 없습니다." if korean else
                    "The retrieved evidence does not establish whether the premise is correct.")
        if reason == "knowledge_insufficient":
            return ("검색된 자료에서 답변을 뒷받침할 직접 근거를 확인하지 못했습니다." if korean else
                    "The retrieved sources did not directly support an answer.")
        if reason.startswith("direct_") and not state.computation_ids:
            if state.unresolved_information:
                return clarification_question(state.unresolved_information, korean)
            target = re.search(r"\b(?:calculate|determine|find|compute)\s+(?:the\s+)?([A-Za-z][A-Za-z_ ]{1,45}?)(?=[.,;?]|$)", state.goal, re.I)
            if target:
                name = target.group(1).strip()
                return (f"{name} 계산에 필요한 관계식과 해당 변수의 측정값·단위를 알려주세요. 값을 추측하지 않습니다."
                        if korean else f"Please provide the equation for {name} and measured values and units for its variables. No value was guessed.")
            return ("제공된 값의 계산 조건을 확인하지 못해 결과를 추정하지 않았습니다. 누락된 값, 단위 또는 연산을 확인해 주세요."
                    if korean else "The supplied values did not establish a complete calculation. "
                                   "Please check the missing input, unit, or operation; no result was guessed.")
        if candidate.strip():
            return candidate
        if reason in {"calculation_permission_required", "simulation_permission_required"}:
            source = ((f"검색 근거의 관계식: {formula.raw_span} [{formula.source_id}]. " if korean else
                       f"The retrieved source states {formula.raw_span} [{formula.source_id}]. ")
                      if formula else "")
            return source + ("Python 실행 승인이 없어 수치 계산을 수행하지 않았습니다." if korean else
                             "No numerical calculation was run because Python execution was not approved.")
        if reason == "simulation_spec_missing":
            return ("계산할 결과의 정의와 모델 식이 없어 시뮬레이션을 실행하지 않았습니다. 결과 변수와 관계식을 알려주세요."
                    if korean else "No result definition or model equation was supplied, so the simulation was not run.")
        if state.computation_ids:
            return ("검증된 결과만으로 필요한 결론을 모두 확인하지 못했습니다." if korean else
                    "The available validated results did not establish every required conclusion.")
        return ("근거 자료에서 필요한 관계식이나 입력값을 확인하지 못해 수치 결과를 계산하거나 추정하지 않았습니다."
                if korean else "The available sources did not establish the required equation or inputs. "
                               "No numerical result was calculated or inferred.")

    @staticmethod
    def _evidence(accumulator: EvidenceAccumulator, users: UserFactRegistry,
                  computations: list[Any], simulation_spec: SimulationSpec | None,
                  simulation_source_id: str, user_equation: str | None = None) -> list[dict[str, Any]]:
        evidence = accumulator.records() + users.evidence()
        if simulation_spec or user_equation:
            evidence.append({"evidence_id": simulation_source_id, "source_type": "user_fact",
                             "locator": "request.goal",
                             "text": (f"{simulation_spec.output_name}={simulation_spec.expression}\n"
                                      + (simulation_spec.source_equation or "") + "\n"
                                      + simulation_spec.model_dump_json()) if simulation_spec else user_equation})
        for computation in computations:
            if not computation.validation_passed:
                continue
            evidence.append({
                "evidence_id": computation.computation_id, "source_type": "calculation",
                "locator": computation.analysis_id,
                "text": computation.summary + " Validated outputs: " +
                        json.dumps({key: {"name": value.get("name"), "value": value.get("value"),
                                          "unit": value.get("unit")}
                                    for key, value in computation.output_manifest.items()}, ensure_ascii=False),
                "source_evidence_ids": computation.source_evidence_ids,
                "source_input_ids": computation.source_input_ids,
                "formula_evidence_ids": computation.formula_evidence_ids,
                "output_files": computation.output_files,
                "output_manifest": computation.output_manifest,
            })
        return evidence

    @staticmethod
    def _derived(computation: Any) -> list[DerivedFact]:
        if not computation.validation_passed:
            return []
        parents = list(dict.fromkeys(computation.source_evidence_ids + computation.source_input_ids +
                                     computation.formula_evidence_ids))
        return [DerivedFact(fact_id=f"{computation.computation_id}:{output_id}",
                            parent_calc_id=computation.computation_id, output_id=output_id,
                            name=str(row.get("name") or output_id), value=float(row["value"]),
                            unit=row.get("unit"), underlying_provenance_ids=parents)
                for output_id, row in computation.output_manifest.items()
                if isinstance(row.get("value"), (int, float))]

    @staticmethod
    def _provenance_complete(computation: Any, evidence: list[dict[str, Any]],
                             request_text: str) -> bool:
        """Validate the full recorded chain before admitting a CALC into the run."""
        if not (computation.validation_passed and computation.contract_validation_passed
                and (computation.formula or computation.formula_source_ids == ["USER_REQUEST"])
                and computation.normalized_formula
                and computation.execution_hash and re.fullmatch(r"[0-9a-f]{64}", computation.execution_hash)
                and computation.formula_source_ids and computation.input_fact_ids
                and computation.bound_variables and computation.output_manifest
                and computation.output == {key: row.get("value") for key, row in computation.output_manifest.items()}):
            return False
        successful_code = next((row.get("code") for row in reversed(computation.attempt_records)
                                if row.get("validation_passed") and isinstance(row.get("code"), str)), None)
        if successful_code is None or hashlib.sha256(successful_code.encode("utf-8")).hexdigest() != computation.execution_hash:
            return False
        sources = {str(row.get("evidence_id")): row for row in evidence}
        if any(value not in sources for value in computation.input_fact_ids):
            return False
        if any(value not in computation.input_fact_ids for value in computation.bound_variables.values()):
            return False
        for fact in computation.input_facts:
            source = sources.get(str(fact.get("evidence_id")), {})
            if source.get("source_type") == "user_fact" and "value" in source:
                if fact.get("value") != source["value"] or str(fact.get("unit") or "") != str(source.get("unit") or ""):
                    return False
        if computation.formula_source_ids == ["USER_REQUEST"]:
            return bool(re.search(r"평균|합계|비율|차이|순위|최대|최소|범위|중앙값|표준편차|분산|기하\s*평균|가중\s*평균|"
                                  r"경과\s*시간|퍼센트|보간|사다리꼴|배분|할당|구간별|속도|"
                                  r"단위\s*변환|시간당|원기둥|원통|에너지|농도|차분|기울기|감소율|순\s*변화|"
                                  r"mean|average|sum|ratio|difference|rank|max|min|range|median|deviation|variance|"
                                  r"elapsed|percent|add|multiply|interpolat|trapezoid|allocation|weighted|combined|piecewise|"
                                  r"convert|conversion|cylinder|energy|concentration|slope|derivative",
                                  request_text, re.I))
        if any(source_id not in sources for source_id in computation.formula_source_ids):
            return False
        records = FormulaSourceRegistry.from_evidence(evidence).records
        return all((bool(equation_ast(computation.source_formula or "")) and
                    normalize_formula(computation.source_formula or "") in
                    normalize_formula(str(sources[source_id].get("text") or "")))
                   if sources[source_id].get("source_type") == "user_fact" else
                   any(record.source_id == source_id and
                       source_contains_equation(record, str(sources[source_id].get("text") or ""),
                                                computation.source_formula or computation.formula)
                       for record in records)
                   for source_id in computation.formula_source_ids)

    @staticmethod
    def _filter_numeric_claims(answer: str, evidence: list[dict[str, Any]],
                               computations: list[Any]) -> tuple[str, int]:
        """No final number survives without its cited literal source or validated output."""
        by_id = {str(row["evidence_id"]): row for row in evidence}
        calcs = {row.computation_id: row for row in computations if row.validation_passed}
        kept, removed = [], 0
        for line in answer.splitlines():
            citations = re.findall(r"\[((?:KB|WEB|FIG|USERF|CALC)\d+)\]", line)
            plain = re.sub(r"\[(?:KB|WEB|FIG|USERF|CALC)\d+\]", "", line)
            matches = list(NUMERIC.finditer(plain))
            if not matches:
                kept.append(line)
                continue
            literal_sources = "\n".join(str(by_id[value].get("text") or "") for value in citations
                                        if value in by_id and by_id[value].get("source_type") != "calculation")
            source_values = [match.group() for match in NUMERIC.finditer(literal_sources)]
            calc_values = [float(row["value"]) for value in citations if value in calcs
                           for row in calcs[value].output_manifest.values()
                           if isinstance(row.get("value"), (int, float)) and not isinstance(row.get("value"), bool)]
            if all(any(match.group().replace(",", "") == value.replace(",", "") for value in source_values)
                   or any(_matches_reported_value(match, value) for value in calc_values)
                   for match in matches):
                kept.append(line)
            else:
                removed += 1
        return "\n".join(kept).strip(), removed

    @staticmethod
    def _api_gravity_answer(request: GoalResearchRequest, computations: list[Any],
                            evidence: list[dict[str, Any]]) -> str | None:
        if not asks_for_api_gravity_calculation(request):
            return None
        source_ids = {str(item["evidence_id"]) for item in evidence
                      if item.get("source_type") in {"knowledge_base", "figure", "web"}}
        sourced_spans = {(item.source_id, item.normalized_span)
                         for item in FormulaSourceRegistry.from_evidence(evidence).records}
        for calc in computations:
            if not calc.validation_passed or not calc.formula or not set(calc.formula_evidence_ids) & source_ids:
                continue
            if not any((source_id, normalize_formula(calc.formula)) in sourced_spans
                       for source_id in calc.formula_evidence_ids):
                continue
            for output_id, output in calc.output_manifest.items():
                if "api" not in str(output.get("name", "")).casefold() or "gravity" not in str(output.get("name", "")).casefold():
                    continue
                parents = list(dict.fromkeys([calc.computation_id, *calc.source_input_ids,
                                               *calc.formula_evidence_ids]))
                value = f"{float(output['value']):.2f} °API"
                claim = f"검증된 API도 {value}" if prefers_korean(request) else f"Validated API gravity {value}"
                issues, _ = validate_calc_claim(claim, parents, [f"{calc.computation_id}:{output_id}"],
                                                {calc.computation_id: calc}, evidence)
                if issues:
                    continue
                answer = claim + " " + " ".join(f"[{item}]" for item in parents)
                formula_text = re.sub(r"\s+", "", calc.formula).casefold()
                matching_source = next((str(item["evidence_id"]) for item in evidence
                                        if item.get("source_type") in {"knowledge_base", "figure", "web"}
                                        and formula_text in re.sub(r"\s+", "", str(item.get("text") or "")).casefold()), None)
                if matching_source:
                    relation = (f"근거 자료의 비중–API도 관계식: {calc.formula} [{matching_source}]"
                                if prefers_korean(request) else
                                f"Source-backed SG–API gravity equation: {calc.formula} [{matching_source}]")
                    answer = relation + "\n\n" + answer
                return answer
        return None

    @staticmethod
    def _simple_user_fact_answer(request: GoalResearchRequest, computations: list[Any],
                                 evidence: list[dict[str, Any]]) -> str | None:
        """Render only validated mean/ranking outputs from the supplied user values."""
        goal = request.goal or request.topic
        if request.expected_result or not re.search(r"\b(?:mean|average|rank|top|highest)\b|평균|순위|가장\s*높", goal, re.I):
            return None
        for calc in computations:
            if (not calc.validation_passed or not calc.source_input_ids or calc.source_evidence_ids
                    or calc.formula_evidence_ids):
                continue
            rows = calc.output_manifest
            if not rows or any(str(row.get("name", "")).casefold() not in {"mean", "ranking"}
                               for row in rows.values()):
                continue
            citations = list(dict.fromkeys([calc.computation_id, *calc.source_input_ids]))
            lines = []
            for output_id, row in rows.items():
                name = str(row.get("name", "")).casefold()
                value = row.get("value")
                if name == "mean" and isinstance(value, (int, float)):
                    claim = f"{'평균 mean' if prefers_korean(request) else 'Mean'}: {value} {row.get('unit') or ''}".strip()
                elif name == "ranking" and isinstance(value, list) and value and all(
                        isinstance(item, str) for item in value):
                    order = " > ".join(value)
                    claim = (f"순위 ranking: {order}; 최고 top: {value[0]}" if prefers_korean(request)
                             else f"Ranking: {order}; top: {value[0]}")
                else:
                    break
                issues, _ = validate_calc_claim(claim, citations, [output_id],
                                                {calc.computation_id: calc}, evidence)
                if issues:
                    break
                lines.append(claim + " " + " ".join(f"[{source}]" for source in citations))
            else:
                return "\n\n".join(lines)
        return None

    @staticmethod
    def _user_formula_answer(request: GoalResearchRequest, computations: list[Any],
                             evidence: list[dict[str, Any]]) -> str | None:
        for calc in computations:
            if not (calc.validation_passed and calc.analysis_id.startswith("USER-FORMULA-")
                    and "OUT_RESULT" in calc.output_manifest):
                continue
            row = calc.output_manifest["OUT_RESULT"]
            citations = [calc.computation_id, *calc.input_fact_ids, *calc.formula_source_ids]
            claim = f"{row['name']} = {row['value']}"
            if validate_calc_claim(claim, citations, ["OUT_RESULT"],
                                   {calc.computation_id: calc}, evidence)[0]:
                continue
            prefix = "검증된 계산 결과: " if prefers_korean(request) else "Validated result: "
            return prefix + claim + " " + " ".join(f"[{value}]" for value in citations)
        return None

    @staticmethod
    def _validated_calculation_answer(request: GoalResearchRequest, computations: list[Any],
                                      evidence: list[dict[str, Any]]) -> str | None:
        lines = []
        for calc in computations:
            if not calc.validation_passed or calc.analysis_id.startswith("SIM-"):
                continue
            citations = list(dict.fromkeys([calc.computation_id, *calc.source_input_ids,
                                             *calc.source_evidence_ids, *calc.formula_evidence_ids,
                                             *[value for value in calc.formula_source_ids
                                               if value != "USER_REQUEST"]]))
            for output_id in calc.required_output_ids or list(calc.output_manifest):
                row = calc.output_manifest.get(output_id)
                if not row:
                    continue
                value = row.get("value")
                if not isinstance(value, (int, float, str, list)) or isinstance(value, bool):
                    continue
                name = str(row.get("name") or output_id)
                if prefers_korean(request):
                    name = {"ratio": "비율 ratio", "difference": "차이 difference",
                            "sum": "합계 sum", "maximum": "최댓값 maximum",
                            "minimum": "최솟값 minimum", "range": "범위 range"}.get(name, name)
                printed = " > ".join(map(str, value)) if isinstance(value, list) else str(value)
                claim = f"{name}: {printed} {row.get('unit') or ''}".strip()
                if validate_calc_claim(claim, citations, [output_id],
                                       {calc.computation_id: calc}, evidence)[0]:
                    continue
                lines.append(claim + " " + " ".join(f"[{value}]" for value in citations))
        if not lines:
            return None
        return "\n".join(lines)

    @staticmethod
    def _extractive_source_answer(request: GoalResearchRequest,
                                  evidence: list[dict[str, Any]]) -> str | None:
        """Require complete literal relation coverage, not merely related source terms."""
        from app.services.source_answerability import literal_answer
        return literal_answer(request, evidence, allow_partial=True)

    @staticmethod
    def _answerability_gate(request, criteria, evidence, result, *, attempt=True):
        """Recheck literal spans, not a rejected candidate's verdict, before discarding support."""
        support = evaluate_claim_support(request, evidence, criteria)
        result.telemetry.update(support.telemetry())
        if not attempt:
            return None, support
        result.telemetry["extractive_fallback_attempted"] = True
        if result.telemetry.get("source_conflict_count", 0):
            result.telemetry["extractive_fallback_failure_reason"] = "retrieved_evidence_conflict"
            return None, support
        validator = EngineeringValidator()
        for claim in support.claims:
            valid = []
            for sid, span in zip(claim.supporting_evidence_ids, claim.supporting_spans):
                row = next((r for r in evidence if r.get("evidence_id") == sid), {})
                text = re.sub(r"\s+", " ", str(row.get("text") or ""))
                if (span in text and validator.validate_claim(span, text, query=request.topic).passed):
                    valid.append((sid, span))
            claim.supporting_evidence_ids = [sid for sid, _ in valid]
            claim.supporting_spans = [span for _, span in valid]
            if not valid:
                claim.support_status = SupportStatus.UNSUPPORTED
        answer = grounded_answer(request, support)
        if answer:
            detected, corrected, _ = validator.false_premise_correction(request.topic, answer)
            if detected and not corrected:
                answer = None
        result.telemetry.update(support.telemetry())
        result.telemetry["extractive_fallback_failure_reason"] = None if answer else "no_verified_relation_span"
        if answer:
            result.telemetry.update({"extractive_fallback_used": True,
                "final_answer_kind": "partial_grounded" if not support.all_required_supported else
                    "underdetermined" if support.underdetermined else "extractive_grounded"})
        return answer, support

    @staticmethod
    def _support_evaluation(criteria, support, korean):
        ids = list(dict.fromkeys(sid for c in support.claims for sid in c.supporting_evidence_ids))
        reason = ("관련 원문 관계와 인용 연결을 검증했습니다." if korean else
                  "The literal relation spans and citation links were verified.")
        return [CriterionEvaluation(criterion_id=c.criterion_id,
                    status=CriterionStatus.MET if support.all_required_supported else CriterionStatus.PARTIAL,
                    reason=reason, supporting_evidence=ids) for c in criteria]

    async def _pre_stop_answer(self, request, intent, criteria, accumulator, result, state, started):
        if intent.kind not in {GoalIntentKind.KNOWLEDGE_QA, GoalIntentKind.FIGURE_QA, GoalIntentKind.PREMISE_CHECK}:
            return None
        if intent.kind == GoalIntentKind.PREMISE_CHECK:
            # Never substitute a topical quote for an explicit premise assessment.
            result.telemetry["claim_support_checked"] = True
            result.telemetry["extractive_fallback_attempted"] = True
            if state.verified or result.telemetry.get("source_conflict_count", 0):
                result.telemetry["extractive_fallback_failure_reason"] = "premise_requires_verified_correction"
                return None
            premise = await assess_premise(self.ollama, request, accumulator.records())
            if premise.verdict not in {"supports", "contradicts"} or not premise.answer:
                result.telemetry["extractive_fallback_failure_reason"] = premise.failure_reason or "premise_not_supported"
                return None
            support = ClaimSupport([RequiredClaim("CLAIM1", request.topic, True, SupportStatus.SUPPORTED,
                list(premise.supporting_source_ids), list(premise.supporting_spans))])
            answer = premise.answer
            result.telemetry.update(support.telemetry())
            result.telemetry.update({"extractive_fallback_used": True, "extractive_fallback_failure_reason": None,
                                     "final_answer_kind": "extractive_grounded"})
        else:
            answer, support = self._answerability_gate(request, criteria, accumulator.records(), result)
        if not answer:
            return None
        achieved = support.all_required_supported
        result.criteria = self._support_evaluation(criteria, support, prefers_korean(request))
        result.goal_coverage = sum(c.support_status == SupportStatus.SUPPORTED for c in support.claims) / max(1, len(support.claims))
        result.goal_coverage_percent = round(result.goal_coverage * 100, 2)
        state.goal_achieved = achieved
        state.current_coverage = result.goal_coverage
        state.verified = True
        for criterion, evaluation in zip(state.criteria, result.criteria):
            criterion.status = evaluation.status
            criterion.support_ids = evaluation.supporting_evidence
        result.internal_sources, result.web_sources, result.figures = accumulator.internal, accumulator.web, accumulator.figures
        result.validation.update({"citation_semantic_passed": True, "engineering_validation_passed": True,
                                  "unsupported_citation_claim_count": 0, "unsupported_numeric_claim_count": 0})
        self._record_stop(result, state, "grounded_answerability" if achieved else "partial_grounded_answer")
        return self._finish(result, GoalRunStatus.COMPLETED if achieved else GoalRunStatus.STOPPED,
                            GoalStatus.ACHIEVED if achieved else GoalStatus.STOPPED,
                            GoalStopReason.GOAL_ACHIEVED if achieved else GoalStopReason.INSUFFICIENT_EVIDENCE,
                            answer, started)

    @staticmethod
    def _finish(result, run_status, status, stop_reason, answer, started):
        telemetry = result.telemetry
        calculated = any(c.validation_passed for c in result.computations)
        kind = telemetry.get("final_answer_kind")
        if kind not in {"partial_grounded", "extractive_grounded", "underdetermined"}:
            kind = "calculation" if calculated else "normal_grounded" if status == GoalStatus.ACHIEVED else "refusal"
        if kind == "refusal" and telemetry.get("intent_route") in {"knowledge_qa", "figure_qa"}:
            missing = [c["description"] for c in telemetry.get("required_claims", [])
                       if c["support_status"] != SupportStatus.SUPPORTED]
            if missing:
                prefix = ("현재 검색된 근거에서 다음 요청을 직접 뒷받침하는 관계를 검증하지 못했습니다: "
                          if re.search(r"[가-힣]", result.topic) else
                          "No direct relation span was verified for these requests in the retrieved evidence: ")
                answer = prefix + "; ".join(missing)
            if telemetry.get("source_conflict_count", 0):
                answer = ("검색된 근거가 충돌하여 단정적인 답변을 보류합니다. 상충하는 출처를 확인해야 합니다."
                          if re.search(r"[가-힣]", result.topic) else
                          "The retrieved evidence conflicts. An unqualified conclusion requires resolving the conflicting sources.")
        telemetry.update({"final_answer_kind": kind, "refusal_generated": kind == "refusal",
                          "refusal_reason": stop_reason.value if kind == "refusal" else None,
                          "calculation_executed": result.python_calls_total > 0,
                          "calculation_validated": calculated})
        return GoalResearchAgent._finish(result, run_status, status, stop_reason, answer, started)

    @staticmethod
    def _simulation_answer(computation: Any, spec: SimulationSpec,
                           evidence: list[dict[str, Any]], source_id: str,
                           korean: bool = False) -> str:
        """Render only externally validated outputs, with explicit parent provenance."""
        manifest = computation.output_manifest
        citations = list(dict.fromkeys([computation.computation_id, source_id,
                                        *computation.source_input_ids, *computation.formula_evidence_ids]))
        citation_text = " ".join(f"[{item}]" for item in citations)
        lines = []
        for key in sorted(value for value in manifest if value.startswith("OUT_CASE_")):
            index = key.rsplit("_", 1)[1]
            parameter_key = f"OUT_PARAMETER_{index}"
            claim = (f"{spec.parameter.name}={manifest[parameter_key]['value']}, "
                     f"{spec.output_name}={manifest[key]['value']}")
            issues, _ = validate_calc_claim(claim, citations, [parameter_key, key],
                                             {computation.computation_id: computation}, evidence)
            if issues:
                raise ValueError("simulation case grounding failed: " + ", ".join(issues))
            lines.append(f"{claim} {citation_text}")
        for label, first, second in (
            ("최적" if korean else "Best", "OUT_BEST_PARAMETER", "OUT_BEST_RESULT"),
            ("최저" if korean else "Worst", "OUT_WORST_PARAMETER", "OUT_WORST_RESULT"),
        ):
            claim = (f"{label} {spec.parameter.name}={manifest[first]['value']}, "
                     f"{spec.output_name}={manifest[second]['value']}")
            issues, _ = validate_calc_claim(claim, citations, [first, second],
                                             {computation.computation_id: computation}, evidence)
            if issues:
                raise ValueError("simulation extrema grounding failed: " + ", ".join(issues))
            lines.append(f"{claim} {citation_text}")
        for label, output_id in ((("평균" if korean else "Mean"), "OUT_MEAN_RESULT"),
                                 (("범위" if korean else "Range"), "OUT_RANGE_RESULT")):
            claim = f"{label} {spec.output_name}={manifest[output_id]['value']}"
            issues, _ = validate_calc_claim(claim, citations, [output_id],
                                             {computation.computation_id: computation}, evidence)
            if issues:
                raise ValueError("simulation aggregate grounding failed: " + ", ".join(issues))
            lines.append(f"{claim} {citation_text}")
        return "\n".join(lines)

    @staticmethod
    def _pause(result: GoalResearchResponse, state: GoalExecutionState,
               accumulator: EvidenceAccumulator, seen_actions: set[str],
               research_validation: dict[str, Any], latest_candidate: str,
               missing: list[str], korean: bool, attempts: int,
               user_replies: list[str], started: float) -> GoalResearchResponse:
        result.run_status = GoalRunStatus.WAITING_FOR_USER_INPUT
        result.status = GoalStatus.PENDING
        result.current_stage = "waiting_for_user_input"
        result.current_action = None
        result.telemetry.update({"final_answer_kind": "clarification", "refusal_generated": False,
                                 "refusal_reason": None})
        result.required_inputs = list(dict.fromkeys(missing))
        result.clarification_question = clarification_question(result.required_inputs, korean)
        result.final_answer = ""
        state.unresolved_information = result.required_inputs.copy()
        result.resume_checkpoint = {
            "state": state.model_dump(mode="json"),
            "seen_actions": sorted(seen_actions),
            "research_validation": research_validation,
            "latest_candidate": latest_candidate,
            "clarification_attempts": attempts,
            "user_replies": user_replies,
        }
        result.internal_sources = accumulator.internal
        result.web_sources = accumulator.web
        result.figures = accumulator.figures
        result.state_history.append(state.snapshot())
        result.timing["elapsed_seconds"] = round(time.perf_counter() - started, 6)
        result.timing["total_seconds"] = result.timing["elapsed_seconds"]
        return result

    @staticmethod
    def _focus_research_answer(candidate: str, criteria: list[GoalCriterion],
                               question: str = "") -> str:
        """Discard tangential cited lines when a research goal has distinct subgoals."""
        if len(criteria) < 2:
            translated = " ".join(english for korean, english in ENGINEERING_TERMS.items()
                                  if korean in question)
            terms = set(re.findall(r"[a-z]{4,}", (question + " " + translated).casefold())) - {
                "what", "which", "does", "this", "that", "explain", "describe", "using",
                "internal", "knowledge", "source", "evidence", "please", "affect",
                "affects", "relationship", "between", "about", "with", "from",
            }
            if len(terms) >= 2 and not re.search(r"\band\b|와|과|및", question, re.I):
                cited = [line.strip() for line in candidate.splitlines()
                         if re.search(r"\[(?:KB|WEB|FIG)\d+\]", line)]
                scores = [len(terms & set(re.findall(r"[a-z]{4,}", line.casefold())))
                          for line in cited]
                if scores and max(scores) >= 2:
                    focused = [line for line, score in zip(cited, scores) if score == max(scores)]
                    return "\n".join(focused[:3])
            return candidate
        words = [set(re.findall(r"[a-z]{4,}", item.description.casefold())) for item in criteria]
        common = set.intersection(*words)
        distinctive = set.union(*words) - common - {
            "source", "supported", "using", "with", "from", "cite", "citations",
            "explain", "compare", "provide", "state", "evidence", "calculate",
        }
        if not distinctive:
            return candidate
        lines = [line.strip() for line in candidate.splitlines() if
                 re.search(r"\[(?:KB|WEB|FIG)\d+\]", line) and
                 set(re.findall(r"[a-z]{4,}", line.casefold())) & distinctive]
        return "\n".join(lines) if lines else candidate

    @staticmethod
    def _deterministic_simulation_criteria(evaluation: Any, criteria: list[GoalCriterion],
                                           candidate: str, computation: Any,
                                           korean: bool = False) -> Any:
        """Prefer exact validated output coverage over stochastic semantic grading."""
        if not computation.validation_passed or not evaluation.engineering_validation_passed:
            return evaluation
        lines = candidate.splitlines()
        case_count = sum(key.startswith("OUT_CASE_") for key in computation.output_manifest)
        cited_case_count = sum(bool(re.match(r"^[A-Za-z_]+=[-+]?\d", line) and
                                    f"[{computation.computation_id}]" in line) for line in lines)
        proof = {"all_cases": cited_case_count == case_count and case_count >= 1,
                 "best": any(line.startswith(("Best ", "최적 ")) for line in lines),
                 "mean": any(line.startswith(("Mean ", "평균 ")) for line in lines),
                 "range": any(line.startswith(("Range ", "범위 ")) for line in lines)}
        supplied = {name.casefold() for name in getattr(computation, "bound_variables", {})}
        updates = []
        by_id = {item.criterion_id: item for item in criteria}
        for item in evaluation.criteria:
            description = by_id[item.criterion_id].description.casefold()
            if re.search(r"\b(?:interpret|explain|causal|why)\b|해석|원인", description):
                updates.append(item)
                continue
            requirements = []
            if re.search(r"\ball\s+(?:simulated\s+)?cases\b|모든\s*경우", description):
                requirements.append("all_cases")
            if re.search(r"\bbest\s+case\b|최적", description):
                requirements.append("best")
            if re.search(r"\bmean\b|평균", description):
                requirements.append("mean")
            if re.search(r"\brange\b|범위", description):
                requirements.append("range")
            missing_input = re.search(r"\b(?:missing|supply|provide)\s+([A-Za-z][A-Za-z0-9_]*)\b|"
                                      r"([A-Za-z][A-Za-z0-9_]*)\s*값(?:이|을)?\s*(?:없|제공)", description)
            if missing_input and (missing_input.group(1) or missing_input.group(2)).casefold() in supplied:
                requirements.append("supplied_input")
                proof["supplied_input"] = True
            if requirements and all(proof[key] for key in requirements):
                updates.append(item.model_copy(update={
                    "status": CriterionStatus.MET,
                    "reason": ("요청한 결과가 검증된 매개변수 계산과 출처가 표시된 답변에 포함되어 있습니다."
                               if korean else
                               "All requested outputs are present in the validated sweep manifest and cited answer."),
                    "supporting_evidence": [computation.computation_id, *computation.source_input_ids],
                }))
            else:
                updates.append(item)
        coverage = GoalEvaluator.coverage(criteria, updates)
        achieved = bool(candidate.strip() and evaluation.engineering_validation_passed and
                        all(item.status == CriterionStatus.MET for item in updates
                            if by_id[item.criterion_id].required))
        return replace(evaluation, criteria=updates, coverage=coverage, achieved=achieved,
                       gaps=[] if achieved else evaluation.gaps)

    @staticmethod
    def _deterministic_calculation_criteria(evaluation: Any, criteria: list[GoalCriterion],
                                             candidate: str, computations: list[Any],
                                             evidence: list[dict[str, Any]],
                                             source_requirement: SourceRequirement,
                                             korean: bool = False) -> Any:
        """Operational criteria follow validated current state, not a stale LLM grade."""
        if not candidate.strip() or not evaluation.engineering_validation_passed:
            return evaluation
        valid = [row for row in computations if row.validation_passed and row.contract_validation_passed]
        if not valid:
            return replace(evaluation, achieved=False, gaps=[*evaluation.gaps, "Validated calculation required"])
        cited = set(re.findall(r"\[((?:CALC|USERF|KB|FIG|WEB)\d+)\]", candidate))
        sources = {str(row.get("evidence_id")) for row in evidence}
        proven = []
        for calc in valid:
            if calc.computation_id not in cited or not GoalExecutionAgent._provenance_complete(
                    calc, evidence, getattr(calc, "purpose", "") + " " + " ".join(item.description for item in criteria)):
                continue
            if source_requirement == SourceRequirement.KB_FORMULA and not (
                    calc.formula_source_ids and all(value in sources and value.startswith(("KB", "FIG", "WEB"))
                                                    for value in calc.formula_source_ids)):
                continue
            if source_requirement == SourceRequirement.USER_FORMULA and not all(
                    value.startswith("USERF") for value in calc.formula_source_ids):
                continue
            outputs = [row for row in calc.output_manifest.values() if row.get("required", True)]
            if not outputs or any(
                    isinstance(row.get("value"), (int, float)) and not any(
                        _matches_reported_value(match, float(row["value"]))
                        for match in NUMERIC.finditer(candidate)) for row in outputs):
                continue
            if any(row.get("unit") and str(row["unit"]) not in candidate for row in outputs):
                continue
            proven.append(calc)
        if not proven:
            return replace(evaluation, achieved=False, gaps=[*evaluation.gaps, "Calculation result, unit or provenance not adopted"])
        by_id = {item.criterion_id: item for item in criteria}
        updates = []
        for item in evaluation.criteria:
            description = by_id[item.criterion_id].description
            requested_units = set(re.findall(
                r"(?<![A-Za-z0-9/])(?:psi|psia|psig|kPa|stb/d|bbl/d|m3/d|kg/m3|"
                r"kWh|kW|m3|ft3|bbl|stb)(?![A-Za-z0-9/])", description, re.I))
            if requested_units and not all(any(
                    str(row.get("unit") or "").casefold() == unit.casefold()
                    for calc in proven for row in calc.output_manifest.values())
                    for unit in requested_units):
                updates.append(item)
                continue
            if re.search(r"\b(?:explain|interpret|why|causal|discuss)\b|설명|해석|원인", description, re.I):
                updates.append(item)
                continue
            if re.search(r"\b(?:calculat|comput|validat|result|output|formula|equation|input|unit|provenance|"
                         r"values|supplied|provided|"
                         r"mean|average|sum|ratio|difference|rank|conversion|slope|energy|concentration)\w*\b|"
                         r"계산|검증|결과|공식|관계식|식|입력|제공된\s*값|단위|평균|합계|비율|차이|순위|변환|기울기|에너지|농도", description, re.I):
                parents = list(dict.fromkeys(value for calc in proven for value in
                                             [calc.computation_id, *calc.input_fact_ids, *calc.formula_source_ids]
                                             if value != "USER_REQUEST"))
                updates.append(item.model_copy(update={"status": CriterionStatus.MET,
                    "reason": "현재 입력과 검증된 계산 결과로 조건을 충족했습니다." if korean else
                              "Current inputs and validated calculation satisfy this criterion.",
                    "supporting_evidence": parents}))
            else:
                updates.append(item)
        coverage = GoalEvaluator.coverage(criteria, updates)
        achieved = bool(all(item.status == CriterionStatus.MET for item in updates
                            if by_id[item.criterion_id].required))
        return replace(evaluation, criteria=updates, coverage=coverage,
                       achieved=achieved, gaps=[] if achieved else evaluation.gaps)

    @staticmethod
    def _calculation_failure_stage(reason: str, *, resumed: bool = False) -> str:
        value = reason.casefold()
        if "unit_not_local" in value:
            return "VALUE_UNIT_LOCALITY"
        if "ambiguous" in value and "formula" in value:
            return "FORMULA_AMBIGUITY"
        if "formula" in value or "source_unavailable" in value:
            return "FORMULA_RETRIEVAL"
        if "unit" in value or "dimension" in value:
            return "UNIT_COMPATIBILITY"
        if "binding" in value or "required_input" in value:
            return "VARIABLE_BINDING"
        if "spec_missing" in value or "simulation_input" in value:
            return "RESUME_SPEC_PARSE" if resumed else "CALCULATION_READINESS"
        if "permission" in value or "preflight" in value:
            return "PYTHON_PREFLIGHT"
        if "validation" in value or "provenance" in value:
            return "VALIDATION"
        if "operation" in value or "arithmetic" in value:
            return "OPERATION_IR"
        if "python" in value or "subprocess" in value:
            return "PYTHON_EXECUTION"
        return "CALCULATION_READINESS"

    async def run(
        self, run_id: str, request: GoalResearchRequest, *,
        is_canceled: Callable[[], bool] | None = None,
        on_progress: Callable[[GoalResearchResponse], None] | None = None,
        resume_state: dict[str, Any] | None = None,
        resume_result: GoalResearchResponse | None = None,
    ) -> GoalResearchResponse:
        autonomous_python = request.execution_mode == "autonomous_goal_execution"
        if autonomous_python:
            # Mode grants bounded tool permission; the action planner still decides if it is needed.
            request = request.model_copy(update={
                "allow_python_execution": True,
                "python_execution_approved": True,
            })
        started = time.perf_counter()
        planning_started = time.perf_counter()
        korean = prefers_korean(request)
        user_text = request.topic + "\n" + "\n".join((resume_state or {}).get("user_replies", []))
        users = UserFactRegistry.from_messages([request.topic, *((resume_state or {}).get("user_replies", []))])
        simulation_spec = self._simulation_spec(request) or parse_user_simulation_spec(user_text)
        intent = classify_goal_intent(request, has_user_facts=bool(users.records),
                                      has_simulation_spec=simulation_spec is not None)
        if (intent.kind == GoalIntentKind.KNOWLEDGE_QA and
                ambiguous_premise_candidate(f"{request.topic} {request.goal or ''}")):
            try:
                raw_intent = await self.ollama.chat_structured([
                    {"role": "system", "content": "Classify whether the user asserts a factual premise that needs verification. "
                     "Do not decide if it is true. Return only booleans."},
                    {"role": "user", "content": f"{request.topic}\n{request.goal or ''}"}],
                    {"type": "object", "properties": {"has_factual_premise": {"type": "boolean"},
                     "requires_verification": {"type": "boolean"}},
                     "required": ["has_factual_premise", "requires_verification"]},
                    model=request.model, temperature=0, seed=request.seed)
                decision = json.loads(raw_intent)
                if decision.get("has_factual_premise") is True and decision.get("requires_verification") is True:
                    intent = GoalIntent(GoalIntentKind.PREMISE_CHECK, SourceRequirement.NONE,
                                        reason="ambiguous_assertion_local_classifier")
            except (AttributeError, TypeError, ValueError, RuntimeError):
                pass
        fallback_added = fallback_rejected = 0
        from app.services.user_fact_registry import numeric_lists
        # List completeness is checked against the original text at the deterministic gate.
        # Model extraction cannot repair a missing observation or reinterpret digits in units.
        explicit_list = any(numeric_lists(user_text))
        if intent.kind == GoalIntentKind.DIRECT_CALC and (
                not users.records or len(re.findall(NUMBER, user_text)) > len(users.records) + 1) and not explicit_list:
            try:
                schema = {"type": "object", "properties": {"facts": {"type": "array", "items": {
                    "type": "object", "properties": {"name": {"type": "string"}, "value": {"type": "number"},
                    "unit": {"type": "string"}, "source_quote": {"type": "string"}},
                    "required": ["name", "value", "unit", "source_quote"]}}}, "required": ["facts"]}
                raw = await self.ollama.chat_structured([
                    {"role": "system", "content": "Extract only literal numeric facts from the user's exact text. "
                     "Each source_quote must be an exact substring containing the value and unit. "
                     "Do not infer formulas, missing values or evidence."},
                    {"role": "user", "content": user_text}], schema, model=request.model,
                    temperature=0, seed=request.seed)
                fallback_added, fallback_rejected = users.add_literal_fallback(
                    user_text, json.loads(raw).get("facts", []))
            except (AttributeError, TypeError, ValueError, RuntimeError, json.JSONDecodeError):
                pass
        requires_sourced_formula = intent.source_requirement == SourceRequirement.KB_FORMULA
        simulation_source_id = f"USERF{len(users.records) + 1}"
        if resume_state and resume_result:
            result = resume_result.model_copy(deep=True)
            criteria = [item.model_copy(deep=True) for item in result.frozen_criteria]
            criteria_hash = result.criteria_hash
            state = GoalExecutionState.model_validate(resume_state["state"])
            state.known_facts = list(dict.fromkeys(state.known_facts + [item.fact_id for item in users.records]))
            state.no_progress_count = 0
            accumulator = EvidenceAccumulator.restore(result.internal_sources, result.web_sources, result.figures)
            seen_actions = set(resume_state["seen_actions"])
            latest_candidate = str(resume_state.get("latest_candidate") or "")
            research_validation = dict(resume_state.get("research_validation") or {})
            clarification_attempts = int(resume_state.get("clarification_attempts") or 0)
            premise_criteria = result.criteria_source == "inferred_premise"
            result.run_status = GoalRunStatus.RUNNING
            result.clarification_question = None
            result.required_inputs = []
            result.resume_checkpoint = {}
        else:
            criteria = [item.model_copy(deep=True) for item in request.success_criteria]
            source = "user" if criteria else "inferred"
            premise_criteria = False
            if not criteria:
                criteria = self._premise_criteria(request)
                if criteria:
                    source = "inferred_premise"
                    premise_criteria = True
                elif intent.kind == GoalIntentKind.PREMISE_CHECK:
                    descriptions = (["질문의 전제를 실제 근거와 대조", "근거가 지지하는 관계를 출처와 함께 제시"]
                                    if korean else
                                    ["Assess the premise against actual evidence",
                                     "State the source-supported relation with a citation"])
                    criteria = [GoalCriterion(criterion_id=f"C{index}", description=value)
                                for index, value in enumerate(descriptions, 1)]
                    source = "inferred_premise"
                    premise_criteria = True
                elif intent.kind in {GoalIntentKind.KNOWLEDGE_QA, GoalIntentKind.FIGURE_QA}:
                    # A planner must not turn plausible but unrequested effects into mandatory claims.
                    claims = evaluate_claim_support(request, []).claims
                    criteria = [GoalCriterion(criterion_id=f"C{index}", description=c.description[:1000])
                                for index, c in enumerate(claims[:20], 1)]
                    source = "inferred_from_request"
                else:
                    criteria = (self._explicit_numeric_criteria(request, users, simulation_spec)
                                if intent.kind not in {GoalIntentKind.KNOWLEDGE_QA, GoalIntentKind.FIGURE_QA} else [])
                if not criteria:
                    criteria = await self.planner.infer_criteria(request)
            criteria_hash = self._criteria_hash(criteria)
            result = GoalResearchResponse(
                run_id=run_id, topic=request.topic, goal=request.goal, expected_result=request.expected_result,
                run_status=GoalRunStatus.RUNNING, status=GoalStatus.PENDING,
                max_iterations=request.max_iterations, criteria_source=source, criteria_hash=criteria_hash,
                frozen_criteria=criteria,
                expected_result_status=ExpectedResultStatus.INSUFFICIENT_EVIDENCE if request.expected_result
                else ExpectedResultStatus.NOT_PROVIDED,
            )
            state = GoalExecutionState.from_criteria(run_id, request.goal or request.topic, criteria)
            state.known_facts = [item.fact_id for item in users.records]
            accumulator = EvidenceAccumulator()
            seen_actions: set[str] = set()
            latest_candidate = ""
            research_validation: dict[str, Any] = {}
            clarification_attempts = 0
        if autonomous_python:
            result.telemetry["python_authorization_source"] = "autonomous_execution_mode"
        for key, value in {
            "claim_support_checked": False, "required_claim_count": 0, "supported_claim_count": 0,
            "partially_supported_claim_count": 0, "answerability_status": "NOT_CHECKED",
            "extractive_fallback_attempted": False, "extractive_fallback_used": False,
            "extractive_fallback_failure_reason": None, "refusal_generated": False, "refusal_reason": None,
            "relevant_evidence_present": False, "final_answer_kind": None,
            "operands_expected": 0, "operands_bound": 0, "operand_validation_passed": False,
            "formula_selected": False, "formula_ready": False, "calculation_ready": False,
            "calculation_executed": False, "calculation_validated": False,
        }.items():
            result.telemetry.setdefault(key, value)
        result.telemetry["intent_route"] = intent.kind.value
        result.telemetry["intent"] = {"selected_intent": intent.kind.value, "intent_reason": intent.reason,
                                      "premise_cue_detected": intent.premise_cue_detected,
                                      "formula_origin": intent.formula_origin.value}
        result.telemetry["source_requirement"] = intent.source_requirement.value
        result.telemetry["fact_extraction"] = {
            "deterministic_fact_count": len(users.records) - fallback_added,
            "fallback_fact_count": fallback_added,
            "rejected_fact_count": fallback_rejected,
            "fact_rejection_reasons": users.rejection_reasons,
            "normalized_units": {item.fact_id: {"raw": item.raw_unit, "canonical": item.canonical_unit}
                                 for item in users.records if item.raw_unit},
        }
        operation_text = " ".join([request.goal or request.topic, *[item.description for item in criteria]])
        direct_operations = [name for name, pattern in OPERATIONS.items()
                             if re.search(pattern, operation_text, re.I)] if intent.kind == GoalIntentKind.DIRECT_CALC else []
        for dominant, subsumed in (("weighted_average", "mean"), ("geometric_mean", "mean"),
                                   ("cylinder_volume", "unit_conversion"),
                                   ("combined_rate", "sum"), ("allocation", "sum"),
                                   ("piecewise_cost", "sum"), ("repeated_percent", "percent_change"),
                                   ("weighted_average_by_duration", "weighted_average"),
                                   ("weighted_average_by_duration", "mean"),
                                   ("unit_conversion", "mean"),
                                   ("finite_difference", "percent_change"),
                                   ("finite_difference", "difference"),
                                   ("centered_difference", "finite_difference"),
                                   ("centered_difference", "difference"),
                                   ("linear_regression_slope", "linear_regression"),
                                   ("percentage_decrease", "percent_change"),
                                   ("percentage_increase", "percent_change"),
                                   ("net_difference", "difference")):
            if dominant in direct_operations and subsumed in direct_operations:
                direct_operations.remove(subsumed)
        direct_fast = bool(direct_operations and set(direct_operations) <= {
            "mean", "sum", "ranking", "maximum", "minimum", "range", "ratio", "difference",
            "median", "std_population", "std_sample", "variance_population", "variance",
            "geometric_mean", "add", "multiply", "divide", "subtract", "elapsed_time", "percent_conversion",
            "weighted_average", "combined_rate", "interpolation", "trapezoid", "repeated_percent",
            "allocation", "piecewise_cost", "unit_conversion", "finite_difference",
            "centered_difference", "linear_regression_slope", "percentage_decrease", "percentage_increase", "percent_change",
            "net_difference", "cylinder_volume", "power_times_duration",
            "concentration_mass_per_volume", "weighted_average_by_duration"})
        direct_users = users.named_operands(user_text, direct_operations)
        direct_orders, direct_missing = direct_operation_operands(user_text, direct_users, direct_operations)
        if intent.kind == GoalIntentKind.DIRECT_CALC:
            direct_missing.extend(direct_readiness(user_text, direct_users, direct_operations))
            if users.records and not direct_users.records:
                direct_missing.append("명시한 계산 대상 값")
        if intent.kind == GoalIntentKind.DIRECT_CALC and not users.records:
            direct_missing.append("계산에 사용할 입력값")
        if "std_unspecified" in direct_operations:
            direct_missing.append("표준편차의 모/표본 구분")
        result.telemetry["calculation"] = {"requested_operation_family": ",".join(direct_operations),
                                           "direct_calc_ready": bool(direct_fast and users.records and not direct_missing),
                                           "missing_operands": direct_missing,
                                           "selected_input_fact_ids": [item.fact_id for item in direct_users.records]}
        for stage in ("planning_seconds", "retrieval_seconds", "llm_generation_seconds",
                      "python_seconds", "verification_seconds", "evaluation_seconds",
                      "synthesis_seconds"):
            result.timing.setdefault(stage, 0.0)
        self._add_time(result, "planning_seconds", time.perf_counter() - planning_started)
        retrieval_cache: dict[tuple[str, bool, bool, str], ResearchResponse] = {}
        self._notify(result, on_progress)

        for iteration in range(state.iteration + 1, request.max_iterations + 1):
            if is_canceled and is_canceled():
                return self._finish(result, GoalRunStatus.CANCELED, GoalStatus.CANCELED,
                                    GoalStopReason.CANCELED, latest_candidate, started)
            state.iteration = iteration - 1
            evidence_rows = accumulator.records()
            formula_available = any(item.expression_candidate for item in
                                    FormulaSourceRegistry.from_evidence(evidence_rows).records)
            evidence_fact_ids = [item.fact_id for item in EvidenceFactRegistry.from_evidence(evidence_rows).records]
            selected_formula, formula_selection = rank_formula_candidates(
                evidence_rows, f"{request.goal or ''} {request.topic}",
                [item.name for item in users.records],
            ) if formula_available and requires_sourced_formula else (None, None)
            formula_missing = calculation_readiness(selected_formula, evidence_rows, users, state.derived_facts) if selected_formula else []
            state.formula_ready = bool(selected_formula and not formula_missing)
            result.telemetry["formula"] = ({"candidates_found": formula_selection.candidates_found,
                                             "selected_formula_id": formula_selection.formula_id,
                                             "selection_scores": {"total": formula_selection.score,
                                                                  "lhs": formula_selection.lhs_score,
                                                                  "variable_overlap": formula_selection.variable_overlap_score,
                                                                  "context": formula_selection.context_score,
                                                                  "heading": formula_selection.heading_score},
                                             "ambiguity_reason": formula_selection.selection_reason,
                                             "candidate_scores": formula_selection.candidate_scores}
                                            if formula_selection else {"candidates_found": 0,
                                                                       "selected_formula_id": None})
            if selected_formula and selected_formula.expression_candidate:
                source_text = next((str(row.get("text") or "") for row in evidence_rows
                                    if row.get("evidence_id") == selected_formula.source_id), "")
                result.telemetry["dimension_inference"] = [inference for variable in
                    sorted(expression_variables(selected_formula.expression_candidate) or ())
                    if (inference := infer_dimensionless(variable, source_text))]
            user_formula_missing = (user_formula_bindings(intent.user_equation, users)[1]
                                    if intent.kind == GoalIntentKind.USER_FORMULA_CALC and intent.user_equation else [])
            user_simulation_missing_inputs = (user_simulation_missing(user_text, intent.user_equation, users)
                                              if intent.kind == GoalIntentKind.USER_FORMULA_SIMULATION and not simulation_spec
                                              else [])
            simulation_source = None
            simulation_formula = None
            simulation_inputs: list[str] = []
            missing_simulation: list[str] = []
            if (simulation_spec is None and SIMULATE_WORDS.search(f"{request.topic} {request.goal or ''}")
                    and intent.source_requirement == SourceRequirement.KB_FORMULA):
                readiness = simulation_readiness(f"{user_text}\n{request.goal or ''}", evidence_rows,
                                                  users, state.derived_facts)
                simulation_spec = readiness.spec
                simulation_source = readiness.formula_source_id
                simulation_formula = readiness.formula_equation
                simulation_inputs = readiness.input_ids
                missing_simulation = readiness.missing
            selection_started = time.perf_counter()
            action = self.action_planner.select(request, state, user_fact_ids=[r.fact_id for r in users.records],
                                                evidence_fact_ids=evidence_fact_ids,
                                                formula_ready=selected_formula is not None,
                                                formula_id=selected_formula.formula_id if selected_formula else None,
                                                python_calls_used=result.python_calls_total,
                                                simulation_spec=simulation_spec,
                                                formula_inputs_ready=not (formula_missing or user_formula_missing or direct_missing),
                                                intent=intent)
            result.telemetry["transition"] = {"formula_ready": bool(selected_formula),
                                               "calculation_ready": action.reason_code in {"formula_ready", "calculation_ready"},
                                               "blocking_reason": action.reason_code if action.action_type == GoalActionType.STOP else None}
            equation = intent.user_equation or (selected_formula.expression_candidate if selected_formula else None)
            bindings, missing_bindings = user_formula_bindings(equation, users) if equation else ({}, [])
            ready = action.action_type in {GoalActionType.CALCULATE, GoalActionType.SIMULATE}
            result.telemetry.update({
                "operands_expected": len(expression_variables(equation) or []) if equation else len(direct_users.records) + len(direct_missing),
                "operands_bound": len(bindings) if equation else len(direct_users.records),
                "operand_validation_passed": not (missing_bindings or formula_missing or direct_missing) and bool(users.records),
                "formula_selected": bool(equation) or (intent.kind == GoalIntentKind.DIRECT_CALC and bool(direct_operations)),
                "formula_ready": state.formula_ready if requires_sourced_formula else bool(equation and not missing_bindings) or direct_fast,
                "calculation_ready": ready or result.telemetry["calculation_ready"],
            })
            self._add_time(result, "planning_seconds", time.perf_counter() - selection_started)
            if action.action_type == GoalActionType.STOP:
                grounded = await self._pre_stop_answer(request, intent, criteria, accumulator, result, state, started)
                if grounded is not None:
                    return grounded
                calculation_stalled = (action.reason_code == "no_progress" and not state.computation_ids
                                       and bool(CALC_WORDS.search(f"{request.topic} {request.goal or ''}")))
                needs_clarification = action.reason_code in {"simulation_spec_missing", "calculation_blocked"} or (
                    action.reason_code == "retrieve_no_progress" and bool(missing_simulation)) or (
                    action.reason_code == "no_progress" and (bool(missing_simulation) or calculation_stalled))
                if needs_clarification and clarification_attempts < 3:
                    missing = (missing_simulation or user_simulation_missing_inputs if missing_simulation or user_simulation_missing_inputs else
                               user_formula_missing or direct_missing or formula_missing or
                               (calculation_missing(selected_formula, evidence_rows, users, state.derived_facts)
                                if requires_sourced_formula else []))
                    if missing:
                        return self._pause(result, state, accumulator, seen_actions, research_validation,
                                           latest_candidate, missing, korean, clarification_attempts + 1,
                                           list((resume_state or {}).get("user_replies", [])), started)
                reason = {
                    "no_progress": GoalStopReason.NO_PROGRESS,
                    "simulation_permission_required": GoalStopReason.SIMULATION_BLOCKED,
                    "simulation_spec_missing": GoalStopReason.SIMULATION_BLOCKED,
                    "calculation_permission_required": GoalStopReason.CALCULATION_BLOCKED,
                    "calculation_blocked": GoalStopReason.CALCULATION_BLOCKED,
                    "formula_source_unavailable": GoalStopReason.INSUFFICIENT_EVIDENCE,
                    "retrieve_no_progress": GoalStopReason.NO_PROGRESS,
                    "python_call_budget_exhausted": GoalStopReason.CALCULATION_BLOCKED,
                }.get(action.reason_code, GoalStopReason.INSUFFICIENT_EVIDENCE)
                self._record_stop(result, state, action.reason_code)
                if intent.kind in {GoalIntentKind.DIRECT_CALC, GoalIntentKind.USER_FORMULA_CALC,
                                   GoalIntentKind.USER_FORMULA_SIMULATION, GoalIntentKind.KB_FORMULA_CALC}:
                    result.telemetry["calculation_failure_stage"] = self._calculation_failure_stage(
                        action.reason_code, resumed=bool(resume_state))
                safe_reason = ("missing_validated_formula"
                               if autonomous_python and requires_sourced_formula and not state.computation_ids
                               and action.reason_code in {"no_progress", "calculation_blocked", "insufficient_evidence"}
                               else "premise_insufficient" if intent.kind == GoalIntentKind.PREMISE_CHECK
                               else "knowledge_insufficient" if intent.kind in {
                                   GoalIntentKind.KNOWLEDGE_QA, GoalIntentKind.FIGURE_QA}
                               else "direct_" + action.reason_code if intent.kind == GoalIntentKind.DIRECT_CALC
                               else action.reason_code)
                return self._finish(result, GoalRunStatus.STOPPED, GoalStatus.STOPPED,
                                    reason, self._safe_unavailable_answer(
                                        latest_candidate, state, safe_reason, selected_formula, korean), started)
            input_ids = [r.fact_id for r in users.records] + state.evidence_ids + state.computation_ids
            signature = action.fingerprint(input_ids)
            if signature in seen_actions:
                grounded = await self._pre_stop_answer(request, intent, criteria, accumulator, result, state, started)
                if grounded is not None:
                    return grounded
                self._record_stop(result, state, "repeated_action_fingerprint")
                return self._finish(result, GoalRunStatus.STOPPED, GoalStatus.STOPPED,
                                    GoalStopReason.NO_PROGRESS,
                                    self._safe_unavailable_answer(latest_candidate, state,
                                                                  reason="missing_validated_formula" if autonomous_python and requires_sourced_formula and not state.computation_ids else "",
                                                                  korean=korean), started)
            seen_actions.add(signature)
            before = state.fingerprint()
            action_started = datetime.now(timezone.utc)
            action_clock = time.perf_counter()
            coverage_before = state.current_coverage
            result.current_iteration = iteration
            result.current_action = action.action_type.value
            result.current_stage = action.action_type.value
            self._notify(result, on_progress)
            status = "completed"
            failure: str | None = None
            added: list[str] = []
            calc_ids: list[str] = []
            details: dict[str, Any] = {}

            try:
                if action.action_type == GoalActionType.RETRIEVE:
                    query = action.query or request.goal or request.topic
                    qa_retrieval = (intent.kind in {GoalIntentKind.KNOWLEDGE_QA, GoalIntentKind.PREMISE_CHECK}
                                    and request.use_internal and
                                    getattr(self.research_agent, "vector_store", None) is not None)
                    query_plan = (plan_query(request.topic or request.goal or query,
                                             premise=intent.kind == GoalIntentKind.PREMISE_CHECK,
                                             refined=action.reason_code == "premise_evidence_retry")
                                  if qa_retrieval else None)
                    if query_plan:
                        query = query_plan.search_text
                    cache_key = (query, request.use_internal, request.use_external, request.model)
                    cached = retrieval_cache.get(cache_key)
                    response = cached.model_copy(deep=True) if cached else await self.research_agent.research(ResearchRequest(
                        query=query,
                        use_internal=request.use_internal, use_external=request.use_external,
                        engineering_validation=request.engineering_validation, evidence_only=True,
                        model=request.model,
                        internal_top_k=min(20, max(request.internal_top_k * 3, 12)) if query_plan
                        else request.internal_top_k, external_top_k=request.external_top_k,
                        temperature=request.temperature, seed=request.seed,
                    ))
                    if cached is None:
                        retrieval_cache[cache_key] = response.model_copy(deep=True)
                        self._add_time(result, "retrieval_seconds", response.timing.retrieval_seconds)
                        self._add_time(result, "llm_generation_seconds", response.timing.reasoning_seconds)
                    rerank_debug = None
                    if query_plan:
                        selected, rerank_debug = rerank_sources(response.internal_sources, query_plan,
                                                                limit=request.internal_top_k)
                        if rerank_debug["confidence"] == "LOW" and action.reason_code != "premise_evidence_retry":
                            refined = plan_query(request.topic or request.goal or query,
                                                 premise=intent.kind == GoalIntentKind.PREMISE_CHECK,
                                                 refined=True)
                            if refined.search_text != query:
                                followup = await self.research_agent.research(ResearchRequest(
                                    query=refined.search_text, use_internal=True,
                                    use_external=False, engineering_validation=request.engineering_validation,
                                    evidence_only=True, model=request.model,
                                    internal_top_k=min(20, max(request.internal_top_k * 3, 12)),
                                    temperature=request.temperature, seed=request.seed))
                                self._add_time(result, "retrieval_seconds", followup.timing.retrieval_seconds)
                                selected, second_debug = rerank_sources(
                                    [*response.internal_sources, *followup.internal_sources], refined,
                                    limit=request.internal_top_k)
                                rerank_debug["refined_retrieval"] = second_debug
                                rerank_debug["refined_recovery"] = bool(selected)
                                rerank_debug["confidence"] = second_debug["confidence"]
                        response = response.model_copy(update={"internal_sources": selected,
                            "evidence_counts": EvidenceCounts(internal=len(selected),
                                                               external=len(response.web_sources))})
                        result.telemetry["retrieval_rerank"] = rerank_debug
                        result.telemetry.setdefault("retrieval_rerank_history", []).append(rerank_debug)
                    added = accumulator.add(response)
                    state.evidence_ids.extend(added)
                    state.known_facts = list(dict.fromkeys(
                        state.known_facts + [item.fact_id for item in
                                             EvidenceFactRegistry.from_evidence(accumulator.records()).records]))
                    research_validation = response.validation
                    result.telemetry["source_conflict_count"] = max(
                        result.telemetry.get("source_conflict_count", 0), len(response.conflicts),
                        int(response.validation.get("conflict_count") or 0))
                    details = {"new_evidence_count": len(added), "retrieval_mode": response.retrieval_mode,
                               "query": query,
                               "cache_hit": cached is not None}
                    if rerank_debug:
                        details["relevance_confidence"] = rerank_debug["confidence"]
                    state.verified = False
                    if not added:
                        status, failure = "blocked", "retrieve_no_progress"
                        state.unresolved_information = [failure]
                elif (action.action_type == GoalActionType.CALCULATE and direct_fast):
                    python_started = time.perf_counter()
                    computation = await run_direct_arithmetic(
                        get_settings(), request, run_id, direct_users, direct_operations,
                        f"CALC{len(result.computations) + 1}", direct_orders, original_text=user_text)
                    self._add_time(result, "python_seconds", time.perf_counter() - python_started)
                    if not self._provenance_complete(
                            computation, self._evidence(accumulator, users, [], simulation_spec,
                                                        simulation_source_id),
                            f"{user_text}\n{request.goal or ''}"):
                        raise ValueError("direct arithmetic provenance incomplete")
                    result.computations.append(computation)
                    result.python_calls_total += 1
                    result.python_attempts_total += 1
                    calc_ids.append(computation.computation_id)
                    state.computation_ids.append(computation.computation_id)
                    state.derived_facts.extend(self._derived(computation))
                    state.source_complete = True
                    state.pending_verifications = state.computation_ids.copy()
                    details = {"subprocess_reached": True,
                               "source_requirement": SourceRequirement.NONE.value,
                               "operations": direct_operations}
                elif (action.action_type == GoalActionType.CALCULATE and
                      intent.kind == GoalIntentKind.USER_FORMULA_CALC):
                    if not intent.user_equation or user_formula_missing:
                        raise ValueError("missing_required_input")
                    python_started = time.perf_counter()
                    computation = await run_user_formula_calculation(
                        get_settings(), request, run_id, intent.user_equation, users,
                        f"CALC{len(result.computations) + 1}", simulation_source_id, original_text=user_text)
                    self._add_time(result, "python_seconds", time.perf_counter() - python_started)
                    if not self._provenance_complete(
                            computation, self._evidence(accumulator, users, [], simulation_spec,
                                                        simulation_source_id, intent.user_equation),
                            f"{user_text}\n{request.goal or ''}"):
                        raise ValueError("user formula provenance incomplete")
                    result.computations.append(computation)
                    result.python_calls_total += 1
                    result.python_attempts_total += 1
                    calc_ids.append(computation.computation_id)
                    state.computation_ids.append(computation.computation_id)
                    state.derived_facts.extend(self._derived(computation))
                    state.source_complete = True
                    state.pending_verifications = state.computation_ids.copy()
                    details = {"subprocess_reached": True,
                               "source_requirement": SourceRequirement.USER_FORMULA.value,
                               "formula_source_ids": computation.formula_source_ids}
                elif (action.action_type == GoalActionType.CALCULATE and
                      intent.kind == GoalIntentKind.KB_FORMULA_CALC and selected_formula and
                      selected_formula.expression_candidate and not formula_missing and
                      not user_formula_bindings(selected_formula.expression_candidate, users)[1]):
                    # Literal source equation + uniquely bound user facts are sufficient for
                    # a bounded, independently checked calculation; no second LLM plan is needed.
                    python_started = time.perf_counter()
                    computation = await run_user_formula_calculation(
                        get_settings(), request, run_id, selected_formula.expression_candidate,
                        users, f"CALC{len(result.computations) + 1}", selected_formula.source_id, original_text=user_text)
                    self._add_time(result, "python_seconds", time.perf_counter() - python_started)
                    computation.analysis_id = f"KB-FORMULA-{computation.computation_id}"
                    computation.formula_evidence_ids = [selected_formula.source_id]
                    computation.source_evidence_ids = [selected_formula.source_id]
                    if asks_for_api_gravity_calculation(request) and selected_formula.expression_candidate.split("=", 1)[0].strip().casefold() == "api":
                        output = computation.output_manifest.pop("OUT_RESULT")
                        output["name"] = "API_gravity"
                        output["unit"] = "°API"
                        computation.output_manifest["OUT_default_API_gravity"] = output
                        computation.output = {"OUT_default_API_gravity": output["value"]}
                        computation.required_output_ids = ["OUT_default_API_gravity"]
                        computation.produced_output_ids = ["OUT_default_API_gravity"]
                        computation.units["API_gravity"] = "°API"
                    if not self._provenance_complete(
                            computation, self._evidence(accumulator, users, [], simulation_spec,
                                                        simulation_source_id),
                            f"{user_text}\n{request.goal or ''}"):
                        raise ValueError("sourced formula provenance incomplete")
                    result.computations.append(computation)
                    result.python_calls_total += 1
                    result.python_attempts_total += 1
                    calc_ids.append(computation.computation_id)
                    state.computation_ids.append(computation.computation_id)
                    state.derived_facts.extend(self._derived(computation))
                    state.source_complete = True
                    state.pending_verifications = state.computation_ids.copy()
                    details = {"subprocess_reached": True, "source_requirement": SourceRequirement.KB_FORMULA.value,
                               "formula_source_ids": computation.formula_source_ids}
                elif action.action_type == GoalActionType.CALCULATE:
                    focused = selected_formula
                    if not (request.allow_python_execution and request.python_execution_approved):
                        raise PermissionError("calculation_permission_required")
                    if requires_sourced_formula and not focused:
                        raise ValueError("formula_source_unavailable")
                    if focused and formula_missing:
                        raise ValueError("missing_required_input")
                    snapshot = _EvidenceSnapshot(accumulator, request.model,
                                                 focused.source_id if focused else None,
                                                 focused.raw_span if focused else None,
                                                 get_settings().retrieval_mode)
                    adapter = GoalResearchAgent(snapshot, self.ollama, planner=self.planner,
                                                evaluator=self.evaluator, synthesizer=self.synthesizer,
                                                tool_planner=self.tool_planner,
                                                contract_builder=self.contract_builder,
                                                analysis_factory=self.analysis_factory)
                    subrequest = request.model_copy(update={"topic": user_text, "max_iterations": 1,
                                                    "success_criteria": criteria,
                                                    "max_python_calls": request.max_python_calls - result.python_calls_total,
                                                    "deliverables": []})
                    subresult = await adapter.run(f"{run_id}-A{iteration}", subrequest)
                    self._add_time(result, "python_seconds", subresult.timing.get("python_seconds", 0.0))
                    self._add_time(result, "llm_generation_seconds",
                                   subresult.timing.get("synthesis_seconds", 0.0) +
                                   subresult.timing.get("evaluation_seconds", 0.0))
                    result.python_calls_total += subresult.python_calls_total
                    result.python_attempts_total += subresult.python_attempts_total
                    result.python_failures += subresult.python_failures
                    trace = subresult.iterations[-1].python_trace if subresult.iterations else None
                    details = {"subprocess_reached": bool(trace and trace.subprocess_reached),
                               "blocked_stage": trace.blocked_stage if trace else "no_trace",
                               "source_complete": trace.source_complete if trace else None,
                               "python_calls": subresult.python_calls_total,
                               "user_fact_ids": [item.fact_id for item in users.records],
                               "evidence_fact_ids": evidence_fact_ids,
                               "formula_id": selected_formula.formula_id if selected_formula else None,
                               "missing_variables": trace.missing_variables if trace else [],
                               "unit_mismatch_variables": trace.unit_mismatch_variables if trace else []}
                    state.source_complete = trace.source_complete if trace else None
                    source_map = {
                        item.evidence_id: original.evidence_id
                        for item in subresult.internal_sources
                        for original in accumulator.internal
                        if (item.document, item.page, item.chunk_id) ==
                           (original.document, original.page, original.chunk_id)
                    }
                    source_map.update({
                        item.evidence_id: original.evidence_id
                        for item in subresult.web_sources
                        for original in accumulator.web
                        if item.url == original.url
                    })
                    source_formulas = {(item.source_id, item.normalized_span)
                                       for item in FormulaSourceRegistry.from_evidence(accumulator.records()).records}
                    for computation in subresult.computations:
                        computation.source_evidence_ids = [source_map.get(value, value)
                                                           for value in computation.source_evidence_ids]
                        computation.formula_evidence_ids = [source_map.get(value, value)
                                                            for value in computation.formula_evidence_ids]
                        computation.formula_source_ids = [source_map.get(value, value)
                                                          for value in computation.formula_source_ids]
                        computation.input_fact_ids = [source_map.get(value, value)
                                                      for value in computation.input_fact_ids]
                        computation.bound_variables = {name: source_map.get(value, value)
                                                        for name, value in computation.bound_variables.items()}
                        for fact in computation.input_facts:
                            fact["evidence_id"] = source_map.get(str(fact.get("evidence_id")), fact.get("evidence_id"))
                        if (computation.formula and computation.formula_evidence_ids and not any(
                                (value, normalize_formula(computation.formula)) in source_formulas
                                for value in computation.formula_evidence_ids)):
                            computation.validation_passed = False
                        if computation.validation_passed and not self._provenance_complete(
                                computation, self._evidence(accumulator, users, [], simulation_spec,
                                                            simulation_source_id), f"{user_text}\n{request.goal or ''}"):
                            computation.validation_passed = False
                        computation.computation_id = f"CALC{len(result.computations) + 1}"
                        targets = set(computation.target_criteria)
                        computation.target_criteria = [item.criterion_id for item in criteria
                                                       if item.criterion_id in targets or item.description in targets]
                        result.computations.append(computation)
                        if computation.validation_passed:
                            calc_ids.append(computation.computation_id)
                            state.computation_ids.append(computation.computation_id)
                            state.derived_facts.extend(self._derived(computation))
                            state.known_facts.extend(item.fact_id for item in self._derived(computation))
                            state.generated_artifacts.extend(computation.output_files)
                    if not calc_ids:
                        status, failure = "blocked", details["blocked_stage"] or "calculation_failed"
                        state.blocked_reasons = [failure]
                        state.unresolved_information = [failure]
                    else:
                        state.blocked_reasons.clear()
                        state.unresolved_information.clear()
                        state.pending_calculations.clear()
                        state.verified = False
                        state.pending_verifications = state.computation_ids.copy()
                elif action.action_type == GoalActionType.SIMULATE:
                    if simulation_spec is None:
                        raise ValueError("simulation specification unavailable")
                    if not (request.allow_python_execution and request.python_execution_approved):
                        raise PermissionError("simulation_permission_required")
                    if simulation_source and simulation_formula and simulation_source != simulation_source_id:
                        source = next((item for item in accumulator.records()
                                       if item.get("evidence_id") == simulation_source), None)
                        if source is None or not any(
                                record.source_id == simulation_source and
                                source_contains_equation(record, str(source.get("text") or ""), simulation_formula)
                                for record in FormulaSourceRegistry.from_evidence([source]).records):
                            raise ValueError("simulation_formula_source_unavailable")
                    python_started = time.perf_counter()
                    computation = await run_parameter_sweep(get_settings(), request, run_id,
                                                            simulation_spec, f"CALC{len(result.computations) + 1}",
                                                            simulation_source_id)
                    self._add_time(result, "python_seconds", time.perf_counter() - python_started)
                    if simulation_spec.fixed_fact_ids:
                        fixed_ids = list(simulation_spec.fixed_fact_ids.values())
                        computation.source_input_ids = list(dict.fromkeys([*computation.source_input_ids, *fixed_ids]))
                        computation.input_fact_ids = list(dict.fromkeys([*computation.input_fact_ids, *fixed_ids]))
                        computation.used_input_ids = list(dict.fromkeys([*computation.used_input_ids, *fixed_ids]))
                        computation.bound_variables.update(simulation_spec.fixed_fact_ids)
                        computation.input_facts.extend({
                            "name": item.name, "value": item.value, "unit": item.unit,
                            "evidence_id": item.fact_id, "source_type": "user_fact",
                        } for item in users.records if item.fact_id in fixed_ids)
                        computation.units.update({item.name: item.unit for item in users.records
                                                  if item.fact_id in fixed_ids})
                        for output in computation.output_manifest.values():
                            output["source_fact_ids"] = list(dict.fromkeys(
                                [*output.get("source_fact_ids", []), *fixed_ids]))
                        computation.source_formula = simulation_spec.source_equation
                        computation.normalized_formula = normalize_formula(simulation_spec.source_equation or "")
                    if simulation_source:
                        computation.formula_evidence_ids = [simulation_source]
                        computation.source_evidence_ids = [simulation_source]
                        computation.source_input_ids = list(dict.fromkeys(
                            [*computation.source_input_ids, *simulation_inputs]))
                        computation.formula_source_ids = [simulation_source]
                        computation.source_formula = simulation_formula
                        computation.normalized_formula = normalize_formula(simulation_formula or "")
                        computation.input_fact_ids = list(computation.source_input_ids)
                        for item in users.records:
                            if item.fact_id in simulation_inputs:
                                computation.bound_variables[item.name] = item.fact_id
                    if not self._provenance_complete(
                            computation, self._evidence(accumulator, users, [], simulation_spec,
                                                        simulation_source_id), f"{user_text}\n{request.goal or ''}"):
                        raise ValueError("simulation provenance incomplete")
                    result.computations.append(computation)
                    calc_ids.append(computation.computation_id)
                    state.computation_ids.append(computation.computation_id)
                    state.derived_facts.extend(self._derived(computation))
                    state.pending_simulations.clear()
                    state.source_complete = True
                    state.known_facts.extend(item.fact_id for item in self._derived(computation))
                    state.generated_artifacts.extend(computation.output_files)
                    result.python_calls_total += 1
                    result.python_attempts_total += 1
                    details = {"subprocess_reached": True,
                               "case_count": sum(key.startswith("OUT_CASE_") for key in computation.output_manifest),
                               "best": computation.output_manifest["OUT_BEST_PARAMETER"]["value"]}
                    state.verified = False
                    state.pending_verifications = state.computation_ids.copy()
                elif action.action_type == GoalActionType.ANALYZE:
                    if not state.derived_facts:
                        status, failure = "blocked", "validated_derived_facts_missing"
                    else:
                        # Only validated calculation outputs enter a later analysis action.
                        values = [item.value for item in state.derived_facts
                                  if item.output_id.startswith("OUT_CASE_")]
                        details = {"derived_fact_ids_used": [item.fact_id for item in state.derived_facts],
                                   "case_mean": sum(values) / len(values) if values else None,
                                   "case_range": max(values) - min(values) if values else None}
                        state.analyzed = True
                elif action.action_type == GoalActionType.VERIFY:
                    evidence = self._evidence(accumulator, users, result.computations,
                                              simulation_spec, simulation_source_id, intent.user_equation)
                    simulation = next((item for item in result.computations
                                       if item.validation_passed and item.analysis_id.startswith("SIM-")), None)
                    synthesis_started = time.perf_counter()
                    result.current_stage = "synthesize"
                    self._notify(result, on_progress)
                    premise_assessment = (await assess_premise(self.ollama, request, evidence)
                                          if intent.kind == GoalIntentKind.PREMISE_CHECK else PremiseAssessment())
                    if (intent.kind == GoalIntentKind.PREMISE_CHECK and
                            premise_assessment.verdict == "insufficient" and
                            "premise_context_expansion" not in result.telemetry and
                            getattr(self.research_agent, "vector_store", None) is not None):
                        neighbors, expansion = await asyncio.to_thread(
                            expand_premise_context, self.research_agent.vector_store,
                            accumulator.internal)
                        result.telemetry["premise_context_expansion"] = expansion
                        context_ids = accumulator.add_internal(neighbors)
                        state.evidence_ids.extend(context_ids)
                        if context_ids:
                            evidence = self._evidence(accumulator, users, result.computations,
                                                      simulation_spec, simulation_source_id,
                                                      intent.user_equation)
                            premise_assessment = await assess_premise(self.ollama, request, evidence)
                    if intent.kind == GoalIntentKind.PREMISE_CHECK:
                        result.telemetry["premise_grounding_method"] = premise_assessment.method
                        result.telemetry["premise_source_id"] = premise_assessment.source_id
                        result.telemetry["premise_supporting_source_ids"] = list(premise_assessment.supporting_source_ids)
                        result.telemetry["premise_relation_type"] = premise_assessment.relation_type
                        result.telemetry["premise_grounding_failure_reason"] = premise_assessment.failure_reason
                    latest_candidate = (premise_assessment.answer if intent.kind == GoalIntentKind.PREMISE_CHECK else
                                        self._simulation_answer(simulation, simulation_spec, evidence,
                                                                simulation_source_id, korean)
                                        if simulation and simulation_spec else
                                        self._api_gravity_answer(request, result.computations, evidence)
                                        or self._simple_user_fact_answer(request, result.computations, evidence)
                                        or self._user_formula_answer(request, result.computations, evidence)
                                        or self._validated_calculation_answer(request, result.computations, evidence)
                                        or await self._synthesize(request, criteria, evidence, [],
                                                                  computations=result.computations))
                    synthesis_seconds = time.perf_counter() - synthesis_started
                    self._add_time(result, "synthesis_seconds", synthesis_seconds)
                    self._add_time(result, "llm_generation_seconds", synthesis_seconds)
                    result.current_stage = "verify"
                    self._notify(result, on_progress)
                    if not result.computations:
                        latest_candidate = self._focus_research_answer(
                            latest_candidate, criteria, request.topic)
                    grounded_premise_answer = DrillingValidator().grounded_correction(
                        f"{request.topic}\n{request.goal or ''}", evidence, korean)
                    if grounded_premise_answer:
                        latest_candidate = grounded_premise_answer
                    rejected_claims: list[str] = []
                    if (not grounded_premise_answer and premise_assessment.method != "source_ratio"
                            and callable(getattr(self.ollama, "chat_structured", None))):
                        latest_candidate, rejected_claims = await ground_research_claims(
                            self.ollama, request, latest_candidate, evidence)
                    latest_candidate, rejected_numeric = self._filter_numeric_claims(
                        latest_candidate, evidence, result.computations)
                    if intent.kind == GoalIntentKind.PREMISE_CHECK:
                        result.telemetry["premise_candidate_retained"] = bool(latest_candidate)
                        result.telemetry["premise_numeric_rejections"] = rejected_numeric
                    evaluation_started = time.perf_counter()
                    evaluation = await self.evaluator.evaluate(request, criteria, latest_candidate,
                                                               evidence, research_validation,
                                                               computations=result.computations)
                    if intent.kind in {GoalIntentKind.KNOWLEDGE_QA, GoalIntentKind.FIGURE_QA}:
                        refusal = bool(re.search(r"cannot\s+(?:answer|verify|confirm)|insufficient\s+evidence|"
                            r"did\s+not\s+directly\s+support|근거.{0,15}(?:부족|없)|답변할\s*수\s*없", latest_candidate, re.I))
                        extracted, support = self._answerability_gate(request, criteria, evidence, result,
                            attempt=not evaluation.achieved or not latest_candidate.strip() or bool(rejected_claims) or refusal)
                        if evaluation.achieved and support.some_supported and not support.all_required_supported:
                            # Positive partial coverage must not masquerade as complete coverage.
                            # No literal match is an abstention, not a veto of normal semantic verification.
                            extracted, support = self._answerability_gate(request, criteria, evidence, result)
                            evaluation = replace(evaluation, achieved=False,
                                gaps=[c.description for c in support.claims if c.support_status != SupportStatus.SUPPORTED])
                        if extracted:
                            latest_candidate = extracted
                            coverage = sum(c.support_status == SupportStatus.SUPPORTED for c in support.claims) / max(1, len(support.claims))
                            evaluation = replace(evaluation,
                                criteria=self._support_evaluation(criteria, support, korean),
                                coverage=coverage, achieved=support.all_required_supported,
                                gaps=[c.description for c in support.claims if c.support_status != SupportStatus.SUPPORTED],
                                engineering_validation_passed=True, engineering_contradiction_count=0,
                                unsupported_engineering_claim_count=0)
                            rejected_claims, rejected_numeric = [], 0
                    if premise_criteria:
                        evaluation = self._validated_premise_criteria(
                            evaluation, criteria, request, latest_candidate, evidence)
                        if (not EngineeringValidator().detect_false_premises(f"{request.topic}\n{request.goal or ''}")
                                and premise_assessment.verdict in {"supports", "contradicts"}
                                and f"[{premise_assessment.source_id}]" in latest_candidate
                                and premise_assessment.quote in latest_candidate
                                and evaluation.engineering_validation_passed and not rejected_claims):
                            reason = ("전제를 실제 근거와 대조하고 출처가 밝힌 관계를 제시했습니다." if korean else
                                      "The premise was checked against the cited source relation.")
                            evaluations = [CriterionEvaluation(
                                criterion_id=item.criterion_id, status=CriterionStatus.MET,
                                reason=reason, supporting_evidence=[premise_assessment.source_id])
                                for item in criteria]
                            evaluation = replace(evaluation, criteria=evaluations, coverage=1.0,
                                                 achieved=True, gaps=[])
                    if intent.kind == GoalIntentKind.PREMISE_CHECK:
                        result.telemetry["premise_verdict"] = premise_assessment.verdict
                        if not latest_candidate.strip():
                            evaluation = replace(evaluation, achieved=False,
                                                 gaps=[*evaluation.gaps, "Premise lacks source-grounded assessment"])
                    if (not grounded_premise_answer and
                            DrillingValidator().detect_false_premises(f"{request.topic}\n{request.goal or ''}")):
                        latest_candidate = ("근거상 질문의 전제를 확인하거나 교정하지 못해 결론을 보류합니다."
                                            if korean else "The premise could not be corrected from the available evidence.")
                        evaluation = replace(evaluation, achieved=False,
                                             gaps=[*evaluation.gaps, "False premise lacks a supported correction"])
                    evaluation_seconds = time.perf_counter() - evaluation_started
                    self._add_time(result, "evaluation_seconds", evaluation_seconds)
                    self._add_time(result, "llm_generation_seconds", evaluation_seconds)
                    if simulation:
                        evaluation = self._deterministic_simulation_criteria(
                            evaluation, criteria, latest_candidate, simulation, korean)
                    elif intent.kind in {GoalIntentKind.DIRECT_CALC, GoalIntentKind.USER_FORMULA_CALC,
                                         GoalIntentKind.KB_FORMULA_CALC}:
                        evaluation = self._deterministic_calculation_criteria(
                            evaluation, criteria, latest_candidate, result.computations, evidence,
                            intent.source_requirement, korean)
                    citation_semantic_passed = bool(latest_candidate.strip()) and (
                        intent.kind not in {GoalIntentKind.PREMISE_CHECK, GoalIntentKind.KNOWLEDGE_QA, GoalIntentKind.FIGURE_QA} or
                        any(f'[{row["evidence_id"]}]' in latest_candidate for row in evidence
                            if row.get("source_type") in {"knowledge_base", "web", "figure"}))
                    if not citation_semantic_passed:
                        evaluation = replace(evaluation, achieved=False,
                                             gaps=[*evaluation.gaps, "Direct source support needed for the answer"])
                    self._assert_criteria_frozen(criteria, criteria_hash)
                    state.current_coverage = evaluation.coverage
                    state.unresolved_information = evaluation.gaps[:5]
                    if (intent.kind == GoalIntentKind.PREMISE_CHECK and
                            premise_assessment.verdict == "insufficient"):
                        state.unresolved_information.append("premise_relation_not_supported_by_retrieved_evidence")
                    by_id = {item.criterion_id: item for item in evaluation.criteria}
                    for item in state.criteria:
                        value = by_id.get(item.criterion_id)
                        if value:
                            item.status = value.status
                            item.support_ids = value.supporting_evidence
                            item.missing_requirements = [] if value.status == CriterionStatus.MET else evaluation.gaps[:3]
                    requires_computation = intent.kind in {
                        GoalIntentKind.DIRECT_CALC, GoalIntentKind.USER_FORMULA_CALC,
                        GoalIntentKind.USER_FORMULA_SIMULATION, GoalIntentKind.KB_FORMULA_CALC,
                    }
                    state.goal_achieved = bool(evaluation.achieved and
                                               (not requires_computation or state.computation_ids))
                    state.verified = True
                    state.pending_verifications.clear()
                    result.criteria = evaluation.criteria
                    result.goal_coverage = evaluation.coverage
                    result.goal_coverage_percent = round(evaluation.coverage * 100, 2)
                    result.expected_result_status = evaluation.expected_result_status
                    result.validation = {"engineering_validation_passed": evaluation.engineering_validation_passed,
                                         "engineering_contradiction_count": evaluation.engineering_contradiction_count,
                                         "unsupported_engineering_claim_count": evaluation.unsupported_engineering_claim_count,
                                         "citation_semantic_passed": citation_semantic_passed,
                                         "unsupported_citation_claim_count": len(rejected_claims),
                                         "unsupported_numeric_claim_count": rejected_numeric,
                                         "criteria_frozen": True}
                    details = {"engineering_validation_passed": evaluation.engineering_validation_passed,
                               "goal_achieved": state.goal_achieved}
                elif action.action_type == GoalActionType.SYNTHESIZE:
                    result.final_answer = latest_candidate
                    state.synthesized = True
            except (ValueError, RuntimeError, OSError, PermissionError, TypeError) as exc:
                status, failure = "failed", type(exc).__name__
                state.blocked_reasons = [failure]
                state.unresolved_information = [failure]
                details = {"error_type": type(exc).__name__,
                           "failure_stage": self._calculation_failure_stage(str(exc), resumed=bool(resume_state))
                           if action.action_type in {GoalActionType.CALCULATE, GoalActionType.SIMULATE} else None}
                if details["failure_stage"]:
                    result.telemetry["calculation_failure_stage"] = details["failure_stage"]

            self._add_time(result, f"{action.action_type.value}_action_seconds",
                           time.perf_counter() - action_clock)
            if action.action_type == GoalActionType.VERIFY:
                self._add_time(result, "verification_seconds", time.perf_counter() - action_clock)

            state.iteration = iteration
            record = ActionRecord(iteration=iteration, action_id=action.action_id,
                                  action_type=action.action_type, target_criteria=action.target_criteria,
                                  status=status, reason_code=action.reason_code, evidence_added=added,
                                  started_at=action_started, finished_at=datetime.now(timezone.utc),
                                  new_evidence_count=len(added),
                                  computation_ids=calc_ids, coverage_before=coverage_before,
                                  coverage_after=state.current_coverage, failure_reason=failure,
                                  details=details)
            state.completed_actions.append(record)
            state.no_progress_count = 0 if state.fingerprint() != before else state.no_progress_count + 1
            result.action_history.append(record.model_dump(mode="json"))
            result.state_history.append(state.snapshot())
            result.iterations_completed = iteration
            result.internal_sources = accumulator.internal
            result.web_sources = accumulator.web
            result.figures = accumulator.figures
            result.final_answer = latest_candidate
            self._notify(result, on_progress)
            if (action.action_type == GoalActionType.CALCULATE and status == "blocked" and
                    failure in {"calculation_contract_unit_missing", "missing_required_input",
                                "variable_binding_missing", "simulation_input_missing"} and
                    any(item.action_type == GoalActionType.RETRIEVE for item in state.completed_actions) and
                    clarification_attempts < 3):
                missing = [f"{value.split(':')[-1]} 값과 단위" for value in
                           [*details["missing_variables"], *details["unit_mismatch_variables"]]]
                missing = missing or calculation_missing(selected_formula, accumulator.records(),
                                                         users, state.derived_facts)
                return self._pause(result, state, accumulator, seen_actions, research_validation,
                                   latest_candidate, missing or ["필수 입력값과 단위"], korean,
                                   clarification_attempts + 1,
                                   list((resume_state or {}).get("user_replies", [])), started)
            if state.synthesized and state.goal_achieved:
                self._record_stop(result, state, "goal_achieved")
                return self._finish(result, GoalRunStatus.COMPLETED, GoalStatus.ACHIEVED,
                                    GoalStopReason.GOAL_ACHIEVED, latest_candidate, started)

        if not state.goal_achieved:
            grounded = await self._pre_stop_answer(request, intent, criteria, accumulator, result, state, started)
            if grounded is not None:
                return grounded
        reason = (GoalStopReason.GOAL_ACHIEVED if state.goal_achieved else
                  GoalStopReason.INSUFFICIENT_EVIDENCE if state.blocked_reasons and not state.computation_ids else
                  GoalStopReason.MAX_ITERATIONS)
        self._record_stop(result, state, reason.value)
        formula_unverified = (autonomous_python and requires_sourced_formula and
                              not state.goal_achieved and not state.computation_ids)
        return self._finish(result, GoalRunStatus.COMPLETED if state.goal_achieved else GoalRunStatus.STOPPED,
                            GoalStatus.ACHIEVED if state.goal_achieved else GoalStatus.STOPPED,
                            reason, self._safe_unavailable_answer(latest_candidate, state,
                                                                  reason="" if state.goal_achieved else "missing_validated_formula" if formula_unverified else
                                                                  "premise_insufficient" if intent.kind == GoalIntentKind.PREMISE_CHECK else
                                                                  "knowledge_insufficient" if intent.kind in {
                                                                      GoalIntentKind.KNOWLEDGE_QA, GoalIntentKind.FIGURE_QA} else
                                                                  "direct_calculation_blocked" if intent.kind == GoalIntentKind.DIRECT_CALC else "",
                                                                  korean=korean), started)
