"""Trading Journal review output. Statistics are always computed
deterministically (quant/performance/stats.py) before Claude ever sees
them -- Claude only identifies qualitative patterns over data it's handed,
never recomputes a number (Rule 2).
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

MIN_SAMPLE_SIZE = 10

PATTERN_REVIEW_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "patterns": {"type": "array", "items": {"type": "string"}},
        "repeated_mistakes": {"type": "array", "items": {"type": "string"}},
        "rule_violations": {"type": "array", "items": {"type": "string"}},
        "lessons": {"type": "array", "items": {"type": "string"}},
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Lower when sample size is small (Rule: don't claim "
            "significance a small sample doesn't support).",
        },
    },
    "required": ["patterns", "repeated_mistakes", "rule_violations", "lessons", "confidence"],
}


class GroupStats(BaseModel):
    label: str
    trade_count: int
    win_rate: float
    profit_factor: float
    expectancy_r: float
    average_winner_r: float
    average_loser_r: float
    sample_size_warning: str | None = None


class JournalReview(BaseModel):
    period_start: dt.date | None
    period_end: dt.date | None
    overall: GroupStats
    by_strategy: list[GroupStats] = Field(default_factory=list)
    by_regime: list[GroupStats] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    repeated_mistakes: list[str] = Field(default_factory=list)
    rule_violations: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    confidence: float
    generated_at: dt.datetime
