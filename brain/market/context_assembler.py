"""Builds a `ContextBundle` for a ticker by pulling targeted slices of
Obsidian, PostgreSQL, and the quant engine -- never the full vault.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from brain.market.context import ContextBundle
from data.ingestion.provider import MarketDataProvider
from integrations.obsidian.errors import ObsidianError
from integrations.obsidian.knowledge_store import KnowledgeStore
from models.asset import Asset
from models.market_regime import MarketRegimeObservation
from models.thesis import Thesis
from models.trade import Trade
from quant.indicators.moving_average import sma
from quant.indicators.oscillators import rsi
from quant.indicators.returns import simple_returns, volatility

_SEARCH_LIMIT = 5


class ContextAssembler:
    def __init__(
        self,
        knowledge_store: KnowledgeStore,
        session: Session,
        market_data: MarketDataProvider,
    ) -> None:
        self._knowledge_store = knowledge_store
        self._session = session
        self._market_data = market_data

    def build(
        self,
        ticker: str,
        *,
        include_company: bool = True,
        include_sector: bool = True,
        include_macro: bool = False,
        include_thesis: bool = True,
        include_recent_trades: bool = True,
    ) -> ContextBundle:
        bundle = ContextBundle(ticker=ticker)
        asset = self._get_asset(ticker)

        sector = asset.company.sector if asset is not None and asset.company is not None else None

        if include_company:
            bundle.company_notes = self._safe_search(ticker)
        if include_sector and sector:
            bundle.sector_notes = self._safe_search(sector)
        if include_macro:
            bundle.macro_notes = self._safe_search("macro")
        if include_thesis and asset is not None:
            bundle.thesis_summary, bundle.thesis_note = self._get_thesis(asset)
        if include_recent_trades and asset is not None:
            bundle.recent_trades = self._get_recent_trades(asset)

        bundle.quant_summary = self._compute_quant_summary(ticker)
        bundle.market_regime = self._get_latest_regime()
        return bundle

    def _get_asset(self, ticker: str) -> Asset | None:
        return self._session.scalars(select(Asset).where(Asset.ticker == ticker)).first()

    def _safe_search(self, query: str) -> list[Any]:
        try:
            return self._knowledge_store.search(query, limit=_SEARCH_LIMIT)
        except ObsidianError:
            return []

    def _get_thesis(self, asset: Asset) -> tuple[dict[str, Any] | None, Any]:
        thesis = self._session.scalars(
            select(Thesis)
            .where(Thesis.asset_id == asset.id, Thesis.status == "active")
            .order_by(Thesis.updated_at.desc())
        ).first()
        if thesis is None:
            return None, None

        summary = {
            "title": thesis.title,
            "current_assessment": thesis.current_assessment,
            "conviction": thesis.conviction,
            "time_horizon": thesis.time_horizon,
        }
        note = None
        if thesis.obsidian_note_path:
            try:
                note = self._knowledge_store.read(thesis.obsidian_note_path)
            except ObsidianError:
                note = None
        return summary, note

    def _get_recent_trades(self, asset: Asset, limit: int = 5) -> list[dict[str, Any]]:
        trades = self._session.scalars(
            select(Trade)
            .where(Trade.asset_id == asset.id)
            .order_by(Trade.opened_at.desc())
            .limit(limit)
        ).all()
        return [
            {
                "direction": t.direction,
                "status": t.status,
                "result": t.result,
                "r_multiple": float(t.r_multiple) if t.r_multiple is not None else None,
                "opened_at": t.opened_at.isoformat(),
            }
            for t in trades
        ]

    def _compute_quant_summary(self, ticker: str) -> dict[str, Any]:
        today = dt.datetime.now(dt.UTC).date()
        bars = self._market_data.get_historical_prices(
            ticker, today - dt.timedelta(days=400), today
        )
        if not bars:
            return {}

        closes = [bar.close for bar in bars]
        summary: dict[str, Any] = {
            "last_close": closes[-1],
            "source": bars[-1].source,
        }
        sma50 = sma(closes, 50)[-1]
        sma200 = sma(closes, 200)[-1]
        rsi14 = rsi(closes, 14)[-1]
        if sma50 is not None:
            summary["sma_50"] = round(sma50, 2)
        if sma200 is not None:
            summary["sma_200"] = round(sma200, 2)
        if rsi14 is not None:
            summary["rsi_14"] = round(rsi14, 2)
        if len(closes) > 20:
            summary["volatility_20d_annualized"] = round(
                volatility(simple_returns(closes[-21:])), 4
            )
        return summary

    def _get_latest_regime(self) -> dict[str, str] | None:
        row = self._session.scalars(
            select(MarketRegimeObservation).order_by(MarketRegimeObservation.observed_at.desc())
        ).first()
        if row is None:
            return None
        return {
            "trend_regime": row.regime,
            "volatility_regime": row.volatility_regime,
            "risk_regime": row.risk_regime,
        }
