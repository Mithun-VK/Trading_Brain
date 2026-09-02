"""phase 16 watchlists and paper portfolio

Revision ID: 9d2f7a1c3e58
Revises: 7c41e5b2d904
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9d2f7a1c3e58"
down_revision: str | Sequence[str] | None = "7c41e5b2d904"
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
        "watchlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("kind", sa.String(32), nullable=False, server_default="personal"),
        _created_at(),
        _updated_at(),
    )
    op.create_index("ix_watchlists_name", "watchlists", ["name"])
    op.create_index("ix_watchlists_kind", "watchlists", ["kind"])

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "watchlist_id",
            sa.Integer(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("watchlist_id", "asset_id", name="uq_watchlist_items_list_asset"),
    )
    op.create_index("ix_watchlist_items_watchlist_id", "watchlist_items", ["watchlist_id"])
    op.create_index("ix_watchlist_items_asset_id", "watchlist_items", ["asset_id"])

    op.create_table(
        "paper_portfolios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("base_currency", sa.String(8), nullable=False, server_default="INR"),
        sa.Column("initial_cash", sa.Numeric(18, 6), nullable=False),
        sa.Column("cash_balance", sa.Numeric(18, 6), nullable=False),
        sa.Column("description", sa.Text()),
        _created_at(),
        _updated_at(),
    )
    op.create_index("ix_paper_portfolios_name", "paper_portfolios", ["name"])

    op.create_table(
        "paper_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("paper_portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("average_cost", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint(
            "portfolio_id", "asset_id", name="uq_paper_positions_portfolio_asset"
        ),
    )
    op.create_index("ix_paper_positions_portfolio_id", "paper_positions", ["portfolio_id"])
    op.create_index("ix_paper_positions_asset_id", "paper_positions", ["asset_id"])

    op.create_table(
        "paper_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("paper_portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("price", sa.Numeric(18, 6), nullable=False),
        sa.Column("fees", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("cash_delta", sa.Numeric(18, 6), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("note", sa.Text()),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
    )
    op.create_index("ix_paper_transactions_portfolio_id", "paper_transactions", ["portfolio_id"])
    op.create_index("ix_paper_transactions_asset_id", "paper_transactions", ["asset_id"])
    op.create_index("ix_paper_transactions_executed_at", "paper_transactions", ["executed_at"])


def downgrade() -> None:
    op.drop_table("paper_transactions")
    op.drop_table("paper_positions")
    op.drop_table("paper_portfolios")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
