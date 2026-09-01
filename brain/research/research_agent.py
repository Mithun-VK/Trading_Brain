"""Research Agent: retrieves knowledge + quant metrics via ContextAssembler,
asks Claude to synthesize evidence into a structured ResearchAnalysis, then
renders that structure into an Obsidian Markdown report.

The structured JSON is always produced first; Markdown is a rendering of
it, never a separate free-text call -- so what's stored in Obsidian and
what TradingBrain reasoned about can never drift apart.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from brain.market.context_assembler import ContextAssembler
from brain.research.schemas import RESEARCH_ANALYSIS_SCHEMA, ResearchAnalysis
from data.storage.research_repository import get_latest_research_document, save_research_document
from integrations.claude.llm_provider import LLMProvider
from integrations.obsidian.knowledge_store import KnowledgeStore
from models.asset import Asset

_DISCLAIMER = (
    "> AI-generated research synthesis. Not a guaranteed prediction or financial "
    "advice (Rule 12). Confidence reflects Claude's own stated uncertainty, not a "
    "statistical guarantee."
)


class ResearchAgent:
    def __init__(
        self,
        context_assembler: ContextAssembler,
        llm_provider: LLMProvider,
        knowledge_store: KnowledgeStore,
        session: Session,
    ) -> None:
        self._context_assembler = context_assembler
        self._llm_provider = llm_provider
        self._knowledge_store = knowledge_store
        self._session = session

    def research(self, ticker: str, asset: Asset | None = None) -> ResearchAnalysis:
        bundle = self._context_assembler.build(ticker)
        prompt_context = bundle.to_prompt_context()

        previous_summary = None
        if asset is not None:
            previous = get_latest_research_document(self._session, asset.id)
            if previous is not None:
                previous_summary = previous.summary

        if previous_summary:
            prompt_context += f"\n\n## Previous research summary\n{previous_summary}"

        extracted = self._llm_provider.extract(
            prompt_context, schema=RESEARCH_ANALYSIS_SCHEMA, max_tokens=2048
        )

        source_notes = [
            note.path
            for note in (*bundle.company_notes, *bundle.sector_notes, *bundle.macro_notes)
        ]
        return ResearchAnalysis(ticker=ticker, source_notes=source_notes, **extracted)

    def render_markdown(self, analysis: ResearchAnalysis) -> str:
        lines = [
            "---",
            "type: research",
            f"ticker: {analysis.ticker}",
            f"confidence: {analysis.confidence}",
            f"generated: {dt.datetime.now(dt.UTC).date().isoformat()}",
            "---",
            "",
            f"# Research: {analysis.ticker}",
            "",
            _DISCLAIMER,
            "",
            "## Summary",
            analysis.summary,
            "",
            "## Positive Factors",
            *(f"- {f}" for f in analysis.positive_factors),
            "",
            "## Negative Factors",
            *(f"- {f}" for f in analysis.negative_factors),
            "",
            "## Contradictions",
            *(f"- {c}" for c in analysis.contradictions),
            "",
            "## Risks",
            *(f"- {r}" for r in analysis.risks),
            "",
            "## Catalysts",
            *(f"- {c}" for c in analysis.catalysts),
            "",
            "## Source Notes",
            *(f"- [[{n}]]" for n in analysis.source_notes),
        ]
        return "\n".join(lines)

    def publish(
        self, analysis: ResearchAnalysis, asset: Asset | None = None, note_path: str | None = None
    ) -> str:
        path = note_path or (
            f"08 Research/{analysis.ticker}-{dt.datetime.now(dt.UTC).date().isoformat()}.md"
        )
        self._knowledge_store.write(path, self.render_markdown(analysis))
        save_research_document(self._session, analysis, note_path=path, asset=asset)
        return path
