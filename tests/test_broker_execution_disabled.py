"""Rule 8: no live broker integration in these phases.

These paths must never resolve to a real handler, even if a future change
accidentally registers one — the middleware guard blocks them outright.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("path", ["/orders", "/execute", "/buy", "/sell"])
def test_broker_execution_paths_are_blocked(client: TestClient, path: str) -> None:
    response = client.post(path)

    assert response.status_code == 403
