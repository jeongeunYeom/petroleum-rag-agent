import pytest

from app.services.engineering_validator import (
    EngineeringValidator,
    STRICT_REFUSAL,
)


SOURCES = [
    {
        "document": "Heriot-Watt_University_-_Well_Test_Analysis.pdf",
        "page": 219,
        "chunk_id": "p219:c0",
    }
]


def test_correct_regime_answer_passes():
    answer = (
        "Wellbore storage에서는 pressure와 pressure derivative가 "
        "겹치며 unit-slope diagonal을 따른다. "
        "Radial flow의 middle-time region에서는 pressure derivative가 "
        "수평 plateau를 형성한다. "
        "[Well Test Analysis, p.219]"
    )
    result = EngineeringValidator().validate_well_test_answer(
        "Wellbore storage와 radial flow를 구분해줘.",
        answer,
        retrieved_sources=SOURCES,
    )
    assert result.passed is True
    assert result.errors == []


def test_affirmative_radial_pressure_unit_slope_is_blocked():
    answer = (
        "Radial flow에서는 pressure가 unit-slope를 따른다. "
        "Wellbore storage에서는 pressure와 derivative가 겹치며 "
        "unit-slope를 따른다. "
        "Radial flow derivative는 plateau를 형성한다. "
        "[Well Test Analysis, p.219]"
    )
    result = EngineeringValidator().validate_well_test_answer(
        "Wellbore storage와 radial flow를 구분해줘.",
        answer,
        retrieved_sources=SOURCES,
    )
    assert result.passed is False
    assert "WT-RADIAL-001" in result.rule_ids


def test_negated_bad_claim_is_not_blocked():
    answer = (
        "Radial flow에서 pressure가 unit-slope를 따르는 것은 아니다. "
        "Wellbore storage에서는 pressure와 derivative가 겹치며 "
        "unit-slope를 따른다. "
        "Radial flow에서는 derivative가 수평 plateau를 형성한다. "
        "[Well Test Analysis, p.219]"
    )
    result = EngineeringValidator().validate_well_test_answer(
        "잘못된 설명을 검토해줘. Radial flow에서 pressure가 "
        "unit-slope를 따른다.",
        answer,
        retrieved_sources=SOURCES,
    )
    assert result.passed is True


def test_missing_radial_plateau_fails():
    answer = (
        "Wellbore storage에서는 pressure와 derivative가 겹치며 "
        "unit-slope를 따른다. [Well Test Analysis, p.219]"
    )
    result = EngineeringValidator().validate_well_test_answer(
        "Wellbore storage와 radial flow를 구분해줘.",
        answer,
        retrieved_sources=SOURCES,
    )
    assert result.passed is False
    assert "WT-RADIAL-003" in result.rule_ids


def test_no_sources_requires_exact_refusal():
    validator = EngineeringValidator()

    passed = validator.validate_well_test_answer(
        "문서에 없는 유전의 생산량을 알려줘.",
        STRICT_REFUSAL,
        retrieved_sources=[],
    )
    failed = validator.validate_well_test_answer(
        "문서에 없는 유전의 생산량을 알려줘.",
        "주입률은 14,000 m3/day입니다.",
        retrieved_sources=[],
    )

    assert passed.passed is True
    assert failed.passed is False
    assert "WT-EVIDENCE-001" in failed.rule_ids


def test_missing_citation_is_warning_not_error():
    answer = (
        "Wellbore storage에서는 pressure와 derivative가 겹치며 "
        "unit-slope를 따른다. Radial flow에서는 derivative가 "
        "수평 plateau를 형성한다."
    )
    result = EngineeringValidator().validate_well_test_answer(
        "Wellbore storage와 radial flow를 구분해줘.",
        answer,
        retrieved_sources=SOURCES,
    )
    assert result.passed is True
    assert result.warnings



def test_radial_derivative_unit_slope_is_blocked():
    answer = (
        "Wellbore storage에서는 pressure와 derivative가 겹치며 "
        "unit-slope를 따른다. "
        "Radial flow에서는 pressure derivative가 unit-slope를 "
        "따르면서 plateau를 형성한다. "
        "[Well Test Analysis, p.219]"
    )
    result = EngineeringValidator().validate_well_test_answer(
        "Wellbore storage와 radial flow를 구분해줘.",
        answer,
        retrieved_sources=SOURCES,
    )
    assert result.passed is False
    assert "WT-RADIAL-005" in result.rule_ids
    assert "WT-RADIAL-001" not in result.rule_ids


def test_pressure_derivative_is_not_bare_pressure():
    validator = EngineeringValidator()
    assert validator._mentions_derivative(
        "pressure derivative가 plateau를 형성한다"
    )
    assert not validator._mentions_pressure(
        "pressure derivative가 plateau를 형성한다"
    )



def test_supported_rft_comparison_refusal_is_blocked():
    sources = [
        {
            "document": "Well_Test_Analysis.pdf",
            "page": 440,
            "excerpt": (
                "title: Appraisal Well RFT Survey\n"
                "title: RFT Survey after Significant Production"
            ),
        }
    ]
    result = EngineeringValidator().validate_well_test_answer(
        (
            "Appraisal Well RFT Survey와 RFT Survey after "
            "Significant Production을 비교해줘."
        ),
        STRICT_REFUSAL,
        retrieved_sources=sources,
    )
    assert result.passed is False
    assert "WT-RFT-001" in result.rule_ids



def test_unit_slope_radial_association_is_blocked():
    answer = (
        "Unit-slope diagonal은 방사형 유동에서 나타난다. "
        "압력과 도함수 응답은 겹친다. "
        "[Well Test Analysis, p.219]"
    )
    result = EngineeringValidator().validate_well_test_answer(
        (
            "Log-log diagnostic plot에서 unit-slope diagonal은 "
            "어떤 유동 구간을 의미하는지 설명해줘."
        ),
        answer,
        retrieved_sources=SOURCES,
    )
    assert result.passed is False
    assert "WT-UNIT-002" in result.rule_ids


def test_rft_comparison_requires_all_gradients():
    sources = [
        {
            "document": "Well_Test_Analysis.pdf",
            "page": 440,
            "excerpt": (
                "Appraisal Well RFT Survey. "
                "RFT Survey after Significant Production."
            ),
        }
    ]
    answer = (
        "Figure 3은 0.29, 0.37, 0.42 psi/ft를 보인다. "
        "[Well Test Analysis, p.440]"
    )
    result = EngineeringValidator().validate_well_test_answer(
        (
            "Appraisal Well RFT Survey와 RFT Survey after "
            "Significant Production을 비교해줘."
        ),
        answer,
        retrieved_sources=sources,
    )
    assert result.passed is False
    assert "WT-RFT-002" in result.rule_ids


def test_open_circle_supercharged_answer_passes():
    answer = (
        "Supercharged points는 open-circle points로 표시된다. "
        "[Well Test Analysis, p.441]"
    )
    result = EngineeringValidator().validate_well_test_answer(
        (
            "RFT 그래프에서 supercharged points가 어떻게 "
            "표시되거나 처리되었는지 설명해줘."
        ),
        answer,
        retrieved_sources=SOURCES,
    )
    assert "WT-RFT-008" not in result.rule_ids


def test_fracture_omission_is_blocked():
    answer = (
        "Wellbore storage는 unit-slope를 보이고 radial flow는 "
        "derivative plateau를 보인다. "
        "[Well Test Analysis, p.219]"
    )
    result = EngineeringValidator().validate_well_test_answer(
        (
            "Wellbore storage, radial flow, fracture flow의 "
            "pressure derivative 특징을 설명해줘."
        ),
        answer,
        retrieved_sources=SOURCES,
    )
    assert result.passed is False
    assert "WT-FRACTURE-001" in result.rule_ids


@pytest.mark.parametrize(
    ("claim", "evidence"),
    [
        (
            "Wellbore storage has unit-slope pressure and derivative overlap.",
            "Wellbore storage has unit-slope pressure and derivative overlap.",
        ),
        (
            "Infinite-acting radial flow has a horizontal constant derivative plateau.",
            "Infinite-acting radial flow has a horizontal constant derivative plateau.",
        ),
        (
            "Spherical flow has a derivative slope = -1/2.",
            "Spherical flow has a derivative slope = -1/2.",
        ),
        (
            "Linear flow has a derivative slope = +1/2.",
            "Linear flow has a derivative slope = +1/2.",
        ),
        (
            "Late-time boundary behavior may show a unit-slope response.",
            "Late-time boundary behavior may show a unit-slope response.",
        ),
    ],
)
def test_claim_level_flow_regime_rules_pass(claim, evidence):
    result = EngineeringValidator().validate_claim(claim, evidence)

    assert result.passed is True
    assert result.engineering_contradiction_count == 0
    assert result.unsupported_engineering_claim_count == 0


def test_claim_level_radial_unit_slope_fails_even_with_similar_evidence():
    result = EngineeringValidator().validate_claim(
        "Radial flow has a unit-slope pressure derivative.",
        "Radial flow has a horizontal constant derivative plateau, not unit-slope.",
    )

    assert result.passed is False
    assert result.engineering_contradiction_count == 1
    assert result.reasons[0]["rule_id"] == "WT-REGIME-CONTRADICTION"


def test_false_premise_agreement_fails():
    detected, corrected, reasons = EngineeringValidator().false_premise_correction(
        "In radial flow, pressure and derivative overlap with unit-slope. Correct?",
        "Correct. Radial flow pressure and derivative overlap with unit-slope.",
    )

    assert detected is True
    assert corrected is False
    assert reasons


def test_false_premise_explicit_correction_passes():
    detected, corrected, reasons = EngineeringValidator().false_premise_correction(
        "In radial flow, pressure and derivative overlap with unit-slope. Correct?",
        (
            "No. Radial flow does not have unit-slope and its pressure and "
            "derivative do not overlap. Wellbore storage pressure and derivative "
            "overlap on a unit-slope line. Radial flow pressure derivative is a "
            "horizontal constant plateau."
        ),
    )

    assert detected is True
    assert corrected is True
    assert reasons == []


def test_conflicting_engineering_evidence_blocks_overconfident_claim():
    result = EngineeringValidator().validate_claim(
        "Spherical flow definitely has a derivative slope = -1/2.",
        (
            "Source A says spherical flow has slope = -1/2. "
            "Source B says spherical flow has slope = +1/2."
        ),
    )

    assert result.passed is False
    assert result.unsupported_engineering_claim_count == 1
    assert any(
        reason["rule_id"] == "WT-EVIDENCE-CONFLICT"
        for reason in result.reasons
    )


def test_citation_with_reversed_engineering_meaning_is_unsupported():
    result = EngineeringValidator().validate_claim(
        "Spherical flow has a derivative slope = -1/2.",
        "Linear flow has a derivative slope = +1/2.",
    )

    assert result.passed is False
    assert result.unsupported_engineering_claim_count == 1
    assert result.reasons[0]["rule_id"] == "WT-CITATION-MEANING"


def test_boundary_unit_slope_requires_late_time_or_conditional_context():
    result = EngineeringValidator().validate_claim(
        "Boundary behavior always has unit-slope.",
        "Boundary behavior always has unit-slope.",
    )

    assert result.passed is False
    assert result.reasons[0]["rule_id"] == "WT-BOUNDARY-CONTEXT"


def test_negated_radial_unit_slope_is_not_treated_as_positive_claim():
    result = EngineeringValidator().validate_claim(
        (
            "Radial flow pressure and derivative do not follow the same unit-slope "
            "line, but the derivative is horizontal."
        ),
        "On the diagnostic plot, radial flow is indicated by a horizontal derivative.",
    )

    assert result.passed is True


def test_quoted_false_premise_rejection_is_not_a_positive_attribution():
    result = EngineeringValidator().validate_claim(
        (
            "The premise that radial-flow pressure and derivative both follow a "
            "unit-slope line is incorrect. Radial flow has a horizontal derivative."
        ),
        "Radial flow is indicated by a horizontal derivative.",
    )

    assert result.passed is True


def test_boundary_context_does_not_attribute_plateau_to_boundary_flow():
    result = EngineeringValidator().validate_claim(
        "The interpretation of a radial-flow plateau may be affected by boundary effects.",
        "Radial flow is indicated by a horizontal derivative before boundary effects.",
    )

    assert result.engineering_contradiction_count == 0


def test_unrelated_regime_detail_does_not_create_evidence_conflict():
    result = EngineeringValidator().validate_claim(
        "Radial flow is indicated by a horizontal derivative.",
        (
            "Radial flow is indicated by a horizontal derivative. "
            "Volumetric flow can produce a unit-slope response."
        ),
    )

    assert result.passed is True
