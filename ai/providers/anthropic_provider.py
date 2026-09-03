"""Anthropic provider.

This is the **only** place in the application that may construct an Anthropic
SDK client. `tests/ai/test_no_provider_bypass.py` asserts that by parsing the
source tree, so the rule is enforced rather than documented.

Note what this class does *not* do: no routing, no budget checks, no
cross-provider retry, no caching decisions. Those belong to the gateway, so
there is no layer at which a policy can be quietly skipped.
"""

from __future__ import annotations

import time
from typing import Any

import anthropic

from ai.provider import AIModel, AIProvider
from ai.schemas import (
    AIProviderAuthError,
    AIProviderUnavailable,
    AIRateLimited,
    AIRequest,
    AIResponse,
    AIResponseError,
    AITier,
    AIUsage,
    FinishReason,
)
from config.logging import get_logger
from config.settings import Settings

logger = get_logger("ai")

_FINISH_REASONS = {
    "end_turn": FinishReason.COMPLETE,
    "stop_sequence": FinishReason.COMPLETE,
    "tool_use": FinishReason.COMPLETE,
    "max_tokens": FinishReason.MAX_TOKENS,
    "refusal": FinishReason.REFUSAL,
}


class AnthropicAIProvider(AIProvider):
    name = "anthropic"
    is_local = False

    def __init__(
        self, settings: Settings, client: anthropic.Anthropic | None = None
    ) -> None:
        if not settings.anthropic_api_key:
            raise AIProviderAuthError("ANTHROPIC_API_KEY is not configured")
        self._client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._settings = settings

    def models(self) -> list[AIModel]:
        """Configured models only.

        A tier with no configured model is genuinely unavailable, and the
        router reports that rather than substituting a model from another
        tier -- silently answering a Tier 3 question with a Tier 2 model is
        the failure this design exists to prevent.
        """
        s = self._settings
        found: list[AIModel] = []

        standard = s.ai_frontier_model or s.anthropic_model
        if standard:
            found.append(
                AIModel(
                    name=standard,
                    provider=self.name,
                    tier=AITier.FRONTIER,
                    max_context_chars=600_000,
                    supports_tools=True,
                    supports_caching=True,
                )
            )
        if s.ai_frontier_high_model:
            found.append(
                AIModel(
                    name=s.ai_frontier_high_model,
                    provider=self.name,
                    tier=AITier.FRONTIER_HIGH,
                    max_context_chars=600_000,
                    supports_tools=True,
                    supports_caching=True,
                )
            )
        return found

    def health(self) -> tuple[bool, str]:
        """Configuration only. A health endpoint that bills per poll is a bad
        health endpoint -- the same rule the Claude health check already
        follows. Reachability surfaces through real request failures."""
        if not self._settings.anthropic_api_key:
            return False, "ANTHROPIC_API_KEY not set."
        models = [m.name for m in self.models()]
        return True, f"Configured ({', '.join(models)}). Not probed."

    def invoke(self, request: AIRequest, model: str) -> AIResponse:
        started = time.perf_counter()
        kwargs = self._build_kwargs(request)

        try:
            response = self._client.messages.create(model=model, **kwargs)
        except anthropic.AuthenticationError as exc:
            raise AIProviderAuthError("Anthropic rejected the configured API key") from exc
        except anthropic.RateLimitError as exc:
            # Its own class, not folded into "unavailable": a 429 means we
            # are asking too fast, and the gateway must back off rather than
            # immediately retry the request the provider just refused.
            raise AIRateLimited(str(exc), retry_after=_retry_after(exc)) from exc
        except anthropic.APIConnectionError as exc:
            raise AIProviderUnavailable(f"Anthropic unreachable: {type(exc).__name__}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise AIProviderUnavailable(f"Anthropic returned {exc.status_code}") from exc
            raise AIResponseError(f"Anthropic returned {exc.status_code}") from exc

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return self._to_response(request, model, response, latency_ms)

    # -- internals ------------------------------------------------------------

    def _build_kwargs(self, request: AIRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "max_tokens": request.policy.max_output_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
        }

        # The static prefix is the cacheable half: system rules, schemas, and
        # framework text that never vary between requests of a task. Dynamic
        # market evidence stays in the user message and is never cached --
        # caching live market data would serve stale prices as fresh.
        system_text = "\n\n".join(p for p in (request.system, request.static_prefix) if p)
        if system_text:
            block: dict[str, Any] = {"type": "text", "text": system_text}
            if len(system_text) >= MIN_CACHEABLE_CHARS:
                block["cache_control"] = {"type": "ephemeral"}
            kwargs["system"] = [block]

        if request.schema is not None:
            kwargs["tools"] = [
                {
                    "name": "extract_data",
                    "description": "Record the extracted structured data.",
                    "input_schema": request.schema,
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": "extract_data"}

        return kwargs

    def _to_response(
        self, request: AIRequest, model: str, response: Any, latency_ms: float
    ) -> AIResponse:
        text_parts: list[str] = []
        data: dict[str, Any] | None = None

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                data = dict(block.input)

        if request.schema is not None and data is None:
            raise AIResponseError(
                "Structured extraction was requested but no tool_use block was "
                "returned. Refusing to guess a result."
            )

        return AIResponse(
            request_id=request.context.request_id,
            success=True,
            provider=self.name,
            model=model,
            text="".join(text_parts),
            data=data,
            usage=_usage_from(response),
            latency_ms=latency_ms,
            finish_reason=_FINISH_REASONS.get(
                getattr(response, "stop_reason", None) or "", FinishReason.COMPLETE
            ),
        )


# Below this size a cache breakpoint costs more than it saves: a cache write
# is billed above a normal input token, so caching a short prefix is a net
# loss. The exact provider minimum varies by model; this is a conservative
# floor, not a claim about a specific model's threshold.
MIN_CACHEABLE_CHARS = 2048


def _usage_from(response: Any) -> AIUsage:
    """Read token counts, leaving anything absent as None.

    Before this gateway existed these numbers were returned on every call and
    discarded on every call, which is why the system could not answer what it
    had spent.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return AIUsage()
    return AIUsage(
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", None),
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", None),
    )


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    try:
        raw = headers.get("retry-after")
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
