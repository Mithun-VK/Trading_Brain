"""Backtest API.

The backend is authoritative: the engine runs server-side, and results are
persisted with the full parameter set so a stored metric is reproducible
rather than a number without provenance.

Anti-lookahead is a property of the engine (`backtesting/`), not something
this router can weaken -- it only supplies a date range, and a range
extending into the future simply has no bars to leak.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dependencies import get_market_data, get_session
from apps.api.routers._common import get_asset_or_404
from apps.api.schemas_v2 import (
    BacktestOut,
    BacktestRunIn,
    BacktestTradeOut,
    EquityPointOut,
)
from backtesting.engine import BacktestEngine
from backtesting.schemas import BacktestConfig, BacktestResult
from backtesting.sizing import FixedFractionSizer
from backtesting.strategy import BuyAndHoldStrategy, MovingAverageCrossStrategy, Strategy
from data.ingestion.errors import ProviderError
from data.ingestion.provider import MarketDataProvider
from models.backtest_run import BacktestRun

router = APIRouter(tags=["backtests"])

STRATEGIES = ("buy_and_hold", "ma_cross")
# A backtest over an unbounded range is a denial-of-service on your own API.
MAX_RANGE_DAYS = 3650


def _build_strategy(payload: BacktestRunIn) -> Strategy:
    if payload.strategy == "buy_and_hold":
        return BuyAndHoldStrategy(list(payload.tickers))
    if payload.strategy == "ma_cross":
        if payload.fast >= payload.slow:
            raise HTTPException(
                status_code=422, detail="fast window must be shorter than slow window"
            )
        return MovingAverageCrossStrategy(
            fast=payload.fast, slow=payload.slow, tickers=list(payload.tickers)
        )
    raise HTTPException(
        status_code=422,
        detail=f"Unknown strategy {payload.strategy!r}. Available: {', '.join(STRATEGIES)}",
    )


def _to_out(run: BacktestRun) -> BacktestOut:
    return BacktestOut(
        id=run.id,
        strategy=run.strategy,
        tickers=list(run.tickers or []),
        start=run.period_start,
        end=run.period_end,
        parameters=dict(run.parameters or {}),
        commission_bps=float(run.commission_bps),
        slippage_bps=float(run.slippage_bps),
        metrics=dict(run.metrics or {}),
        equity_curve=[EquityPointOut(**p) for p in (run.equity_curve or [])],
        closed_trades=[BacktestTradeOut(**t) for t in (run.closed_trades or [])],
        unfilled=list(run.unfilled or []),
        generated_at=run.generated_at,
    )


def _serialize(result: BacktestResult) -> tuple[list[dict], list[dict]]:
    equity = [
        {
            "timestamp": p.timestamp.isoformat(),
            "equity": p.equity,
            "cash": p.cash,
            "positions_value": p.positions_value,
        }
        for p in result.equity_curve
    ]
    trades = [
        {
            "ticker": t.ticker,
            "quantity": t.quantity,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "opened_at": t.opened_at.isoformat(),
            "closed_at": t.closed_at.isoformat(),
            "pnl": t.pnl,
            "return_pct": t.return_pct,
        }
        for t in result.closed_trades
    ]
    return equity, trades


@router.get("/backtests", response_model=list[BacktestOut])
def list_backtests(
    strategy: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[BacktestOut]:
    query = select(BacktestRun).order_by(BacktestRun.generated_at.desc())
    if strategy:
        query = query.where(BacktestRun.strategy == strategy)
    return [_to_out(r) for r in session.scalars(query.limit(limit)).all()]


@router.get("/backtests/{run_id}", response_model=BacktestOut)
def get_backtest(run_id: int, session: Session = Depends(get_session)) -> BacktestOut:
    run = session.get(BacktestRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No backtest with id {run_id}")
    return _to_out(run)


@router.post("/backtests/run", response_model=BacktestOut, status_code=201)
def run_backtest(
    payload: BacktestRunIn,
    session: Session = Depends(get_session),
    market_data: MarketDataProvider = Depends(get_market_data),
) -> BacktestOut:
    if payload.end < payload.start:
        raise HTTPException(status_code=422, detail="end must not be before start")
    if (payload.end - payload.start).days > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422, detail=f"Date range exceeds {MAX_RANGE_DAYS} days"
        )

    # Every ticker must be a known asset -- a backtest on a symbol the
    # system doesn't track would silently measure nothing.
    for ticker in payload.tickers:
        get_asset_or_404(session, ticker)

    strategy = _build_strategy(payload)

    bars_by_ticker = {}
    for ticker in payload.tickers:
        try:
            bars_by_ticker[ticker] = market_data.get_historical_prices(
                ticker, payload.start, payload.end
            )
        except ProviderError as exc:
            raise HTTPException(
                status_code=502, detail=f"Market data unavailable for {ticker}: {exc}"
            ) from exc

    if not any(bars_by_ticker.values()):
        raise HTTPException(
            status_code=422,
            detail="No price data available for the requested tickers and range",
        )

    engine = BacktestEngine(
        BacktestConfig(
            initial_cash=payload.initial_cash,
            commission_bps=payload.commission_bps,
            slippage_bps=payload.slippage_bps,
        ),
        sizer=FixedFractionSizer(payload.position_fraction),
    )
    result = engine.run(strategy, bars_by_ticker)
    equity, trades = _serialize(result)

    parameters = {
        "initial_cash": payload.initial_cash,
        "position_fraction": payload.position_fraction,
    }
    if payload.strategy == "ma_cross":
        parameters |= {"fast": payload.fast, "slow": payload.slow}

    run = BacktestRun(
        strategy=payload.strategy,
        tickers=list(payload.tickers),
        period_start=payload.start,
        period_end=payload.end,
        parameters=parameters,
        commission_bps=payload.commission_bps,
        slippage_bps=payload.slippage_bps,
        metrics={
            k: (None if v == float("inf") else v) for k, v in result.metrics.items()
        },
        equity_curve=equity,
        closed_trades=trades,
        unfilled=result.unfilled,
        generated_at=dt.datetime.now(dt.UTC),
    )
    session.add(run)
    session.commit()
    return _to_out(run)
