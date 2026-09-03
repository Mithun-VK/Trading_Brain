"""Centralized application settings, loaded from environment variables / .env.

Every other module reads configuration through `get_settings()` rather than
calling `os.environ` directly, so secrets stay isolated to this one place.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_auth_tokens: str = Field(default="", alias="API_AUTH_TOKENS")

    # --- PostgreSQL ---
    database_url: str = Field(
        default="postgresql+psycopg://trading_brain:change-me@localhost:5432/trading_brain",
        alias="DATABASE_URL",
    )

    # --- Redis ---
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # --- Obsidian ---
    obsidian_base_url: str = Field(default="https://127.0.0.1:27124", alias="OBSIDIAN_BASE_URL")
    obsidian_api_key: str = Field(default="", alias="OBSIDIAN_API_KEY")
    obsidian_vault_path: str = Field(default="", alias="OBSIDIAN_VAULT_PATH")
    # The plugin serves a self-signed cert on loopback by default, so
    # verification is off unless you opt in. Trusting its downloadable CA
    # (see docs/obsidian.md) is the better option and takes precedence.
    obsidian_verify_tls: bool = Field(default=False, alias="OBSIDIAN_VERIFY_TLS")
    obsidian_ca_cert_path: str = Field(default="", alias="OBSIDIAN_CA_CERT_PATH")

    # --- Claude / Anthropic ---
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-5", alias="ANTHROPIC_MODEL")

    # --- Market data ---
    market_data_provider: str = Field(default="mock", alias="MARKET_DATA_PROVIDER")
    # Comma-separated provider names tried, in order, when the primary fails.
    # Synthetic providers (mock) are rejected here -- see ProviderRegistry.
    market_data_fallbacks: str = Field(default="", alias="MARKET_DATA_FALLBACKS")
    market_data_timeout_seconds: float = Field(
        default=10.0, alias="MARKET_DATA_TIMEOUT_SECONDS"
    )
    alphavantage_api_key: str = Field(default="", alias="ALPHAVANTAGE_API_KEY")

    # --- AI gateway ---
    # Tier -> model. Empty means the tier is unavailable and the router says
    # so, rather than silently substituting a model from another tier.
    ai_local_model: str = Field(default="", alias="AI_LOCAL_MODEL")
    ai_frontier_model: str = Field(default="", alias="AI_FRONTIER_MODEL")
    ai_frontier_high_model: str = Field(default="", alias="AI_FRONTIER_HIGH_MODEL")
    # OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, llama.cpp server).
    # Empty disables the local provider entirely.
    local_llm_base_url: str = Field(default="", alias="LOCAL_LLM_BASE_URL")
    local_llm_api_key: str = Field(default="", alias="LOCAL_LLM_API_KEY")
    local_llm_timeout_seconds: float = Field(
        default=120.0, alias="LOCAL_LLM_TIMEOUT_SECONDS"
    )
    # Per-million-token rates as JSON; see config/ai_pricing.py. Unset means
    # costs report as unknown -- never as zero.
    ai_model_pricing: str = Field(default="", alias="AI_MODEL_PRICING")
    ai_pricing_currency: str = Field(default="USD", alias="AI_PRICING_CURRENCY")
    # Budgets. 0 disables that window's ceiling.
    ai_budget_per_request: float = Field(default=0.0, alias="AI_BUDGET_PER_REQUEST")
    ai_budget_per_hour: float = Field(default=0.0, alias="AI_BUDGET_PER_HOUR")
    ai_budget_per_day: float = Field(default=0.0, alias="AI_BUDGET_PER_DAY")
    ai_budget_per_month: float = Field(default=0.0, alias="AI_BUDGET_PER_MONTH")
    # Fraction of a budget at which the gateway warns before it blocks.
    ai_budget_warn_ratio: float = Field(default=0.8, alias="AI_BUDGET_WARN_RATIO")
    # Inbound rate limits on AI-spending routes. 0 disables that dimension.
    ai_rate_limit_per_minute: int = Field(default=10, alias="AI_RATE_LIMIT_PER_MINUTE")
    ai_rate_limit_per_hour: int = Field(default=100, alias="AI_RATE_LIMIT_PER_HOUR")
    # Cache lifetime for completed identical requests, per task type default.
    ai_cache_ttl_seconds: int = Field(default=900, alias="AI_CACHE_TTL_SECONDS")
    # When a model has no configured price: allow the call and flag it, or
    # refuse. Allowing is the default so adding a model does not break the
    # system, but operators who want strict cost control can invert it.
    ai_allow_unpriced_models: bool = Field(
        default=True, alias="AI_ALLOW_UNPRICED_MODELS"
    )

    @property
    def market_data_fallback_list(self) -> list[str]:
        return [name.strip() for name in self.market_data_fallbacks.split(",") if name.strip()]

    @property
    def ai_enabled(self) -> bool:
        """True when at least one AI provider is configured.

        The deterministic core must work when this is False, which is
        asserted by tests/ai/test_deterministic_independence.py.
        """
        return bool(self.anthropic_api_key or self.local_llm_base_url)

    @property
    def auth_tokens(self) -> set[str]:
        return {t.strip() for t in self.api_auth_tokens.split(",") if t.strip()}

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    def production_issues(self) -> list[str]:
        """Configuration that is fine for local development and wrong in
        production.

        Every default in this class is chosen so a developer's first run
        works with no setup. That is the right trade -- but it means the
        unsafe configuration is also the *quiet* one: nothing about running
        with a synthetic price feed and no authentication looks different
        from running correctly. This method is what makes it look different.

        Returns an empty list outside production, since none of these are
        problems there.
        """
        if not self.is_production:
            return []

        issues: list[str] = []

        if self.market_data_provider.lower() in _SYNTHETIC_PROVIDERS:
            issues.append(
                f"MARKET_DATA_PROVIDER={self.market_data_provider!r} is a synthetic "
                "generator. Prices, and every number derived from them, would be "
                "invented (Rule 4)."
            )
        if not self.auth_tokens:
            issues.append(
                "API_AUTH_TOKENS is empty, so every endpoint is publicly callable -- "
                "including ones that spend Anthropic API credits."
            )
        if "change-me" in self.database_url:
            issues.append("DATABASE_URL still contains the placeholder password 'change-me'.")
        if not self.anthropic_api_key:
            issues.append(
                "ANTHROPIC_API_KEY is not set; the research and thesis agents cannot run."
            )
        if self.obsidian_api_key and not (self.obsidian_verify_tls or self.obsidian_ca_cert_path):
            issues.append(
                "Obsidian is configured but TLS verification is off and no CA is pinned "
                "(set OBSIDIAN_CA_CERT_PATH)."
            )
        if self.log_level.upper() == "DEBUG":
            issues.append("LOG_LEVEL=DEBUG is unusually verbose for production.")

        return issues


# Providers that generate numbers rather than retrieve them. Kept here so
# settings can name them without importing the ingestion package.
_SYNTHETIC_PROVIDERS = frozenset({"mock", "synthetic", "fake"})


@lru_cache
def get_settings() -> Settings:
    return Settings()
