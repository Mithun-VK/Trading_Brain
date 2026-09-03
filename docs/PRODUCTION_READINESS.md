# Production Readiness

An assessment of what TradingBrain is fit for, and what it is not. It is
written to be useful rather than reassuring: the RED and YELLOW rows are the
point of the document, and a category is only GREEN when there is code and a
test behind the claim.

**Verified at:** commit `9f0e2d1` (Phases 38-45)
**Verification:** 696 tests passing · mypy clean (164 source files) · ruff
clean · tsc clean · eslint clean · `next build` clean (18 routes) · 10
migrations apply from an empty Postgres with zero schema drift against the
models, and survive a full downgrade-to-base and re-upgrade round trip.

**Docker:** both images build. The API image starts and serves —
`GET /health/live` answers 200 from the container; the three packages that were previously
missing (`backtesting`, `observability`, `paper_trading`) all import;
`alembic.ini` and `alembic/` are present so migrations can be run from the
image; the execution guard returns 403 for `POST /orders`; and the process
runs as uid 10001, not root. The worker image imports its entrypoint and
registers all 8 scheduled jobs, also as uid 10001.

One environment note for reproducing this: builds must run with
`DOCKER_BUILDKIT=0`, because `docker buildx` fails here with "The parameter
is incorrect". The legacy builder also emits a warning about
`docker-credential-gcloud` being absent from `PATH` (a `credHelpers` entry
in `~/.docker/config.json` points at a GCP registry unrelated to this
project); the warning is noisy but does not block the build.

---

## Scope: what this system is

A **single-operator research and reasoning platform**. It forms investment
views, records why it holds them, and checks itself against what actually
happened.

It is **not** an autonomous trading system, and this is a structural fact
rather than a policy: no broker SDK is imported anywhere in the tree, no
route resembling order placement is registered, and no signal category names
an executable action. Both properties are asserted by tests over the real
source tree, not by convention.

---

## Readiness by category

| # | Category | Rating | Basis |
|---|---|---|---|
| 1 | Broker-execution safety | **GREEN** | No SDK, no route, no category. Enforced by `tests/test_system_invariants.py` over the parsed source tree and every HTTP method |
| 2 | Data integrity / no fabrication | **GREEN** | Unknowns are `null` not `0.0` end to end; unpriced positions excluded, not valued at cost; synthetic providers cannot be fallbacks |
| 3 | Auditability & lineage | **GREEN** | Every signal carries evidence or is not served; `/lineage/*` marks gaps `recorded: false` rather than inventing provenance |
| 4 | Deterministic financial math | **GREEN** | All quant in Python; Claude never computes a number that reaches a report |
| 5 | Test coverage | **GREEN** | 696 tests, no live external calls in CI, deterministic fakes throughout |
| 6 | Type & lint hygiene | **GREEN** | mypy and ruff clean over 161 source files; `[tool.mypy]` lists its own files so a bare `mypy` matches the CI gate |
| 7 | Database & migrations | **GREEN** | 10 migrations apply cleanly from empty; 25 tables, no drift versus the models; full down/up round trip verified |
| 7b | Container images | **GREEN** | A real defect was found and fixed (3 packages never copied, so the API image could not have started). Both images build; API serves `/health/live`, worker registers its 8 jobs, both run non-root; a test derives the expected package list from `pyproject.toml` |
| 8 | Observability | **GREEN** | Three-state health with worst-wins aggregation; a DB outage is a 503 in health shape, never a 500 |
| 9 | Frontend | **GREEN** | Builds clean; every data area handles error/empty/success distinctly; four visually distinct kinds of "unknown" |
| 10 | Configuration safety | **YELLOW** | `production_issues()` + `scripts/preflight.py` name every unsafe default, but nothing *enforces* them — a misconfigured production instance logs loudly and still starts |
| 11 | Authentication | **YELLOW** | Real shared-token auth with constant-time comparison, but opt-in and single-secret: no user accounts, no per-user attribution, no revocation short of rotating for everyone |
| 12 | Resilience | **YELLOW** | Timeouts, capped retries, exponential backoff, transient-vs-permanent classification, DB-backed restart safety, idempotent jobs — but no circuit breaker and no request idempotency keys |
| 13 | Rate limiting | **YELLOW** | AI-spending routes are limited per principal and bounded by budgets, tested against a 200-request loop. Ordinary read endpoints remain unlimited |
| 13b | AI cost governance | **GREEN** | Gateway enforces rate limits, dedup/cache, per-request and per-hour/day/month budgets, and bounded retries. Unpriced models report unknown cost, never zero |
| 13c | AI architecture | **GREEN** | Every call passes the gateway; no provider bypass, asserted by parsing the tree. Deterministic core runs with all providers disabled |
| 14 | Multi-user operation | **RED** | Not designed for it. One shared secret, one portfolio namespace, no tenancy, no per-user audit |
| 15 | Transport security | **RED** | No TLS termination in-app; plaintext unless fronted by a reverse proxy. Obsidian TLS verification is off by default |
| 16 | Dependency scanning | **RED** | No vulnerability scanning in CI |

---

## Overall: **YELLOW — ready for its intended use, not for general deployment**

Fit for a single operator running it on `localhost` or a private network,
with `API_AUTH_TOKENS` set and `python -m scripts.preflight` passing.

Not fit for exposure to an untrusted network, for multiple users, or for
unattended operation, because of rows 13–16.

The distinction that matters: none of the RED items is a *defect* in what
was built. They are capabilities that were never in scope. What would be a
defect — and what this assessment is designed to catch — is a RED item that
looks GREEN from the outside. Row 11 was exactly that before Phase 32:
`API_AUTH_TOKENS` existed in settings, was read by nothing, and so read like
a control that was in force.

---

## Before deploying anywhere but localhost

1. `python -c "import secrets; print(secrets.token_urlsafe(32))"` →
   `API_AUTH_TOKENS`, and the same value into the dashboard's
   `TRADINGBRAIN_API_TOKEN`.
2. `APP_ENV=production`, then `python -m scripts.preflight` — it exits
   non-zero and names every issue.
3. Replace the `change-me` database password.
4. Set `MARKET_DATA_PROVIDER` to a real provider. A synthetic primary in
   production makes `/health` report DEGRADED, and every downstream number
   is generated.
5. Terminate TLS at a reverse proxy; do not expose the app port.
6. Regenerate the Obsidian API key — see the leak recorded in
   [security.md](security.md#2-secret-handling).
7. `GET /health` should be `healthy`, not merely reachable.

---

## What would change each RED to GREEN

| Row | Work required |
|---|---|
| 13 | A token-bucket limiter keyed by token, tightest on the Claude-spending routes |
| 14 | User accounts, per-user portfolio scoping, and identity in the audit log — a substantial redesign, not a feature |
| 15 | A reverse proxy with TLS, plus pinning the Obsidian CA (`OBSIDIAN_CA_CERT_PATH`) |
| 16 | `pip-audit` and `npm audit` in CI, failing the build on high severity |

## Related

- [security.md](security.md) — controls that exist, and the gaps
- [resilience.md](resilience.md) — failure behaviour, and the gaps
- [architecture.md](architecture.md) — how the pieces fit together
