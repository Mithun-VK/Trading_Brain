"""AlphaHypothesis determinism/signature, and the concentration control's
verdict logic."""

from __future__ import annotations

import datetime as dt
import random

from backtesting.strategy import Strategy
from experiments.alpha import controls
from experiments.alpha.candidates.cross_sectional_momentum import (
    CrossSectionalMomentumHypothesis,
    default_metadata,
    default_parameters,
)
from experiments.alpha.hypothesis import AlphaHypothesis
from experiments.alpha.schema import HypothesisMetadata, ParameterRecord, ParameterSet
from experiments.trade_analysis import TradeRecord


class _NoOpStrategy(Strategy):
    name = "noop"

    def on_bar(self, view):  # noqa: ANN001
        return []


class _StubHypothesis(AlphaHypothesis):
    def build_strategy(self) -> Strategy:
        return _NoOpStrategy()


def _metadata(hid: str = "stub_hyp") -> HypothesisMetadata:
    return HypothesisMetadata(
        hypothesis_id=hid, hypothesis_name="Stub", economic_mechanism="m",
        expected_direction="long", expected_holding_period="1m",
        expected_market_behavior="trending", required_features=("f",),
        known_failure_modes=("m1",), falsification_criteria=("c1",),
        researcher="tester", data_dependencies=("d1",),
    )


def _params(value: float = 1.0) -> ParameterSet:
    return ParameterSet(parameters=(
        ParameterRecord(name="p", value=value, source="lit", justification="x",
                       frozen_before_test=True, selected_after_observation=False),
    ))


# -- signature / determinism ---------------------------------------------------------


def test_identical_hypothesis_and_parameters_produce_the_same_signature() -> None:
    a = _StubHypothesis(_metadata(), _params(1.0))
    b = _StubHypothesis(_metadata(), _params(1.0))
    assert a.signature() == b.signature()


def test_a_different_parameter_value_changes_the_signature() -> None:
    a = _StubHypothesis(_metadata(), _params(1.0))
    b = _StubHypothesis(_metadata(), _params(2.0))
    assert a.signature() != b.signature()


def test_a_different_hypothesis_id_changes_the_signature() -> None:
    a = _StubHypothesis(_metadata("h1"), _params(1.0))
    b = _StubHypothesis(_metadata("h2"), _params(1.0))
    assert a.signature() != b.signature()


def test_build_strategy_returns_a_fresh_instance_each_call() -> None:
    """A shared instance would leak mutable state (e.g. `_held`) across
    separate backtest runs -- exactly the bug class this project has hit
    before in the random-entry control's on_start contract."""
    hyp = _StubHypothesis(_metadata(), _params(1.0))
    a = hyp.build_strategy()
    b = hyp.build_strategy()
    assert a is not b


def test_default_placebo_hook_returns_none() -> None:
    hyp = _StubHypothesis(_metadata(), _params(1.0))
    assert hyp.build_placebo_strategy(random.Random(1)) is None


def test_momentum_hypothesis_signature_is_reproducible() -> None:
    a = CrossSectionalMomentumHypothesis(tickers=["AAA", "BBB"])
    b = CrossSectionalMomentumHypothesis(tickers=["AAA", "BBB"])
    assert a.signature() == b.signature()


def test_momentum_default_parameters_are_all_frozen_before_test() -> None:
    params = default_parameters()
    assert params.any_contaminated is False


def test_momentum_metadata_is_valid() -> None:
    meta = default_metadata()
    assert meta.hypothesis_id == "momentum_xs_v1"
    assert meta.falsification_criteria


def test_momentum_placebo_strategy_permutes_not_none() -> None:
    hyp = CrossSectionalMomentumHypothesis(tickers=["AAA", "BBB", "CCC"])
    placebo = hyp.build_placebo_strategy(random.Random(1))
    assert placebo is not None
    assert placebo.name == "cross_sectional_momentum"


# -- concentration verdict -------------------------------------------------------------


def _trade(ticker: str, pnl: float) -> TradeRecord:
    d = dt.date(2020, 1, 1)
    return TradeRecord(
        ticker=ticker, entry_date=d, exit_date=d, entry_price=100,
        exit_price=100 + pnl, quantity=1, pnl=pnl, return_pct=pnl / 100,
        holding_days=1,
    )


def test_concentration_dependent_when_sharpe_retention_below_floor() -> None:
    records = [_trade("A", 100), _trade("B", 1)]
    verdict = controls.analyze(records, full_sharpe=1.0, sharpe_excluding_top=0.3)
    assert verdict.concentration_dependent is True
    assert verdict.sharpe_retention == 0.3


def test_not_concentration_dependent_when_pnl_and_retention_are_both_balanced() -> None:
    records = [_trade("A", 34), _trade("B", 33), _trade("C", 33)]
    verdict = controls.analyze(records, full_sharpe=1.0, sharpe_excluding_top=0.9)
    assert verdict.concentration_dependent is False


def test_concentration_dependent_when_sharpe_turns_negative_without_top_contributor() -> None:
    records = [_trade("A", 100), _trade("B", 10)]
    verdict = controls.analyze(records, full_sharpe=1.0, sharpe_excluding_top=-0.2)
    assert verdict.concentration_dependent is True


def test_top_contributor_share_is_correctly_identified() -> None:
    records = [_trade("A", 90), _trade("B", 10)]
    verdict = controls.analyze(records, full_sharpe=1.0, sharpe_excluding_top=0.9)
    assert verdict.top_contributor == "A"
    assert verdict.top_contributor_share == 0.9


def test_top_n_share_handles_more_n_than_trades() -> None:
    records = [_trade("A", 10)]
    assert controls.top_n_share(records, 5) is None


def test_top_n_share_on_empty_records() -> None:
    assert controls.top_n_share([], 3) is None


def test_concentration_verdict_with_no_records_does_not_crash() -> None:
    verdict = controls.analyze([], full_sharpe=None, sharpe_excluding_top=None)
    assert verdict.concentration_dependent is False
    assert verdict.top_contributor is None
