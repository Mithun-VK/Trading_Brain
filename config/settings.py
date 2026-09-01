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

    @property
    def market_data_fallback_list(self) -> list[str]:
        return [name.strip() for name in self.market_data_fallbacks.split(",") if name.strip()]

    @property
    def auth_tokens(self) -> set[str]:
        return {t.strip() for t in self.api_auth_tokens.split(",") if t.strip()}

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
