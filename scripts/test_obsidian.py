"""CLI smoke test for the Obsidian integration.

Usage: python -m scripts.test_obsidian

Exercises connection, authentication, search, read, write, update, and
append against a single dedicated test note. Never touches existing vault
content.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

from config.settings import get_settings
from integrations.obsidian.errors import ObsidianError
from integrations.obsidian.obsidian_knowledge_store import ObsidianKnowledgeStore

TEST_NOTE_PATH = "99 Archive/_tradingbrain_connection_test.md"


def _step(name: str, fn: Callable[[], None]) -> bool:
    try:
        fn()
    except ObsidianError as exc:
        print(f"[FAIL] {name}: {exc}")
        return False
    else:
        print(f"[OK]   {name}")
        return True


def main() -> int:
    settings = get_settings()
    if not settings.obsidian_api_key:
        print("OBSIDIAN_API_KEY is not set - copy .env.example to .env and configure it.")
        return 1

    store = ObsidianKnowledgeStore(settings)
    ok = True

    def check_connection() -> None:
        store.list_notes()

    def check_write() -> None:
        store.write(TEST_NOTE_PATH, "# TradingBrain connection test\n\nstatus: initial\n")

    def check_read() -> None:
        note = store.read(TEST_NOTE_PATH)
        assert "TradingBrain connection test" in note.content

    def check_update() -> None:
        store.update(TEST_NOTE_PATH, "# TradingBrain connection test\n\nstatus: updated\n")
        note = store.read(TEST_NOTE_PATH)
        assert "status: updated" in note.content

    def check_append() -> None:
        store.append(TEST_NOTE_PATH, "\nappended line\n")
        note = store.read(TEST_NOTE_PATH)
        assert "appended line" in note.content

    def check_search() -> None:
        store.search("TradingBrain connection test")

    try:
        ok &= _step("connection + authentication (list vault root)", check_connection)
        ok &= _step("write test note", check_write)
        ok &= _step("read test note", check_read)
        ok &= _step("update test note", check_update)
        ok &= _step("append to test note", check_append)
        ok &= _step("search vault", check_search)
    finally:
        store.close()

    print()
    print(f"Test note left at: {TEST_NOTE_PATH}")
    if ok:
        print("All Obsidian integration checks passed.")
        return 0
    print("One or more Obsidian integration checks failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
