"""Hypothesis metadata and parameter provenance."""

from __future__ import annotations

import pytest

from experiments.alpha.schema import (
    DataQualityLevel,
    DatasetContract,
    HypothesisMetadata,
    ParameterRecord,
    ParameterSet,
    SurvivorshipRisk,
    UniverseType,
)


def _metadata(**overrides) -> HypothesisMetadata:
    base = dict(
        hypothesis_id="test_hyp",
        hypothesis_name="Test Hypothesis",
        economic_mechanism="A mechanism.",
        expected_direction="long",
        expected_holding_period="1 month",
        expected_market_behavior="works in trends",
        required_features=("f1",),
        known_failure_modes=("mode1",),
        falsification_criteria=("criterion1",),
        researcher="tester",
        data_dependencies=("dep1",),
    )
    return HypothesisMetadata(**{**base, **overrides})


# -- metadata validation ----------------------------------------------------------


def test_a_hypothesis_without_a_mechanism_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="economic_mechanism"):
        _metadata(economic_mechanism="")


def test_a_hypothesis_without_falsification_criteria_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="falsification_criteria"):
        _metadata(falsification_criteria=())


def test_a_hypothesis_without_failure_modes_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="known_failure_modes"):
        _metadata(known_failure_modes=())


def test_a_hypothesis_without_required_features_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="required_features"):
        _metadata(required_features=())


def test_whitespace_only_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="researcher"):
        _metadata(researcher="   ")


def test_a_complete_hypothesis_constructs_and_serializes() -> None:
    meta = _metadata()
    data = meta.to_dict()
    assert data["hypothesis_id"] == "test_hyp"
    assert data["required_features"] == ["f1"]


# -- parameter provenance --------------------------------------------------------


def test_a_parameter_without_justification_is_rejected() -> None:
    with pytest.raises(ValueError, match="justification"):
        ParameterRecord(
            name="p", value=1, source="lit", justification="",
            frozen_before_test=True, selected_after_observation=False,
        )


def test_a_parameter_cannot_claim_both_frozen_and_selected_after() -> None:
    with pytest.raises(ValueError, match="both"):
        ParameterRecord(
            name="p", value=1, source="lit", justification="because",
            frozen_before_test=True, selected_after_observation=True,
        )


def test_a_frozen_parameter_is_not_contaminated() -> None:
    p = ParameterRecord(
        name="p", value=1, source="lit", justification="because",
        frozen_before_test=True, selected_after_observation=False,
    )
    assert p.contaminated is False


def test_a_parameter_selected_after_observation_is_contaminated() -> None:
    p = ParameterRecord(
        name="p", value=1, source="grid search", justification="best on validation",
        frozen_before_test=False, selected_after_observation=True,
    )
    assert p.contaminated is True


def test_a_parameter_not_frozen_before_test_is_contaminated_even_if_not_flagged_selected() -> None:
    """The absence of frozen_before_test is itself contamination -- a
    parameter's provenance must be positively established, not assumed
    clean by default."""
    p = ParameterRecord(
        name="p", value=1, source="unknown", justification="unclear",
        frozen_before_test=False, selected_after_observation=False,
    )
    assert p.contaminated is True


def test_a_parameter_set_detects_any_contamination() -> None:
    clean = ParameterRecord(
        name="a", value=1, source="lit", justification="x",
        frozen_before_test=True, selected_after_observation=False,
    )
    dirty = ParameterRecord(
        name="b", value=2, source="grid search", justification="best fit",
        frozen_before_test=False, selected_after_observation=True,
    )
    params = ParameterSet(parameters=(clean, dirty))

    assert params.any_contaminated is True
    assert params.contaminated_names == ["b"]


def test_a_clean_parameter_set_reports_no_contamination() -> None:
    clean = ParameterRecord(
        name="a", value=1, source="lit", justification="x",
        frozen_before_test=True, selected_after_observation=False,
    )
    params = ParameterSet(parameters=(clean,))
    assert params.any_contaminated is False


def test_as_values_extracts_the_plain_dict() -> None:
    p = ParameterRecord(
        name="lookback", value=126, source="lit", justification="x",
        frozen_before_test=True, selected_after_observation=False,
    )
    assert ParameterSet(parameters=(p,)).as_values() == {"lookback": 126}


# -- dataset contract -------------------------------------------------------------


def test_static_current_universe_always_warns() -> None:
    contract = DatasetContract(
        provider="yahoo", universe_type=UniverseType.STATIC_CURRENT,
        survivorship_bias_risk=SurvivorshipRisk.HIGH,
        corporate_action_quality=DataQualityLevel.ASSUMED,
        delisted_security_coverage=DataQualityLevel.UNKNOWN,
    )
    warnings = contract.warnings()
    assert any("survivorship" in w.lower() for w in warnings)
    assert any("STATIC_CURRENT" in w for w in warnings)


def test_a_confirmed_point_in_time_contract_has_fewer_warnings() -> None:
    contract = DatasetContract(
        provider="hypothetical_pit_vendor", universe_type=UniverseType.POINT_IN_TIME,
        survivorship_bias_risk=SurvivorshipRisk.LOW,
        corporate_action_quality=DataQualityLevel.CONFIRMED,
        delisted_security_coverage=DataQualityLevel.CONFIRMED,
    )
    assert contract.warnings() == []
