"""Audit row for one AI invocation.

Reuses the existing observability conventions rather than inventing a
parallel system: one row per request, written whether the request succeeded,
failed, or was blocked, so "how many were refused" is answerable and not
merely absent.

**Prompt content is deliberately not stored.** Only a fingerprint and sizes
are kept. Prompts carry portfolio positions, thesis reasoning, and whatever
a research note contains, and a durable table of them is a liability that
grows quietly. `prompt_fingerprint` is enough to detect duplicates and to
correlate a complaint with a request; the content itself is not needed after
the call and is not kept.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class AIRequestRecord(Base):
    __tablename__ = "ai_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # What was asked
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    principal: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    trigger: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    context_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Where it went, and why (Rule 12: routing must be auditable)
    tier: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    routing_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    downgraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # What it consumed. Nullable throughout: a provider that does not report
    # token counts must not be recorded as having used zero.
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Cost, and whether it is even knowable
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    cost_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost_unknown_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Outcome
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    error_kind: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    __table_args__ = (
        # The three questions actually asked of this table: spend over a
        # window, spend by task, and spend by model.
        Index("ix_ai_requests_created_task", "created_at", "task_type"),
        Index("ix_ai_requests_created_model", "created_at", "model"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<AIRequestRecord {self.request_id} {self.task_type} "
            f"{self.model} success={self.success}>"
        )
