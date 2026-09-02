"""phase 19 signal attention columns

Extends the existing `signals` table rather than adding a parallel one --
these are still signals, just richer ones.

Revision ID: c5a92b7e1d38
Revises: b4e81f0a6c27
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5a92b7e1d38"
down_revision: str | Sequence[str] | None = "b4e81f0a6c27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("signals", sa.Column("category", sa.String(32)))
    op.add_column("signals", sa.Column("confidence", sa.Numeric(5, 4)))
    op.add_column("signals", sa.Column("reasoning", sa.Text()))
    op.add_column(
        "signals", sa.Column("evidence", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column(
        "signals",
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    )
    op.add_column("signals", sa.Column("acknowledged_at", sa.DateTime(timezone=True)))
    op.create_index("ix_signals_category", "signals", ["category"])
    op.create_index("ix_signals_status", "signals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_signals_status", table_name="signals")
    op.drop_index("ix_signals_category", table_name="signals")
    op.drop_column("signals", "acknowledged_at")
    op.drop_column("signals", "status")
    op.drop_column("signals", "evidence")
    op.drop_column("signals", "reasoning")
    op.drop_column("signals", "confidence")
    op.drop_column("signals", "category")
