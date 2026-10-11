"""Evaluation-only checks for frozen deterministic numeric rules."""

from score_results import numeric_ok


def task(value, units):
    return {"numeric_gold": {"value": value, "unit": units[0]},
            "accepted_units": units,
            "numeric_tolerance": {"absolute": 0.01, "relative": 0.001}}


def test_value_and_unit_required():
    item = task(44, ["bbl", "barrels"])
    assert numeric_ok(item, {"numeric_output": 44, "output_unit": "bbl"}, "Loss = 44 bbl")[0]
    assert not numeric_ok(item, {"numeric_output": 44, "output_unit": None}, "Loss = 44")[0]
    assert not numeric_ok(item, {"numeric_output": 45, "output_unit": "bbl"}, "Loss = 45 bbl")[0]


def test_dimensionless_marker_and_intermediate_number():
    item = task(0.22, ["dimensionless", "무차원", "unitless", "1"])
    assert numeric_ok(item, {"numeric_output": 0.22, "output_unit": "무차원"}, "fw = 0.22 무차원")[0]
    assert not numeric_ok(item, {"numeric_output": 0.22, "output_unit": "1"}, "fw = 0.22")[0]
    assert not numeric_ok(item, {"numeric_output": 0.22, "output_unit": "무차원"}, "입력 0.22; 결과는 미정입니다")[0]
