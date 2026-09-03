"""V1/V2 — the experiment configuration and runner.

The tests that matter here are the refusals. A validation framework that
happily certifies a backtest over generated prices is worse than no
framework, because it produces an authoritative-looking table of metrics
that means nothing.
"""

from __future__ import annotations

import datetime as dt

import pytest

from backtesting.strategy import BuyAndHoldStrategy, MovingAverageCrossStrategy
from data.ingestion.schemas import PriceBar
from experiments import runner
from experiments.config import (
    AIMode,
    CostModel,
    DataQuality,
    ExperimentConfig,
    Period,
    RiskLimits,
    certifiable,
)

START = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)


def _bars(n: int, *, source: str, start_price: float = 100.0) -> list[PriceBar]:
    out = []
    price = start_price
    for i in range(n):
        price *= 1.001 if i % 3 else 0.999
        out.append(
            PriceBar(
                ts=START + dt.timedelta(days=i),
                open=price, high=price * 1.01, low=price * 0.99,
                close=price, volume=1_000, interval="1d", source=source,
            )
        )
    return out


def _config(**overrides) -> ExperimentConfig:
    base = {
        "experiment_id": "V-TEST",
        "strategy": "buy_and_hold",
        "strategy_version": "1.0",
        "frozen_at_commit": "25f6746",
        "universe": ("AAPL",),
        "test": Period("test", dt.date(2024, 1, 1), dt.date(2024, 12, 31)),
    }
    return ExperimentConfig(**{**base, **overrides})


# -- V1: the configuration is a contract ----------------------------------------


def test_overlapping_train_and_validation_is_rejected() -> None:
    """One shared bar is data leakage, and leakage does not announce itself
    in the results -- it just makes them good."""
    with pytest.raises(ValueError, match="leak"):
        _config(
            train=Period("train", dt.date(2020, 1, 1), dt.date(2022, 1, 1)),
            validation=Period("val", dt.date(2021, 12, 31), dt.date(2023, 1, 1)),
        )


def test_adjacent_periods_are_allowed() -> None:
    """Half-open ranges: validation may begin the day training ends."""
    config = _config(
        train=Period("train", dt.date(2020, 1, 1), dt.date(2022, 1, 1)),
        validation=Period("val", dt.date(2022, 1, 1), dt.date(2023, 1, 1)),
        test=Period("test", dt.date(2023, 1, 1), dt.date(2024, 1, 1)),
    )

    assert config.train is not None


def test_an_ai_arm_must_name_its_model() -> None:
    """An AI result whose model is unrecorded cannot be reproduced or
    attributed, so it is not an experiment."""
    with pytest.raises(ValueError, match="no model is named"):
        _config(ai_mode=AIMode.FRONTIER_ONLY)


def test_the_fingerprint_changes_when_anything_material_changes() -> None:
    baseline = _config().fingerprint()

    assert _config(position_size_pct=0.20).fingerprint() != baseline
    assert _config(costs=CostModel(commission_bps=10.0)).fingerprint() != baseline
    assert _config(random_seed=7).fingerprint() != baseline
    assert _config(universe=("AAPL", "MSFT")).fingerprint() != baseline


def test_identical_configurations_fingerprint_identically() -> None:
    assert _config().fingerprint() == _config().fingerprint()


def test_a_period_must_move_forward() -> None:
    with pytest.raises(ValueError, match="end must be after start"):
        Period("bad", dt.date(2024, 1, 1), dt.date(2024, 1, 1))


# -- V1: certification ----------------------------------------------------------


def test_synthetic_data_is_never_certifiable() -> None:
    """The rule this framework exists to enforce."""
    bars = {"AAPL": _bars(300, source="mock")}
    provenance = runner.describe_data(bars, provider="mock")

    ok, reason = certifiable(_config(), provenance)

    assert provenance.quality is DataQuality.SYNTHETIC
    assert ok is False
    assert "generator" in reason


def test_quality_is_derived_from_the_bars_not_the_caller() -> None:
    """A caller that mislabels synthetic data as vendor data is exactly the
    failure this guard catches, so the claim is ignored."""
    bars = {"AAPL": _bars(10, source="mock")}

    provenance = runner.describe_data(bars, provider="alphavantage")

    assert provenance.quality is DataQuality.SYNTHETIC


def test_vendor_data_over_a_test_period_is_certifiable() -> None:
    bars = {"AAPL": _bars(300, source="alphavantage")}
    provenance = runner.describe_data(bars, provider="alphavantage")

    ok, reason = certifiable(_config(), provenance)

    assert ok is True
    assert "out-of-sample" in reason


def test_real_data_without_a_test_period_is_not_certifiable() -> None:
    """A result measured only where the strategy was fitted is not an
    out-of-sample result."""
    bars = {"AAPL": _bars(300, source="alphavantage")}
    provenance = runner.describe_data(bars, provider="alphavantage")

    ok, reason = certifiable(_config(test=None), provenance)

    assert ok is False
    assert "out-of-sample" in reason


def test_the_snapshot_hash_detects_a_revised_price() -> None:
    """A vendor silently revising one close, or a corporate action applied
    later, changes the snapshot -- which is what stops two runs being
    compared as though they used the same data."""
    original = {"AAPL": _bars(50, source="vendor")}
    revised = {"AAPL": _bars(50, source="vendor")}
    revised["AAPL"][10] = PriceBar(
        ts=revised["AAPL"][10].ts, open=1.0, high=1.0, low=1.0, close=1.0,
        volume=1, interval="1d", source="vendor",
    )

    assert runner.snapshot_bars(original) != runner.snapshot_bars(revised)


def test_one_extra_bar_changes_the_snapshot() -> None:
    assert runner.snapshot_bars({"A": _bars(50, source="v")}) != runner.snapshot_bars(
        {"A": _bars(51, source="v")}
    )


# -- V2: the run ----------------------------------------------------------------


def test_a_synthetic_run_executes_but_is_not_certified() -> None:
    """The machinery must be runnable without a market data subscription.
    The run is allowed; the conclusion is not."""
    bars = {"AAPL": _bars(300, source="mock")}

    result = runner.run(_config(), BuyAndHoldStrategy(), bars, provider="mock")

    assert result.performance.total_return is not None  # it really ran
    assert result.certified is False
    assert result.headline()["certified"] is False


def test_the_headline_always_carries_its_verdict() -> None:
    """The figures a summary table shows are never separable from whether
    they mean anything."""
    bars = {"AAPL": _bars(300, source="mock")}

    headline = runner.run(_config(), BuyAndHoldStrategy(), bars, provider="mock").headline()

    for key in ("certified", "certification_reason", "data_quality", "snapshot"):
        assert key in headline


def test_the_full_metric_set_is_populated() -> None:
    bars = {"AAPL": _bars(400, source="mock")}

    record = runner.run(
        _config(strategy="ma_cross"),
        MovingAverageCrossStrategy(fast=10, slow=30),
        bars,
        provider="mock",
    ).performance

    for field_name in ("volatility", "calmar", "average_exposure", "time_in_market",
                       "var_95", "cvar_95", "worst_day"):
        assert getattr(record, field_name) is not None, f"{field_name} was not computed"


def test_costs_are_measured_from_fills_not_restated_from_config() -> None:
    """If the realised rate disagrees with the configured one, the backtest
    has a bug, and this is where it shows."""
    bars = {"AAPL": _bars(400, source="mock")}
    config = _config(costs=CostModel(commission_bps=5.0, slippage_bps=5.0))

    record = runner.run(
        config, MovingAverageCrossStrategy(fast=10, slow=30), bars, provider="mock"
    ).performance

    if record.trade_count:
        assert record.total_commission > 0
        assert record.realised_cost_bps is not None
        # Commission alone is 5bp of notional; total must be at least that.
        assert record.realised_cost_bps >= 5.0


def test_a_strategy_that_never_trades_reports_undefined_not_zero() -> None:
    """A win rate of 0.0 would claim it lost every trade. It made none."""
    bars = {"AAPL": _bars(20, source="mock")}

    record = runner.run(
        _config(), MovingAverageCrossStrategy(fast=50, slow=200), bars, provider="mock"
    ).performance

    assert record.trade_count == 0
    assert record.win_rate is None
    assert record.profit_factor is None
    assert any("undefined rather than zero" in n for n in record.notes)


def test_a_small_sample_is_labelled_as_one() -> None:
    bars = {"AAPL": _bars(120, source="mock")}

    record = runner.run(
        _config(), MovingAverageCrossStrategy(fast=5, slow=15), bars, provider="mock"
    ).performance

    if 0 < record.trade_count < 30:
        assert any("no statistical weight" in n for n in record.notes)


def test_risk_limit_breaches_are_reported_not_absorbed() -> None:
    """A strategy that only performs by exceeding its own limits has not
    been tested under those limits."""
    bars = {"AAPL": _bars(300, source="mock")}
    strict = _config(risk=RiskLimits(max_portfolio_exposure=0.01, max_leverage=0.01))

    result = runner.run(strict, BuyAndHoldStrategy(), bars, provider="mock")

    assert result.limit_breaches
    assert any("exposure" in b.lower() for b in result.limit_breaches)


def test_the_same_seed_reproduces_the_same_run() -> None:
    bars = {"AAPL": _bars(300, source="mock")}
    config = _config(random_seed=42)

    first = runner.run(config, BuyAndHoldStrategy(), bars, provider="mock")
    second = runner.run(config, BuyAndHoldStrategy(), bars, provider="mock")

    assert first.performance.total_return == second.performance.total_return
    assert first.provenance.snapshot_id == second.provenance.snapshot_id
    assert first.config_fingerprint == second.config_fingerprint
