"""phase 17 research queue

Revision ID: b4e81f0a6c27
Revises: 9d2f7a1c3e58
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4e81f0a6c27"
down_revision: str | Sequence[str] | None = "9d2f7a1c3e58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("change_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("score", sa.Numeric(6, 4), nullable=False),
        sa.Column("importance", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("novelty", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("portfolio_impact", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("watchlist_relevance", sa.Numeric(6, 4), nullable=False, server_default="0"),
        sa.Column("reasons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("note", sa.Text()),
        sa.Column(
            "detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "research_document_id", sa.Integer(), sa.ForeignKey("research_documents.id")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_research_queue_asset_id", "research_queue", ["asset_id"])
    op.create_index("ix_research_queue_ticker", "research_queue", ["ticker"])
    op.create_index("ix_research_queue_change_type", "research_queue", ["change_type"])
    op.create_index("ix_research_queue_status", "research_queue", ["status"])
    op.create_index("ix_research_queue_score", "research_queue", ["score"])


def downgrade() -> None:
    op.drop_table("research_queue")
