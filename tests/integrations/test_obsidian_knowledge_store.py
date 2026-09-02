from __future__ import annotations

import json

import httpx
import pytest

from config.settings import Settings
from integrations.obsidian.errors import (
    ObsidianAPIError,
    ObsidianAuthError,
    ObsidianConnectionError,
    ObsidianNotFoundError,
)
from integrations.obsidian.obsidian_knowledge_store import (
    ObsidianKnowledgeStore,
    _tls_verification,
)


def _settings() -> Settings:
    return Settings(OBSIDIAN_API_KEY="test-key", OBSIDIAN_BASE_URL="https://obsidian.local")


def _store(handler) -> ObsidianKnowledgeStore:
    return ObsidianKnowledgeStore(_settings(), transport=httpx.MockTransport(handler))


def test_requires_api_key() -> None:
    settings = Settings(OBSIDIAN_API_KEY="", OBSIDIAN_BASE_URL="https://obsidian.local")

    with pytest.raises(ObsidianAuthError):
        ObsidianKnowledgeStore(settings)


def test_read_returns_note_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/vault/Companies/RELIANCE.md"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, text="# RELIANCE\n")

    note = _store(handler).read("Companies/RELIANCE.md")

    assert note.content == "# RELIANCE\n"
    assert note.path == "Companies/RELIANCE.md"


def test_write_sends_put_with_content() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = request.content
        return httpx.Response(200)

    _store(handler).write("note.md", "hello")

    assert captured["method"] == "PUT"
    assert captured["body"] == b"hello"


def test_append_sends_post() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        return httpx.Response(200)

    _store(handler).append("note.md", "more")

    assert captured["method"] == "POST"


def test_search_parses_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "filename": "note.md",
                    "score": 1.5,
                    "matches": [{"context": "some context"}],
                }
            ],
        )

    results = _store(handler).search("query")

    assert len(results) == 1
    assert results[0].path == "note.md"
    assert results[0].context == "some context"


def test_list_notes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"files": ["a.md", "b.md", "sub/"]})

    notes = _store(handler).list_notes()

    assert notes == ["a.md", "b.md"]


def test_404_raises_not_found() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(ObsidianNotFoundError):
        _store(handler).read("missing.md")


def test_401_raises_auth_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with pytest.raises(ObsidianAuthError):
        _store(handler).read("note.md")


def test_500_raises_api_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(ObsidianAPIError):
        _store(handler).read("note.md")


def test_connect_error_raises_connection_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ObsidianConnectionError):
        _store(handler).read("note.md")


def test_append_to_section_targets_the_heading() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        return httpx.Response(200)

    targeted = _store(handler).append_to_section("t.md", "Historical Changes", "entry")

    assert targeted is True
    assert captured["method"] == "PATCH"
    assert captured["body"] == {
        "targetType": "heading",
        "target": ["Historical Changes"],
        "operation": "append",
        "content": "entry",
    }


def test_append_to_section_falls_back_when_heading_is_missing() -> None:
    """An audit entry must never be lost just because a heading was renamed."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "PATCH":
            return httpx.Response(404)
        return httpx.Response(200)

    targeted = _store(handler).append_to_section("t.md", "Missing", "entry")

    assert targeted is False
    assert calls == ["PATCH", "POST"]  # fell back to a plain append


def test_ca_cert_path_is_used_for_verification_when_configured() -> None:
    settings = Settings(
        OBSIDIAN_API_KEY="k",
        OBSIDIAN_BASE_URL="https://obsidian.local",
        OBSIDIAN_CA_CERT_PATH="/path/to/ca.crt",
    )

    assert _tls_verification(settings) == "/path/to/ca.crt"


def test_verification_defaults_to_disabled_for_the_self_signed_loopback_cert() -> None:
    settings = Settings(OBSIDIAN_API_KEY="k", OBSIDIAN_BASE_URL="https://obsidian.local")

    assert _tls_verification(settings) is False


def test_verification_can_be_enabled_without_a_custom_ca() -> None:
    settings = Settings(
        OBSIDIAN_API_KEY="k",
        OBSIDIAN_BASE_URL="https://obsidian.local",
        OBSIDIAN_VERIFY_TLS=True,
    )

    assert _tls_verification(settings) is True
