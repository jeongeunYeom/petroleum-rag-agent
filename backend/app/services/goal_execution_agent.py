"""State-driven v8 orchestration around the existing research and calculation tools."""

from __future__ import annotations

import re
import time
import json
from dataclasses import replace
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.models.goal_research_schemas import (
    CriterionStatus, ExpectedResultStatus, GoalCriterion, GoalResearchRequest,
    GoalResearchResponse, GoalRunStatus, GoalStatus, GoalStopReason,
)
from app.models.research_schemas import EvidenceCounts, ResearchRequest, ResearchResponse, ResearchTiming
from app.services.formula_source_registry import FormulaSourceRegistry
from app.services.calculation_requirements import select_formula_candidate
from app.services.goal_clarification import calculation_missing, clarification_question, simulation_readiness
from app.services.evidence_fact_registry import EvidenceFactRegistry
from app.services.calc_claim_grounding import validate_calc_claim
from app.services.goal_action_planner import CALC_WORDS, GoalActionPlanner
from app.services.goal_intent import asks_for_api_gravity_calculation, prefers_korean
from app.services.goal_evaluator import GoalEvaluator
from app.services.goal_execution_state import (
    ActionRecord, DerivedFact, GoalActionType, GoalExecutionState, SimulationParameter, SimulationSpec,
)
from app.services.goal_research_agent import EvidenceAccumulator, GoalResearchAgent
from app.services.goal_tool_planner import (
    AnalysisPlanSelection, GoalToolPlanner, ToolDecision, materialize_analysis_plan_v4,
)
from app.services.goal_simulation import run_parameter_sweep
from app.services.user_fact_registry import UserFactRegistry


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
        elif simulation_spec:
            descriptions.append("Report all simulated cases from the validated parameter sweep")
            for word, phrase in ((r"\bbest\b|\bmaxim", "Identify the best case"),
                                 (r"\bmean\b|\baverage\b", "Report the mean simulated result"),
                                 (r"\brange\b|\bsensitiv", "Report the sensitivity range")):
                if re.search(word, goal, re.I):
                    descriptions.append(phrase)
        elif users.records and re.search(r"공식|수식|관계식|\b(?:formula|equation|correlation)\b", goal, re.I) and re.search(
                r"계산|구해|\b(?:calculat\w*|comput\w*)\b", goal, re.I):
            descriptions.append("출처 있는 관계식과 제공된 입력으로 검증된 계산 결과를 제시" if prefers_korean(request)
                                else "Provide a validated result from a sourced equation and supplied inputs")
        elif users.records and re.search(r"\b(?:calculat|comput|determine|find)\w*\b|계산|구해|구하", goal, re.I):
            if re.search(r"\bmean\b|\baverage\b|평균", goal, re.I):
                descriptions.append("제공된 입력의 평균을 계산하여 제시" if prefers_korean(request)
                                    else "Calculate the requested mean from the supplied inputs")
            if re.search(r"\b(?:rank|top|best|highest)\b|순위|최고|최적|가장\s*높", goal, re.I):
                descriptions.append("제공된 입력의 순위와 가장 높은 항목을 제시" if prefers_korean(request)
                                    else "Identify the requested ranking or top case from the supplied inputs")
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
    def _simulation_spec(request: GoalResearchRequest) -> SimulationSpec | None:
        if request.simulation_spec:
            return SimulationSpec.model_validate(request.simulation_spec)
        text = "\n".join(filter(None, (request.topic, request.goal)))
        interval = re.search(
            r"\b(?P<name>[A-Za-z][A-Za-z0-9_]*)\s+from\s+(?P<start>[-+]?\d+(?:\.\d+)?)"
            r"\s+to\s+(?P<stop>[-+]?\d+(?:\.\d+)?)\s+(?:in\s+)?steps?\s+(?:of\s+)?"
            r"(?P<step>\d+(?:\.\d+)?)", text, re.I,
        )
        formula = re.search(r"\b(?:model|formula)\s+(?P<output>[A-Za-z][A-Za-z0-9_]*)\s*=\s*"
                            r"(?P<expression>[^;,\n]+)", text, re.I)
        if not interval or not formula:
            return None
        return SimulationSpec(
            parameter=SimulationParameter(name=interval.group("name"), start=float(interval.group("start")),
                                          stop=float(interval.group("stop")), step=float(interval.group("step"))),
            output_name=formula.group("output"), expression=formula.group("expression").strip(),
            objective="min" if re.search(r"\bminimi[sz]e\b|최소", text, re.I) else "max",
        )

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
                  simulation_source_id: str) -> list[dict[str, Any]]:
        evidence = accumulator.records() + users.evidence()
        if simulation_spec:
            evidence.append({"evidence_id": simulation_source_id, "source_type": "user_fact",
                             "locator": "request.goal", "text": simulation_spec.model_dump_json()})
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
    def _api_gravity_answer(request: GoalResearchRequest, computations: list[Any],
                            evidence: list[dict[str, Any]]) -> str | None:
        if not asks_for_api_gravity_calculation(request):
            return None
        source_ids = {str(item["evidence_id"]) for item in evidence
                      if item.get("source_type") in {"knowledge_base", "figure", "web"}}
        for calc in computations:
            if not calc.validation_passed or not calc.formula or not set(calc.formula_evidence_ids) & source_ids:
                continue
            for output_id, output in calc.output_manifest.items():
                if "api" not in str(output.get("name", "")).casefold() or "gravity" not in str(output.get("name", "")).casefold():
                    continue
                parents = list(dict.fromkeys([calc.computation_id, *calc.source_input_ids,
                                               *calc.formula_evidence_ids]))
                value = f"{output['name']}: {output['value']} {output.get('unit') or ''}".strip()
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
               user_replies: list[str]) -> GoalResearchResponse:
        result.run_status = GoalRunStatus.WAITING_FOR_USER_INPUT
        result.status = GoalStatus.PENDING
        result.current_stage = "waiting_for_user_input"
        result.current_action = None
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
        return result

    @staticmethod
    def _focus_research_answer(candidate: str, criteria: list[GoalCriterion]) -> str:
        """Discard tangential cited lines when a research goal has distinct subgoals."""
        if len(criteria) < 2:
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
        korean = prefers_korean(request)
        requires_sourced_formula = bool(
            re.search(r"공식|수식|관계식|\b(?:formula|equation|correlation)\b", request.goal or request.topic, re.I)
            and re.search(r"계산|구해|\b(?:calculat\w*|comput\w*)\b", request.goal or request.topic, re.I)
        )
        user_text = request.topic + "\n" + "\n".join((resume_state or {}).get("user_replies", []))
        users = UserFactRegistry.from_topic(user_text)
        simulation_spec = self._simulation_spec(request)
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
            result.run_status = GoalRunStatus.RUNNING
            result.clarification_question = None
            result.required_inputs = []
            result.resume_checkpoint = {}
        else:
            criteria = [item.model_copy(deep=True) for item in request.success_criteria]
            source = "user" if criteria else "inferred"
            if not criteria:
                criteria = self._explicit_numeric_criteria(request, users, simulation_spec)
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
            selected_formula = select_formula_candidate(
                evidence_rows, f"{request.goal or ''} {request.topic}",
                [item.name for item in users.records],
            ) if formula_available else None
            simulation_source = None
            simulation_inputs: list[str] = []
            missing_simulation: list[str] = []
            if simulation_spec is None and re.search(r"\b(?:simulat\w*|sweep|vary\w*)\b|시뮬레이션|바꿔가며|바꾸면서|간격으로",
                                                      f"{request.topic} {request.goal or ''}", re.I):
                readiness = simulation_readiness(f"{user_text}\n{request.goal or ''}", evidence_rows,
                                                  users, state.derived_facts)
                simulation_spec = readiness.spec
                simulation_source = readiness.formula_source_id
                simulation_inputs = readiness.input_ids
                missing_simulation = readiness.missing
            action = self.action_planner.select(request, state, user_fact_ids=[r.fact_id for r in users.records],
                                                evidence_fact_ids=evidence_fact_ids,
                                                formula_ready=selected_formula is not None,
                                                formula_id=selected_formula.formula_id if selected_formula else None,
                                                python_calls_used=result.python_calls_total,
                                                simulation_spec=simulation_spec)
            if action.action_type == GoalActionType.STOP:
                calculation_stalled = (action.reason_code == "no_progress" and not state.computation_ids
                                       and bool(CALC_WORDS.search(f"{request.topic} {request.goal or ''}")))
                needs_clarification = action.reason_code in {"simulation_spec_missing", "calculation_blocked"} or (
                    action.reason_code == "no_progress" and (bool(missing_simulation) or calculation_stalled))
                if needs_clarification and request.use_internal and clarification_attempts < 3:
                    missing = (missing_simulation if missing_simulation else
                               calculation_missing(selected_formula, evidence_rows, users, state.derived_facts))
                    if missing:
                        return self._pause(result, state, accumulator, seen_actions, research_validation,
                                           latest_candidate, missing, korean, clarification_attempts + 1,
                                           list((resume_state or {}).get("user_replies", [])))
                reason = {
                    "no_progress": GoalStopReason.NO_PROGRESS,
                    "simulation_permission_required": GoalStopReason.SIMULATION_BLOCKED,
                    "simulation_spec_missing": GoalStopReason.SIMULATION_BLOCKED,
                    "calculation_permission_required": GoalStopReason.CALCULATION_BLOCKED,
                    "calculation_blocked": GoalStopReason.CALCULATION_BLOCKED,
                    "python_call_budget_exhausted": GoalStopReason.CALCULATION_BLOCKED,
                }.get(action.reason_code, GoalStopReason.INSUFFICIENT_EVIDENCE)
                self._record_stop(result, state, action.reason_code)
                safe_reason = ("missing_validated_formula"
                               if autonomous_python and requires_sourced_formula and not state.computation_ids
                               and action.reason_code in {"no_progress", "calculation_blocked", "insufficient_evidence"}
                               else action.reason_code)
                return self._finish(result, GoalRunStatus.STOPPED, GoalStatus.STOPPED,
                                    reason, self._safe_unavailable_answer(
                                        latest_candidate, state, safe_reason, selected_formula, korean), started)
            input_ids = [r.fact_id for r in users.records] + state.evidence_ids + state.computation_ids
            signature = action.fingerprint(input_ids)
            if signature in seen_actions:
                self._record_stop(result, state, "repeated_action_fingerprint")
                return self._finish(result, GoalRunStatus.STOPPED, GoalStatus.STOPPED,
                                    GoalStopReason.NO_PROGRESS,
                                    self._safe_unavailable_answer(latest_candidate, state,
                                                                  reason="missing_validated_formula" if autonomous_python and requires_sourced_formula and not state.computation_ids else "",
                                                                  korean=korean), started)
            seen_actions.add(signature)
            before = state.fingerprint()
            action_started = datetime.now(timezone.utc)
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
                    response = await self.research_agent.research(ResearchRequest(
                        query=action.query or request.goal or request.topic,
                        use_internal=request.use_internal, use_external=request.use_external,
                        engineering_validation=request.engineering_validation, model=request.model,
                        internal_top_k=request.internal_top_k, external_top_k=request.external_top_k,
                        temperature=request.temperature, seed=request.seed,
                    ))
                    added = accumulator.add(response)
                    state.evidence_ids.extend(added)
                    state.known_facts = list(dict.fromkeys(
                        state.known_facts + [item.fact_id for item in
                                             EvidenceFactRegistry.from_evidence(accumulator.records()).records]))
                    research_validation = response.validation
                    details = {"new_evidence_count": len(added), "retrieval_mode": response.retrieval_mode}
                    state.verified = False
                    if not added:
                        status, failure = "blocked", "retrieve_no_progress"
                        state.unresolved_information = [failure]
                elif action.action_type == GoalActionType.CALCULATE:
                    focused = selected_formula
                    snapshot = _EvidenceSnapshot(accumulator, request.model,
                                                 focused.source_id if focused else None,
                                                 focused.raw_span if focused else None,
                                                 get_settings().retrieval_mode)
                    adapter = GoalResearchAgent(snapshot, self.ollama, planner=self.planner,
                                                evaluator=self.evaluator, synthesizer=self.synthesizer,
                                                tool_planner=self.tool_planner,
                                                contract_builder=self.contract_builder,
                                                analysis_factory=self.analysis_factory)
                    subrequest = request.model_copy(update={"max_iterations": 1, "success_criteria": criteria,
                                                    "max_python_calls": request.max_python_calls - result.python_calls_total,
                                                    "deliverables": []})
                    subresult = await adapter.run(f"{run_id}-A{iteration}", subrequest)
                    result.python_calls_total += subresult.python_calls_total
                    result.python_attempts_total += subresult.python_attempts_total
                    result.python_failures += subresult.python_failures
                    trace = subresult.iterations[-1].python_trace if subresult.iterations else None
                    details = {"subprocess_reached": bool(trace and trace.subprocess_reached),
                               "blocked_stage": trace.blocked_stage if trace else "no_trace",
                               "source_complete": trace.source_complete if trace else None,
                               "python_calls": subresult.python_calls_total}
                    state.source_complete = trace.source_complete if trace else None
                    for computation in subresult.computations:
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
                    computation = await run_parameter_sweep(get_settings(), request, run_id,
                                                            simulation_spec, f"CALC{len(result.computations) + 1}",
                                                            simulation_source_id)
                    if simulation_source:
                        computation.formula_evidence_ids = [simulation_source]
                        computation.source_evidence_ids = [simulation_source]
                        computation.source_input_ids = list(dict.fromkeys(
                            [*computation.source_input_ids, *simulation_inputs]))
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
                                              simulation_spec, simulation_source_id)
                    simulation = next((item for item in result.computations
                                       if item.validation_passed and item.analysis_id.startswith("SIM-")), None)
                    latest_candidate = (self._simulation_answer(simulation, simulation_spec, evidence,
                                                                simulation_source_id, korean)
                                        if simulation and simulation_spec else
                                        self._api_gravity_answer(request, result.computations, evidence)
                                        or await self._synthesize(request, criteria, evidence, [],
                                                                  computations=result.computations))
                    if not result.computations:
                        latest_candidate = self._focus_research_answer(latest_candidate, criteria)
                    evaluation = await self.evaluator.evaluate(request, criteria, latest_candidate,
                                                               evidence, research_validation,
                                                               computations=result.computations)
                    if simulation:
                        evaluation = self._deterministic_simulation_criteria(
                            evaluation, criteria, latest_candidate, simulation, korean)
                    self._assert_criteria_frozen(criteria, criteria_hash)
                    state.current_coverage = evaluation.coverage
                    state.unresolved_information = evaluation.gaps[:5]
                    by_id = {item.criterion_id: item for item in evaluation.criteria}
                    for item in state.criteria:
                        value = by_id.get(item.criterion_id)
                        if value:
                            item.status = value.status
                            item.support_ids = value.supporting_evidence
                            item.missing_requirements = [] if value.status == CriterionStatus.MET else evaluation.gaps[:3]
                    requires_computation = bool(re.search(r"\b(?:calculat|comput|simulat|sweep)\w*\b|계산|시뮬레이션",
                                                          request.goal or request.topic, re.I)
                                                or asks_for_api_gravity_calculation(request))
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
                details = {"error_type": type(exc).__name__}

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
            if state.synthesized and state.goal_achieved:
                self._record_stop(result, state, "goal_achieved")
                return self._finish(result, GoalRunStatus.COMPLETED, GoalStatus.ACHIEVED,
                                    GoalStopReason.GOAL_ACHIEVED, latest_candidate, started)

        reason = (GoalStopReason.GOAL_ACHIEVED if state.goal_achieved else
                  GoalStopReason.INSUFFICIENT_EVIDENCE if state.blocked_reasons and not state.computation_ids else
                  GoalStopReason.MAX_ITERATIONS)
        self._record_stop(result, state, reason.value)
        formula_unverified = (autonomous_python and requires_sourced_formula and
                              not state.goal_achieved and not state.computation_ids)
        return self._finish(result, GoalRunStatus.COMPLETED if state.goal_achieved else GoalRunStatus.STOPPED,
                            GoalStatus.ACHIEVED if state.goal_achieved else GoalStatus.STOPPED,
                            reason, self._safe_unavailable_answer(latest_candidate, state,
                                                                  reason="missing_validated_formula" if formula_unverified else "",
                                                                  korean=korean), started)
