"""Response/request models for the Phase 22-26 API surface.

Kept separate from `schemas.py` (the Phase 12 surface) so the original
contract stays readable; both are re-exported through the routers that use
them.

These are transport shapes only. Every number they carry is computed by a
domain service -- routers never calculate.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, field_validator

# --- watchlists --------------------------------------------------------------


class WatchlistItemOut(BaseModel):
    asset_id: int
    ticker: str
    name: str
    note: str | None = None
    added_at: dt.datetime | None = None


class WatchlistOut(BaseModel):
    id: int
    name: str
    description: str | None
    kind: str
    item_count: int
    items: list[WatchlistItemOut] = Field(default_factory=list)
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class WatchlistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: str = "personal"
    description: str | None = None

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        allowed = {"theme", "sector", "personal"}
        if value not in allowed:
            raise ValueError(f"kind must be one of {sorted(allowed)}")
        return value


class WatchlistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    kind: str | None = None


class WatchlistItemCreate(BaseModel):
    ticker: str = Field(min_length=1, max_length=32)
    note: str | None = None


# --- portfolio ---------------------------------------------------------------


class PositionOut(BaseModel):
    ticker: str
    quantity: float
    average_cost: float
    current_price: float | None
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    allocation: float
    # True when no current price was available; the position is excluded
    # from market value rather than valued at cost (Rule 4).
    unpriced: bool = False


class PortfolioOut(BaseModel):
    portfolio_name: str
    base_currency: str
    cash: float
    positions_value: float
    total_value: float
    unrealized_pnl: float
    realized_pnl: float
    total_return: float
    exposure: float
    position_count: int
    unpriced_positions: int


class PortfolioPerformanceOut(BaseModel):
    portfolio_name: str
    snapshots: int
    total_return: float
    daily_return: float | None
    cagr: float
    sharpe: float
    volatility: float
    max_drawdown: float
    current_equity: float
    current_exposure: float
    fully_priced: bool
    caveat: str | None = None


class ExposureBucketOut(BaseModel):
    label: str
    value: float
    weight: float


class ExposureOut(BaseModel):
    portfolio_name: str
    gross_exposure: float
    cash_weight: float
    by_sector: list[ExposureBucketOut] = Field(default_factory=list)
    by_asset: list[ExposureBucketOut] = Field(default_factory=list)
    unpriced_positions: int = 0


# --- signals -----------------------------------------------------------------


class EvidenceOut(BaseModel):
    kind: str
    detail: str
    stance: str
    value: float | str | None = None


class SignalOut(BaseModel):
    id: int
    asset_id: int
    ticker: str
    category: str
    confidence: float | None
    reasoning: str | None
    # Never empty: a signal without evidence is not returned (Rule 10).
    evidence: list[EvidenceOut]
    status: str
    generated_at: dt.datetime
    acknowledged_at: dt.datetime | None = None
    market_regime: str | None = None
    thesis_assessment: str | None = None
    latest_research_at: dt.datetime | None = None


# --- research queue ----------------------------------------------------------


class AIRecommendationOut(BaseModel):
    """The escalation gate's verdict, surfaced before anything is spent."""

    escalate: bool
    outcome: str
    tier: str | None
    reason: str
    materiality: float
    trigger: str | None = None


class ResearchQueueOut(BaseModel):
    id: int
    asset_id: int
    ticker: str
    change_type: str
    status: str
    score: float
    importance: float
    novelty: float
    portfolio_impact: float
    watchlist_relevance: float
    reasons: list[str] = Field(default_factory=list)
    detail: dict = Field(default_factory=dict)
    detected_at: dt.datetime
    processed_at: dt.datetime | None = None
    research_document_id: int | None = None
    note: str | None = None
    # Whether reasoning about this entry is judged worth paying for, and why.
    # Present on every entry including the refusals: "we considered this and
    # declined" is more useful operationally than a silently absent field.
    ai_recommendation: AIRecommendationOut | None = None


class QueueDismissIn(BaseModel):
    note: str | None = None


# --- backtests ---------------------------------------------------------------


class BacktestRunIn(BaseModel):
    strategy: str = Field(description="buy_and_hold | ma_cross")
    tickers: list[str] = Field(min_length=1)
    start: dt.date
    end: dt.date
    initial_cash: float = 100_000.0
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    position_fraction: float = Field(default=0.2, gt=0, le=1)
    fast: int = 10
    slow: int = 30

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, value: dt.date, info) -> dt.date:
        start = info.data.get("start")
        if start is not None and value < start:
            raise ValueError("end must not be before start")
        return value


class BacktestTradeOut(BaseModel):
    ticker: str
    quantity: float
    entry_price: float
    exit_price: float
    opened_at: dt.datetime
    closed_at: dt.datetime
    pnl: float
    return_pct: float


class EquityPointOut(BaseModel):
    timestamp: dt.datetime
    equity: float
    cash: float
    positions_value: float


class BacktestOut(BaseModel):
    id: int | None = None
    strategy: str
    tickers: list[str]
    start: dt.date
    end: dt.date
    parameters: dict
    commission_bps: float
    slippage_bps: float
    metrics: dict
    equity_curve: list[EquityPointOut] = Field(default_factory=list)
    closed_trades: list[BacktestTradeOut] = Field(default_factory=list)
    unfilled: list[dict] = Field(default_factory=list)
    generated_at: dt.datetime | None = None


# --- paper trades ------------------------------------------------------------


class PaperTradeCreate(BaseModel):
    portfolio: str
    ticker: str
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    stop_price: float | None = None
    target_price: float | None = None
    reasoning: str = Field(min_length=1)
    signal_id: int | None = None
    # Explicit human confirmation. The request is refused without it -- a
    # paper position is never opened as a side effect (Rule 7).
    confirm: bool = False


class PaperTradeCloseIn(BaseModel):
    price: float = Field(gt=0)
    confirm: bool = False


class PaperTradeOut(BaseModel):
    id: int
    ticker: str
    portfolio: str
    direction: str
    status: str
    quantity: float
    entry_price: float
    stop_price: float | None
    target_price: float | None
    risk_amount: float | None
    r_multiple: float | None
    result: str | None
    market_regime: str | None
    opened_at: dt.datetime
    closed_at: dt.datetime | None
    holding_period_days: int | None = None
    pnl: float | None = None
    signal_id: int | None = None
    reasoning: str | None = None


class PaperTradePerformanceOut(BaseModel):
    trade_count: int
    scored_trades: int
    win_rate: float
    profit_factor: float
    expectancy_r: float
    average_winner_r: float
    average_loser_r: float
    max_drawdown: float
    is_significant: bool
    caveat: str | None = None


# --- learning ----------------------------------------------------------------


class LearningReportOut(BaseModel):
    id: int
    kind: str
    period_start: dt.date
    period_end: dt.date
    generated_at: dt.datetime
    obsidian_note_path: str | None
    metrics: dict


class LearningGenerateIn(BaseModel):
    kind: str = "monthly"
    as_of: dt.date | None = None
    publish_to_obsidian: bool = False

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        allowed = {"monthly", "quarterly", "annual"}
        if value not in allowed:
            raise ValueError(f"kind must be one of {sorted(allowed)}")
        return value
