"""V4 — what happened inside each trade.

A closed trade records where it started and where it ended. That hides the
part which usually explains the result: what the position did in between.

MAE (maximum adverse excursion) is the worst unrealised loss a trade went
through; MFE (maximum favourable excursion) is the best unrealised gain it
gave back. Together they separate three outcomes a P&L column renders
identically:

    a trade that went straight to target
    a trade that was 8% underwater first
    a trade that was 12% up and closed at 2%

Excursions are computed from the high/low of each bar in the holding
window, not from closes, because a stop is hit intraday and a close-only
series would report that it never happened.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from backtesting.schemas import BacktestResult, ClosedTrade
from data.ingestion.schemas import PriceBar
from experiments.regimes import Regime, RegimeLabel, index_by_date, lookup


@dataclass
class TradeRecord:
    """One round trip, with its context attached."""

    ticker: str
    entry_date: dt.date
    exit_date: dt.date
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    return_pct: float
    holding_days: float

    # --- regime context ---
    entry_regime: Regime = Regime.UNKNOWN
    exit_regime: Regime = Regime.UNKNOWN
    entry_volatility_regime: Regime = Regime.UNKNOWN
    entry_momentum_regime: Regime = Regime.UNKNOWN
    regime_changed: bool = False
    regimes_visited: tuple[str, ...] = ()
    entry_trend_slope: float | None = None
    entry_annualised_vol: float | None = None

    # --- excursions ---
    mae: float | None = None  # worst unrealised return, <= 0
    mfe: float | None = None  # best unrealised return, >= 0
    edge_ratio: float | None = None  # MFE / |MAE|
    give_back: float | None = None  # MFE - realised return
    bars_held: int = 0

    exit_reason: str = "signal"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "entry_date": self.entry_date.isoformat(),
            "exit_date": self.exit_date.isoformat(),
            "entry_regime": str(self.entry_regime),
            "exit_regime": str(self.exit_regime),
            "entry_volatility_regime": str(self.entry_volatility_regime),
            "entry_momentum_regime": str(self.entry_momentum_regime),
            "regime_changed": self.regime_changed,
            "regimes_visited": list(self.regimes_visited),
            "holding_days": self.holding_days,
            "return_pct": self.return_pct,
            "pnl": self.pnl,
            "mae": self.mae,
            "mfe": self.mfe,
            "edge_ratio": self.edge_ratio,
            "give_back": self.give_back,
            "entry_annualised_vol": self.entry_annualised_vol,
            "entry_trend_slope": self.entry_trend_slope,
            "exit_reason": self.exit_reason,
        }


def _excursions(
    bars: list[PriceBar], entry: dt.date, exit_: dt.date, entry_price: float
) -> tuple[float | None, float | None, int]:
    """Worst and best unrealised return between entry and exit.

    Uses bar lows and highs rather than closes: a position that traded 9%
    down intraday was 9% down, whatever the close said, and a decomposition
    built on closes would report a risk the trade never took.
    """
    window = [b for b in bars if entry <= b.ts.date() <= exit_]
    if not window or entry_price <= 0:
        return None, None, 0

    worst = min((b.low - entry_price) / entry_price for b in window)
    best = max((b.high - entry_price) / entry_price for b in window)
    return round(min(worst, 0.0), 6), round(max(best, 0.0), 6), len(window)


def enrich(
    result: BacktestResult,
    bars_by_ticker: dict[str, list[PriceBar]],
    labels_by_ticker: dict[str, list[RegimeLabel]] | None = None,
    market_labels: list[RegimeLabel] | None = None,
) -> list[TradeRecord]:
    """Attach regime and excursion context to every closed trade.

    `market_labels` (typically SPY) provides the market regime; per-ticker
    labels are used when supplied. Market regime is the default because
    "does this strategy work in a bear market" is a question about the
    market, not about one name's own trend.
    """
    market_index = index_by_date(market_labels) if market_labels else {}
    ticker_index = {
        ticker: index_by_date(labels) for ticker, labels in (labels_by_ticker or {}).items()
    }

    records: list[TradeRecord] = []
    for trade in result.closed_trades:
        records.append(
            _one(trade, bars_by_ticker.get(trade.ticker, []), market_index, ticker_index)
        )
    return records


def _one(
    trade: ClosedTrade,
    bars: list[PriceBar],
    market_index: dict[dt.date, RegimeLabel],
    ticker_index: dict[str, dict[dt.date, RegimeLabel]],
) -> TradeRecord:
    entry_date = trade.opened_at.date()
    exit_date = trade.closed_at.date()

    record = TradeRecord(
        ticker=trade.ticker,
        entry_date=entry_date,
        exit_date=exit_date,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        quantity=trade.quantity,
        pnl=trade.pnl,
        return_pct=trade.return_pct,
        holding_days=round((trade.closed_at - trade.opened_at).total_seconds() / 86400, 3),
    )

    index = market_index or ticker_index.get(trade.ticker, {})
    entry_label = lookup(index, entry_date)
    exit_label = lookup(index, exit_date)

    if entry_label is None:
        record.notes.append(
            "No regime label was determinable at entry: the detector needs "
            "its full lookback, and this trade opened before enough history "
            "existed. Excluded from regime statistics rather than guessed."
        )
    else:
        record.entry_regime = entry_label.primary
        record.entry_volatility_regime = entry_label.volatility
        record.entry_momentum_regime = entry_label.momentum
        record.entry_trend_slope = entry_label.trend_slope
        record.entry_annualised_vol = entry_label.annualised_vol

    if exit_label is not None:
        record.exit_regime = exit_label.primary

    record.regime_changed = (
        entry_label is not None
        and exit_label is not None
        and entry_label.primary != exit_label.primary
    )
    if index:
        visited = {
            str(label.primary)
            for date, label in index.items()
            if entry_date <= date <= exit_date
        }
        record.regimes_visited = tuple(sorted(visited))

    mae, mfe, bars_held = _excursions(bars, entry_date, exit_date, trade.entry_price)
    record.mae, record.mfe, record.bars_held = mae, mfe, bars_held
    if mae is not None and mfe is not None:
        record.edge_ratio = round(mfe / abs(mae), 4) if mae < 0 else None
        record.give_back = round(mfe - trade.return_pct, 6)
    if mae is None:
        record.notes.append("No bars found in the holding window; excursions unavailable.")

    return record


# -- aggregation ----------------------------------------------------------------


@dataclass
class RegimeStats:
    """Per-regime performance. Every field is None when undefined, and the
    sample size is always carried alongside so a 3-trade regime is never
    read as a finding."""

    regime: str
    trades: int = 0
    total_pnl: float = 0.0
    win_rate: float | None = None
    expectancy: float | None = None
    average_return: float | None = None
    median_return: float | None = None
    profit_factor: float | None = None
    average_mae: float | None = None
    average_mfe: float | None = None
    average_holding_days: float | None = None
    best: float | None = None
    worst: float | None = None
    is_significant: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)


MIN_TRADES_FOR_SIGNIFICANCE = 30


def by_regime(records: list[TradeRecord], *, key: str = "entry_regime") -> list[RegimeStats]:
    """Group trades by a regime attribute and compute per-group statistics.

    Trades whose regime was not determinable are grouped under `unknown`
    rather than dropped: silently discarding them would change the
    denominator without saying so.
    """
    groups: dict[str, list[TradeRecord]] = {}
    for record in records:
        groups.setdefault(str(getattr(record, key)), []).append(record)

    stats = []
    for regime, trades in groups.items():
        returns = [t.return_pct for t in trades]
        wins = [r for r in returns if r > 0]
        maes = [t.mae for t in trades if t.mae is not None]
        mfes = [t.mfe for t in trades if t.mfe is not None]

        gross_win = sum(t.pnl for t in trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))

        stats.append(
            RegimeStats(
                regime=regime,
                trades=len(trades),
                total_pnl=round(sum(t.pnl for t in trades), 2),
                win_rate=round(len(wins) / len(trades), 4) if trades else None,
                expectancy=round(sum(returns) / len(returns), 6) if returns else None,
                average_return=round(sum(returns) / len(returns), 6) if returns else None,
                median_return=round(sorted(returns)[len(returns) // 2], 6) if returns else None,
                profit_factor=(
                    round(gross_win / gross_loss, 4) if gross_loss > 0 else None
                ),
                average_mae=round(sum(maes) / len(maes), 6) if maes else None,
                average_mfe=round(sum(mfes) / len(mfes), 6) if mfes else None,
                average_holding_days=(
                    round(sum(t.holding_days for t in trades) / len(trades), 2) if trades else None
                ),
                best=round(max(returns), 6) if returns else None,
                worst=round(min(returns), 6) if returns else None,
                is_significant=len(trades) >= MIN_TRADES_FOR_SIGNIFICANCE,
            )
        )

    return sorted(stats, key=lambda s: s.total_pnl, reverse=True)


def concentration(records: list[TradeRecord]) -> dict:
    """How much of the P&L came from how few trades.

    A strategy whose entire result is three trades has not demonstrated an
    edge; it has demonstrated that three things happened. This is the single
    most useful check against reading a good backtest as a good strategy.
    """
    if not records:
        return {"trades": 0, "note": "No trades to analyse."}

    pnls = sorted((t.pnl for t in records), reverse=True)
    total = sum(pnls)
    positive = sum(p for p in pnls if p > 0)

    def share(n: int) -> float | None:
        if total == 0 or n > len(pnls):
            return None
        return round(sum(pnls[:n]) / total, 4)

    return {
        "trades": len(pnls),
        "total_pnl": round(total, 2),
        "top_1_share_of_pnl": share(1),
        "top_5_share_of_pnl": share(5),
        "top_10_share_of_pnl": share(10),
        "winners": sum(1 for p in pnls if p > 0),
        "losers": sum(1 for p in pnls if p < 0),
        "gross_profit": round(positive, 2),
        "largest_win": round(pnls[0], 2),
        "largest_loss": round(pnls[-1], 2),
    }


def by_ticker(records: list[TradeRecord]) -> dict[str, dict]:
    """Is the edge broad, or is it one name?"""
    groups: dict[str, list[TradeRecord]] = {}
    for record in records:
        groups.setdefault(record.ticker, []).append(record)

    out = {}
    for ticker, trades in sorted(groups.items()):
        returns = [t.return_pct for t in trades]
        out[ticker] = {
            "trades": len(trades),
            "total_pnl": round(sum(t.pnl for t in trades), 2),
            "win_rate": round(sum(1 for r in returns if r > 0) / len(returns), 4),
            "average_return": round(sum(returns) / len(returns), 6),
        }
    return out
