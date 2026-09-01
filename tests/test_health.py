from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "app_env" in body


def test_health_response_has_request_id_header(client: TestClient) -> None:
    response = client.get("/health")

    assert "X-Request-ID" in response.headers
