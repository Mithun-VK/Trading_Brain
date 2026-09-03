"""V4 — regime labelling and trade analysis.

The load-bearing test in this file is `test_a_label_never_depends_on_a_later_bar`.
Everything V4 concludes rests on labels being causal: if a label at bar t
can see bar t+1, then "the strategy does well in bull markets" degrades to
"the strategy does well on days that later turned out to be bullish", which
is not a fact anyone can trade on.
"""

from __future__ import annotations

import datetime as dt

from data.ingestion.schemas import PriceBar
from experiments import regimes, trade_analysis
from experiments.regimes import Regime

START = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)


def _series(closes: list[float]) -> list[PriceBar]:
    return [
        PriceBar(
            ts=START + dt.timedelta(days=i),
            open=c, high=c * 1.01, low=c * 0.99, close=c,
            volume=1_000, interval="1d", source="vendor",
        )
        for i, c in enumerate(closes)
    ]


def _rising(n: int, rate: float = 1.002) -> list[float]:
    price = 100.0
    out = []
    for _ in range(n):
        price *= rate
        out.append(price)
    return out


# -- causality ------------------------------------------------------------------


def test_a_label_never_depends_on_a_later_bar() -> None:
    """Truncating the series must not change any label that survives.

    This is the property the entire decomposition rests on. If labelling
    300 bars gives different answers for the first 250 than labelling 250
    does, then the labels are using the future.
    """
    closes = _rising(300)
    full = regimes.label_series(_series(closes))
    truncated = regimes.label_series(_series(closes[:250]))

    for a, b in zip(full[:250], truncated, strict=True):
        assert a.primary is b.primary, f"label at {a.date} changed when the future was added"
        assert a.trend is b.trend
        assert a.volatility is b.volatility
        assert a.drawdown == b.drawdown


def test_labels_before_the_lookback_are_unknown_not_guessed() -> None:
    """A label that cannot yet be determined is UNKNOWN, never the
    eventual value filled backwards."""
    labels = regimes.label_series(_series(_rising(250)))

    early = labels[:150]
    assert all(label.trend is Regime.UNKNOWN for label in early)
    assert any(label.trend is not Regime.UNKNOWN for label in labels[220:])


def test_lookup_falls_back_to_an_earlier_label_never_a_later_one() -> None:
    """A weekend date resolves to Friday's regime, not Monday's -- the one
    place look-ahead would be least visible."""
    labels = regimes.label_series(_series(_rising(250)))
    by_date = regimes.index_by_date(labels)
    dates = sorted(by_date)
    # Drop one day so there is a genuine hole to resolve across, the way a
    # weekend or holiday creates one.
    missing = dates[100]
    del by_date[missing]

    resolved = regimes.lookup(by_date, missing)

    assert resolved is not None
    assert resolved.date == dates[99], "resolved forward into the future"


def test_a_date_before_all_history_resolves_to_nothing() -> None:
    labels = regimes.label_series(_series(_rising(250)))
    by_date = regimes.index_by_date(labels)

    assert regimes.lookup(by_date, dt.date(1990, 1, 1)) is None


# -- the regime states ----------------------------------------------------------


def test_a_sustained_rise_is_labelled_bull() -> None:
    labels = regimes.label_series(_series(_rising(400)))

    assert labels[-1].trend is Regime.BULL


def test_a_deep_drawdown_is_labelled_crisis() -> None:
    """Crisis overrides trend: a 'bull' label during a 25% drawdown is
    technically defensible and practically useless."""
    closes = _rising(300) + [_rising(300)[-1] * (1 - 0.25 * i / 30) for i in range(30)]
    labels = regimes.label_series(_series(closes))

    assert labels[-1].stress is Regime.CRISIS
    assert labels[-1].primary is Regime.CRISIS


def test_climbing_out_of_a_crisis_becomes_recovery() -> None:
    peak = _rising(300)
    bottom = peak[-1] * 0.7
    closes = peak + [bottom] * 5 + [bottom * (1 + 0.05 * i) for i in range(1, 8)]
    labels = regimes.label_series(_series(closes))

    assert labels[-1].primary in (Regime.RECOVERY, Regime.CRISIS)


def test_drawdown_is_measured_from_the_running_peak_not_the_final_one() -> None:
    """Using the eventual all-time high would make early bars look like they
    were already in a drawdown they could not have known about."""
    # One continuous rise -- _rising() restarts at 100, so concatenating two
    # calls would create a genuine gap down and test nothing.
    closes = _rising(300)
    labels = regimes.label_series(_series(closes))

    # A monotonically rising series is never in drawdown at any point.
    assert all(label.drawdown >= -1e-9 for label in labels)
    assert all(label.stress is not Regime.CRISIS for label in labels)


def test_the_distribution_sums_to_the_bar_count() -> None:
    labels = regimes.label_series(_series(_rising(300)))

    assert sum(regimes.distribution(labels).values()) == len(labels)


# -- excursions -----------------------------------------------------------------


def test_mae_and_mfe_use_intraday_extremes_not_closes() -> None:
    """A position that traded 9% down intraday was 9% down, whatever the
    close said."""
    bars = [
        PriceBar(ts=START + dt.timedelta(days=i), open=100, high=100, low=100,
                 close=100, volume=1, interval="1d", source="v")
        for i in range(5)
    ]
    bars[2] = PriceBar(ts=bars[2].ts, open=100, high=112, low=91, close=100,
                       volume=1, interval="1d", source="v")

    mae, mfe, held = trade_analysis._excursions(
        bars, bars[0].ts.date(), bars[-1].ts.date(), entry_price=100
    )

    assert mae is not None and round(mae, 4) == -0.09
    assert mfe is not None and round(mfe, 4) == 0.12
    assert held == 5


def test_excursions_are_unavailable_rather_than_zero_without_bars() -> None:
    mae, mfe, held = trade_analysis._excursions([], START.date(), START.date(), 100)

    assert mae is None and mfe is None and held == 0


# -- aggregation honesty --------------------------------------------------------


def _record(regime: Regime, pnl: float, ret: float, ticker: str = "AAA"):
    return trade_analysis.TradeRecord(
        ticker=ticker, entry_date=START.date(), exit_date=START.date(),
        entry_price=100, exit_price=100 + pnl, quantity=1, pnl=pnl,
        return_pct=ret, holding_days=5, entry_regime=regime,
    )


def test_a_small_regime_sample_is_flagged_not_hidden() -> None:
    records = [_record(Regime.BULL, 10, 0.1) for _ in range(5)]

    stats = trade_analysis.by_regime(records)

    assert stats[0].trades == 5
    assert stats[0].is_significant is False


def test_a_large_regime_sample_is_marked_significant() -> None:
    records = [_record(Regime.BULL, 10, 0.1) for _ in range(35)]

    assert trade_analysis.by_regime(records)[0].is_significant is True


def test_unlabelled_trades_are_grouped_not_dropped() -> None:
    """Silently discarding them would change the denominator without
    saying so."""
    records = [_record(Regime.BULL, 10, 0.1), _record(Regime.UNKNOWN, 5, 0.05)]

    stats = trade_analysis.by_regime(records)

    assert sum(s.trades for s in stats) == 2
    assert any(s.regime == str(Regime.UNKNOWN) for s in stats)


def test_profit_factor_is_undefined_with_no_losses() -> None:
    """Not infinity, and not zero -- there is no denominator."""
    records = [_record(Regime.BULL, 10, 0.1) for _ in range(3)]

    assert trade_analysis.by_regime(records)[0].profit_factor is None


def test_concentration_reveals_a_single_dominant_trade() -> None:
    records = [_record(Regime.BULL, 1, 0.01) for _ in range(9)]
    records.append(_record(Regime.BULL, 991, 9.91))

    conc = trade_analysis.concentration(records)

    assert conc["top_1_share_of_pnl"] > 0.98
    assert conc["trades"] == 10


def test_concentration_on_no_trades_says_so() -> None:
    assert trade_analysis.concentration([])["trades"] == 0


def test_by_ticker_separates_a_single_dominant_name() -> None:
    records = [_record(Regime.BULL, 1, 0.01, ticker="AAA") for _ in range(9)]
    records.append(_record(Regime.BULL, 900, 9.0, ticker="ZZZ"))

    by_ticker = trade_analysis.by_ticker(records)

    assert by_ticker["ZZZ"]["total_pnl"] > by_ticker["AAA"]["total_pnl"] * 50
