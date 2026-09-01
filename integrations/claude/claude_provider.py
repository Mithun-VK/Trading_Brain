"""LLMProvider implementation backed by the Anthropic API.

The model name is always read from configuration (`ANTHROPIC_MODEL`),
never hard-coded (see docs/claude.md).
"""

from __future__ import annotations

from typing import Any

import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.logging import get_logger
from config.settings import Settings
from integrations.claude.errors import ClaudeAPIError, ClaudeAuthError, ClaudeConnectionError
from integrations.claude.llm_provider import LLMProvider

logger = get_logger("claude")

_ANALYZE_SYSTEM_PROMPT = (
    "You are the reasoning layer of TradingBrain, a personal research assistant. "
    "You analyze evidence that a deterministic quantitative engine has already computed -- "
    "you never invent financial data or perform calculations yourself. "
    "Always state your confidence/uncertainty explicitly. "
    "Never present your analysis as guaranteed financial advice or a guaranteed prediction."
)

_SUMMARIZE_SYSTEM_PROMPT = (
    "Summarize the given text concisely and factually. Do not add information, "
    "opinions, or predictions that are not present in the source text."
)

_EXTRACT_SYSTEM_PROMPT = (
    "Extract structured data from the given text using the extract_data tool. "
    "Only populate fields you can support directly from the text; omit fields "
    "you cannot support rather than guessing."
)


class ClaudeProvider(LLMProvider):
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None) -> None:
        if not settings.anthropic_api_key:
            raise ClaudeAuthError("ANTHROPIC_API_KEY is not configured")
        self._client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    def analyze(self, prompt: str, context: str = "", *, max_tokens: int = 1024) -> str:
        user_message = f"Context:\n{context}\n\nTask:\n{prompt}" if context else prompt
        return self._complete(_ANALYZE_SYSTEM_PROMPT, user_message, max_tokens)

    def summarize(self, text: str, *, max_tokens: int = 512) -> str:
        return self._complete(_SUMMARIZE_SYSTEM_PROMPT, text, max_tokens)

    def extract(
        self, text: str, schema: dict[str, Any], *, max_tokens: int = 1024
    ) -> dict[str, Any]:
        tool = {
            "name": "extract_data",
            "description": "Record the extracted structured data.",
            "input_schema": schema,
        }
        response = self._request(
            max_tokens=max_tokens,
            system=_EXTRACT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "extract_data"},
        )
        for block in response.content:
            if block.type == "tool_use":
                return dict(block.input)
        raise ClaudeAPIError(200, "Claude did not return a tool_use block for extract()")

    def _complete(self, system: str, user_message: str, max_tokens: int) -> str:
        response = self._request(
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    @retry(
        retry=retry_if_exception_type(ClaudeConnectionError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        reraise=True,
    )
    def _request(self, **kwargs: Any) -> anthropic.types.Message:
        try:
            return self._client.messages.create(model=self._model, **kwargs)
        except anthropic.AuthenticationError as exc:
            raise ClaudeAuthError("Anthropic API rejected the configured API key") from exc
        except (anthropic.APIConnectionError, anthropic.RateLimitError) as exc:
            logger.warning("claude_transient_error", operation="messages.create", status="retry")
            raise ClaudeConnectionError(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            raise ClaudeAPIError(exc.status_code, str(exc)) from exc
