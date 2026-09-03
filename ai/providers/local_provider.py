"""Local LLM provider, over an OpenAI-compatible endpoint.

Works with Ollama, LM Studio, vLLM, and llama.cpp's server -- all of which
expose `/v1/chat/completions`. Configured by `LOCAL_LLM_BASE_URL`; when that
is unset the provider is never registered, so nothing here runs.

Why local matters here beyond cost: a request marked `local_only` must not
leave the machine, and this is the only provider that can satisfy it. The
router refuses rather than escalating such a request -- a privacy constraint
outranks output quality.

Structured extraction is handled by asking for JSON and validating it,
because tool-calling support across local runtimes is inconsistent. Invalid
JSON is a failure, never a salvage attempt: a half-parsed extraction is
indistinguishable from a fabricated one.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from ai.provider import AIModel, AIProvider
from ai.schemas import (
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

_JSON_INSTRUCTION = (
    "Respond with a single JSON object matching this schema. Output only the "
    "JSON object, with no prose, no explanation, and no markdown fences. "
    "Populate only fields you can support from the provided text; omit fields "
    "you cannot support rather than guessing.\n\nSchema:\n"
)


class LocalAIProvider(AIProvider):
    name = "local"
    is_local = True

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.local_llm_base_url:
            raise AIProviderUnavailable("LOCAL_LLM_BASE_URL is not configured")
        self._settings = settings
        self._base_url = settings.local_llm_base_url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if settings.local_llm_api_key:
            headers["Authorization"] = f"Bearer {settings.local_llm_api_key}"
        self._client = client or httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=settings.local_llm_timeout_seconds,
        )

    def models(self) -> list[AIModel]:
        model = self._settings.ai_local_model
        if not model:
            return []
        return [
            AIModel(
                name=model,
                provider=self.name,
                tier=AITier.LOCAL,
                # Conservative: local runtimes vary widely and silently
                # truncate when the window is exceeded. The router refuses to
                # route oversized work here rather than risk a truncated
                # answer being presented as a complete one.
                max_context_chars=24_000,
                supports_tools=False,
                supports_caching=False,
            )
        ]

    def health(self) -> tuple[bool, str]:
        """Single-shot probe with a short timeout.

        Local inference is free to call, so unlike the Anthropic check this
        one genuinely probes -- but a health check must still fail fast.
        """
        try:
            response = self._client.get("/v1/models", timeout=HEALTH_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 -- health must never raise
            return False, f"Unreachable at {self._base_url}: {type(exc).__name__}"
        if response.status_code >= 400:
            return False, f"Endpoint responded {response.status_code}."
        return True, f"Reachable at {self._base_url}."

    def invoke(self, request: AIRequest, model: str) -> AIResponse:
        started = time.perf_counter()
        payload = self._build_payload(request, model)

        try:
            response = self._client.post("/v1/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise AIProviderUnavailable(f"Local model timed out: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise AIProviderUnavailable(f"Local model unreachable: {type(exc).__name__}") from exc

        if response.status_code == 429:
            raise AIRateLimited("Local endpoint is throttling requests")
        if response.status_code >= 500:
            raise AIProviderUnavailable(f"Local endpoint returned {response.status_code}")
        if response.status_code >= 400:
            raise AIResponseError(f"Local endpoint returned {response.status_code}")

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return self._to_response(request, model, response.json(), latency_ms)

    # -- internals ------------------------------------------------------------

    def _build_payload(self, request: AIRequest, model: str) -> dict[str, Any]:
        system_text = "\n\n".join(p for p in (request.system, request.static_prefix) if p)
        user_content = request.prompt

        if request.schema is not None:
            user_content = (
                f"{request.prompt}\n\n{_JSON_INSTRUCTION}"
                f"{json.dumps(request.schema, indent=2)}"
            )

        messages: list[dict[str, str]] = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.append({"role": "user", "content": user_content})

        return {
            "model": model,
            "messages": messages,
            "max_tokens": request.policy.max_output_tokens,
            "temperature": 0.0,  # deterministic: this is analysis, not prose
            "stream": False,
        }

    def _to_response(
        self, request: AIRequest, model: str, body: dict[str, Any], latency_ms: float
    ) -> AIResponse:
        choices = body.get("choices") or []
        if not choices:
            raise AIResponseError("Local endpoint returned no choices")

        message = choices[0].get("message") or {}
        text = (message.get("content") or "").strip()
        finish = choices[0].get("finish_reason")

        data: dict[str, Any] | None = None
        if request.schema is not None:
            data = _parse_json_object(text)
            if data is None:
                raise AIResponseError(
                    "Local model did not return a parseable JSON object for a "
                    "structured extraction. Refusing to salvage a partial result."
                )

        usage_block = body.get("usage") or {}
        return AIResponse(
            request_id=request.context.request_id,
            success=True,
            provider=self.name,
            model=model,
            text="" if data is not None else text,
            data=data,
            usage=AIUsage(
                input_tokens=usage_block.get("prompt_tokens"),
                output_tokens=usage_block.get("completion_tokens"),
            ),
            latency_ms=latency_ms,
            finish_reason=(
                FinishReason.MAX_TOKENS if finish == "length" else FinishReason.COMPLETE
            ),
        )


HEALTH_TIMEOUT = 2.0

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object, tolerating a markdown fence around it.

    Fence-stripping is the one accommodation made for local models, which
    add them habitually despite instructions. Nothing beyond that is
    attempted: repairing malformed JSON would mean guessing what the model
    meant, and a guessed field is a fabricated one.
    """
    candidate = text.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
