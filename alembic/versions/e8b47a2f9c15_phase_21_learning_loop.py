"""phase 21 learning loop

Revision ID: e8b47a2f9c15
Revises: d7f13c86b402
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8b47a2f9c15"
down_revision: str | Sequence[str] | None = "d7f13c86b402"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "thesis_review_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thesis_id", sa.Integer(), sa.ForeignKey("theses.id"), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id")),
        sa.Column("previous_assessment", sa.String(32), nullable=False),
        sa.Column("assessment", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("reasoning", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_thesis_review_records_thesis_id", "thesis_review_records", ["thesis_id"])
    op.create_index("ix_thesis_review_records_asset_id", "thesis_review_records", ["asset_id"])
    op.create_index(
        "ix_thesis_review_records_assessment", "thesis_review_records", ["assessment"]
    )
    op.create_index(
        "ix_thesis_review_records_reviewed_at", "thesis_review_records", ["reviewed_at"]
    )

    op.create_table(
        "learning_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("summary", sa.Text()),
        sa.Column("obsidian_note_path", sa.String(512)),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("kind", "period_start", name="uq_learning_reviews_kind_period"),
    )
    op.create_index("ix_learning_reviews_kind", "learning_reviews", ["kind"])
    op.create_index("ix_learning_reviews_period_start", "learning_reviews", ["period_start"])
    op.create_index("ix_learning_reviews_generated_at", "learning_reviews", ["generated_at"])


def downgrade() -> None:
    op.drop_table("learning_reviews")
    op.drop_table("thesis_review_records")
