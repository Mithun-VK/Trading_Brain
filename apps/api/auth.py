"""API authentication.

Honest position on what this is and isn't:

- It is **shared-token** auth (`Authorization: Bearer <token>`), suitable
  for a single-operator local/private deployment. It is not user accounts,
  not per-user authorization, and not a permission model.
- It is **opt-in**: with `API_AUTH_TOKENS` empty the API is open, which is
  the right default for `localhost` development. But an unauthenticated API
  in production is a real exposure, so `observability.checks` reports that
  combination as a health finding rather than letting it pass silently.

Exempt paths are only those needed to diagnose an unreachable system:
liveness and the OpenAPI docs.
"""

from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import JSONResponse

from config.logging import get_logger
from config.settings import Settings

logger = get_logger("api")

# Reachable without a token: liveness and schema. Everything else -- including
# every read endpoint -- requires one when tokens are configured.
EXEMPT_PATHS = frozenset(
    {"/health/live", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
)


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value:
        return value.strip()
    return request.headers.get("X-API-Key") or None


def is_authorized(request: Request, settings: Settings) -> bool:
    tokens = settings.auth_tokens
    if not tokens:
        return True  # auth disabled; see module docstring

    presented = _extract_token(request)
    if not presented:
        return False
    # compare_digest against every configured token: constant-time, and it
    # does not leak which token matched via timing.
    return any(hmac.compare_digest(presented, token) for token in tokens)


def unauthorized_response() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "detail": (
                "Missing or invalid API token. Send 'Authorization: Bearer "
                "<token>' with a value from API_AUTH_TOKENS."
            )
        },
        headers={"WWW-Authenticate": "Bearer"},
    )
