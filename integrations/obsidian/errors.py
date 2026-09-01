"""Structured errors for the Obsidian integration.

Callers should catch `ObsidianError` (or a specific subclass) rather than
raw `httpx` exceptions, so the rest of the codebase does not need to know
which HTTP client the integration uses underneath.
"""

from __future__ import annotations


class ObsidianError(Exception):
    """Base class for all Obsidian integration errors."""


class ObsidianConnectionError(ObsidianError):
    """Could not reach the Obsidian Local REST API (connection/timeout)."""


class ObsidianAuthError(ObsidianError):
    """The API key was missing or rejected (401/403)."""


class ObsidianNotFoundError(ObsidianError):
    """The requested note does not exist (404)."""


class ObsidianAPIError(ObsidianError):
    """The API responded with an unexpected error status."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Obsidian API error ({status_code}): {message}")
