from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from config.settings import Settings
from integrations.claude.claude_provider import ClaudeProvider
from integrations.claude.errors import ClaudeAPIError, ClaudeAuthError, ClaudeConnectionError


def _settings() -> Settings:
    return Settings(ANTHROPIC_API_KEY="test-key", ANTHROPIC_MODEL="claude-test-model")


def _fake_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status_code=status_code, request=request)


def _provider(create_side_effect: object) -> ClaudeProvider:
    client = MagicMock(spec=anthropic.Anthropic)
    client.messages.create = MagicMock(side_effect=create_side_effect)
    return ClaudeProvider(_settings(), client=client)


def test_requires_api_key() -> None:
    settings = Settings(ANTHROPIC_API_KEY="", ANTHROPIC_MODEL="claude-test-model")

    with pytest.raises(ClaudeAuthError):
        ClaudeProvider(settings)


def test_analyze_returns_text() -> None:
    message = SimpleNamespace(content=[SimpleNamespace(type="text", text="the answer")])
    provider = _provider(create_side_effect=lambda **_: message)

    result = provider.analyze("what happened?", context="some evidence")

    assert result == "the answer"


def test_analyze_uses_configured_model() -> None:
    captured = {}

    def fake_create(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")])

    provider = _provider(create_side_effect=fake_create)
    provider.analyze("prompt")

    assert captured["model"] == "claude-test-model"


def test_summarize_returns_text() -> None:
    message = SimpleNamespace(content=[SimpleNamespace(type="text", text="short version")])
    provider = _provider(create_side_effect=lambda **_: message)

    assert provider.summarize("a very long text") == "short version"


def test_extract_returns_tool_input() -> None:
    message = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input={"ticker": "RELIANCE", "score": 0.8})]
    )
    provider = _provider(create_side_effect=lambda **_: message)

    result = provider.extract("some text", schema={"type": "object"})

    assert result == {"ticker": "RELIANCE", "score": 0.8}


def test_extract_raises_when_no_tool_use_block() -> None:
    message = SimpleNamespace(content=[SimpleNamespace(type="text", text="oops, plain text")])
    provider = _provider(create_side_effect=lambda **_: message)

    with pytest.raises(ClaudeAPIError):
        provider.extract("some text", schema={"type": "object"})


def test_authentication_error_maps_to_claude_auth_error() -> None:
    response = _fake_response(status_code=401)
    error = anthropic.AuthenticationError("bad key", response=response, body=None)
    provider = _provider(create_side_effect=error)

    with pytest.raises(ClaudeAuthError):
        provider.analyze("prompt")


def test_connection_error_maps_and_retries() -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.APIConnectionError(message="refused", request=request)
    provider = _provider(create_side_effect=error)

    with pytest.raises(ClaudeConnectionError):
        provider.analyze("prompt")

    assert provider._client.messages.create.call_count == 3


def test_status_error_maps_to_claude_api_error() -> None:
    response = _fake_response(status_code=500)
    error = anthropic.InternalServerError("boom", response=response, body=None)
    provider = _provider(create_side_effect=error)

    with pytest.raises(ClaudeAPIError) as exc_info:
        provider.analyze("prompt")

    assert exc_info.value.status_code == 500
