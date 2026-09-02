"""Obsidian link resolution.

The requirement is "never create broken links", so this resolver **only**
emits `[[wikilinks]]` to notes it has confirmed exist. Anything else is
rendered as plain text.

Two consequences worth stating:
- With no knowledge store (or an unreachable one), every reference degrades
  to plain text rather than a link into nothing.
- The vault listing is fetched **once per report** and cached, so a report
  with fifty references costs one call, not fifty.
"""

from __future__ import annotations

from config.logging import get_logger
from integrations.obsidian.errors import ObsidianError
from integrations.obsidian.knowledge_store import KnowledgeStore

logger = get_logger("reporting")


class LinkResolver:
    def __init__(self, knowledge_store: KnowledgeStore | None = None) -> None:
        self._store = knowledge_store
        self._known: set[str] | None = None
        self._basenames: set[str] | None = None

    def _load(self) -> None:
        """Cache the vault listing. A failure disables linking rather than
        failing the report -- a report without links is still useful.
        """
        if self._known is not None:
            return
        self._known = set()
        self._basenames = set()
        if self._store is None:
            return
        try:
            paths = self._store.list_notes()
        except ObsidianError as exc:
            logger.warning(
                "reporting_link_listing_failed",
                operation="list_notes",
                status="degraded",
                error=type(exc).__name__,
            )
            return
        for path in paths:
            self._known.add(path)
            self._known.add(path.removesuffix(".md"))
            self._basenames.add(path.rsplit("/", 1)[-1].removesuffix(".md"))

    def exists(self, note_path: str | None) -> bool:
        if not note_path:
            return False
        self._load()
        assert self._known is not None
        stripped = note_path.removesuffix(".md")
        return (
            note_path in self._known
            or stripped in self._known
            or stripped.rsplit("/", 1)[-1] in (self._basenames or set())
        )

    def link(self, note_path: str | None, label: str) -> str:
        """`[[path|label]]` when the note exists, otherwise just `label`."""
        if not self.exists(note_path):
            return label
        assert note_path is not None
        target = note_path.removesuffix(".md")
        if target.rsplit("/", 1)[-1] == label:
            return f"[[{target}]]"
        return f"[[{target}|{label}]]"

    def link_by_name(self, name: str) -> str:
        """Link to a note by bare name (e.g. a ticker note) if one exists."""
        self._load()
        if name in (self._basenames or set()):
            return f"[[{name}]]"
        return name
