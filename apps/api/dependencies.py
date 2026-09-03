"""FastAPI dependency providers. Centralized here so routers never
construct an integration/provider directly -- keeps error handling
(missing API key, unreachable Obsidian) consistent across endpoints.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import HTTPException
from sqlalchemy.orm import Session

from config.settings import get_settings
from data.ingestion.factory import get_market_data_provider
from data.ingestion.provider import MarketDataProvider
from data.storage.session import get_db
from integrations.obsidian.errors import ObsidianAuthError
from integrations.obsidian.knowledge_store import KnowledgeStore
from integrations.obsidian.obsidian_knowledge_store import ObsidianKnowledgeStore


def get_session() -> Generator[Session, None, None]:
    yield from get_db()


def get_market_data() -> MarketDataProvider:
    return get_market_data_provider(get_settings().market_data_provider)


def get_knowledge_store() -> Generator[KnowledgeStore, None, None]:
    try:
        store = ObsidianKnowledgeStore(get_settings())
    except ObsidianAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        yield store
    finally:
        store.close()

# NOTE: there is deliberately no `get_llm_provider` here any more.
# AI providers are reached only through the gateway -- see
# apps/api/ai_dependencies.py. A dependency that handed a router a raw
# provider would be a path around routing, budgets, rate limits, and usage
# accounting, which is exactly what tests/ai/test_no_provider_bypass.py
# exists to prevent.
