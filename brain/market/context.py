"""Structured context for a Claude call: targeted retrieval across
Obsidian, PostgreSQL, and the deterministic quant engine -- never the full
vault (see docs/research-agents.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from integrations.obsidian.knowledge_store import Note, SearchResult


@dataclass
class ContextBundle:
    ticker: str
    company_notes: list[SearchResult] = field(default_factory=list)
    sector_notes: list[SearchResult] = field(default_factory=list)
    macro_notes: list[SearchResult] = field(default_factory=list)
    thesis_summary: dict[str, Any] | None = None
    thesis_note: Note | None = None
    recent_trades: list[dict[str, Any]] = field(default_factory=list)
    quant_summary: dict[str, Any] = field(default_factory=dict)
    market_regime: dict[str, str] | None = None

    def to_prompt_context(self) -> str:
        """Render a compact text block suitable for an LLM prompt -- note
        paths and short search-result snippets, not full note bodies.
        """
        lines = [f"# Context for {self.ticker}", ""]

        if self.quant_summary:
            lines.append("## Quantitative summary (deterministic)")
            for key, value in self.quant_summary.items():
                lines.append(f"- {key}: {value}")
            lines.append("")

        if self.market_regime:
            lines.append("## Market regime (descriptive, not predictive)")
            for key, value in self.market_regime.items():
                lines.append(f"- {key}: {value}")
            lines.append("")

        if self.thesis_summary:
            lines.append("## Active thesis")
            for key, value in self.thesis_summary.items():
                lines.append(f"- {key}: {value}")
            lines.append("")

        if self.recent_trades:
            lines.append("## Recent trades")
            for trade in self.recent_trades:
                lines.append(f"- {trade}")
            lines.append("")

        for label, notes in (
            ("Company notes", self.company_notes),
            ("Sector notes", self.sector_notes),
            ("Macro notes", self.macro_notes),
        ):
            if notes:
                lines.append(f"## {label}")
                for note in notes:
                    lines.append(f"- {note.path}: {note.context}")
                lines.append("")

        if self.thesis_note:
            lines.append("## Thesis note excerpt")
            lines.append(self.thesis_note.content[:2000])

        return "\n".join(lines)
