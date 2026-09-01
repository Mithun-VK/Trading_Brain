# Context Pipeline and Research Agent

## Context Assembler (`brain/market/context_assembler.py`)

`ContextAssembler.build(ticker, include_company=True, include_sector=True,
include_macro=False, include_thesis=True, include_recent_trades=True)`
returns a `ContextBundle` combining:

- targeted Obsidian search results (company/sector/macro notes — top 5
  matches each, never a full-vault dump)
- the active thesis summary + note excerpt (if any)
- recent trades for the ticker (from PostgreSQL)
- a deterministic quant summary (last close, SMA-50/200, RSI-14, 20-day
  annualized volatility — computed by `quant/indicators`, never by Claude)
- the latest market regime observation

`ContextBundle.to_prompt_context()` renders this into a compact text block.
Note bodies are never dumped in full — search results carry only their
match context, and even the thesis note excerpt is capped at 2000 chars.

Missing data degrades gracefully: an unknown ticker, a missing thesis, or an
unreachable Obsidian instance (`ObsidianError` is caught) all just produce
an emptier bundle rather than an exception — the quant summary and regime
lookup, which don't depend on the vault, still populate.

## Research Agent (`brain/research/research_agent.py`)

1. Build context via `ContextAssembler`.
2. If the asset has a prior `ResearchDocument`, append its summary to the
   context so Claude can reason about what's changed.
3. Call `LLMProvider.extract()` with `RESEARCH_ANALYSIS_SCHEMA` — forced
   tool-use, so the result is a `ResearchAnalysis` (summary, positive/
   negative factors, contradictions, risks, catalysts, confidence 0-1),
   not free text Claude chose to format itself.
4. `render_markdown()` renders the structured analysis to Obsidian
   Markdown, including a standing disclaimer (Rule 12) — Markdown is a
   rendering of the structured result, never a separate generation.
5. `publish()` writes the note (`08 Research/<ticker>-<date>.md` by
   default) and records a `ResearchDocument` row pointing at it.

## Testing

`tests/brain/market/test_context_assembler.py` and
`tests/brain/research/test_research_agent.py` use `tests/fakes.py`
(`FakeKnowledgeStore`, `FakeLLMProvider`) plus the real deterministic
`MockProvider` — no live Obsidian, Claude API key, or PostgreSQL required.
