# Thesis Engine

`brain/thesis/thesis_agent.py`. Compares current evidence (via
`ContextAssembler`, same as the Research Agent) against an existing
`Thesis` row and produces an explicit `ThesisReview`.

## Assessment states

`brain/thesis/schemas.py::ThesisAssessment` — mirrors
`models.Thesis.current_assessment`:

- `THESIS_INTACT`
- `THESIS_STRENGTHENED`
- `THESIS_WEAKENED`
- `THESIS_INVALIDATED`
- `INSUFFICIENT_EVIDENCE`

Every review also states, explicitly and separately: supporting evidence,
contradicting evidence, changed assumptions, and which invalidation
conditions (if any) were triggered — via forced tool-use extraction
(`THESIS_REVIEW_SCHEMA`), the same pattern as the Research Agent.

## Rule 9: auditability

`ThesisAgent.apply()` **never overwrites** the human-authored sections of a
thesis note (Thesis Statement, Bull/Base/Bear Case, Invalidation
Conditions). It only:

1. Appends a dated entry to the note's `## Historical Changes` section
   (`KnowledgeStore.append`, not `write`/`update`) — prior entries are
   preserved.
2. Updates the tracked `current_assessment` and `last_reviewed_at` columns
   on the `theses` row.

Claude cannot silently change a thesis: the only path from "Claude produced
a review" to "the thesis record changed" is `ThesisAgent.apply()`, which
always writes the audit entry first.

`review()` and `apply()` are separate calls (plus a `review_and_apply()`
convenience) so a caller — e.g. a future API endpoint or a human running
`scripts/` — can inspect a review before deciding whether to apply it.

## Testing

`tests/brain/thesis/test_thesis_agent.py` asserts the audit entry is
appended (not a replacement), that pre-existing note content survives, and
that a thesis with no Obsidian note yet still updates its DB-tracked
assessment without erroring.
