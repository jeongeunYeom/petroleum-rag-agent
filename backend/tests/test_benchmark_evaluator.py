from app.services.benchmark_evaluator import (
    STRICT_REFUSAL,
    evaluate_benchmark_answer,
)
from app.services.refusal_policy import NO_EVIDENCE_REFUSAL


WT1 = {
    "id": "WT-001",
    "expected_behavior": "answer",
    "expected_document": "Well_Test_Analysis.pdf",
    "preferred_pages": [219],
    "required_patterns": [
        (
            r"(wellbore\s*storage|유정\s*저장).{0,240}"
            r"(pressure|압력).{0,100}(derivative|미분)"
            r".{0,100}(겹|overlap)"
        ),
        (
            r"(radial\s*flow|방사\s*유동).{0,240}"
            r"(derivative|미분).{0,100}"
            r"(plateau|평탄|수평|일정)"
        ),
    ],
    "forbidden_patterns": [
        (
            r"(radial\s*flow|방사\s*유동).{0,180}"
            r"(pressure|압력).{0,120}"
            r"(unit[- ]?slope|단위\s*기울기)"
        )
    ],
}

SOURCES = [
    {
        "document": "Well_Test_Analysis.pdf",
        "page": 219,
    }
]


def test_correct_answer_passes():
    answer = (
        "Wellbore storage에서는 pressure와 derivative가 "
        "서로 겹쳐 unit-slope diagonal을 따른다. "
        "Radial flow에서는 derivative가 일정해져 "
        "수평 plateau를 형성한다."
    )
    result = evaluate_benchmark_answer(
        WT1,
        answer,
        sources=SOURCES,
    )
    assert result.passed is True
    assert result.answer_passed is True
    assert result.hallucination_detected is False
    assert result.preferred_page_hit is True
    assert result.expected_document_hit is True


def test_affirmative_forbidden_claim_fails():
    answer = (
        "Wellbore storage에서는 pressure와 derivative가 "
        "서로 겹친다. Radial flow에서는 pressure가 "
        "unit-slope를 따른다. Radial flow derivative는 "
        "plateau를 형성한다."
    )
    result = evaluate_benchmark_answer(
        WT1,
        answer,
        sources=SOURCES,
    )
    assert result.passed is False
    assert result.answer_passed is False
    assert result.hallucination_detected is True
    assert result.forbidden_hits


def test_negated_correction_does_not_trigger_forbidden():
    answer = (
        "Wellbore storage에서는 pressure와 derivative가 "
        "서로 겹친다. Radial flow에서는 pressure가 "
        "unit-slope를 따르지 않는다. Radial flow에서는 "
        "derivative가 수평 plateau를 형성한다."
    )
    result = evaluate_benchmark_answer(
        WT1,
        answer,
        sources=SOURCES,
    )
    assert result.forbidden_hits == []


def test_contrast_clause_does_not_cross_trigger_forbidden():
    answer = (
        "Wellbore storage pressure and derivative overlap on a unit-slope line, "
        "while radial flow has a horizontal constant derivative plateau."
    )

    result = evaluate_benchmark_answer(WT1, answer, sources=SOURCES)

    assert result.forbidden_hits == []
    assert result.hallucination_detected is False


def test_shared_contrast_preamble_uses_nearest_regime_attribution():
    answer = (
        "Wellbore storage and radial flow can be distinguished on the pressure "
        "derivative plot: wellbore storage shows a unit-slope line, while radial "
        "flow shows a horizontal derivative plateau."
    )

    result = evaluate_benchmark_answer(WT1, answer, sources=SOURCES)

    assert result.forbidden_hits == []


def test_radial_unit_slope_claim_still_triggers_forbidden():
    result = evaluate_benchmark_answer(
        WT1,
        "Radial flow pressure follows a unit-slope line.",
        sources=SOURCES,
    )

    assert result.forbidden_hits


def test_plateau_transition_is_not_wellbore_storage_attribution():
    item = {
        "expected_behavior": "answer",
        "required_patterns": [],
        "forbidden_patterns": [
            r"(plateau|horizontal).{0,160}(wellbore\s*storage)"
        ],
    }

    transition = evaluate_benchmark_answer(
        item,
        "The plateau begins after the wellbore storage period ends.",
    )
    attribution = evaluate_benchmark_answer(
        item,
        "The plateau is a wellbore storage response.",
    )

    assert transition.forbidden_hits == []
    assert attribution.forbidden_hits


def test_supercharging_removal_vocabulary_and_unrelated_claim():
    item = {
        "expected_behavior": "answer",
        "required_patterns": [
            r"supercharg",
            r"eliminat|discriminat(?:e|ed)\s*out|exclude|remove",
        ],
        "forbidden_patterns": [r"equipment\s*failure|sensor\s*failure"],
    }

    eliminated = evaluate_benchmark_answer(
        item,
        "Two supercharged points were eliminated from consideration.",
    )
    discriminated = evaluate_benchmark_answer(
        item,
        "Supercharged points were discriminated out.",
    )
    unrelated = evaluate_benchmark_answer(
        item,
        "Supercharged points indicate sensor failure.",
    )

    assert eliminated.answer_passed is True
    assert discriminated.answer_passed is True
    assert unrelated.answer_passed is False


def test_varied_gradient_wording_satisfies_rft_semantics():
    item = {
        "expected_behavior": "answer",
        "required_patterns": [
            r"(?:multiple|several|varied|range\s+of).{0,60}gradients?"
        ],
        "forbidden_patterns": [],
    }

    assert evaluate_benchmark_answer(
        item,
        "Production data show a more varied gradient pattern.",
    ).answer_passed is True
    assert evaluate_benchmark_answer(
        item,
        "Production data show a range of gradients.",
    ).answer_passed is True


def test_exact_refusal_behavior():
    item = {
        "expected_behavior": "refuse",
        "expected_document": None,
        "preferred_pages": [],
        "required_patterns": [],
        "forbidden_patterns": [],
    }
    passed = evaluate_benchmark_answer(
        item,
        STRICT_REFUSAL,
        sources=[],
    )
    failed = evaluate_benchmark_answer(
        item,
        "문서에는 없지만 14,000 m3/day입니다.",
        sources=[],
    )
    assert passed.passed is True
    assert failed.passed is False


def test_research_safe_refusal_passes_without_exact_string_match():
    item = {
        "expected_behavior": "refuse",
        "required_patterns": [],
        "forbidden_patterns": [],
    }

    result = evaluate_benchmark_answer(item, NO_EVIDENCE_REFUSAL, sources=[])

    assert result.behavior_passed is True
    assert result.answer_passed is True
    assert result.passed is True
    assert result.hallucination_detected is False


def test_refusal_with_fabricated_number_fails():
    item = {
        "expected_behavior": "refuse",
        "required_patterns": [],
        "forbidden_patterns": [],
    }

    result = evaluate_benchmark_answer(
        item,
        "근거를 찾지 못해 추측하지 않지만 값은 14,000 psi입니다.",
        sources=[],
    )

    assert result.behavior_passed is False
    assert result.answer_passed is False
    assert result.hallucination_detected is True


def test_refusal_expected_but_general_answer_fails():
    item = {
        "expected_behavior": "refuse",
        "required_patterns": [],
        "forbidden_patterns": [],
    }

    result = evaluate_benchmark_answer(
        item,
        "일반적으로 radial flow에서는 derivative plateau가 나타납니다.",
        sources=[],
    )

    assert result.answer_passed is False
    assert result.hallucination_detected is True


def test_engineering_evidence_is_scoped_to_sentence_citations():
    item = {
        "expected_behavior": "answer",
        "required_patterns": [],
        "forbidden_patterns": [],
    }
    answer = "Radial flow has a horizontal constant derivative plateau. [KB1][KB2]"
    sources = [
        {
            "evidence_id": "KB1",
            "excerpt": "Radial flow has a horizontal constant derivative plateau.",
        },
        {
            "evidence_id": "KB2",
            "excerpt": "A different passage associates radial flow with unit-slope.",
        },
    ]

    result = evaluate_benchmark_answer(item, answer, sources=sources)

    assert result.answer_passed is True
    assert result.engineering_contradiction_count == 0
    assert result.unsupported_engineering_claim_count == 0
    assert result.hallucination_detected is False


def test_missing_expected_document_fails():
    answer = (
        "Wellbore storage에서는 pressure와 derivative가 "
        "겹친다. Radial flow derivative는 plateau를 "
        "형성한다."
    )
    result = evaluate_benchmark_answer(
        WT1,
        answer,
        sources=[
            {
                "document": "Other_Document.pdf",
                "page": 219,
            }
        ],
    )
    assert result.passed is False
    assert result.expected_document_hit is False



def test_open_hyphen_circle_matches_supercharged_rule():
    item = {
        "expected_behavior": "answer",
        "expected_document": "Well_Test_Analysis.pdf",
        "preferred_pages": [441],
        "required_patterns": [
            r"supercharg",
            r"open[- ]?circle|제외|제거",
        ],
        "forbidden_patterns": [],
    }
    result = evaluate_benchmark_answer(
        item,
        "Supercharged points는 open-circle points로 표시된다.",
        sources=[
            {
                "document": "Well_Test_Analysis.pdf",
                "page": 441,
            }
        ],
    )
    assert result.passed is True


def test_shared_rft_unit_is_accepted():
    item = {
        "expected_behavior": "answer",
        "expected_document": "Well_Test_Analysis.pdf",
        "preferred_pages": [440],
        "required_patterns": [
            r"0\.29",
            r"0\.37",
            r"0\.42",
            r"psi\s*/\s*ft",
        ],
        "forbidden_patterns": [],
    }
    result = evaluate_benchmark_answer(
        item,
        "압력 기울기는 0.29, 0.37, 0.42 psi/ft이다.",
        sources=[
            {
                "document": "Well_Test_Analysis.pdf",
                "page": 440,
            }
        ],
    )
    assert result.passed is True



def test_wt007_comparison_sentence_is_not_false_positive():
    item = {
        "id": "WT-007",
        "expected_behavior": "answer",
        "expected_document": "Well_Test_Analysis.pdf",
        "preferred_pages": [439, 440],
        "required_patterns": [
            r"0\.34",
            r"0\.29",
            r"0\.37",
            r"0\.42",
            r"psi\s*/\s*ft|psi\s*per\s*ft",
            (
                r"(pressure\s*discontinu|압력\s*불연속|"
                r"permeability\s*barrier|투과(?:율|성)\s*장벽|"
                r"differential\s*depletion|차별적\s*고갈|"
                r"여러.{0,60}(gradient|구배|기울기)|"
                r"압력\s*분포.{0,80}(변화|달라))"
            ),
        ],
        "forbidden_patterns": [
            (
                r"(figure\s*2|appraisal)"
                r"(?![^.\n]{0,320}"
                r"(figure\s*3|after\s*significant\s*production|"
                r"rft\s*survey\s*after|생산\s*후))"
                r"[^.\n]{0,320}"
                r"0\.29[^.\n]{0,140}"
                r"0\.37[^.\n]{0,140}"
                r"0\.42"
            ),
        ],
    }

    answer = (
        "Figure 2 Appraisal RFT는 0.34 psi/ft이다. "
        "Figure 3 RFT Survey after Significant Production은 "
        "0.29, 0.37, 0.42 psi/ft이며 투과성 장벽으로 "
        "구분된다. 두 조사를 비교하면 Appraisal은 0.34 "
        "psi/ft이고 생산 후 조사는 0.29, 0.37, 0.42 "
        "psi/ft이다."
    )

    result = evaluate_benchmark_answer(
        item,
        answer,
        sources=[
            {
                "document": "Well_Test_Analysis.pdf",
                "page": 439,
            },
            {
                "document": "Well_Test_Analysis.pdf",
                "page": 440,
            },
        ],
    )

    assert result.passed is True
    assert result.forbidden_hits == []


def test_wt007_real_appraisal_misassignment_still_fails():
    item = {
        "id": "WT-007",
        "expected_behavior": "answer",
        "expected_document": "Well_Test_Analysis.pdf",
        "preferred_pages": [439, 440],
        "required_patterns": [],
        "forbidden_patterns": [
            (
                r"(figure\s*2|appraisal)"
                r"(?![^.\n]{0,320}"
                r"(figure\s*3|after\s*significant\s*production|"
                r"rft\s*survey\s*after|생산\s*후))"
                r"[^.\n]{0,320}"
                r"0\.29[^.\n]{0,140}"
                r"0\.37[^.\n]{0,140}"
                r"0\.42"
            ),
        ],
    }

    answer = (
        "Figure 2 Appraisal RFT에는 "
        "0.29, 0.37, 0.42 psi/ft 세 구간이 있다."
    )

    result = evaluate_benchmark_answer(
        item,
        answer,
        sources=[
            {
                "document": "Well_Test_Analysis.pdf",
                "page": 439,
            }
        ],
    )

    assert result.passed is False
    assert result.forbidden_hits


def test_engineering_metrics_detect_false_premise_agreement():
    item = {
        "question": (
            "Radial flow pressure and derivative overlap with unit-slope. Correct?"
        ),
        "expected_behavior": "answer",
        "required_patterns": [],
        "forbidden_patterns": [],
    }
    result = evaluate_benchmark_answer(
        item,
        "Correct. Radial flow pressure and derivative overlap with unit-slope.",
        sources=[
            {
                "excerpt": (
                    "Radial flow has a horizontal constant derivative plateau."
                )
            }
        ],
    )

    assert result.answer_passed is False
    assert result.engineering_contradiction_count >= 1
    assert result.false_premise_detected is True
    assert result.false_premise_correction_success is False


def test_engineering_metrics_accept_false_premise_correction():
    item = {
        "question": (
            "Radial flow pressure and derivative overlap with unit-slope. Correct?"
        ),
        "expected_behavior": "answer",
        "required_patterns": [],
        "forbidden_patterns": [],
    }
    result = evaluate_benchmark_answer(
        item,
        (
            "No. Radial flow does not have unit-slope and its pressure and "
            "derivative do not overlap. Wellbore storage pressure and derivative "
            "overlap on a unit-slope line. Radial flow derivative is a horizontal "
            "constant plateau."
        ),
        sources=[
            {
                "excerpt": (
                    "Wellbore storage pressure and derivative overlap on a unit-slope "
                    "line. Radial flow has a horizontal constant derivative plateau."
                )
            }
        ],
    )

    assert result.answer_passed is True
    assert result.engineering_contradiction_count == 0
    assert result.false_premise_correction_success is True
    assert result.unsupported_engineering_claim_count == 0


def test_engineering_metrics_count_unsupported_citation_meaning():
    item = {
        "question": "What is the spherical-flow derivative slope?",
        "expected_behavior": "answer",
        "required_patterns": [],
        "forbidden_patterns": [],
    }
    result = evaluate_benchmark_answer(
        item,
        "Spherical flow has a derivative slope = -1/2.",
        sources=[
            {"excerpt": "Linear flow has a derivative slope = +1/2."}
        ],
    )

    assert result.answer_passed is False
    assert result.unsupported_engineering_claim_count == 1
