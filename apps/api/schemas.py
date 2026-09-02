"""Shared response models for the API routers."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class AssetOut(BaseModel):
    ticker: str
    exchange: str
    asset_type: str
    name: str
    currency: str
    sector: str | None = None
    industry: str | None = None


class QuoteOut(BaseModel):
    ticker: str
    price: float
    change: float
    change_percent: float
    volume: int
    as_of: dt.datetime
    source: str


class AnalysisOut(BaseModel):
    ticker: str
    quant_summary: dict[str, object]
    market_regime: dict[str, str] | None = None


class MarketRegimeOut(BaseModel):
    observed_at: dt.datetime
    scope: str
    trend_regime: str
    volatility_regime: str
    risk_regime: str


class TradeIn(BaseModel):
    ticker: str
    direction: str
    strategy_name: str | None = None
    timeframe: str
    entry_price: float
    stop_price: float
    target_price: float | None = None
    risk_amount: float
    position_size: float
    market_regime: str | None = None
    opened_at: dt.datetime


class TradeOut(BaseModel):
    id: int
    ticker: str
    direction: str
    timeframe: str
    entry_price: float
    # Nullable: a paper trade may be opened without a defined stop, in which
    # case there is no honest risk_amount either.
    stop_price: float | None
    target_price: float | None
    risk_amount: float | None
    position_size: float
    r_multiple: float | None
    status: str
    result: str | None
    market_regime: str | None
    opened_at: dt.datetime
    closed_at: dt.datetime | None


class ThesisOut(BaseModel):
    id: int
    ticker: str
    title: str
    status: str
    current_assessment: str
    conviction: str | None
    time_horizon: str | None
    last_reviewed_at: dt.datetime | None


class PortfolioSummaryOut(BaseModel):
    open_trade_count: int
    open_exposure_value: float
    trades_by_status: dict[str, int]
