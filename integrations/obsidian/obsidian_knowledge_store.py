"""KnowledgeStore implementation backed by the Obsidian Local REST API
community plugin (https://github.com/coddingtonbear/obsidian-local-rest-api).

The plugin serves HTTPS on a loopback port with a self-signed certificate by
design (it is not meant to be exposed beyond localhost), so TLS verification
is disabled here rather than pointed at a CA bundle.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config.logging import get_logger
from config.settings import Settings
from integrations.obsidian.errors import (
    ObsidianAPIError,
    ObsidianAuthError,
    ObsidianConnectionError,
    ObsidianNotFoundError,
)
from integrations.obsidian.knowledge_store import KnowledgeStore, Note, SearchResult

logger = get_logger("obsidian")

_RETRYABLE = (ObsidianConnectionError,)


class ObsidianKnowledgeStore(KnowledgeStore):
    def __init__(
        self,
        settings: Settings,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not settings.obsidian_api_key:
            raise ObsidianAuthError("OBSIDIAN_API_KEY is not configured")

        self._client = httpx.Client(
            base_url=settings.obsidian_base_url,
            headers={"Authorization": f"Bearer {settings.obsidian_api_key}"},
            timeout=timeout,
            verify=_tls_verification(settings),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ObsidianKnowledgeStore:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # -- KnowledgeStore interface -------------------------------------------------

    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        response = self._request(
            "POST",
            "/search/simple/",
            params={"query": query, "contextLength": 200},
        )
        raw_results = response.json()
        results = [
            SearchResult(
                path=item["filename"],
                score=item.get("score", 0.0),
                context=_flatten_matches(item.get("matches", [])),
            )
            for item in raw_results
        ]
        return results[:limit]

    def read(self, path: str) -> Note:
        response = self._request("GET", f"/vault/{_encode(path)}")
        return Note(path=path, content=response.text)

    def write(self, path: str, content: str) -> None:
        self._request(
            "PUT",
            f"/vault/{_encode(path)}",
            content=content.encode("utf-8"),
            headers={"Content-Type": "text/markdown; charset=utf-8"},
        )
        logger.info("obsidian_write", operation="write", status="ok", path=path)

    def update(self, path: str, content: str) -> None:
        self.write(path, content)
        logger.info("obsidian_update", operation="update", status="ok", path=path)

    def append(self, path: str, content: str) -> None:
        self._request(
            "POST",
            f"/vault/{_encode(path)}",
            content=content.encode("utf-8"),
            headers={"Content-Type": "text/markdown; charset=utf-8"},
        )
        logger.info("obsidian_append", operation="append", status="ok", path=path)

    def append_to_section(self, path: str, section: str, content: str) -> bool:
        """Append under a specific heading via the plugin's PATCH instruction.

        Plain `append` writes to the *end of the file*, which only lands in
        the right place while the target heading happens to be last. This
        targets the heading explicitly.

        Returns True if the section was targeted, False if it wasn't found
        and the content was appended to the end of the file instead -- the
        caller can then surface that the note needs the heading restored.
        """
        instruction = {
            "targetType": "heading",
            "target": [section],
            "operation": "append",
            "content": content,
        }
        try:
            self._request(
                "PATCH",
                f"/vault/{_encode(path)}",
                json_body=instruction,
                headers={"Content-Type": "application/json"},
            )
        except (ObsidianNotFoundError, ObsidianAPIError):
            # The heading isn't in the note (or the server rejected the
            # target). Fall back rather than losing an audit entry.
            logger.warning(
                "obsidian_section_append_fallback",
                operation="append_to_section",
                status="fallback",
                path=path,
                section=section,
            )
            self.append(path, content)
            return False

        logger.info(
            "obsidian_append_to_section",
            operation="append_to_section",
            status="ok",
            path=path,
            section=section,
        )
        return True

    def list_notes(self, folder: str | None = None) -> list[str]:
        prefix = f"/vault/{_encode(folder)}/" if folder else "/vault/"
        response = self._request("GET", prefix)
        files = response.json().get("files", [])
        base = f"{folder}/" if folder else ""
        return [f"{base}{f}" for f in files if not f.endswith("/")]

    def backlinks(self, path: str) -> list[str]:
        # The Local REST API has no dedicated backlinks endpoint, so this
        # approximates it: search for wikilinks to the note's basename.
        # False negatives are possible for aliased/renamed links.
        note_name = path.rsplit("/", 1)[-1].removesuffix(".md")
        results = self.search(f"[[{note_name}", limit=100)
        return [r.path for r in results if r.path != path]

    # -- internals ------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        # Mapping (covariant) rather than dict (invariant), so callers can
        # pass a more specifically-typed instruction dict.
        json_body: Mapping[str, object] | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                content=content,
                json=json_body,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            logger.warning("obsidian_timeout", operation=method, status="timeout", path=path)
            raise ObsidianConnectionError(f"Timed out calling Obsidian API: {path}") from exc
        except httpx.ConnectError as exc:
            logger.warning("obsidian_connect_error", operation=method, status="error", path=path)
            raise ObsidianConnectionError(f"Could not connect to Obsidian API: {path}") from exc

        if response.status_code in (401, 403):
            raise ObsidianAuthError("Obsidian API rejected the configured API key")
        if response.status_code == 404:
            raise ObsidianNotFoundError(f"Note not found: {path}")
        if response.status_code >= 400:
            raise ObsidianAPIError(response.status_code, response.text)

        return response


def _tls_verification(settings: Settings) -> bool | str:
    """Resolve how TLS is verified against the plugin's local server.

    The plugin generates its own name-constrained CA (it can only vouch for
    localhost), downloadable from `/obsidian-local-rest-api.crt`. Pointing
    at that file is strictly better than disabling verification, so it wins
    when configured. Verification-off remains the default because it is the
    plugin's out-of-the-box state on a loopback address.
    """
    if settings.obsidian_ca_cert_path:
        return settings.obsidian_ca_cert_path
    return settings.obsidian_verify_tls


def _encode(path: str) -> str:
    from urllib.parse import quote

    return quote(path)


def _flatten_matches(matches: list[dict]) -> str:
    contexts = [m.get("context", "") for m in matches]
    return " … ".join(c for c in contexts if c)
