from __future__ import annotations

import httpx
import pytest

from config.settings import Settings
from integrations.obsidian.errors import (
    ObsidianAPIError,
    ObsidianAuthError,
    ObsidianConnectionError,
    ObsidianNotFoundError,
)
from integrations.obsidian.obsidian_knowledge_store import ObsidianKnowledgeStore


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
