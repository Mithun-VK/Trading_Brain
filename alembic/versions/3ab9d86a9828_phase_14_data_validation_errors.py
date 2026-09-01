"""phase 14 data validation errors

Revision ID: 3ab9d86a9828
Revises: f2cbe2c691b0
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3ab9d86a9828"
down_revision: str | Sequence[str] | None = "f2cbe2c691b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_validation_errors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id")),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="error"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("bar_ts", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_data_validation_errors_asset_id", "data_validation_errors", ["asset_id"])
    op.create_index("ix_data_validation_errors_ticker", "data_validation_errors", ["ticker"])
    op.create_index("ix_data_validation_errors_code", "data_validation_errors", ["code"])


def downgrade() -> None:
    op.drop_table("data_validation_errors")
