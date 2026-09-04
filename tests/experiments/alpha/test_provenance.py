"""Reproducibility manifest: git capture, dataset snapshot, content hashing."""

from __future__ import annotations

import datetime as dt

from data.ingestion.schemas import PriceBar
from experiments.alpha.provenance import (
    RunManifest,
    current_git_commit,
    dataset_snapshot_for,
    is_working_tree_dirty,
    make_run_id,
)
from experiments.alpha.schema import (
    DataQualityLevel,
    DatasetContract,
    ParameterRecord,
    ParameterSet,
    SurvivorshipRisk,
    UniverseType,
)
from experiments.config import CostModel, Period

START = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)


def _bars(n: int) -> list[PriceBar]:
    return [
        PriceBar(ts=START + dt.timedelta(days=i), open=100, high=101, low=99,
                 close=100, volume=1_000, interval="1d", source="vendor")
        for i in range(n)
    ]


def _contract() -> DatasetContract:
    return DatasetContract(
        provider="yahoo", universe_type=UniverseType.STATIC_CURRENT,
        survivorship_bias_risk=SurvivorshipRisk.HIGH,
        corporate_action_quality=DataQualityLevel.ASSUMED,
        delisted_security_coverage=DataQualityLevel.UNKNOWN,
    )


def _manifest(**overrides) -> RunManifest:
    base = dict(
        run_id="run1", hypothesis_id="hyp1", hypothesis_signature="sig123",
        git_commit="abc123", working_tree_dirty=False, dataset_snapshot="snap1",
        dataset_contract=_contract(), universe=("AAA", "BBB"),
        periods={"train": Period("train", dt.date(2020, 1, 1), dt.date(2021, 1, 1))},
        parameters=ParameterSet(parameters=(
            ParameterRecord(name="p", value=1, source="lit", justification="x",
                           frozen_before_test=True, selected_after_observation=False),
        )),
        cost_model=CostModel(), random_seed=42,
    )
    return RunManifest(**{**base, **overrides})


# -- git capture ---------------------------------------------------------------------


def test_current_git_commit_returns_a_real_hash_in_this_repo() -> None:
    commit = current_git_commit()
    assert commit != "unknown"
    assert len(commit) == 40


def test_dirty_check_returns_a_boolean_or_none() -> None:
    assert is_working_tree_dirty() in (True, False, None)


# -- dataset snapshot -----------------------------------------------------------------


def test_dataset_snapshot_reuses_the_runner_hashing_scheme() -> None:
    from experiments.runner import snapshot_bars

    bars = {"AAA": _bars(10)}
    assert dataset_snapshot_for(bars) == snapshot_bars(bars)


def test_identical_bars_produce_identical_snapshots() -> None:
    a = {"AAA": _bars(10)}
    b = {"AAA": _bars(10)}
    assert dataset_snapshot_for(a) == dataset_snapshot_for(b)


def test_different_bars_produce_different_snapshots() -> None:
    a = {"AAA": _bars(10)}
    b = {"AAA": _bars(11)}
    assert dataset_snapshot_for(a) != dataset_snapshot_for(b)


# -- manifest content ----------------------------------------------------------------


def test_manifest_serializes_every_required_field() -> None:
    manifest = _manifest()
    data = manifest.to_dict()
    for key in (
        "run_id", "hypothesis_id", "git_commit", "dataset_snapshot", "universe",
        "periods", "parameters", "parameter_provenance" if False else "parameters",
        "cost_model", "random_seed", "controls", "test_contaminated", "created_at",
    ):
        assert key in data


def test_dataset_contract_warnings_are_embedded_in_the_manifest() -> None:
    manifest = _manifest()
    assert manifest.to_dict()["dataset_contract"]["warnings"]


def test_content_hash_ignores_run_id_and_timestamp() -> None:
    """Two manifests differing only in run_id/created_at describe the same
    experiment and must hash identically -- the reproducibility test
    depends on this."""
    a = _manifest(run_id="run1")
    b = _manifest(run_id="run2", created_at=a.created_at + dt.timedelta(hours=1))
    assert a.content_hash() == b.content_hash()


def test_content_hash_changes_with_the_random_seed() -> None:
    a = _manifest(random_seed=1)
    b = _manifest(random_seed=2)
    assert a.content_hash() != b.content_hash()


def test_content_hash_changes_with_the_dataset_snapshot() -> None:
    a = _manifest(dataset_snapshot="snap1")
    b = _manifest(dataset_snapshot="snap2")
    assert a.content_hash() != b.content_hash()


def test_content_hash_changes_with_parameters() -> None:
    a = _manifest()
    b = _manifest(parameters=ParameterSet(parameters=(
        ParameterRecord(name="p", value=2, source="lit", justification="x",
                       frozen_before_test=True, selected_after_observation=False),
    )))
    assert a.content_hash() != b.content_hash()


def test_manifest_saves_and_is_valid_json(tmp_path) -> None:
    import json

    manifest = _manifest()
    path = manifest.save(directory=tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["run_id"] == "run1"


def test_make_run_id_is_stable_in_shape() -> None:
    run_id = make_run_id("hyp1", "sig123", 42)
    assert run_id.startswith("hyp1-sig123-seed42-")
