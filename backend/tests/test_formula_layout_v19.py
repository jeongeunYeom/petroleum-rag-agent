"""Fresh, non-benchmark source-layout and dimensional safety regressions."""

import ast

import pytest

from app.models.goal_research_schemas import GoalStatus
from app.services.calculation_requirements import infer_dimensionless, normalize_symbol
from app.services.formula_layout_normalizer import isolate_equation, normalize_extracted_equation
from app.services.formula_source_registry import FormulaSourceRegistry, source_contains_equation
from app.services.formula_units import formula_output_unit
from test_agent_reliability_v19_dev import actions, execute


def unit(expression, units, values=None):
    return formula_output_unit(ast.parse(expression, mode="eval").body, units, values)


@pytest.mark.parametrize("expression,units,values,expected", [
    ("F*Rw/(Sw**n)", {"F": "dimensionless", "Rw": "ohm-m",
                     "Sw": "dimensionless", "n": "dimensionless"}, {"n": 2}, "ohm-m"),
    ("distance/time", {"distance": "ft", "time": "s"}, None, "ft/s"),
    ("pressure*distance", {"pressure": "psi", "distance": "ft"}, None, "psi*ft"),
    ("pressure+pressure", {"pressure": "psi"}, None, "psi"),
    ("length/width", {"length": "ft", "width": "ft"}, None, ""),
    ("length**2", {"length": "ft"}, None, "ft^2"),
    ("length**power", {"length": "ft", "power": "dimensionless"}, {"power": 2}, "ft^2"),
    ("volume/time", {"volume": "bbl", "time": "day"}, None, "bbl/day"),
])
def test_unit_propagation(expression, units, values, expected):
    assert unit(expression, units, values) == expected


@pytest.mark.parametrize("expression,units,values", [
    ("pressure+distance", {"pressure": "psi", "distance": "ft"}, None),
    ("length**power", {"length": "ft", "power": "psi"}, {"power": 2}),
    ("length**power", {"length": "ft", "power": "dimensionless"}, None),
])
def test_incompatible_or_unbound_dimensional_exponent_blocks(expression, units, values):
    with pytest.raises(ValueError):
        unit(expression, units, values)


def test_dimensionless_cannot_bleed_from_neighboring_saturation_sentence():
    source = "Rw is formation water resistivity. Water saturation is a fraction of pore volume."
    assert infer_dimensionless("Rw", source) is None
    assert infer_dimensionless("Sw", "Sw is the water saturation fraction.") is not None


def test_non_archie_stacked_fraction_preserves_exact_span():
    raw = "Q = k A\nmu L"
    source = ("Equation 3 flow relation. Q is flow rate. k is permeability. "
              "A is area. mu is viscosity. L is length.\n" + raw)
    registry = FormulaSourceRegistry.from_evidence([{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": source,
        "document": "synthetic-flow.pdf", "page": 7}])
    record = next(row for row in registry.records if row.lhs == "Q")
    assert record.raw_span == raw
    assert record.expression_candidate == "Q = (k*A)/(mu*L)"
    assert record.normalized_expression == record.expression_candidate
    assert record.layout_transformations == ["stacked_fraction", "implicit_multiplication"]
    assert record.source_document == "synthetic-flow.pdf" and record.source_page == 7
    assert source_contains_equation(record, source)
    assert not source_contains_equation(record.model_copy(update={"expression_candidate": "Q=k*A*mu*L"}), source)


def test_exponent_on_own_line_and_bounded_target_isolation():
    raw = "P\n2 = X"
    source = "Equation 4. P is a measured quantity. X is its squared result.\n" + raw
    layout = normalize_extracted_equation(raw, source)
    assert layout.normalized_expression == "P**2 = X"
    registry = FormulaSourceRegistry.from_evidence([{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": source}])
    record = next(row for row in registry.records if row.lhs == "X")
    assert source_contains_equation(record, source)
    assert record.source_equation == "P**2 = X"
    assert record.formula_derivation == "algebraic_isolation"
    assert isolate_equation("Y = A + X", "X") == "X = (Y)-(A)"
    assert isolate_equation("Y = A - X", "X") == "X = (A)-(Y)"
    assert isolate_equation("Y = A * X", "X") == "X = (Y)/(A)"
    assert isolate_equation("Y = A / X", "X") == "X = (A)/(Y)"
    assert isolate_equation("Y = X / A", "X") == "X = (Y)*(A)"
    assert isolate_equation("Y = X**2", "X") is None


def test_implicit_product_only_inside_supported_equation_block():
    raw = "Y = A B / C"
    source = "Equation 5. A is area. B is factor. C is coefficient.\n" + raw
    record = next(row for row in FormulaSourceRegistry.from_evidence([{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": source}]).records
        if row.lhs == "Y")
    assert record.expression_candidate == "Y = A*B / C"
    assert source_contains_equation(record, source)
    assert normalize_extracted_equation(raw, raw).normalized_expression is None
    parenthesized = "Y = A (B+C)"
    context = "Equation 6. A is a factor. B is a term. C is a term. " + parenthesized
    assert normalize_extracted_equation(parenthesized, context).normalized_expression == "Y = A*(B+C)"
    captioned = "A is a factor. B is a factor.\nY = A B\nEquation 7 product relation"
    rows = FormulaSourceRegistry.from_evidence([{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": captioned}]).records
    assert any(row.expression_candidate == "Y = A*B" for row in rows)


def test_subscript_aliases_are_narrow():
    assert normalize_symbol("P_wf") == normalize_symbol("Pwf")
    assert normalize_symbol("Rₓ") == normalize_symbol("Rx")
    assert normalize_symbol("qₒ") == normalize_symbol("qo")
    assert normalize_symbol("Pwf") != normalize_symbol("Pws")


def test_ambiguous_stack_does_not_run_python(tmp_path, monkeypatch):
    raw = "Q = A B\nC"
    layout = normalize_extracted_equation(raw, raw)
    assert layout.is_ambiguous and layout.normalized_expression is None
    result, _, _ = execute(tmp_path, monkeypatch,
        "A=2 ft, B=3 ft, C=4 ft. Find the internal Q relation and calculate Q.",
        [[(4, raw)]])
    assert result.status != GoalStatus.ACHIEVED
    assert not result.computations and result.python_calls_total == 0
    assert result.telemetry["formula_layout_ambiguous"]
    assert "calculate" not in actions(result)


def test_prose_without_equation_is_not_reconstructed():
    source = "Pressure and flow are discussed on separate lines.\nP\nX is a field observation."
    assert FormulaSourceRegistry.from_evidence([{
        "evidence_id": "KB1", "source_type": "knowledge_base", "text": source}]).records == []


def test_unit_evidence_rejects_wrong_layout():
    raw = "Q = A B\nC"
    layout = normalize_extracted_equation(raw, raw, known_units={
        "Q": "psi", "A": "psi", "B": "ft", "C": "ft"})
    assert layout.normalized_expression == "Q = (A*B)/(C)"
    assert layout.candidate_count == 2 and layout.rejected_candidates == ("Q = (A*B)*(C)",)
