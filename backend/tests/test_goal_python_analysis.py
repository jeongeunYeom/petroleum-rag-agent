from __future__ import annotations

import asyncio
import json

from app.core.config import Settings
from app.models.goal_research_schemas import GoalResearchRequest
from app.models.goal_research_schemas import GoalCriterion, CriterionStatus
from app.services.goal_evaluator import GoalEvaluator
from app.services.goal_python_analysis import GoalPythonAnalysis
from app.services.goal_tool_planner import InputFact, PythonAnalysisPlan


EVIDENCE = [
    {"evidence_id": "KB1", "source_type": "knowledge_base", "locator": "book p.1", "text": "Case A measures 10 mD."},
    {"evidence_id": "KB2", "source_type": "knowledge_base", "locator": "book p.2", "text": "Case B measures 20 mD."},
]


def plan(*, missing=False):
    return PythonAnalysisPlan(
        purpose="Calculate percent change from A to B",
        target_criteria=["C2"],
        input_facts=[
            InputFact(name="A", value=10, unit="mD", evidence_id="KB1", source_excerpt="Case A measures 10 mD."),
            InputFact(name="B", value=30 if missing else 20, unit="mD", evidence_id="KB2", source_excerpt="Case B measures 20 mD."),
        ],
    )


def code(name="analysis_001.json"):
    return (
        "import json\n"
        f"with open('{name}', 'w', encoding='utf-8') as handle:\n"
        "    json.dump({'inputs': {'A': 10, 'B': 20}, 'result': {'difference': 10, 'percent_change': 100}, 'summary': 'B is 100 percent above A.'}, handle)\n"
    )


class CodeOllama:
    def __init__(self, codes):
        self.codes = codes
        self.calls = 0

    async def chat_structured(self, *_args, **_kwargs):
        value = self.codes[min(self.calls, len(self.codes) - 1)]
        self.calls += 1
        return json.dumps({"code": value})


def setup(tmp_path, codes=None):
    settings = Settings(data_dir=tmp_path / "data", agent_workspace_dir=tmp_path / "workspace")
    ollama = CodeOllama(codes or [code()])
    return GoalPythonAnalysis(settings, ollama, "GR-TEST"), ollama


def approved(**kwargs):
    return GoalResearchRequest(
        topic="Compare A and B", allow_python_execution=True,
        python_execution_approved=True, **kwargs,
    )


def test_autonomous_calculation_runs_in_existing_sandbox(tmp_path):
    analysis, ollama = setup(tmp_path)
    record, executed = asyncio.run(analysis.execute(approved(), plan(), EVIDENCE))
    assert executed and record.validation_passed
    assert record.computation_id == "CALC1"
    assert record.source_evidence_ids == ["KB1", "KB2"]
    assert record.attempts == 1 and ollama.calls == 1
    assert (tmp_path / "workspace" / record.output_files[0]).is_file()


def test_python_requires_both_explicit_permissions(tmp_path):
    analysis, ollama = setup(tmp_path)
    for allow, approve in [(False, True), (True, False), (False, False)]:
        record, executed = asyncio.run(analysis.execute(GoalResearchRequest(topic="x", allow_python_execution=allow, python_execution_approved=approve), plan(), EVIDENCE))
        assert record is None and not executed
    assert analysis.calls == 0 and ollama.calls == 0


def test_missing_or_invented_input_is_rejected_before_code_generation(tmp_path):
    analysis, ollama = setup(tmp_path)
    record, executed = asyncio.run(analysis.execute(approved(), plan(missing=True), EVIDENCE))
    assert record is None and not executed
    assert analysis.calls == 0 and ollama.calls == 0


def test_python_repair_second_attempt_succeeds(tmp_path):
    analysis, ollama = setup(tmp_path, ["raise ValueError('first attempt')", code()])
    record, _ = asyncio.run(analysis.execute(approved(), plan(), EVIDENCE))
    assert record.validation_passed and record.attempts == 2
    assert analysis.attempts == 2 and ollama.calls == 2


def test_python_call_budget_and_dedup(tmp_path):
    analysis, ollama = setup(tmp_path)
    request = approved(max_python_calls=1)
    first, _ = asyncio.run(analysis.execute(request, plan(), EVIDENCE))
    second, executed = asyncio.run(analysis.execute(request, plan(), EVIDENCE))
    assert second.computation_id == first.computation_id and not executed
    excerpt_variant = plan()
    excerpt_variant.input_facts[0].source_excerpt = "10 mD"
    third, executed = asyncio.run(analysis.execute(request, excerpt_variant, EVIDENCE))
    assert third.computation_id == first.computation_id and not executed
    changed = plan().model_copy(update={"purpose": "Calculate raw difference"})
    blocked, executed = asyncio.run(analysis.execute(request, changed, EVIDENCE))
    assert blocked is None and not executed
    assert analysis.calls == 1 and ollama.calls == 1


def test_network_import_is_blocked_before_execution(tmp_path):
    analysis, _ = setup(tmp_path, ["import requests\n" + code()])
    record, executed = asyncio.run(analysis.execute(approved(max_python_attempts_per_call=1), plan(), EVIDENCE))
    assert executed and not record.validation_passed
    assert "Blocked Python import" in record.attempt_records[0]["error"]


def test_workspace_escape_is_blocked_before_execution(tmp_path):
    analysis, _ = setup(tmp_path, ["open('../../outside.json', 'w')\n" + code()])
    record, executed = asyncio.run(analysis.execute(approved(max_python_attempts_per_call=1), plan(), EVIDENCE))
    assert executed and not record.validation_passed
    assert "parent-directory" in record.attempt_records[0]["error"]


def test_formula_requires_source_provenance(tmp_path):
    analysis, ollama = setup(tmp_path)
    unsupported = plan().model_copy(update={"formula": "kh = k * h"})
    record, executed = asyncio.run(analysis.execute(approved(), unsupported, EVIDENCE))
    assert record is None and not executed and ollama.calls == 0


def test_basic_arithmetic_formula_does_not_mislabel_input_sources_as_formula_sources(tmp_path):
    analysis, _ = setup(tmp_path)
    arithmetic = plan().model_copy(update={
        "formula": "difference = B - A; percent_change = difference / A * 100",
        "supporting_evidence_ids": ["KB1", "KB2"],
    })
    record, executed = asyncio.run(analysis.execute(approved(), arithmetic, EVIDENCE))
    assert executed and record.validation_passed
    assert record.formula_evidence_ids == []


def test_unrelated_citation_cannot_ground_specialist_formula(tmp_path):
    analysis, ollama = setup(tmp_path)
    unsupported = plan().model_copy(update={
        "formula": "kh = k * h",
        "supporting_evidence_ids": ["KB1"],
    })
    record, executed = asyncio.run(analysis.execute(approved(), unsupported, EVIDENCE))
    assert record is None and not executed and ollama.calls == 0


def test_validated_png_chart_is_recorded(tmp_path):
    chart_code = code() + (
        "import matplotlib.pyplot as plt\n"
        "plt.bar(['A', 'B'], [10, 20])\n"
        "plt.savefig('analysis_001.png')\n"
    )
    analysis, _ = setup(tmp_path, [chart_code])
    chart_plan = plan().model_copy(update={"create_chart": True})
    record, executed = asyncio.run(analysis.execute(approved(), chart_plan, EVIDENCE))
    assert executed and record.validation_passed
    assert any(value.endswith(".png") for value in record.output_files)


def test_validated_csv_output_is_recorded(tmp_path):
    csv_code = code() + (
        "import csv\n"
        "with open('analysis_001.csv', 'w', newline='') as handle:\n"
        "    writer = csv.writer(handle)\n"
        "    writer.writerow(['case', 'value'])\n"
        "    writer.writerow(['A', 10])\n"
        "    writer.writerow(['B', 20])\n"
    )
    analysis, _ = setup(tmp_path, [csv_code])
    csv_plan = plan().model_copy(update={"expected_outputs": ["comparison.csv"]})
    record, executed = asyncio.run(analysis.execute(approved(), csv_plan, EVIDENCE))
    assert executed and record.validation_passed
    assert any(value.endswith(".csv") for value in record.output_files)


def test_nan_output_fails_result_validation(tmp_path):
    bad = (
        "import json\n"
        "with open('analysis_001.json', 'w') as handle:\n"
        "    json.dump({'inputs': {'A': 10, 'B': 20}, 'result': float('nan'), 'summary': 'invalid'}, handle)\n"
    )
    analysis, _ = setup(tmp_path, [bad])
    record, _ = asyncio.run(analysis.execute(approved(max_python_attempts_per_call=1), plan(), EVIDENCE))
    assert not record.validation_passed
    assert analysis.failures == 1


class CriterionOllama:
    async def chat_structured(self, *_args, **_kwargs):
        return json.dumps({
            "criteria": [{"criterion_id": "C1", "status": "met", "reason": "Calculation available", "supporting_evidence": ["CALC1"]}],
            "expected_result_status": "not_provided", "gaps": [],
            "next_research_need": None, "goal_conflicts_with_evidence": False,
        })


def test_quantitative_criterion_needs_validated_calc_and_original_provenance():
    criterion = GoalCriterion(criterion_id="C1", description="Calculate percent change")
    request = GoalResearchRequest(topic="Compare", success_criteria=[criterion], engineering_validation=False)
    evidence = [*EVIDENCE, {"evidence_id": "CALC1", "source_type": "calculation", "locator": "PA-001", "text": "B is 100 percent above A."}]
    evaluator = GoalEvaluator(CriterionOllama())
    without = asyncio.run(evaluator.evaluate(request, [criterion], "B is 100 percent above A [CALC1]", evidence, {}))
    assert without.criteria[0].status != CriterionStatus.MET
    from app.models.goal_research_schemas import ComputationRecord
    computation = ComputationRecord(
        computation_id="CALC1", analysis_id="PA-001", purpose="percent change",
        source_evidence_ids=["KB1", "KB2"], summary="B is 100 percent above A.",
        validation_passed=True,
    )
    with_calc = asyncio.run(evaluator.evaluate(
        request, [criterion], "B is 100 percent above A [CALC1][KB1][KB2]",
        evidence, {}, computations=[computation],
    ))
    assert with_calc.criteria[0].status == CriterionStatus.MET
    assert with_calc.criteria[0].supporting_evidence == ["CALC1", "KB1", "KB2"]
    assert with_calc.achieved


def test_chart_criterion_needs_actual_validated_png():
    criterion = GoalCriterion(criterion_id="C1", description="Generate a chart of values")
    request = GoalResearchRequest(topic="Compare", success_criteria=[criterion], engineering_validation=False)
    evidence = [*EVIDENCE, {"evidence_id": "CALC1", "source_type": "calculation", "locator": "PA-001", "text": "B is 100 percent above A."}]
    from app.models.goal_research_schemas import ComputationRecord
    computation = ComputationRecord(
        computation_id="CALC1", analysis_id="PA-001", purpose="comparison",
        source_evidence_ids=["KB1", "KB2"], validation_passed=True,
    )
    result = asyncio.run(GoalEvaluator(CriterionOllama()).evaluate(
        request, [criterion], "Values shown [CALC1][KB1][KB2]", evidence, {}, computations=[computation],
    ))
    assert result.criteria[0].status != CriterionStatus.MET
