"""Fresh synthetic v21.1 source/layout/binding checks; no evaluation items."""

import asyncio
import pytest

from app.core.config import Settings
from app.models.goal_research_schemas import GoalResearchRequest
from app.services.formula_layout_normalizer import normalize_extracted_equation
from app.services.formula_source_registry import FormulaSourceRegistry, source_contains_equation
from app.services.source_answerability import SupportStatus, evaluate_claim_support
from app.services.source_local_aliases import bind_source_aliases
from app.services.sourced_conversion_units import sourced_conversion_units
from app.services.goal_simulation import formula_input_readiness, run_user_formula_calculation
from app.services.formula_dependency import resolve_formula_dependencies
from app.services.source_verification_text import verification_view
from app.services.user_fact_registry import UserFactRegistry


def row(text, source_id="KB1", document="synthetic-manual.pdf", page=7):
    return {"source_type": "knowledge_base", "evidence_id": source_id, "text": text,
            "document": document, "page": page, "locator": f"p.{page}"}


def support(question, rows):
    request = GoalResearchRequest(topic=question, goal=question, model="qwen3:8b",
                                  use_external=False, execution_mode="autonomous_goal_execution")
    return evaluate_claim_support(request, rows).claims[0]


@pytest.mark.parametrize("raw,expected", [
    ("produc-\ntivity index", "productivity index"),
    ("con-\r\n ductivity", "conductivity"),
    ("multi\u00adphase  flow", "multiphase flow"),
    ("pressure  \n  drawdown", "pressure drawdown"),
])
def test_pdf_verification_normalization(raw, expected):
    assert expected in verification_view(raw)


def test_lexical_hyphen_stays_distinct():
    assert verification_view("two-phase well-test") == "two-phase well-test"


@pytest.mark.parametrize("text,question", [
    ("X = A * B\nX = head pressure (psi)\nA = fluid density (ppg)\nB = depth (ft)",
     "How is fluid density related to head pressure?"),
    ("Y = K / M\nY = phase mobility (mD/cP)\nK = relative permeability (mD)\nM = viscosity (cP)",
     "How does relative permeability relate to phase mobility?"),
    ("F = R / T\nF = discharge flux (bbl/d)\nR = flow rate (bbl)\nT = duration (d)",
     "How does flow rate relate to discharge flux?"),
    ("P = 0.07 x W x H\nP = column pressure (psi)\nW = fluid weight (ppg)\nH = height (ft)",
     "How is fluid weight related to column pressure?"),
])
def test_literal_equation_and_local_definitions_support_qa(text, question):
    claim = support(question, [row(text)])
    assert claim.support_status == SupportStatus.SUPPORTED
    assert claim.supporting_spans[0] in text


@pytest.mark.parametrize("left,right,question", [
    ("The brine factor controls the interface response.",
     "The interface response is the capillary response.",
     "How does brine factor control capillary response?"),
    ("The polymer ratio determines the flow response.",
     "The flow response is the displacement response.",
     "How does polymer ratio determine displacement response?"),
    ("The pump setting reduces the vibration response.",
     "The vibration response is the rotor response.",
     "How does pump setting reduce rotor response?"),
])
def test_two_same_page_spans_can_support_one_relation(left, right, question):
    claim = support(question, [row(left, "KB1"), row(right, "KB2")])
    assert claim.support_status == SupportStatus.SUPPORTED
    assert claim.supporting_evidence_ids == ["KB1", "KB2"]


def test_two_documents_cannot_manufacture_relation():
    claim = support("How does brine factor control capillary response?", [
        row("The brine factor controls the interface response.", "KB1", "first.pdf"),
        row("The interface response is the capillary response.", "KB2", "second.pdf")])
    assert claim.support_status != SupportStatus.SUPPORTED


def test_unrelated_relation_word_is_not_support():
    claim = support("How does brine factor affect capillary response?", [
        row("The brine factor is listed in the catalog. The pump controls the capillary response.")])
    assert claim.support_status != SupportStatus.SUPPORTED


def test_korean_relation_matches_literally_sourced_english_meaning():
    text = "Permeability increases as porosity increases in the measured core samples."
    claim = support("공극률과 투과도의 관계를 설명해줘.", [row(text)])
    assert claim.support_status == SupportStatus.SUPPORTED
    assert claim.supporting_spans == [text]


def test_korean_relation_matches_equation_and_definitions():
    text = ("H = 0.073 x W x Z\nH = hydrostatic pressure (psi)\n"
            "W = mud density (ppg)\nZ = depth (ft)")
    claim = support("정수압과 이수 밀도의 관계를 설명해줘.", [row(text)])
    assert claim.support_status == SupportStatus.SUPPORTED
    assert claim.supporting_spans[0] in text


@pytest.mark.parametrize("raw,expected", [
    ("ED = R + DP\n0.08 x H", "ED = R + DP/(0.08*H)"),
    ("Y = A - B\n0.25 x D", "Y = A - B/(0.25*D)"),
    ("X = A + C\n(2 * H)", "X = A + C/((2 * H))"),
    ("Z = Q +\nP\n/\n(C*L)", "Z = Q + P/(C*L)"),
    ("T = A\n+ B", "T = A + B"),
])
def test_source_anchored_line_wraps(raw, expected):
    text = "The equation uses a fraction divided by depth.\n" + raw + "\nwhere variables are measured."
    layout = normalize_extracted_equation(raw, text)
    assert layout.normalized_expression == expected
    found = [record for record in FormulaSourceRegistry.from_evidence([row(text)]).records
             if record.raw_span.strip() == raw]
    assert found and source_contains_equation(found[0], text)
    assert found[0].raw_span in text


def test_ordinary_prose_after_equation_is_not_a_denominator():
    text = "The equation is X = A + B\nThe apparatus was cleaned after testing."
    records = FormulaSourceRegistry.from_evidence([row(text)]).records
    assert not any("apparatus" in record.raw_span for record in records)


@pytest.mark.parametrize("equation,definitions", [
    ("X = A + B", "X = density (ppg)\nA = fluid density (ppg)\nB = loss pressure (psi)"),
    ("Y = C - D", "Y = length (ft)\nC = path length (ft)\nD = elapsed time (s)"),
    ("Z = R + S", "Z = output rate (bbl/d)\nR = input rate (bbl/d)\nS = pressure (psi)"),
])
def test_incompatible_clipped_addition_rejected(equation, definitions):
    text = equation + "\n" + definitions
    assert not any(record.raw_span.strip() == equation and record.expression_candidate
                   for record in FormulaSourceRegistry.from_evidence([row(text)]).records)


@pytest.mark.parametrize("symbol,definition,label,unit", [
    ("DPa", "annulus pressure drop", "annular pressure loss", "psi"),
    ("DL", "pipe friction pressure loss", "pipe friction pressure loss", "psi"),
    ("H", "depth", "TVD", "ft"),
    ("Kx", "lateral permeability", "lateral permeability", "mD"),
])
def test_source_local_alias_binding(symbol, definition, label, unit):
    text = f"X = {symbol} / C\n{symbol} = {definition} ({unit})\nC = scale constant (dimensionless)"
    formula = next(record for record in FormulaSourceRegistry.from_evidence([row(text)]).records
                   if record.raw_span.strip() == f"X = {symbol} / C")
    facts = UserFactRegistry.from_topic(f"{label}=321 {unit}")
    bound, aliases = bind_source_aliases(formula, [row(text)], facts)
    assert bound[symbol].value == 321
    assert aliases[0].raw_span in text


def test_same_unit_does_not_create_semantic_alias():
    text = "X = Q / C\nQ = annular pressure loss (psi)\nC = coefficient (dimensionless)"
    formula = next(record for record in FormulaSourceRegistry.from_evidence([row(text)]).records
                   if record.raw_span.strip() == "X = Q / C")
    bound, _ = bind_source_aliases(formula, [row(text)], UserFactRegistry.from_topic("tank pressure=321 psi"))
    assert "Q" not in bound


def test_competing_local_definitions_are_ambiguous():
    text = ("X = Q / C\nQ = annular pressure loss (psi)\n"
            "Q = reservoir pressure (psi)\nC = coefficient (dimensionless)")
    formula = next(record for record in FormulaSourceRegistry.from_evidence([row(text)]).records
                   if record.raw_span.strip() == "X = Q / C")
    bound, _ = bind_source_aliases(formula, [row(text)], UserFactRegistry.from_topic("annular pressure loss=321 psi"))
    assert "Q" not in bound


def test_duplicate_user_labels_are_ambiguous():
    text = "X = Q / C\nQ = annular pressure loss (psi)\nC = coefficient (dimensionless)"
    formula = next(record for record in FormulaSourceRegistry.from_evidence([row(text)]).records
                   if record.raw_span.strip() == "X = Q / C")
    facts = UserFactRegistry.from_topic("annular pressure loss=321 psi, annular pressure loss=350 psi")
    bound, _ = bind_source_aliases(formula, [row(text)], facts)
    assert "Q" not in bound


def test_wrapped_source_aliases_and_validated_calculation_chain(tmp_path):
    text = "The equation is a pressure increment divided by depth.\nED = R + DP\n0.08 x H\nED = effective density (ppg)\nR = base density (ppg)"
    definitions = "DP = annular pressure loss (psi)\nH = depth (ft)"
    evidence = [row(text, "KB1", page=7), row(definitions, "KB2", page=8)]
    formula = next(item for item in FormulaSourceRegistry.from_evidence(evidence).records
                   if item.lhs == "ED" and item.layout_transformations)
    message = "R=9.1 ppg, TVD=6000 ft, annular pressure loss=200 psi"
    facts = UserFactRegistry.from_topic(message)
    aliases, sources = bind_source_aliases(formula, evidence, facts)
    constants, source_ids = sourced_conversion_units(formula, evidence)
    assert set(aliases) == {"DP", "H"}
    assert set(source_ids) == {"KB1", "KB2"}
    assert all(item.raw_span in evidence[int(item.source_id[-1])-1]["text"] for item in sources)
    assert formula_input_readiness(formula.expression_candidate, facts, aliases, constants)[1] == []
    request = GoalResearchRequest(topic=message, goal=message, allow_python_execution=True,
                                  python_execution_approved=True,
                                  execution_mode="autonomous_goal_execution")
    calc = asyncio.run(run_user_formula_calculation(
        Settings(data_dir=tmp_path), request, "synthetic-wrap", formula.expression_candidate,
        facts, "CALC1", formula.source_id, original_text=message,
        source_aliases=aliases, constant_units=constants))
    assert calc.validation_passed
    assert calc.output["OUT_RESULT"] == pytest.approx(9.1 + 200/(0.08*6000))
    assert calc.formula_source_ids == ["KB1"]
    assert set(calc.input_fact_ids) == {fact.fact_id for fact in facts.records}


def test_unit_definition_is_not_executable_dependency():
    evidence = [row("The relation is pressure loss divided by depth.\nX = P / H", page=7),
                row("H = depth (ft)\nP = annular pressure loss (psi)", "KB2", page=8)]
    formula = next(item for item in FormulaSourceRegistry.from_evidence(evidence).records
                   if item.lhs == "X")
    assert not any(item.lhs == "H" and item.expression_candidate
                   for item in FormulaSourceRegistry.from_evidence(evidence).records)
    facts = UserFactRegistry.from_topic("TVD=5000 ft, annular pressure loss=300 psi")
    aliases, _ = bind_source_aliases(formula, evidence, facts)
    plan = resolve_formula_dependencies(formula, evidence, facts, [], [], source_aliases=aliases)
    assert plan.next_formula and plan.next_formula.equation_ast == formula.equation_ast
    assert not plan.missing_inputs
