"""Structured Research Agent output. Populated internally as JSON (via
Claude's forced tool-use extraction), then rendered to Obsidian Markdown --
never the other way around, so the structured form is always the source of
truth for what was actually said.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

RESEARCH_ANALYSIS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "positive_factors": {"type": "array", "items": {"type": "string"}},
        "negative_factors": {"type": "array", "items": {"type": "string"}},
        "contradictions": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "catalysts": {"type": "array", "items": {"type": "string"}},
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Claude's stated confidence in this analysis, 0-1 (Rule 11).",
        },
    },
    "required": [
        "summary",
        "positive_factors",
        "negative_factors",
        "contradictions",
        "risks",
        "catalysts",
        "confidence",
    ],
}


class ResearchAnalysis(BaseModel):
    ticker: str
    summary: str
    positive_factors: list[str] = Field(default_factory=list)
    negative_factors: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    confidence: float
    source_notes: list[str] = Field(default_factory=list)
