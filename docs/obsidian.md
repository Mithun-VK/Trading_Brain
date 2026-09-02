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

## Section-targeted writes

`append()` writes to the **end of a note**. That is wrong for audit trails:
it only lands in the right place while the target heading happens to be the
last section, so renaming or adding a section silently misfiles entries.

`append_to_section(path, section, content)` uses the plugin's `PATCH`
instruction to target a heading explicitly:

```json
{"targetType": "heading", "target": ["Historical Changes"],
 "operation": "append", "content": "..."}
```

It returns `True` when the heading was targeted and `False` when the
heading was missing and the content fell back to an end-of-note append — an
audit entry is never dropped, but the caller is told placement wasn't
guaranteed. The Thesis Agent uses this for `## Historical Changes` and logs
a warning on fallback (Rule 9).

## TLS

The plugin generates its own **name-constrained CA** (it can only vouch for
localhost) and serves a certificate signed by it. Options, best first:

```env
# Best: trust the plugin's CA. Download it from
# https://127.0.0.1:27124/obsidian-local-rest-api.crt
OBSIDIAN_CA_CERT_PATH=C:\path\to\obsidian-local-rest-api.crt

# Or enable standard verification (needs the CA in your OS trust store)
OBSIDIAN_VERIFY_TLS=true
```

Default is verification **off**, matching the plugin's out-of-the-box
loopback state. `OBSIDIAN_CA_CERT_PATH` takes precedence when set.

## Also available: the plugin's built-in MCP server

The plugin ships an MCP server at `https://127.0.0.1:27124/mcp/`, separate
from TradingBrain's programmatic integration. It lets an AI agent read and
write the vault directly:

```bash
claude mcp add --transport http obsidian https://127.0.0.1:27124/mcp/ \
  --header "Authorization: Bearer <your-api-key>"
```

TradingBrain does not depend on it — the agents use the REST API above so
they work headlessly. The two coexist fine.

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
