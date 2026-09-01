"""Structured errors for the Claude integration, mirroring
integrations/obsidian/errors.py so both integrations are consistent to
handle.
"""

from __future__ import annotations


class ClaudeError(Exception):
    """Base class for all Claude integration errors."""


class ClaudeAuthError(ClaudeError):
    """The API key was missing or rejected."""


class ClaudeConnectionError(ClaudeError):
    """Could not reach the Anthropic API, or it's rate-limiting us (both
    are transient and safe to retry).
    """


class ClaudeAPIError(ClaudeError):
    """The API responded with an unexpected error status."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"Claude API error ({status_code}): {message}")
