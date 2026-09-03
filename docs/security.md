# Security Posture

This document records the security controls that **actually exist** in
TradingBrain, and — equally deliberately — the ones that **do not**. Nothing
here is aspirational. If a control is listed as present, there is code and a
test behind it; if a control is absent, it is named in
[Known gaps](#known-gaps) rather than implied by omission.

Threat model, stated up front so the rest can be judged against it:
TradingBrain is a **single-operator system** intended to run on `localhost`
or a private network. It is not multi-tenant, has no user accounts, and
holds no customer data. Its assets worth protecting are (a) the API keys in
`.env`, (b) the vault contents, and (c) the ability to spend money by
triggering Claude API calls.

---

## 1. No live trade execution

The strongest security property in this system is a capability that was
never built. There is no broker SDK, no broker credentials, no order
placement path, and no code that can move real money.

| Control | Where | Enforced by |
|---|---|---|
| No broker dependency | `pyproject.toml` | No broker SDK is declared or vendored |
| No execution routers registered | `apps/api/main.py` | The router list is explicit and closed |
| Path guard | `apps/api/main.py:43` | `_BLOCKED_PATH_PREFIXES = ("/orders", "/execute", "/buy", "/sell")` → 403 |
| No execution signal categories | `brain/signals/` | `FORBIDDEN_CATEGORIES` rejected in `__post_init__` |
| Paper trades need explicit confirmation | `apps/api/routers/paper_trades.py` | `confirm=true` required to open **and** to close |

The path guard is **defense in depth, not the primary control**. The primary
control is that no such route exists to be reached. The guard exists so that
adding one by accident fails loudly.

## 2. Secret handling

**Secrets are never committed.** `.gitignore` covers `.env`, `.env.*`,
`.venv/`, `node_modules/`, `.obsidian/`, and `vault/.obsidian/`. Only
`.env.example` — which contains empty placeholders — is tracked.

**Secrets are redacted from logs.** `config/logging.py` defines:

```python
_SENSITIVE_KEYS = {"api_key", "token", "password", "secret", "authorization"}
```

`_redact_sensitive` is wired into the structlog processor chain, so any
event field with one of those keys is replaced before the record is
rendered. Verified additionally by grep: no log call site passes a raw key.

**Secrets are read from the environment only.** `config/settings.py` is the
single source; no key is hard-coded anywhere in the tree. A repository-wide
search for `(api[_-]?key|secret|password|token)\s*[:=]\s*['"][A-Za-z0-9_\-]{12,}`
across tracked `.py`, `.ts`, `.tsx`, `.json`, `.yml`, and `.yaml` files
returns nothing.

> **Historical incident.** An earlier commit accidentally tracked
> `vault/.obsidian/plugins/obsidian-local-rest-api/data.json`, which
> contained a live Obsidian API key, and it was pushed to a public
> repository. The file was untracked and the paths were gitignored, but
> **removal from HEAD does not retract what was published**: that key must
> be treated as compromised and regenerated in Obsidian → Settings → Local
> REST API. This is recorded here rather than quietly fixed, because a
> leaked-secret incident that leaves no trace teaches nothing.

## 3. API authentication

Shared-token bearer auth, implemented in `apps/api/auth.py` and enforced by
the `require_api_token` middleware in `apps/api/main.py`.

- Tokens come from `API_AUTH_TOKENS` (comma-separated).
- Accepted as `Authorization: Bearer <token>` or `X-API-Key: <token>`.
- Comparison uses `hmac.compare_digest` against each configured token, so a
  wrong token cannot be recovered by timing, and a valid **prefix** is not
  accepted.
- Runs **before** any route touches the database or spends Claude credits.
- Exempt paths are only `/health/live`, `/docs`, `/redoc`, and
  `/openapi.json` — enough to tell a down process from a rejected request.

**This auth is opt-in, and that is a real caveat.** With `API_AUTH_TOKENS`
empty the API is fully open. That is the correct default for `localhost`
development and the wrong one anywhere else, so the gap is surfaced rather
than left silent: `observability/checks.py::check_api_auth` reports

- `HEALTHY` — tokens configured;
- `DEGRADED` — no tokens, `APP_ENV != production`;
- `UNAVAILABLE` — no tokens **and** `APP_ENV == production`, which drives
  `/health` to a 503.

What this is **not**: it is not user accounts, not per-user authorization,
not role- or scope-based permissions, and not credential rotation. Every
holder of any token has full access to every endpoint.

## 4. Input validation

All request bodies and query parameters are Pydantic v2 models
(`apps/api/schemas_v2.py`, `apps/api/schemas.py`), so type coercion, required
fields, and range constraints are enforced at the transport boundary and
produce a 422 rather than reaching domain code. Beyond types, routers apply
semantic validation — for example `apps/api/routers/backtests.py` rejects an
end date before the start date, unknown tickers, unknown strategies,
inverted moving-average windows, and ranges beyond `MAX_RANGE_DAYS = 3650`.

All database access goes through SQLAlchemy ORM constructs; there is no
string-interpolated SQL in the tree.

## 5. Failure and outage behaviour

- A database outage returns **503 in health shape**, not a 500 stack trace
  (`SQLAlchemyError` handler, `apps/api/main.py`).
- Health checks never raise; each catches broadly and reports
  `UNAVAILABLE` with the exception **type name only** — not its message,
  which could carry a connection string.
- The Obsidian health probe is single-shot with a 2 s timeout, so a
  health poll cannot be used to amplify load.

## 6. AI-specific security

The reasoning layer adds a category of risk the rest of the system does not
have: text that arrives from outside and is then read by something that
follows instructions.

**External content is data, never instructions.** Research documents, news,
and filings enter prompts fenced as `UNTRUSTED DATA`, and every system
prompt in `ai/adapter.py` states that instructions found inside such content
must never be complied with. Tested in `tests/ai/test_gateway.py`.

**Prompts are never persisted.** The `ai_requests` audit row stores a
`prompt_fingerprint` and a character count, never the text -- a table of
prompts is a table of whatever happened to be in them. The principal is a
truncated SHA-256 of the bearer token, never the token: enough to tell two
callers apart, useless if leaked.

**No provider bypass.** No application module may import `anthropic` or
construct a provider client; only the provider layer may. Asserted by
parsing the source tree in `tests/ai/test_no_provider_bypass.py`, with a
guard that the scan actually sees the files -- a bypass would defeat rate
limiting, budgets, and the audit trail in a single step.

**Bounded inputs and outputs.** Empty prompts, oversized prompts, unbounded
`max_output_tokens`, and retry counts above a ceiling are all rejected at
request construction, before a provider is reached.

**Cost is an attack surface.** An unauthenticated caller looping a research
endpoint is a denial-of-wallet attack. Rate limits apply before any
expensive work, budgets block past a ceiling, and both are tested against a
200-request loop that must not reach the provider more than five times.

**AI cannot execute.** No `ai/` module imports `paper_trading`, the
portfolio or trade repositories, or any broker SDK, and every `/ai` route is
GET-only (`tests/ai/test_ai_cannot_execute.py`).

## 7. Known gaps

Listed plainly, because an undocumented gap is worse than a documented one.

| Gap | Impact | Mitigating factor |
|---|---|---|
| **Rate limiting covers AI routes only** | AI-spending routes are limited per principal and bounded by budgets. Ordinary read endpoints are still unlimited | The unbounded routes are cheap; the expensive ones are the ones now guarded |
| **No CORS policy configured** | FastAPI's default is to send no CORS headers, so browsers block cross-origin calls — safe by default, but not an explicit decision | Dashboard is same-origin or proxied |
| **No HTTPS termination in-app** | Traffic is plaintext unless fronted by a reverse proxy | Intended for loopback/private network |
| **Auth is a single shared secret** | No per-user attribution, no revocation short of rotating the token for everyone | Single operator |
| **No audit log of who called what** | Requests are logged with a request ID, but not an identity | No identity exists to log |
| **Obsidian TLS verification off by default** | `OBSIDIAN_VERIFY_TLS=false` accepts the plugin's self-signed loopback certificate | `OBSIDIAN_CA_CERT_PATH` supports pinning the plugin's own CA and takes precedence |
| **No dependency vulnerability scanning in CI** | Known-vulnerable transitive dependencies would not be flagged | Dependencies are pinned in `pyproject.toml` |

## 8. Deployment checklist

Before running anywhere other than `localhost`:

1. Set `API_AUTH_TOKENS` to a long random value
   (`python -c "import secrets; print(secrets.token_urlsafe(32))"`).
2. Set `APP_ENV=production`, then confirm `/health` is not `unavailable` —
   it will flag both missing auth and a synthetic market-data provider.
3. Change `POSTGRES_PASSWORD` from `change-me`.
4. Terminate TLS at a reverse proxy; do not expose the app port directly.
5. Regenerate the Obsidian API key if the historical leak above has not
   already been remediated.
6. Confirm `git status --porcelain` shows no `.env` and no `.obsidian/`.
