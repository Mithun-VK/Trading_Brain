"""Shared in-memory fakes for tests that exercise agents/assemblers built on
top of KnowledgeStore/LLMProvider, without a live Obsidian instance or
Anthropic API call.
"""

from __future__ import annotations

from typing import Any

from integrations.claude.llm_provider import LLMProvider
from integrations.obsidian.errors import ObsidianNotFoundError
from integrations.obsidian.knowledge_store import KnowledgeStore, Note, SearchResult


class FakeKnowledgeStore(KnowledgeStore):
    def __init__(self, notes: dict[str, str] | None = None) -> None:
        self.notes: dict[str, str] = dict(notes or {})

    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        results = [
            SearchResult(path=path, score=1.0, context=content[:200])
            for path, content in self.notes.items()
            if query.lower() in content.lower() or query.lower() in path.lower()
        ]
        return results[:limit]

    def read(self, path: str) -> Note:
        if path not in self.notes:
            raise ObsidianNotFoundError(f"Note not found: {path}")
        return Note(path=path, content=self.notes[path])

    def write(self, path: str, content: str) -> None:
        self.notes[path] = content

    def update(self, path: str, content: str) -> None:
        self.notes[path] = content

    def append(self, path: str, content: str) -> None:
        self.notes[path] = self.notes.get(path, "") + content

    def append_to_section(self, path: str, section: str, content: str) -> bool:
        """Mirrors the real store: insert at the end of the named section,
        or fall back to end-of-note when the heading is absent.
        """
        body = self.notes.get(path, "")
        heading = f"## {section}"
        if heading not in body:
            self.append(path, content)
            return False

        start = body.index(heading) + len(heading)
        next_heading = body.find("\n## ", start)
        insert_at = len(body) if next_heading == -1 else next_heading
        self.notes[path] = body[:insert_at] + content + body[insert_at:]
        return True

    def list_notes(self, folder: str | None = None) -> list[str]:
        if folder is None:
            return list(self.notes.keys())
        return [p for p in self.notes if p.startswith(folder)]

    def backlinks(self, path: str) -> list[str]:
        name = path.rsplit("/", 1)[-1].removesuffix(".md")
        return [p for p, c in self.notes.items() if p != path and f"[[{name}" in c]


class FakeLLMProvider(LLMProvider):
    """Returns caller-configured canned responses instead of calling Claude."""

    def __init__(
        self,
        analyze_response: str = "analysis",
        summarize_response: str = "summary",
        extract_response: dict[str, Any] | None = None,
    ) -> None:
        self.analyze_response = analyze_response
        self.summarize_response = summarize_response
        self.extract_response = extract_response or {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def analyze(self, prompt: str, context: str = "", *, max_tokens: int = 1024) -> str:
        self.calls.append(("analyze", (prompt, context), {"max_tokens": max_tokens}))
        return self.analyze_response

    def summarize(self, text: str, *, max_tokens: int = 512) -> str:
        self.calls.append(("summarize", (text,), {"max_tokens": max_tokens}))
        return self.summarize_response

    def extract(
        self, text: str, schema: dict[str, Any], *, max_tokens: int = 1024
    ) -> dict[str, Any]:
        self.calls.append(("extract", (text, schema), {"max_tokens": max_tokens}))
        return self.extract_response
