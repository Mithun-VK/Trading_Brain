"""Reasoning-layer abstraction over an LLM vendor.

Callers (research/thesis/review agents) depend only on this interface.
Rule 1: Claude is a reasoning component, not a source of truth -- nothing
in this interface lets a caller place a trade or write to storage directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    @abstractmethod
    def analyze(self, prompt: str, context: str = "", *, max_tokens: int = 1024) -> str:
        """Free-form reasoning over `context` guided by `prompt`. Returns text."""

    @abstractmethod
    def summarize(self, text: str, *, max_tokens: int = 512) -> str:
        """Condense `text`. Returns text."""

    @abstractmethod
    def extract(
        self, text: str, schema: dict[str, Any], *, max_tokens: int = 1024
    ) -> dict[str, Any]:
        """Extract structured data from `text` matching a JSON Schema `schema`.
        Returns a dict conforming to that schema.
        """
