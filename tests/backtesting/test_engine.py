from __future__ import annotations

import datetime as dt

import pytest

from backtesting.engine import BacktestEngine
from backtesting.market_view import MarketView
from backtesting.schemas import BacktestConfig, SignalAction, StrategySignal
from backtesting.sizing import FixedFractionSizer, FixedQuantitySizer, RiskBasedSizer
from backtesting.strategy import BuyAndHoldStrategy, MovingAverageCrossStrategy, Strategy
from data.ingestion.mock_provider import MockProvider
from data.ingestion.schemas import PriceBar

START = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


def _bars(closes: list[float], ticker_offset: int = 0) -> list[PriceBar]:
    """Bars where open == previous close, so fills are easy to reason about."""
    bars = []
    for i, close in enumerate(closes):
        open_price = closes[i - 1] if i > 0 else close
        bars.append(
            PriceBar(
                ts=START + dt.timedelta(days=i + ticker_offset * 0),
                open=open_price,
                high=max(open_price, close) * 1.01,
                low=min(open_price, close) * 0.99,
                close=close,
                volume=1000,
                interval="1d",
                source="test",
            )
        )
    return bars


class _RecordingStrategy(Strategy):
    """Captures exactly what it was allowed to see on each bar."""

    name = "recording"

    def __init__(self) -> None:
        self.seen: list[list[float]] = []

    def on_bar(self, view: MarketView) -> list[StrategySignal]:
        self.seen.append(view.closes("AAA"))
        return []


class _BuyOnceStrategy(Strategy):
    name = "buy_once"

    def __init__(self, on_index: int = 0) -> None:
        self.on_index = on_index
        self._count = 0

    def on_start(self) -> None:
        self._count = 0

    def on_bar(self, view: MarketView) -> list[StrategySignal]:
        index = self._count
        self._count += 1
        if index == self.on_index:
            return [StrategySignal(ticker="AAA", action=SignalAction.BUY)]
        return []


# -- anti-lookahead -----------------------------------------------------------


def test_strategy_only_ever_sees_past_and_present_bars() -> None:
    closes = [10.0, 11.0, 12.0, 13.0, 14.0]
    strategy = _RecordingStrategy()

    BacktestEngine().run(strategy, {"AAA": _bars(closes)})

    # On bar i the strategy must see exactly closes[:i+1] -- never more.
    assert strategy.seen == [closes[: i + 1] for i in range(len(closes))]


def test_market_view_cannot_reach_beyond_its_timestamp() -> None:
    bars = _bars([10.0, 11.0, 12.0, 13.0])
    view = MarketView.at({"AAA": bars}, bars[1].ts)

    assert view.closes("AAA") == [10.0, 11.0]
    assert view.current_price("AAA") == 11.0
    assert view.bar_count("AAA") == 2
    # A generous lookback cannot conjure future bars.
    assert len(view.bars("AAA", lookback=100)) == 2


def test_orders_fill_at_the_next_bar_open_not_the_signal_bar_close() -> None:
    """Filling at the close you just observed would be lookahead."""
    closes = [10.0, 20.0, 30.0]
    engine = BacktestEngine(
        BacktestConfig(commission_bps=0, slippage_bps=0), sizer=FixedQuantitySizer(1)
    )

    result = engine.run(_BuyOnceStrategy(on_index=0), {"AAA": _bars(closes)})

    assert len(result.fills) == 1
    fill = result.fills[0]
    # Signal on bar 0 (close 10) -> fill at bar 1's OPEN, which is 10, not 20.
    assert fill.timestamp == START + dt.timedelta(days=1)
    assert fill.price == 10.0


def test_a_signal_on_the_final_bar_cannot_fill() -> None:
    closes = [10.0, 11.0, 12.0]

    result = BacktestEngine().run(_BuyOnceStrategy(on_index=2), {"AAA": _bars(closes)})

    assert result.fills == []
    assert result.unfilled[0]["reason"] == "no subsequent bar to fill against"


# -- reproducibility ----------------------------------------------------------


def test_backtests_are_deterministic() -> None:
    bars = {"AAA": _bars([10 + i * 0.5 for i in range(60)])}
    engine = BacktestEngine()

    first = engine.run(MovingAverageCrossStrategy(fast=5, slow=15), bars)
    second = engine.run(MovingAverageCrossStrategy(fast=5, slow=15), bars)

    assert first.metrics == second.metrics
    assert first.equity_values == second.equity_values
    assert [(f.ticker, f.price, f.quantity) for f in first.fills] == [
        (f.ticker, f.price, f.quantity) for f in second.fills
    ]


def test_reusing_one_strategy_instance_is_also_deterministic() -> None:
    """on_start must reset state, or the second run would differ."""
    bars = {"AAA": _bars([10 + i * 0.5 for i in range(60)])}
    engine = BacktestEngine()
    strategy = MovingAverageCrossStrategy(fast=5, slow=15)

    first = engine.run(strategy, bars)
    second = engine.run(strategy, bars)

    assert first.equity_values == second.equity_values


# -- costs --------------------------------------------------------------------


def test_slippage_makes_buys_pay_up_and_sells_receive_less() -> None:
    config = BacktestConfig(slippage_bps=100)  # 1%

    assert config.slippage_price(100.0, SignalAction.BUY) == pytest.approx(101.0)
    assert config.slippage_price(100.0, SignalAction.SELL) == pytest.approx(99.0)


def test_commission_reduces_final_equity() -> None:
    bars = {"AAA": _bars([10.0, 10.0, 10.0, 10.0])}
    free = BacktestEngine(
        BacktestConfig(commission_bps=0, slippage_bps=0), sizer=FixedQuantitySizer(10)
    ).run(_BuyOnceStrategy(), bars)
    costly = BacktestEngine(
        BacktestConfig(commission_bps=50, slippage_bps=0), sizer=FixedQuantitySizer(10)
    ).run(_BuyOnceStrategy(), bars)

    assert costly.final_equity < free.final_equity


def test_costs_are_recorded_on_each_fill() -> None:
    bars = {"AAA": _bars([10.0, 10.0, 10.0])}
    engine = BacktestEngine(
        BacktestConfig(commission_bps=50, slippage_bps=100), sizer=FixedQuantitySizer(10)
    )

    result = engine.run(_BuyOnceStrategy(), bars)

    fill = result.fills[0]
    assert fill.commission > 0
    assert fill.slippage > 0


# -- portfolio behaviour ------------------------------------------------------


def test_cash_never_goes_negative() -> None:
    bars = {"AAA": _bars([100.0] * 10)}
    engine = BacktestEngine(
        BacktestConfig(initial_cash=1000.0), sizer=FixedQuantitySizer(1000)
    )

    result = engine.run(_BuyOnceStrategy(), bars)

    assert all(point.cash >= -1e-6 for point in result.equity_curve)


def test_selling_without_a_position_is_rejected_not_shorted() -> None:
    class _SellFirst(Strategy):
        name = "sell_first"

        def on_bar(self, view: MarketView) -> list[StrategySignal]:
            return [StrategySignal(ticker="AAA", action=SignalAction.SELL)]

    result = BacktestEngine().run(_SellFirst(), {"AAA": _bars([10.0, 11.0, 12.0])})

    assert result.fills == []
    assert any("shorting is not supported" in u["reason"] for u in result.unfilled)


def test_buy_and_hold_tracks_the_underlying_move() -> None:
    bars = {"AAA": _bars([100.0, 100.0, 110.0, 120.0, 130.0])}
    engine = BacktestEngine(
        BacktestConfig(initial_cash=10_000, commission_bps=0, slippage_bps=0),
        sizer=FixedFractionSizer(1.0),
    )

    result = engine.run(BuyAndHoldStrategy(["AAA"]), bars)

    assert result.metrics["total_return"] > 0
    assert result.final_equity > 10_000


def test_round_trip_produces_a_closed_trade() -> None:
    class _InOut(Strategy):
        name = "in_out"

        def __init__(self) -> None:
            self.i = 0

        def on_start(self) -> None:
            self.i = 0

        def on_bar(self, view: MarketView) -> list[StrategySignal]:
            self.i += 1
            if self.i == 1:
                return [StrategySignal(ticker="AAA", action=SignalAction.BUY)]
            if self.i == 3:
                return [StrategySignal(ticker="AAA", action=SignalAction.SELL)]
            return []

    engine = BacktestEngine(
        BacktestConfig(commission_bps=0, slippage_bps=0), sizer=FixedQuantitySizer(10)
    )
    result = engine.run(_InOut(), {"AAA": _bars([100.0, 100.0, 110.0, 120.0, 130.0])})

    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.ticker == "AAA"
    assert trade.pnl > 0
    assert result.metrics["trade_count"] == 1.0
    assert result.metrics["win_rate"] == 1.0


# -- multi-asset --------------------------------------------------------------


def test_multiple_assets_are_supported() -> None:
    bars = {
        "AAA": _bars([100.0, 100.0, 110.0, 120.0]),
        "BBB": _bars([50.0, 50.0, 55.0, 60.0]),
    }
    engine = BacktestEngine(
        BacktestConfig(commission_bps=0, slippage_bps=0), sizer=FixedFractionSizer(0.4)
    )

    result = engine.run(BuyAndHoldStrategy(), bars)

    assert {f.ticker for f in result.fills} == {"AAA", "BBB"}
    assert result.final_equity > result.config.initial_cash


def test_weekly_bars_run_the_same_way_as_daily() -> None:
    provider = MockProvider()
    weekly = provider.get_historical_prices(
        "RELIANCE", dt.date(2024, 1, 1), dt.date(2025, 1, 1), interval="1wk"
    )

    result = BacktestEngine().run(BuyAndHoldStrategy(["RELIANCE"]), {"RELIANCE": weekly})

    assert len(result.equity_curve) == len(weekly)
    assert result.metrics["trade_count"] == 0.0  # bought and held


# -- metrics ------------------------------------------------------------------


def test_metrics_cover_the_required_set() -> None:
    bars = {"AAA": _bars([100.0 + i for i in range(40)])}

    result = BacktestEngine().run(BuyAndHoldStrategy(["AAA"]), bars)

    for key in (
        "total_return",
        "cagr",
        "sharpe",
        "sortino",
        "max_drawdown",
        "win_rate",
        "profit_factor",
        "expectancy",
        "trade_count",
    ):
        assert key in result.metrics


def test_drawdown_is_negative_on_a_decline() -> None:
    bars = {"AAA": _bars([100.0, 100.0, 120.0, 60.0, 70.0])}
    engine = BacktestEngine(
        BacktestConfig(commission_bps=0, slippage_bps=0), sizer=FixedFractionSizer(1.0)
    )

    result = engine.run(BuyAndHoldStrategy(["AAA"]), bars)

    assert result.metrics["max_drawdown"] < 0


def test_empty_input_produces_an_empty_result_not_a_crash() -> None:
    result = BacktestEngine().run(BuyAndHoldStrategy(), {})

    assert result.equity_curve == []
    assert result.metrics["trade_count"] == 0.0


# -- sizing -------------------------------------------------------------------


def test_fixed_fraction_sizer_respects_cash() -> None:
    sizer = FixedFractionSizer(0.5)
    signal = StrategySignal(ticker="AAA", action=SignalAction.BUY)

    assert sizer.size(signal, price=10.0, equity=1000.0, cash=1000.0) == 50.0
    assert sizer.size(signal, price=10.0, equity=1000.0, cash=100.0) == 10.0


def test_risk_based_sizer_matches_the_shared_risk_function() -> None:
    sizer = RiskBasedSizer(risk_per_trade=0.01, stop_distance_pct=0.10)
    signal = StrategySignal(ticker="AAA", action=SignalAction.BUY)

    # 1% of 100k = 1000 risk; stop is 10 away from a price of 100 -> 100 units.
    assert sizer.size(signal, price=100.0, equity=100_000.0, cash=1_000_000.0) == pytest.approx(
        100.0
    )


def test_invalid_sizer_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        FixedFractionSizer(0)
    with pytest.raises(ValueError):
        FixedQuantitySizer(-1)
    with pytest.raises(ValueError):
        RiskBasedSizer(risk_per_trade=2.0)


def test_moving_average_strategy_rejects_inverted_windows() -> None:
    with pytest.raises(ValueError, match="fast window must be shorter"):
        MovingAverageCrossStrategy(fast=30, slow=10)
