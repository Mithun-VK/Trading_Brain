# Claude Integration

Claude is the **reasoning layer** — it analyzes evidence a deterministic
quantitative engine and Obsidian/PostgreSQL have already assembled. It is
never a source of truth (Rule 1), never performs a calculation a
deterministic function could (Rule 2), and never executes a trade (Rule 7).

## Abstraction

`integrations/claude/llm_provider.py` defines `LLMProvider`
(`analyze`, `summarize`, `extract`). Agents (research/thesis/review) depend
only on this interface. `integrations/claude/claude_provider.py` implements
it via the official `anthropic` Python SDK.

- `analyze(prompt, context="")` — free-form reasoning, returns text. Every
  call carries a system prompt instructing Claude to state confidence/
  uncertainty and never present output as guaranteed advice (Rules 11-12).
- `summarize(text)` — condensation, instructed not to add information not
  present in the source.
- `extract(text, schema)` — structured extraction via forced tool-use, so
  the result is a dict conforming to the given JSON Schema rather than
  Claude's own free-text formatting choices.

## Configuration

```env
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=
```

The model name is always read from `config.settings.get_settings().anthropic_model`
— never hard-coded in a prompt-building or agent module.

## Error handling

`integrations/claude/errors.py` mirrors the Obsidian integration's
structure: `ClaudeAuthError` (bad/missing key, not retried),
`ClaudeConnectionError` (network failure or rate limit — retried 3x with
exponential backoff via `tenacity`), `ClaudeAPIError` (other 4xx/5xx,
carries `status_code`).

## Testing

`tests/integrations/test_claude_provider.py` — unit tests against a mocked
`anthropic.Anthropic` client (injected via `ClaudeProvider(settings, client=...)`),
no live API key or network call required. Covers `analyze`/`summarize`/
`extract`, the configured-model plumbing, and every error-mapping path.
