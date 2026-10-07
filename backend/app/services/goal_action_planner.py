"""Choose one bounded action from observable goal state, never from hidden reasoning."""

from __future__ import annotations

import re

from app.models.goal_research_schemas import GoalResearchRequest
from app.services.goal_execution_state import GoalAction, GoalActionType, GoalExecutionState, SimulationSpec


CALC_WORDS = re.compile(r"\b(?:calculat\w*|comput\w*|derive|mean|average|rank\w*|compare\s+numeric|difference|ratio)\b|계산|산출|평균|순위", re.I)
ANALYZE_WORDS = re.compile(r"\b(?:rank\w*|best|worst|maximum|minimum|optim\w*|sensitiv\w*|compare)\b|순위|최적|민감도|최대|최소", re.I)
SIMULATE_WORDS = re.compile(r"\b(?:simulat\w*|sweep|parameter\s+range|vary\w*)\b|시뮬레이션|매개변수\s*변화|범위\s*탐색", re.I)


class GoalActionPlanner:
    """Deterministic action gate and malformed-LLM fallback for v8."""

    @staticmethod
    def select(
        request: GoalResearchRequest,
        state: GoalExecutionState,
        *,
        user_fact_ids: list[str],
        evidence_fact_ids: list[str] | None = None,
        formula_ready: bool,
        formula_id: str | None = None,
        python_calls_used: int = 0,
        simulation_spec: SimulationSpec | None,
    ) -> GoalAction:
        text = " ".join(filter(None, (request.topic, request.goal)))
        wants_simulation = bool(SIMULATE_WORDS.search(text) or simulation_spec)
        wants_calculation = bool(CALC_WORDS.search(text)) and not wants_simulation
        wants_analysis = bool(ANALYZE_WORDS.search(text))
        specialist = bool(re.search(r"\b(?:formula|equation|correlation|productivity\s+index)\b|공식|수식|관계식", text, re.I))
        permission = request.allow_python_execution and request.python_execution_approved
        numeric_inputs_ready = bool(user_fact_ids or evidence_fact_ids)
        required = [item.criterion_id for item in state.criteria if item.required and item.status.value != "met"]
        counts = {kind: sum(item.action_type == kind for item in state.completed_actions)
                  for kind in GoalActionType}
        last = state.completed_actions[-1] if state.completed_actions else None

        def action(kind: GoalActionType, reason: str, query: str | None = None) -> GoalAction:
            return GoalAction(action_id=f"ACT-{state.iteration + 1}", action_type=kind,
                              target_criteria=required, objective=reason.replace("_", " "),
                              query=query, reason_code=reason,
                              calculation_intent=request.goal if kind == GoalActionType.CALCULATE else None,
                              formula_id=formula_id if kind == GoalActionType.CALCULATE else None,
                              required_inputs=(user_fact_ids + (evidence_fact_ids or []))
                              if kind == GoalActionType.CALCULATE else [],
                              expected_outputs=[item.description for item in state.criteria
                                                if item.criterion_id in required]
                              if kind in {GoalActionType.CALCULATE, GoalActionType.SIMULATE} else [],
                              simulation_spec=simulation_spec if kind == GoalActionType.SIMULATE else None)

        if state.goal_achieved:
            return action(GoalActionType.STOP if state.synthesized else GoalActionType.SYNTHESIZE,
                          "goal_achieved")
        if state.no_progress_count >= request.no_progress_patience:
            return action(GoalActionType.STOP, "no_progress")
        if state.verified and last and last.action_type == GoalActionType.VERIFY:
            if (not wants_simulation and not state.computation_ids and state.unresolved_information
                    and counts[GoalActionType.RETRIEVE] < request.max_retrieval_actions):
                return action(GoalActionType.RETRIEVE, "missing_requirement",
                              GoalActionPlanner.query(request, state))
            return action(GoalActionType.STOP, "insufficient_evidence")
        if wants_simulation and not counts[GoalActionType.SIMULATE]:
            if not permission:
                return action(GoalActionType.STOP, "simulation_permission_required")
            if python_calls_used >= request.max_python_calls:
                return action(GoalActionType.STOP, "python_call_budget_exhausted")
            if request.max_simulation_actions == 0:
                return action(GoalActionType.STOP, "simulation_budget_exhausted")
            if simulation_spec is None:
                return action(GoalActionType.STOP, "simulation_spec_missing")
            return action(GoalActionType.SIMULATE, "simulation_inputs_ready")
        retry_after_gain = bool(last and last.action_type == GoalActionType.RETRIEVE and
                                last.evidence_added and not state.computation_ids)
        if (wants_calculation and not state.computation_ids and
                (not counts[GoalActionType.CALCULATE] or retry_after_gain) and
                counts[GoalActionType.CALCULATE] < request.max_python_calls):
            if not permission:
                if specialist and not counts[GoalActionType.RETRIEVE] and request.max_retrieval_actions:
                    return action(GoalActionType.RETRIEVE, "source_for_unapproved_calculation",
                                  GoalActionPlanner.query(request, state))
                return action(GoalActionType.STOP, "calculation_permission_required")
            if python_calls_used >= request.max_python_calls:
                return action(GoalActionType.STOP, "python_call_budget_exhausted")
            if numeric_inputs_ready and (not specialist or formula_ready):
                return action(GoalActionType.CALCULATE, "calculation_inputs_ready")
            if counts[GoalActionType.RETRIEVE] < request.max_retrieval_actions:
                return action(GoalActionType.RETRIEVE, "calculation_source_missing",
                              GoalActionPlanner.query(request, state))
            return action(GoalActionType.STOP, "calculation_blocked")
        if (wants_calculation or wants_simulation) and state.computation_ids and wants_analysis and not state.analyzed:
            return action(GoalActionType.ANALYZE, "derived_outputs_need_analysis")
        if last and last.action_type in {GoalActionType.CALCULATE, GoalActionType.SIMULATE} and last.status != "completed":
            if counts[GoalActionType.RETRIEVE] < request.max_retrieval_actions and request.use_internal:
                return action(GoalActionType.RETRIEVE, "calculation_failed_replan",
                              GoalActionPlanner.query(request, state))
            return action(GoalActionType.STOP, "calculation_blocked")
        if not state.evidence_ids and not state.computation_ids and counts[GoalActionType.RETRIEVE] < request.max_retrieval_actions:
            return action(GoalActionType.RETRIEVE, "initial_evidence_needed",
                          GoalActionPlanner.query(request, state))
        if not state.verified:
            if counts[GoalActionType.VERIFY] >= request.max_verification_actions:
                return action(GoalActionType.STOP, "verification_budget_exhausted")
            return action(GoalActionType.VERIFY, "verify_current_support")
        return action(GoalActionType.STOP, "insufficient_evidence")

    @staticmethod
    def query(request: GoalResearchRequest, state: GoalExecutionState) -> str:
        missing = "; ".join(state.unresolved_information[:3])
        unmet = "; ".join(item.description for item in state.criteria if item.required and item.status.value != "met")
        return f"{request.goal or request.topic}\nMissing: {missing or unmet or request.topic}"[:4000]
