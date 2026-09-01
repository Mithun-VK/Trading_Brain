"""Thesis Agent output. `ThesisAssessment` mirrors the values stored in
`models.Thesis.current_assessment` -- keep the two in sync if either changes.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, Field


class ThesisAssessment(StrEnum):
    THESIS_INTACT = "THESIS_INTACT"
    THESIS_STRENGTHENED = "THESIS_STRENGTHENED"
    THESIS_WEAKENED = "THESIS_WEAKENED"
    THESIS_INVALIDATED = "THESIS_INVALIDATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


THESIS_REVIEW_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "assessment": {"type": "string", "enum": [a.value for a in ThesisAssessment]},
        "reasoning": {"type": "string"},
        "supporting_evidence": {"type": "array", "items": {"type": "string"}},
        "contradicting_evidence": {"type": "array", "items": {"type": "string"}},
        "changed_assumptions": {"type": "array", "items": {"type": "string"}},
        "invalidation_conditions_triggered": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "assessment",
        "reasoning",
        "supporting_evidence",
        "contradicting_evidence",
        "changed_assumptions",
        "invalidation_conditions_triggered",
        "confidence",
    ],
}


class ThesisReview(BaseModel):
    thesis_id: int
    ticker: str
    previous_assessment: str
    assessment: ThesisAssessment
    reasoning: str
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    changed_assumptions: list[str] = Field(default_factory=list)
    invalidation_conditions_triggered: list[str] = Field(default_factory=list)
    confidence: float
    reviewed_at: dt.datetime
