"""initial schema

Revision ID: f2cbe2c691b0
Revises:
Create Date: 2026-09-01 19:37:20.192154

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2cbe2c691b0"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("ticker", "exchange", name="uq_assets_ticker_exchange"),
    )
    op.create_index("ix_assets_ticker", "assets", ["ticker"])

    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False, unique=True
        ),
        sa.Column("sector", sa.String(128)),
        sa.Column("industry", sa.String(128)),
        sa.Column("market_cap", sa.BigInteger()),
        sa.Column("country", sa.String(64)),
        _created_at(),
        _updated_at(),
    )
    op.create_index("ix_companies_asset_id", "companies", ["asset_id"])

    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("rules", sa.JSON(), nullable=False, server_default="{}"),
        _created_at(),
        _updated_at(),
    )
    op.create_index("ix_strategies_name", "strategies", ["name"])

    op.create_table(
        "prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("open", sa.Numeric(18, 6), nullable=False),
        sa.Column("high", sa.Numeric(18, 6), nullable=False),
        sa.Column("low", sa.Numeric(18, 6), nullable=False),
        sa.Column("close", sa.Numeric(18, 6), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        _created_at(),
        sa.UniqueConstraint("asset_id", "ts", "interval", name="uq_prices_asset_ts_interval"),
    )
    op.create_index("ix_prices_asset_id", "prices", ["asset_id"])
    op.create_index("ix_prices_ts", "prices", ["ts"])

    op.create_table(
        "financial_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("metric_name", sa.String(64), nullable=False),
        sa.Column("period", sa.String(32), nullable=False),
        sa.Column("value", sa.Numeric(24, 6), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "asset_id", "metric_name", "period", "as_of_date", name="uq_financial_metrics_identity"
        ),
    )
    op.create_index("ix_financial_metrics_asset_id", "financial_metrics", ["asset_id"])
    op.create_index("ix_financial_metrics_metric_name", "financial_metrics", ["metric_name"])

    op.create_table(
        "market_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("related_asset_id", sa.Integer(), sa.ForeignKey("assets.id")),
        sa.Column("source", sa.String(64), nullable=False),
        _created_at(),
    )
    op.create_index("ix_market_events_event_type", "market_events", ["event_type"])
    op.create_index("ix_market_events_occurred_at", "market_events", ["occurred_at"])
    op.create_index("ix_market_events_related_asset_id", "market_events", ["related_asset_id"])

    op.create_table(
        "market_regimes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False, server_default="broad_market"),
        sa.Column("regime", sa.String(32), nullable=False),
        sa.Column("volatility_regime", sa.String(32), nullable=False),
        sa.Column("risk_regime", sa.String(32), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        _created_at(),
    )
    op.create_index("ix_market_regimes_observed_at", "market_regimes", ["observed_at"])

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("signal_type", sa.String(64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
    )
    op.create_index("ix_signals_asset_id", "signals", ["asset_id"])
    op.create_index("ix_signals_signal_type", "signals", ["signal_type"])
    op.create_index("ix_signals_generated_at", "signals", ["generated_at"])

    op.create_table(
        "research_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("obsidian_note_path", sa.String(512)),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("source", sa.String(32), nullable=False),
        _created_at(),
    )
    op.create_index("ix_research_documents_asset_id", "research_documents", ["asset_id"])

    op.create_table(
        "theses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "current_assessment",
            sa.String(32),
            nullable=False,
            server_default="INSUFFICIENT_EVIDENCE",
        ),
        sa.Column("conviction", sa.String(16)),
        sa.Column("time_horizon", sa.String(32)),
        sa.Column("obsidian_note_path", sa.String(512)),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True)),
        _created_at(),
        _updated_at(),
    )
    op.create_index("ix_theses_asset_id", "theses", ["asset_id"])
    op.create_index("ix_theses_status", "theses", ["status"])

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("strategy_id", sa.Integer(), sa.ForeignKey("strategies.id")),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("entry_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("stop_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("target_price", sa.Numeric(18, 6)),
        sa.Column("risk_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("position_size", sa.Numeric(18, 6), nullable=False),
        sa.Column("r_multiple", sa.Numeric(10, 4)),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("result", sa.String(16)),
        sa.Column("market_regime", sa.String(32)),
        sa.Column("obsidian_note_path", sa.String(512)),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        _created_at(),
        _updated_at(),
    )
    op.create_index("ix_trades_asset_id", "trades", ["asset_id"])
    op.create_index("ix_trades_strategy_id", "trades", ["strategy_id"])
    op.create_index("ix_trades_status", "trades", ["status"])
    op.create_index("ix_trades_opened_at", "trades", ["opened_at"])

    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("avg_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        _created_at(),
        _updated_at(),
    )
    op.create_index("ix_positions_asset_id", "positions", ["asset_id"])
    op.create_index("ix_positions_status", "positions", ["status"])


def downgrade() -> None:
    op.drop_table("positions")
    op.drop_table("trades")
    op.drop_table("theses")
    op.drop_table("research_documents")
    op.drop_table("signals")
    op.drop_table("market_regimes")
    op.drop_table("market_events")
    op.drop_table("financial_metrics")
    op.drop_table("prices")
    op.drop_table("strategies")
    op.drop_table("companies")
    op.drop_table("assets")
