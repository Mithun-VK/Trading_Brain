"""Thesis Agent: compares current evidence against an existing thesis and
produces an explicit, auditable assessment.

Rule 9: every thesis change must be auditable. `apply()` never overwrites
the human-authored sections of a thesis note (Thesis Statement, Bull/Base/
Bear Case, Invalidation Conditions) -- it only appends a dated entry to
"Historical Changes" and updates the tracked `current_assessment` field.
Claude never changes a thesis silently.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from brain.market.context_assembler import ContextAssembler
from brain.thesis.schemas import THESIS_REVIEW_SCHEMA, ThesisReview
from config.logging import get_logger
from data.storage.learning_repository import record_thesis_review
from integrations.claude.llm_provider import LLMProvider
from integrations.obsidian.knowledge_store import KnowledgeStore
from models.asset import Asset
from models.thesis import Thesis

logger = get_logger("thesis_agent")

# Must match the heading in vault/_templates/Investment Thesis.md.
HISTORY_SECTION = "Historical Changes"

_DISCLAIMER = (
    "AI-generated thesis review. Not a guaranteed prediction (Rule 12) -- "
    "confidence reflects Claude's stated uncertainty, not a statistical guarantee."
)


class ThesisAgent:
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

    def review(self, thesis: Thesis, asset: Asset) -> ThesisReview:
        bundle = self._context_assembler.build(asset.ticker, include_thesis=True)
        prompt_context = bundle.to_prompt_context()

        extracted = self._llm_provider.extract(
            prompt_context, schema=THESIS_REVIEW_SCHEMA, max_tokens=2048
        )

        return ThesisReview(
            thesis_id=thesis.id,
            ticker=asset.ticker,
            previous_assessment=thesis.current_assessment,
            reviewed_at=dt.datetime.now(dt.UTC),
            **extracted,
        )

    def apply(self, thesis: Thesis, review: ThesisReview) -> None:
        if thesis.obsidian_note_path:
            entry = self._render_change_entry(review)
            # Target the heading explicitly. A plain append would land at the
            # end of the file, which is only correct while "Historical
            # Changes" happens to be the last section -- too fragile for an
            # audit trail (Rule 9).
            targeted = self._knowledge_store.append_to_section(
                thesis.obsidian_note_path, HISTORY_SECTION, entry
            )
            if not targeted:
                logger.warning(
                    "thesis_history_section_missing",
                    operation="apply",
                    status="fallback",
                    path=thesis.obsidian_note_path,
                    section=HISTORY_SECTION,
                )

        # Record the transition in queryable form as well as in the note.
        # The note is the narrative audit trail (Rule 9); this row is what
        # makes thesis accuracy and time-to-invalidation measurable.
        record_thesis_review(
            self._session,
            thesis_id=thesis.id,
            asset_id=thesis.asset_id,
            previous_assessment=review.previous_assessment,
            assessment=review.assessment.value,
            reviewed_at=review.reviewed_at,
            confidence=review.confidence,
            reasoning=review.reasoning,
        )

        thesis.current_assessment = review.assessment.value
        thesis.last_reviewed_at = review.reviewed_at
        self._session.add(thesis)
        self._session.flush()

    def review_and_apply(self, thesis: Thesis, asset: Asset) -> ThesisReview:
        review = self.review(thesis, asset)
        self.apply(thesis, review)
        return review

    def _render_change_entry(self, review: ThesisReview) -> str:
        date_str = review.reviewed_at.date().isoformat()
        lines = [
            "",
            f"### {date_str} — {review.previous_assessment} -> {review.assessment.value}",
            "",
            _DISCLAIMER,
            "",
            f"**Reasoning:** {review.reasoning}",
            "",
            "**Supporting evidence:**",
            *(f"- {e}" for e in review.supporting_evidence),
            "",
            "**Contradicting evidence:**",
            *(f"- {e}" for e in review.contradicting_evidence),
            "",
            "**Changed assumptions:**",
            *(f"- {a}" for a in review.changed_assumptions),
            "",
            "**Invalidation conditions triggered:**",
            *(f"- {c}" for c in review.invalidation_conditions_triggered),
            "",
            f"**Confidence:** {review.confidence}",
            "",
        ]
        return "\n".join(lines)
