"""Backtest engine.

Execution model (this is the anti-lookahead contract):

    step i:  1. fill orders queued at step i-1, at bar[i].OPEN + slippage
             2. build a MarketView sliced through bar[i].CLOSE
             3. ask the strategy for signals
             4. queue the resulting orders for step i+1
             5. mark to market at bar[i].CLOSE

A signal computed from bar i's close therefore fills at bar i+1's open.
Filling at the same close would let a strategy trade on a price at the
instant it first observes it.

Position accounting is delegated to `quant.performance.portfolio` -- the
same functions the paper portfolio uses -- so a backtest and a paper trade
of the same sequence produce the same average cost and realized P&L.

Determinism: no wall clock, no randomness, and every iteration order is
sorted. The same inputs produce a byte-identical result.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from backtesting.market_view import MarketView
from backtesting.schemas import (
    BacktestConfig,
    BacktestResult,
    ClosedTrade,
    EquityPoint,
    Fill,
    SignalAction,
    StrategySignal,
)
from backtesting.sizing import FixedFractionSizer, PositionSizer
from backtesting.strategy import Strategy
from data.ingestion.schemas import PriceBar
from quant.indicators.returns import max_drawdown, simple_returns
from quant.performance.portfolio import PositionState, apply_buy, apply_sell
from quant.performance.stats import (
    cagr,
    expectancy,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    total_return,
    win_rate,
)


@dataclass
class _PendingOrder:
    signal: StrategySignal
    queued_at: dt.datetime


@dataclass
class _OpenLot:
    quantity: float
    entry_price: float
    opened_at: dt.datetime


class BacktestEngine:
    def __init__(
        self,
        config: BacktestConfig | None = None,
        sizer: PositionSizer | None = None,
    ) -> None:
        self.config = config or BacktestConfig()
        self.sizer = sizer or FixedFractionSizer()

    def run(
        self,
        strategy: Strategy,
        bars_by_ticker: dict[str, list[PriceBar]],
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
    ) -> BacktestResult:
        strategy.on_start()

        history = {
            ticker: sorted(bars, key=lambda b: b.ts)
            for ticker, bars in sorted(bars_by_ticker.items())
            if bars
        }
        timeline = self._build_timeline(history, start, end)

        result = BacktestResult(config=self.config)
        if not timeline:
            result.metrics = self._metrics([], [])
            return result

        result.start, result.end = timeline[0], timeline[-1]

        cash = self.config.initial_cash
        positions: dict[str, PositionState] = {}
        open_lots: dict[str, _OpenLot] = {}
        pending: list[_PendingOrder] = []

        for timestamp in timeline:
            # 1. Fill what was decided on the previous bar, at this bar's open.
            cash = self._execute_pending(
                pending, history, timestamp, cash, positions, open_lots, result
            )
            pending = []

            # 2-3. The strategy sees history only through this bar's close.
            view = MarketView.at(history, timestamp)
            equity = self._equity(cash, positions, view)
            signals = strategy.on_bar(view)

            # 4. Queue for the next bar.
            for signal in signals:
                if signal.action is not SignalAction.HOLD:
                    pending.append(_PendingOrder(signal=signal, queued_at=timestamp))

            # 5. Mark to market on the close.
            positions_value = equity - cash
            result.equity_curve.append(
                EquityPoint(
                    timestamp=timestamp,
                    cash=round(cash, 6),
                    positions_value=round(positions_value, 6),
                    equity=round(equity, 6),
                )
            )

        # Orders still queued after the final bar can never fill.
        for order in pending:
            result.unfilled.append(
                {
                    "ticker": order.signal.ticker,
                    "action": str(order.signal.action),
                    "queued_at": order.queued_at.isoformat(),
                    "reason": "no subsequent bar to fill against",
                }
            )

        result.metrics = self._metrics(
            result.equity_values, [t.pnl for t in result.closed_trades]
        )
        return result

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _build_timeline(
        history: dict[str, list[PriceBar]],
        start: dt.datetime | None,
        end: dt.datetime | None,
    ) -> list[dt.datetime]:
        stamps = {bar.ts for bars in history.values() for bar in bars}
        if start is not None:
            stamps = {ts for ts in stamps if ts >= start}
        if end is not None:
            stamps = {ts for ts in stamps if ts <= end}
        return sorted(stamps)

    def _execute_pending(
        self,
        pending: list[_PendingOrder],
        history: dict[str, list[PriceBar]],
        timestamp: dt.datetime,
        cash: float,
        positions: dict[str, PositionState],
        open_lots: dict[str, _OpenLot],
        result: BacktestResult,
    ) -> float:
        for order in pending:
            signal = order.signal
            bar = self._bar_at(history, signal.ticker, timestamp)
            if bar is None:
                result.unfilled.append(
                    {
                        "ticker": signal.ticker,
                        "action": str(signal.action),
                        "queued_at": order.queued_at.isoformat(),
                        "reason": "ticker did not trade on the next bar",
                    }
                )
                continue

            fill_price = self.config.slippage_price(bar.open, signal.action)
            slippage_cost = abs(fill_price - bar.open)
            state = positions.get(signal.ticker, PositionState())

            if signal.action is SignalAction.BUY:
                cash = self._fill_buy(
                    signal, bar, fill_price, slippage_cost, cash, state,
                    positions, open_lots, timestamp, result,
                )
            elif signal.action is SignalAction.SELL:
                cash = self._fill_sell(
                    signal, fill_price, slippage_cost, cash, state,
                    positions, open_lots, timestamp, result,
                )

        return cash

    def _fill_buy(
        self,
        signal: StrategySignal,
        bar: PriceBar,
        fill_price: float,
        slippage_cost: float,
        cash: float,
        state: PositionState,
        positions: dict[str, PositionState],
        open_lots: dict[str, _OpenLot],
        timestamp: dt.datetime,
        result: BacktestResult,
    ) -> float:
        equity_estimate = cash + sum(
            s.quantity * fill_price for t, s in positions.items() if t == signal.ticker
        )
        quantity = self.sizer.size(signal, fill_price, max(equity_estimate, cash), cash)
        if quantity <= 0:
            result.unfilled.append(
                {
                    "ticker": signal.ticker,
                    "action": "buy",
                    "queued_at": timestamp.isoformat(),
                    "reason": "sizer returned zero (insufficient cash or equity)",
                }
            )
            return cash

        commission = self.config.commission_on(quantity * fill_price)
        if quantity * fill_price + commission > cash:
            # Trim to what cash actually supports rather than going negative.
            quantity = max(0.0, (cash / (fill_price * (1 + self.config.commission_bps / 10_000))))
            commission = self.config.commission_on(quantity * fill_price)
        if quantity <= 0:
            return cash

        effect = apply_buy(state, quantity, fill_price, fees=commission)
        positions[signal.ticker] = effect.state
        cash += effect.cash_delta

        lot = open_lots.get(signal.ticker)
        open_lots[signal.ticker] = _OpenLot(
            quantity=effect.state.quantity,
            entry_price=effect.state.average_cost,
            opened_at=lot.opened_at if lot else timestamp,
        )

        result.fills.append(
            Fill(
                ticker=signal.ticker,
                action=SignalAction.BUY,
                quantity=round(quantity, 6),
                price=round(fill_price, 6),
                commission=round(commission, 6),
                slippage=round(slippage_cost * quantity, 6),
                timestamp=timestamp,
                reason=signal.reason,
            )
        )
        return cash

    def _fill_sell(
        self,
        signal: StrategySignal,
        fill_price: float,
        slippage_cost: float,
        cash: float,
        state: PositionState,
        positions: dict[str, PositionState],
        open_lots: dict[str, _OpenLot],
        timestamp: dt.datetime,
        result: BacktestResult,
    ) -> float:
        if state.quantity <= 0:
            result.unfilled.append(
                {
                    "ticker": signal.ticker,
                    "action": "sell",
                    "queued_at": timestamp.isoformat(),
                    "reason": "no position to sell (shorting is not supported)",
                }
            )
            return cash

        quantity = min(state.quantity, state.quantity * max(0.0, min(1.0, signal.strength)))
        if quantity <= 0:
            return cash

        commission = self.config.commission_on(quantity * fill_price)
        effect = apply_sell(state, quantity, fill_price, fees=commission)
        positions[signal.ticker] = effect.state
        cash += effect.cash_delta

        lot = open_lots.get(signal.ticker)
        if lot is not None:
            entry_price = lot.entry_price
            gross = quantity * (fill_price - entry_price)
            result.closed_trades.append(
                ClosedTrade(
                    ticker=signal.ticker,
                    quantity=round(quantity, 6),
                    entry_price=round(entry_price, 6),
                    exit_price=round(fill_price, 6),
                    opened_at=lot.opened_at,
                    closed_at=timestamp,
                    pnl=round(effect.realized_pnl, 6),
                    return_pct=round(gross / (entry_price * quantity), 6)
                    if entry_price > 0
                    else 0.0,
                )
            )
            if effect.state.quantity <= 0:
                open_lots.pop(signal.ticker, None)
            else:
                open_lots[signal.ticker] = _OpenLot(
                    quantity=effect.state.quantity,
                    entry_price=entry_price,
                    opened_at=lot.opened_at,
                )

        result.fills.append(
            Fill(
                ticker=signal.ticker,
                action=SignalAction.SELL,
                quantity=round(quantity, 6),
                price=round(fill_price, 6),
                commission=round(commission, 6),
                slippage=round(slippage_cost * quantity, 6),
                timestamp=timestamp,
                realized_pnl=round(effect.realized_pnl, 6),
                reason=signal.reason,
            )
        )
        return cash

    @staticmethod
    def _bar_at(
        history: dict[str, list[PriceBar]], ticker: str, timestamp: dt.datetime
    ) -> PriceBar | None:
        for bar in history.get(ticker, []):
            if bar.ts == timestamp:
                return bar
        return None

    @staticmethod
    def _equity(
        cash: float, positions: dict[str, PositionState], view: MarketView
    ) -> float:
        value = 0.0
        for ticker, state in sorted(positions.items()):
            if state.quantity <= 0:
                continue
            price = view.current_price(ticker)
            # A position with no observable price is held at cost rather
            # than dropped -- dropping it would silently shrink equity.
            value += state.quantity * (price if price is not None else state.average_cost)
        return cash + value

    def _metrics(self, equity_values: list[float], trade_pnls: list[float]) -> dict[str, float]:
        cfg = self.config
        if len(equity_values) < 2:
            returns: list[float] = []
        else:
            returns = simple_returns(equity_values)

        return {
            "total_return": round(total_return(equity_values), 6) if equity_values else 0.0,
            "cagr": round(cagr(equity_values, cfg.periods_per_year), 6)
            if equity_values
            else 0.0,
            "sharpe": round(
                sharpe_ratio(returns, cfg.risk_free_rate, cfg.periods_per_year), 6
            ),
            "sortino": round(
                sortino_ratio(returns, cfg.risk_free_rate, cfg.periods_per_year), 6
            ),
            "max_drawdown": round(max_drawdown(equity_values), 6),
            "win_rate": round(win_rate(trade_pnls), 6),
            "profit_factor": round(profit_factor(trade_pnls), 6)
            if profit_factor(trade_pnls) != float("inf")
            else float("inf"),
            "expectancy": round(expectancy(trade_pnls), 6),
            "trade_count": float(len(trade_pnls)),
        }
