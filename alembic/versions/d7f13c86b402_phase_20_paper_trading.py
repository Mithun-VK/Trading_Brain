"""phase 20 paper trading

Adds proposals and portfolio snapshots, and relaxes two `trades` columns to
nullable: a paper position opened without a stop has no risk_amount and no
honest R-multiple, and back-fitting one from the exit price would invent
risk that was never defined.

Revision ID: d7f13c86b402
Revises: c5a92b7e1d38
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7f13c86b402"
down_revision: str | Sequence[str] | None = "c5a92b7e1d38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_trade_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("paper_portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("reference_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("stop_price", sa.Numeric(18, 6)),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="pending_approval"
        ),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("source_signal_id", sa.Integer(), sa.ForeignKey("signals.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_note", sa.Text()),
        sa.Column(
            "executed_transaction_id", sa.Integer(), sa.ForeignKey("paper_transactions.id")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_paper_trade_proposals_portfolio_id", "paper_trade_proposals", ["portfolio_id"]
    )
    op.create_index("ix_paper_trade_proposals_asset_id", "paper_trade_proposals", ["asset_id"])
    op.create_index("ix_paper_trade_proposals_ticker", "paper_trade_proposals", ["ticker"])
    op.create_index("ix_paper_trade_proposals_status", "paper_trade_proposals", ["status"])
    op.create_index(
        "ix_paper_trade_proposals_source_signal_id",
        "paper_trade_proposals",
        ["source_signal_id"],
    )

    op.create_table(
        "paper_portfolio_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("paper_portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("cash", sa.Numeric(18, 6), nullable=False),
        sa.Column("positions_value", sa.Numeric(18, 6), nullable=False),
        sa.Column("equity", sa.Numeric(18, 6), nullable=False),
        sa.Column("exposure", sa.Numeric(9, 6), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("unpriced_positions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("portfolio_id", "as_of", name="uq_paper_snapshots_portfolio_date"),
    )
    op.create_index(
        "ix_paper_portfolio_snapshots_portfolio_id",
        "paper_portfolio_snapshots",
        ["portfolio_id"],
    )
    op.create_index(
        "ix_paper_portfolio_snapshots_as_of", "paper_portfolio_snapshots", ["as_of"]
    )

    op.alter_column("trades", "stop_price", existing_type=sa.Numeric(18, 6), nullable=True)
    op.alter_column("trades", "risk_amount", existing_type=sa.Numeric(18, 6), nullable=True)


def downgrade() -> None:
    op.alter_column("trades", "risk_amount", existing_type=sa.Numeric(18, 6), nullable=False)
    op.alter_column("trades", "stop_price", existing_type=sa.Numeric(18, 6), nullable=False)
    op.drop_table("paper_portfolio_snapshots")
    op.drop_table("paper_trade_proposals")
