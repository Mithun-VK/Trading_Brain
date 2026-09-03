"""phase 40 ai requests

Audit trail for every AI invocation: what was asked, where it was routed and
why, what it consumed, and what it cost.

Deliberately stores a prompt *fingerprint* rather than the prompt. Prompts
carry portfolio positions and thesis reasoning, and a durable table of them
is a liability that grows quietly. The fingerprint is enough to detect
duplicates and correlate a complaint with a request.

Revision ID: a2e5f81b6c34
Revises: f1c9d3a705e6
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "a2e5f81b6c34"
down_revision = "f1c9d3a705e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("principal", sa.String(length=128), nullable=True),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("trigger", sa.String(length=128), nullable=True),
        sa.Column("prompt_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("context_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tier", sa.String(length=32), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("routing_reason", sa.Text(), nullable=True),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("escalation_reason", sa.Text(), nullable=True),
        sa.Column("downgraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Nullable throughout: a provider that does not report token counts
        # must not be recorded as having used zero.
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("cost_currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("cost_known", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cost_unknown_reason", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_kind", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_ai_requests_request_id", "ai_requests", ["request_id"])
    op.create_index("ix_ai_requests_created_at", "ai_requests", ["created_at"])
    op.create_index("ix_ai_requests_task_type", "ai_requests", ["task_type"])
    op.create_index("ix_ai_requests_ticker", "ai_requests", ["ticker"])
    op.create_index("ix_ai_requests_prompt_fingerprint", "ai_requests", ["prompt_fingerprint"])
    op.create_index("ix_ai_requests_tier", "ai_requests", ["tier"])
    op.create_index("ix_ai_requests_provider", "ai_requests", ["provider"])
    op.create_index("ix_ai_requests_model", "ai_requests", ["model"])
    op.create_index("ix_ai_requests_success", "ai_requests", ["success"])
    op.create_index("ix_ai_requests_blocked", "ai_requests", ["blocked"])
    op.create_index("ix_ai_requests_error_kind", "ai_requests", ["error_kind"])
    op.create_index("ix_ai_requests_cache_hit", "ai_requests", ["cache_hit"])
    # The three questions actually asked of this table.
    op.create_index("ix_ai_requests_created_task", "ai_requests", ["created_at", "task_type"])
    op.create_index("ix_ai_requests_created_model", "ai_requests", ["created_at", "model"])


def downgrade() -> None:
    op.drop_index("ix_ai_requests_created_model", table_name="ai_requests")
    op.drop_index("ix_ai_requests_created_task", table_name="ai_requests")
    op.drop_index("ix_ai_requests_cache_hit", table_name="ai_requests")
    op.drop_index("ix_ai_requests_error_kind", table_name="ai_requests")
    op.drop_index("ix_ai_requests_blocked", table_name="ai_requests")
    op.drop_index("ix_ai_requests_success", table_name="ai_requests")
    op.drop_index("ix_ai_requests_model", table_name="ai_requests")
    op.drop_index("ix_ai_requests_provider", table_name="ai_requests")
    op.drop_index("ix_ai_requests_tier", table_name="ai_requests")
    op.drop_index("ix_ai_requests_prompt_fingerprint", table_name="ai_requests")
    op.drop_index("ix_ai_requests_ticker", table_name="ai_requests")
    op.drop_index("ix_ai_requests_task_type", table_name="ai_requests")
    op.drop_index("ix_ai_requests_created_at", table_name="ai_requests")
    op.drop_index("ix_ai_requests_request_id", table_name="ai_requests")
    op.drop_table("ai_requests")
