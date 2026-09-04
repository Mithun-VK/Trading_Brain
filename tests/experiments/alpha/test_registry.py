"""The experiment registry: status transitions and contamination."""

from __future__ import annotations

import json

import pytest

from experiments.alpha.registry import (
    ExperimentRegistry,
    InvalidTransitionError,
    RunRecord,
    UnknownHypothesisError,
)
from experiments.alpha.schema import DecisionStatus, ExperimentStatus, HypothesisMetadata


def _metadata(hid: str = "hyp1") -> HypothesisMetadata:
    return HypothesisMetadata(
        hypothesis_id=hid, hypothesis_name="Test", economic_mechanism="mechanism",
        expected_direction="long", expected_holding_period="1m",
        expected_market_behavior="trending", required_features=("f",),
        known_failure_modes=("m",), falsification_criteria=("c",),
        researcher="tester", data_dependencies=("d",),
    )


@pytest.fixture
def registry(tmp_path) -> ExperimentRegistry:
    return ExperimentRegistry(path=tmp_path / "registry.json")


# -- registration -----------------------------------------------------------------


def test_registering_twice_is_rejected(registry: ExperimentRegistry) -> None:
    registry.register(_metadata())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_metadata())


def test_an_unknown_hypothesis_raises_on_lookup(registry: ExperimentRegistry) -> None:
    with pytest.raises(UnknownHypothesisError):
        registry.get("nope")


def test_a_new_hypothesis_starts_proposed(registry: ExperimentRegistry) -> None:
    entry = registry.register(_metadata())
    assert entry.status is ExperimentStatus.PROPOSED


# -- transitions --------------------------------------------------------------------


def test_the_normal_lifecycle_path_is_allowed(registry: ExperimentRegistry) -> None:
    registry.register(_metadata())
    registry.transition("hyp1", ExperimentStatus.IN_DEVELOPMENT)
    registry.transition("hyp1", ExperimentStatus.VALIDATION)
    registry.transition("hyp1", ExperimentStatus.TEST_READY)
    entry = registry.transition("hyp1", ExperimentStatus.TESTED)
    assert entry.status is ExperimentStatus.TESTED


def test_skipping_a_stage_is_rejected(registry: ExperimentRegistry) -> None:
    registry.register(_metadata())
    with pytest.raises(InvalidTransitionError):
        registry.transition("hyp1", ExperimentStatus.TESTED)


@pytest.mark.parametrize("terminal", [
    ExperimentStatus.FALSIFIED, ExperimentStatus.TEST_CONTAMINATED, ExperimentStatus.ARCHIVED,
])
def test_terminal_statuses_have_no_outgoing_transition(
    registry: ExperimentRegistry, terminal: ExperimentStatus
) -> None:
    registry.register(_metadata())
    entry = registry.get("hyp1")
    entry.status = terminal  # force it there directly, bypassing the normal path
    with pytest.raises(InvalidTransitionError):
        registry.transition("hyp1", ExperimentStatus.PROPOSED)
    with pytest.raises(InvalidTransitionError):
        registry.transition("hyp1", ExperimentStatus.IN_DEVELOPMENT)


def test_a_falsified_hypothesis_cannot_return_to_validation(registry: ExperimentRegistry) -> None:
    """No path from FALSIFIED back into the lifecycle -- a materially
    changed hypothesis must get a new id, not resurrect the old one."""
    registry.register(_metadata())
    registry.transition("hyp1", ExperimentStatus.IN_DEVELOPMENT)
    registry.transition("hyp1", ExperimentStatus.VALIDATION)
    registry.transition("hyp1", ExperimentStatus.FALSIFIED)
    with pytest.raises(InvalidTransitionError):
        registry.transition("hyp1", ExperimentStatus.VALIDATION)


# -- TEST contamination --------------------------------------------------------------


def test_the_first_test_observation_is_not_contaminated(registry: ExperimentRegistry) -> None:
    registry.register(_metadata())
    entry = registry.mark_test_observed("hyp1")
    assert entry.test_observed is True
    assert entry.status is not ExperimentStatus.TEST_CONTAMINATED


def test_a_second_test_observation_forces_contamination(registry: ExperimentRegistry) -> None:
    registry.register(_metadata())
    registry.mark_test_observed("hyp1")
    entry = registry.mark_test_observed("hyp1")
    assert entry.status is ExperimentStatus.TEST_CONTAMINATED


def test_a_contaminated_hypothesis_cannot_be_recorded_as_supported(
    registry: ExperimentRegistry,
) -> None:
    registry.register(_metadata())
    registry.mark_test_observed("hyp1")
    registry.mark_test_observed("hyp1")  # forces TEST_CONTAMINATED
    with pytest.raises(ValueError, match="TEST_CONTAMINATED"):
        registry.record_decision("hyp1", DecisionStatus.SUPPORTED, ["looks great"])


def test_a_falsified_hypothesis_stays_falsified_even_after_a_repeat_test_look(
    registry: ExperimentRegistry,
) -> None:
    """A repeated TEST look on an already-falsified hypothesis must not
    resurrect it into TEST_CONTAMINATED as though it were still live --
    FALSIFIED is terminal."""
    registry.register(_metadata())
    registry.transition("hyp1", ExperimentStatus.IN_DEVELOPMENT)
    registry.transition("hyp1", ExperimentStatus.VALIDATION)
    registry.transition("hyp1", ExperimentStatus.FALSIFIED)
    registry.mark_test_observed("hyp1")
    entry = registry.mark_test_observed("hyp1")
    assert entry.status is ExperimentStatus.FALSIFIED


# -- runs and persistence -------------------------------------------------------------


def test_recorded_runs_accumulate_and_are_never_removed(registry: ExperimentRegistry) -> None:
    registry.register(_metadata())
    registry.record_run("hyp1", RunRecord(run_id="r1", manifest_path="p1", stage="validation"))
    registry.record_run("hyp1", RunRecord(run_id="r2", manifest_path="p2", stage="test"))
    assert [r.run_id for r in registry.get("hyp1").runs] == ["r1", "r2"]


def test_saving_and_reloading_round_trips(tmp_path) -> None:
    path = tmp_path / "registry.json"
    registry = ExperimentRegistry(path=path)
    registry.register(_metadata())
    registry.transition("hyp1", ExperimentStatus.IN_DEVELOPMENT)
    registry.record_run("hyp1", RunRecord(run_id="r1", manifest_path="p1", stage="validation"))
    registry.save()

    reloaded = ExperimentRegistry(path=path)
    entry = reloaded.get("hyp1")
    assert entry.status is ExperimentStatus.IN_DEVELOPMENT
    assert len(entry.runs) == 1
    assert entry.runs[0].run_id == "r1"


def test_the_saved_file_is_valid_json(tmp_path) -> None:
    path = tmp_path / "registry.json"
    registry = ExperimentRegistry(path=path)
    registry.register(_metadata())
    registry.save()
    json.loads(path.read_text(encoding="utf-8"))  # raises if malformed


# -- historical archival ----------------------------------------------------------------


def test_archive_historical_ingests_without_a_run(registry: ExperimentRegistry) -> None:
    entry = registry.archive_historical(
        _metadata("ma_20_50_v1"), status=ExperimentStatus.FALSIFIED, note="see report",
    )
    assert entry.status is ExperimentStatus.FALSIFIED
    assert entry.runs == []
    assert "see report" in entry.archived_note


def test_archiving_the_same_historical_id_twice_is_rejected(registry: ExperimentRegistry) -> None:
    registry.archive_historical(_metadata(), status=ExperimentStatus.FALSIFIED, note="x")
    with pytest.raises(ValueError, match="already registered"):
        registry.archive_historical(_metadata(), status=ExperimentStatus.FALSIFIED, note="y")


def test_every_status_change_is_logged_to_history(registry: ExperimentRegistry) -> None:
    registry.register(_metadata())
    registry.transition("hyp1", ExperimentStatus.IN_DEVELOPMENT)
    entry = registry.get("hyp1")
    assert len(entry.history) >= 2  # registered + one transition
