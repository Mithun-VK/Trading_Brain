from __future__ import annotations

from fastapi.testclient import TestClient


def test_liveness_reports_the_process_is_up(client: TestClient) -> None:
    """Liveness says the process answers -- and nothing more than that."""
    response = client.get("/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "app_env" in body


def test_health_reports_a_database_outage_instead_of_500(client: TestClient) -> None:
    """This client has no database configured for it.

    A running process is not a healthy system: /health must report the
    outage in health shape (503 + unavailable), not crash with a 500, since
    reporting exactly this situation is the endpoint's job.
    """
    response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"][0]["name"] == "database"


def test_health_response_has_request_id_header(client: TestClient) -> None:
    response = client.get("/health/live")

    assert "X-Request-ID" in response.headers
