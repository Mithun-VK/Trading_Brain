"""Shared-token API authentication.

The point of these tests is that the setting actually does something. Before
this, `API_AUTH_TOKENS` existed in `Settings` and was read by nothing --
which is worse than having no auth at all, because it reads like a control
that is in force.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from config.settings import Settings
from observability.checks import Status, check_api_auth

TOKEN = "test-token-value-0123456789"


@pytest.fixture
def authed_client() -> TestClient:
    """Settings are injected rather than set through the environment: mutating
    the process-wide settings cache leaks into every later test."""
    settings = Settings(API_AUTH_TOKENS=f"{TOKEN},second-token")
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_requests_without_a_token_are_rejected(authed_client: TestClient) -> None:
    response = authed_client.get("/health/data")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_configured_token_is_accepted(authed_client: TestClient) -> None:
    response = authed_client.get(
        "/health/data", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code != 401


def test_any_configured_token_is_accepted(authed_client: TestClient) -> None:
    response = authed_client.get(
        "/health/data", headers={"Authorization": "Bearer second-token"}
    )

    assert response.status_code != 401


def test_a_wrong_token_is_rejected(authed_client: TestClient) -> None:
    response = authed_client.get(
        "/health/data", headers={"Authorization": "Bearer not-the-token"}
    )

    assert response.status_code == 401


def test_a_token_prefix_is_not_enough(authed_client: TestClient) -> None:
    """Guards against a substring/startswith comparison creeping in."""
    response = authed_client.get(
        "/health/data", headers={"Authorization": f"Bearer {TOKEN[:10]}"}
    )

    assert response.status_code == 401


def test_liveness_stays_reachable_without_a_token(authed_client: TestClient) -> None:
    """You must be able to tell a down process from a rejected one."""
    assert authed_client.get("/health/live").status_code == 200


def test_expensive_endpoints_are_covered(authed_client: TestClient) -> None:
    """Auth runs before anything spends Claude credits or writes a position."""
    for method, path, body in (
        ("post", "/research/queue/1/process", {}),
        ("post", "/paper-trades/open", {"ticker": "X", "quantity": 1, "confirm": True}),
        ("post", "/backtests/run", {}),
    ):
        response = getattr(authed_client, method)(path, json=body)
        assert response.status_code == 401, path


def test_execution_endpoints_stay_unavailable_under_auth(
    authed_client: TestClient,
) -> None:
    """Rule 8 does not depend on the auth layer -- but must not be weakened
    by it either. Blocked either way; never reachable."""
    for path in ("/orders", "/execute", "/buy", "/sell"):
        assert authed_client.post(path, json={}).status_code in (401, 403)


def test_no_tokens_configured_leaves_the_api_open(client: TestClient) -> None:
    """The documented development default -- asserted so that it is a
    deliberate choice rather than an accident."""
    assert client.get("/health/live").status_code == 200


# -- the health finding -------------------------------------------------------


def test_unauthenticated_production_is_unavailable() -> None:
    check = check_api_auth(Settings(APP_ENV="production", API_AUTH_TOKENS=""))

    assert check.status is Status.UNAVAILABLE
    assert "publicly callable" in check.detail


def test_unauthenticated_development_is_degraded_not_broken() -> None:
    check = check_api_auth(Settings(APP_ENV="development", API_AUTH_TOKENS=""))

    assert check.status is Status.DEGRADED


def test_configured_tokens_are_healthy() -> None:
    check = check_api_auth(Settings(APP_ENV="production", API_AUTH_TOKENS="a,b"))

    assert check.status is Status.HEALTHY
    assert "2 API token(s)" in check.detail
