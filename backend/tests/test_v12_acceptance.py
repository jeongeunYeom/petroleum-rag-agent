"""Synthetic regressions for the old smoke harness's intermediate-result false positives."""

from scripts.v12_acceptance import ExpectedRun, assess


EXPECTED = ExpectedRun("direct_calc", "none", ("calculate", "verify", "synthesize"),
                       ("flow_rate",), 12.5, "stb/d")


def _success():
    return {"intent": "direct_calc", "source_requirement": "none", "facts": ["flow_rate"],
            "actions": ["calculate", "verify", "synthesize"], "calc_validated": True,
            "binding_pass": True,
            "numeric": 12.5, "unit": "stb/d", "provenance_complete": True,
            "answer": "Computed flow rate: 12.5 stb/d [CALC1]", "run_status": "completed",
            "status": "achieved", "stop_reason": "goal_achieved"}


def test_strict_smoke_rejects_partial_criteria_after_successful_calc():
    row = _success() | {"status": "stopped", "stop_reason": "max_iterations"}
    assert not assess(row, EXPECTED)["overall_pass"]


def test_strict_smoke_rejects_stopped_resume_even_after_correct_calc():
    expected = ExpectedRun(**(EXPECTED.__dict__ | {"resume": True}))
    row = _success() | {"initial_waiting": True, "missing_variable_pass": True,
                        "same_run": True, "prior_facts_kept": True, "followup_facts_merged": True,
                        "run_status": "stopped"}
    assert not assess(row, expected)["overall_pass"]


def test_strict_smoke_rejects_formula_found_without_calculation():
    row = _success() | {"actions": ["retrieve", "verify", "synthesize"], "calc_validated": False}
    assert not assess(row, EXPECTED)["overall_pass"]


def test_strict_smoke_rejects_missing_unit_or_provenance():
    for change in ({"unit": ""}, {"provenance_complete": False}):
        assert not assess(_success() | change, EXPECTED)["overall_pass"]


def test_strict_smoke_rejects_empty_final_answer():
    assert not assess(_success() | {"answer": ""}, EXPECTED)["overall_pass"]


def test_strict_smoke_rejects_wrong_fact_value_or_operation():
    expected = ExpectedRun(**(EXPECTED.__dict__ | {
        "fact_values": (("flow_rate", 20, "stb/d"),), "operation": "unit_conversion"}))
    row = _success() | {"fact_values": {"flow_rate": (12.5, "stb/d")},
                        "operation": "mean"}
    checks = assess(row, expected)
    assert not checks["fact_pass"] and not checks["operation_pass"]
