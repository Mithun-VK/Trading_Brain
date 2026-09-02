"""phase 24 backtest runs

Revision ID: f1c9d3a705e6
Revises: e8b47a2f9c15
Create Date: 2026-09-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1c9d3a705e6"
down_revision: str | Sequence[str] | None = "e8b47a2f9c15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("tickers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("commission_bps", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("slippage_bps", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("equity_curve", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("closed_trades", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("unfilled", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_backtest_runs_strategy", "backtest_runs", ["strategy"])
    op.create_index("ix_backtest_runs_generated_at", "backtest_runs", ["generated_at"])


def downgrade() -> None:
    op.drop_table("backtest_runs")
