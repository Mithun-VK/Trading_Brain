"""The reasoning-layer interface.

`ClaudeProvider` used to live here and construct an Anthropic client
directly. It was removed in Phase 40: the Anthropic SDK is now reached only
through `ai.providers.anthropic_provider`, behind the gateway, so that no
call can skip routing, budgets, rate limiting, or usage accounting.

The `LLMProvider` interface stays -- the agents depend on it, and
`ai.adapter.GatewayLLMProvider` implements it over the gateway.
"""

from integrations.claude.llm_provider import LLMProvider

__all__ = ["LLMProvider"]
