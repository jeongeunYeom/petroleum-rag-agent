"""Fresh synthetic obligations; no observed benchmark questions or source pages."""

from types import SimpleNamespace

import pytest

from app.models.goal_research_schemas import GoalResearchRequest
from app.services.goal_execution_state import RequiredGoal
from app.services.required_goals import (GoalProof, check_required_goals,
                                         parse_required_goals, repair_required_answer)


def request(text):
    return GoalResearchRequest(topic=text, goal=text, execution_mode="autonomous_goal_execution")


def numeric(name="X", value=12.5, unit="psi", calc_id="CALC1"):
    return SimpleNamespace(validation_passed=True, contract_validation_passed=True,
                           computation_id=calc_id,
                           output_manifest={"OUT_RESULT": {"name": name, "value": value, "unit": unit}})


def goal(kind, target, number):
    return RequiredGoal(goal_id=f"G{number}", goal_type=kind, semantic_target=target,
                        source_text_span=target, requires_evidence=kind.startswith("knowledge"),
                        requires_calculation=kind == "numeric_calculation")


SOURCE = [{"evidence_id": "KB1", "source_type": "knowledge_base", "document": "Synthetic handbook",
           "page": 7, "text": "Permeability affects mobility. Higher permeability increases mobility."}]


@pytest.mark.parametrize("text,expected", [
    ("Explain how permeability affects mobility, then calculate X.",
     ["knowledge_explanation", "numeric_calculation"]),
    ("Calculate X and explain how permeability affects mobility.",
     ["numeric_calculation", "knowledge_explanation"]),
    ("Find the relation between permeability and mobility, then compute X.",
     ["knowledge_explanation", "numeric_calculation"]),
    ("관계를 설명하고 X를 계산해줘", ["knowledge_explanation", "numeric_calculation"]),
    ("X를 계산하고 이동도 관계를 설명해줘", ["numeric_calculation", "knowledge_explanation"]),
    ("압력과 X 관계식을 각각 찾아 X를 계산해줘", ["knowledge_relation", "numeric_calculation"]),
    ("Calculate X and explain what it means.", ["numeric_calculation", "knowledge_explanation"]),
    ("Explain a relation and compute X.", ["knowledge_explanation", "numeric_calculation"]),
])
def test_multi_goal_parse(text, expected):
    parsed = parse_required_goals(request(text), "kb_formula_calc", "X")
    assert [item.goal_type for item in parsed] == expected
    assert [item.goal_id for item in parsed] == ["G1", "G2"]
    assert all(item.source_text_span for item in parsed)


@pytest.mark.parametrize("answer,have_source,have_calc,expected", [
    ("X: 12.5 psi [CALC1]", True, True, ["PARTIAL", "MET"]),
    ("X: 12.5 psi [CALC1]", False, True, ["UNMET", "MET"]),
    ("Permeability affects mobility. [KB1]", True, True, ["MET", "PARTIAL"]),
    ("Permeability affects mobility. [KB1]\nX: 12.5 psi [CALC1]", True, True, ["MET", "MET"]),
    ("X: 12.5 psi [CALC1]", True, False, ["PARTIAL", "UNMET"]),
    ("X: 12.5 psi [KB1]", True, True, ["PARTIAL", "PARTIAL"]),
])
def test_conceptual_numeric_completion(answer, have_source, have_calc, expected):
    goals = [goal("knowledge_relation", "permeability affects mobility", 1),
             goal("numeric_calculation", "X", 2)]
    checked, _ = check_required_goals(goals, request("Explain permeability and calculate X"),
                                      answer, SOURCE if have_source else [],
                                      [numeric()] if have_calc else [])
    assert [item.status for item in checked] == expected


@pytest.mark.parametrize("answer,expected", [
    ("A: 12.5 psi [CALC1]", ["MET", "PARTIAL"]),
    ("B: 18.0 psi [CALC2]", ["PARTIAL", "MET"]),
    ("A: 12.5 psi [CALC1]\nB: 18.0 psi [CALC2]", ["MET", "MET"]),
    ("A: 12.5 psi [CALC1]\nB: 18.0 psi [CALC1]", ["MET", "PARTIAL"]),
])
def test_multiple_numeric_outputs(answer, expected):
    checked, _ = check_required_goals([goal("numeric_calculation", "A", 1),
                                       goal("numeric_calculation", "B", 2)],
                                      request("Calculate A and B separately"), answer, [],
                                      [numeric("A"), numeric("B", 18.0, calc_id="CALC2")])
    assert [item.status for item in checked] == expected


@pytest.mark.parametrize("answer,expected", [
    ("Permeability affects mobility. [KB1]", ["MET", "PARTIAL"]),
    ("Higher permeability increases mobility. [KB1]", ["PARTIAL", "MET"]),
    ("Permeability affects mobility. [KB1]\nHigher permeability increases mobility. [KB1]", ["MET", "MET"]),
    ("Permeability affects mobility.", ["PARTIAL", "PARTIAL"]),
])
def test_multiple_conceptual_claims(answer, expected):
    goals = [goal("knowledge_relation", "permeability affects mobility", 1),
             goal("knowledge_relation", "higher permeability increases mobility", 2)]
    checked, _ = check_required_goals(goals, request("Explain both relations"), answer, SOURCE, [])
    assert [item.status for item in checked] == expected


@pytest.mark.parametrize("answer,missing", [
    ("X: 12.5 psi [CALC1]", ["G1"]),
    ("Permeability affects mobility. [KB1]", ["G2"]),
    ("X: 12.5 psi [KB1]", ["G1", "G2"]),
    ("Permeability affects mobility. [KB1]\nX: 12.5 psi [CALC1]", []),
])
def test_post_synthesis_omission_detection(answer, missing):
    goals = [goal("knowledge_relation", "permeability affects mobility", 1),
             goal("numeric_calculation", "X", 2)]
    checked, _ = check_required_goals(goals, request("Explain the relation, then calculate X"),
                                      answer, SOURCE, [numeric()])
    assert [item.goal_id for item in checked if item.status != "MET"] == missing


@pytest.mark.parametrize("proofs,expected_attempt", [
    ({"G1": GoalProof("PARTIAL", ["KB1"], '"Permeability affects mobility." [KB1]')}, True),
    ({"G1": GoalProof("UNMET", [], "")}, False),
    ({"G1": GoalProof("PARTIAL", ["KB1"], '"Permeability affects mobility." [KB1]'),
      "G2": GoalProof("PARTIAL", ["KB1"], '"Permeability affects mobility." [KB1]')}, True),
])
def test_bounded_append_only_repair(proofs, expected_attempt):
    answer, attempted = repair_required_answer("X: 12.5 psi [CALC1]", list(proofs), proofs)
    assert attempted is expected_attempt
    assert answer.startswith("X: 12.5 psi [CALC1]")
    assert answer.count('"Permeability affects mobility."') <= 1


@pytest.mark.parametrize("text", [
    "Explain oil and gas flow.",
    "Describe porosity and permeability in a reservoir.",
    "Calculate the flow of oil and gas using supplied values.",
    "What is pressure and temperature coupling?",
    "유체와 암석의 상호작용을 설명해줘.",
])
def test_false_positive_noun_split_guard(text):
    assert len(parse_required_goals(request(text), "knowledge_qa", None)) == 1


@pytest.mark.parametrize("text,targets", [
    ("Calculate alpha and beta separately.", ["alpha", "beta"]),
    ("공극률과 투과도를 각각 설명해줘.", ["공극률", "투과도"]),
])
def test_explicit_each_creates_separate_targets(text, targets):
    parsed = parse_required_goals(request(text), "direct_calc", None)
    assert [item.semantic_target for item in parsed] == targets


@pytest.mark.parametrize("answer,expected", [
    ("A is higher than B. [CALC2]", "MET"),
    ("Calculation complete. [CALC2]", "PARTIAL"),
    ("A is higher than B.", "UNMET"),
])
def test_comparison_needs_validated_derived_conclusion(answer, expected):
    derived = numeric("ranking", value=1, unit="dimensionless", calc_id="CALC2")
    checked, _ = check_required_goals([goal("comparison", "compare A and B", 1)],
                                      request("Compare A and B"), answer, [], [derived])
    assert checked[0].status == expected
