"""Abstraction over the vault knowledge layer.

Business logic (research agent, thesis agent, review agent) depends on this
interface, never on a specific Obsidian plugin/API. `ObsidianKnowledgeStore`
is the only implementation today; a future implementation (e.g. a different
notes backend) can be swapped in without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Note:
    path: str
    content: str


@dataclass(frozen=True)
class SearchResult:
    path: str
    score: float
    context: str


class KnowledgeStore(ABC):
    @abstractmethod
    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        """Full-text search across the vault."""

    @abstractmethod
    def read(self, path: str) -> Note:
        """Read a note's raw content by vault-relative path."""

    @abstractmethod
    def write(self, path: str, content: str) -> None:
        """Create a note, or overwrite it if it already exists."""

    @abstractmethod
    def update(self, path: str, content: str) -> None:
        """Overwrite an existing note's content."""

    @abstractmethod
    def append(self, path: str, content: str) -> None:
        """Append content to the end of an existing (or new) note."""

    @abstractmethod
    def list_notes(self, folder: str | None = None) -> list[str]:
        """List vault-relative note paths, optionally scoped to a folder."""

    @abstractmethod
    def backlinks(self, path: str) -> list[str]:
        """List paths of notes that link to the given note."""
