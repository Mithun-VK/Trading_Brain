# Obsidian Integration

Obsidian is the **knowledge layer** — see [vault/README.md](../vault/README.md)
for the vault structure, templates, and setup steps. This document covers
the integration architecture.

## Abstraction

`integrations/obsidian/knowledge_store.py` defines `KnowledgeStore`, an
abstract interface (`search`, `read`, `write`, `update`, `append`,
`list_notes`, `backlinks`). Business logic (research/thesis/review agents)
depends only on this interface, never on the Obsidian plugin directly — a
future backend could implement the same interface without touching callers.

`integrations/obsidian/obsidian_knowledge_store.py` implements it via the
**Local REST API** community plugin
(coddingtonbear/obsidian-local-rest-api), which exposes an HTTPS API on a
loopback port with a self-signed certificate.

## Error handling

`integrations/obsidian/errors.py` defines a structured hierarchy
(`ObsidianConnectionError`, `ObsidianAuthError`, `ObsidianNotFoundError`,
`ObsidianAPIError`) so callers never need to know the integration is
HTTP-based underneath. Only connection/timeout failures are retried
(3 attempts, exponential backoff via `tenacity`) — 4xx responses fail fast.

## `backlinks`

The Local REST API has no dedicated backlinks endpoint. `backlinks()`
approximates it by searching for `[[note-name` wikilink syntax across the
vault. This can miss aliased or piped links (`[[note-name|Alias]]` still
matches; a link that uses only an alias without the real note name would
not) — treat it as best-effort, not authoritative, until/unless a future
phase adds a proper graph index.

## Security

The API key is never logged — `config/logging.py`'s structlog processor
redacts any field named `api_key`/`token`/`password`/`secret`/
`authorization` before a log line is emitted. Requests carry it only as an
`Authorization: Bearer` header.

## Testing

- `tests/integrations/test_obsidian_knowledge_store.py` — unit tests against
  `httpx.MockTransport`, no live Obsidian instance required.
- `scripts/test_obsidian.py` (`python -m scripts.test_obsidian`) — CLI smoke
  test against a real running Obsidian + Local REST API plugin, using a
  single dedicated test note (`99 Archive/_tradingbrain_connection_test.md`)
  so it never touches real vault content.
