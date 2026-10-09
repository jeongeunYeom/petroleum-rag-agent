from app.services.engineering import (
    EngineeringValidatorRegistry,
    ReservoirValidator,
    WellTestValidator,
)
from app.services.engineering_validator import EngineeringValidator


def registry() -> EngineeringValidatorRegistry:
    return EngineeringValidatorRegistry([WellTestValidator(), ReservoirValidator()])


def test_registry_routes_well_test_reservoir_unrelated_and_multi_domain() -> None:
    validator_registry = registry()
    assert validator_registry.domains("pressure derivative well test") == ["well_test"]
    assert validator_registry.domains("porosity and permeability") == ["reservoir"]
    assert validator_registry.domains("write a project summary") == []
    assert validator_registry.domains("pressure transient test permeability") == [
        "well_test",
        "reservoir",
    ]


def test_duplicate_validator_registration_is_ignored() -> None:
    validator_registry = registry()
    validator_registry.register(WellTestValidator())
    assert validator_registry.validator_names("well test") == ["WellTestValidator"]


def test_registry_preserves_multi_domain_issue_identity() -> None:
    result = registry().validate_claim(
        "pressure transient and porosity permeability",
        "Radial flow has unit-slope, and porosity means permeability.",
        "Radial flow has a horizontal derivative; porosity and permeability are distinct.",
    )
    assert result.passed is False
    assert {(item["domain"], item["code"]) for item in result.reasons} == {
        ("well_test", "WT-REGIME-CONTRADICTION"),
        ("reservoir", "RES-POR-001"),
    }


def test_porosity_definition_is_grounded_but_equating_it_to_permeability_fails() -> None:
    validator = EngineeringValidator()
    passed = validator.validate_claim(
        "Porosity is pore volume divided by bulk volume.",
        "Porosity is defined as pore volume divided by bulk volume.",
        query="explain porosity",
    )
    failed = validator.validate_claim(
        "Porosity means permeability.",
        "Porosity is pore volume divided by bulk volume; permeability describes flow capacity.",
        query="porosity and permeability",
    )
    assert passed.passed is True
    assert failed.reasons[0]["code"] == "RES-POR-001"


def test_phase_saturations_sum_to_one_and_sum_above_one_fails() -> None:
    validator = EngineeringValidator()
    relation = "Oil, water, and gas saturation sum to 1: So + Sw + Sg = 1."
    assert validator.validate_claim(
        relation,
        relation,
        query="oil water gas saturation",
    ).passed
    failed = validator.validate_claim(
        "Oil, water, and gas saturation total can exceed 1.",
        relation,
        query="oil water gas saturation",
    )
    assert failed.reasons[0]["code"] == "RES-SAT-001"


def test_porosity_does_not_deterministically_set_permeability() -> None:
    result = EngineeringValidator().validate_claim(
        "Higher porosity always means higher permeability.",
        "Permeability depends on pore connectivity and pore structure.",
        query="porosity permeability relationship",
    )
    assert result.passed is False
    assert result.reasons[0]["code"] == "RES-PERM-001"


def test_darcy_direction_and_permeability_flow_rules() -> None:
    validator = EngineeringValidator()
    correct = "Darcy flow proceeds from higher pressure to lower pressure and opposes the pressure gradient."
    assert validator.validate_claim(correct, correct, query="Darcy flow").passed
    wrong_direction = validator.validate_claim(
        "Darcy flow moves from low pressure to high pressure.",
        correct,
        query="Darcy flow",
    )
    wrong_permeability = validator.validate_claim(
        "Higher permeability reduces fluid flow.",
        "Under comparable conditions, higher permeability allows easier fluid flow.",
        query="permeability and Darcy flow",
    )
    assert wrong_direction.reasons[0]["code"] == "RES-DARCY-001"
    assert wrong_permeability.reasons[0]["code"] == "RES-DARCY-002"


def test_fvf_material_balance_and_drive_mechanisms_are_grounded() -> None:
    validator = EngineeringValidator()
    claims = [
        "Formation volume factor relates reservoir-condition volume to standard-condition volume.",
        "Material balance is reservoir accounting based on conservation of mass.",
        "Solution-gas drive, gas-cap drive, and water drive are reservoir drive mechanisms.",
    ]
    queries = ["formation volume factor", "material balance", "reservoir drive mechanism"]
    for claim, query in zip(claims, queries, strict=True):
        assert validator.validate_claim(claim, claim, query=query).passed


def test_reservoir_claim_without_evidence_is_rejected() -> None:
    result = EngineeringValidator().validate_claim(
        "Porosity is pore volume divided by bulk volume.",
        "",
        query="porosity definition",
    )
    assert result.passed is False
    assert result.reasons[0]["code"] == "RES-CITATION-MEANING"


def test_domain_rules_do_not_cross_trigger() -> None:
    validator = EngineeringValidator()
    well_test = validator.validate_claim(
        "Radial flow has a horizontal derivative plateau.",
        "Radial flow has a horizontal derivative plateau.",
        query="radial flow pressure derivative",
    )
    reservoir = validator.validate_claim(
        "Porosity is pore volume divided by bulk volume.",
        "Porosity is pore volume divided by bulk volume.",
        query="porosity definition",
    )
    assert all(reason["domain"] != "reservoir" for reason in well_test.reasons)
    assert all(reason["domain"] != "well_test" for reason in reservoir.reasons)


def test_reservoir_false_premise_requires_explicit_correction() -> None:
    validator = EngineeringValidator()
    question = "Higher porosity always means higher permeability. Why?"
    detected, corrected, _ = validator.false_premise_correction(
        question,
        "Yes, higher porosity always means higher permeability.",
    )
    assert detected and not corrected
    detected, corrected, failures = validator.false_premise_correction(
        question,
        "No. Higher porosity does not necessarily mean higher permeability; pore connectivity and structure matter.",
    )
    assert detected and corrected and failures == []
