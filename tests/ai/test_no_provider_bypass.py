"""CRITICAL TEST: no production path may reach a provider SDK directly.

The whole gateway is worthless if application code can construct
`anthropic.Anthropic(...)` and skip routing, budgets, rate limits, and usage
accounting. Documenting that rule would not hold it -- it has to be checked.

Parsed with `ast` rather than grepped, so the many deliberate mentions of
"Anthropic" in docstrings and comments across this repository do not trip it.
Only real imports and real calls count.
"""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# Every package that ships. Tests are excluded: a test may legitimately
# construct a fake client to prove the provider handles it.
SOURCE_DIRS = (
    "apps",
    "backtesting",
    "brain",
    "config",
    "data",
    "integrations",
    "models",
    "observability",
    "paper_trading",
    "quant",
    "scripts",
    "ai",
)

# The only modules permitted to import a vendor SDK.
PROVIDER_LAYER = {
    pathlib.Path("ai/providers/anthropic_provider.py"),
    pathlib.Path("ai/providers/local_provider.py"),
}

VENDOR_SDKS = {"anthropic", "openai", "cohere", "google.generativeai", "mistralai"}


def _source_files() -> list[pathlib.Path]:
    return [
        path
        for directory in SOURCE_DIRS
        for path in (REPO_ROOT / directory).rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _relative(path: pathlib.Path) -> pathlib.Path:
    return path.relative_to(REPO_ROOT)


def test_only_the_provider_layer_imports_a_vendor_sdk() -> None:
    offenders: list[str] = []

    for path in _source_files():
        relative = _relative(path)
        if relative in PROVIDER_LAYER:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                if root in {sdk.split(".")[0] for sdk in VENDOR_SDKS}:
                    offenders.append(f"{relative}:{node.lineno} imports {name}")

    assert offenders == [], (
        "These modules import a vendor SDK outside the provider layer, which "
        f"bypasses the gateway: {offenders}"
    )


def test_no_module_outside_the_provider_layer_constructs_a_client() -> None:
    """Catches `Anthropic(...)` / `AsyncAnthropic(...)` by call name.

    Complements the import check: an alias import
    (`from anthropic import Anthropic`) would already be caught above, but
    this also catches a client constructed from a re-export.
    """
    forbidden_calls = {"Anthropic", "AsyncAnthropic", "OpenAI", "AsyncOpenAI"}
    offenders: list[str] = []

    for path in _source_files():
        relative = _relative(path)
        if relative in PROVIDER_LAYER:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in forbidden_calls:
                offenders.append(f"{relative}:{node.lineno} constructs {name}()")

    assert offenders == [], f"Provider clients constructed outside the layer: {offenders}"


def test_the_scan_actually_sees_the_repository() -> None:
    """Guards the guard.

    A path-resolution mistake would make every assertion above iterate an
    empty list and pass while protecting nothing -- exactly the vacuous-test
    failure found and fixed in Phase 37.
    """
    files = _source_files()

    assert len(files) > 100, f"Only {len(files)} source files found; the scan is broken"
    assert any(_relative(f) in PROVIDER_LAYER for f in files), (
        "The provider layer itself was not found, so the exemption list is stale"
    )


def test_the_provider_layer_does_import_the_sdk() -> None:
    """The exemption is real, not theoretical.

    If the Anthropic provider stopped importing the SDK, the tests above
    would pass trivially and the whole check would be measuring nothing.
    """
    source = (REPO_ROOT / "ai/providers/anthropic_provider.py").read_text(encoding="utf-8")

    assert "import anthropic" in source


def test_there_is_no_raw_ai_endpoint() -> None:
    """No generic prompt-forwarding endpoint.

    Such a route is a task-classification bypass, a budget laundering path,
    and a prompt-injection surface at once. The AI routes that exist are
    read-only operations endpoints.
    """
    from apps.api.main import create_app

    paths = list(create_app().openapi()["paths"])
    ai_paths = [p for p in paths if p.startswith("/ai")]

    assert ai_paths, "The scan found no /ai routes at all; it is not seeing the app"
    for path in ai_paths:
        methods = create_app().openapi()["paths"][path]
        assert set(methods) <= {"get"}, (
            f"{path} accepts {sorted(methods)}. AI operations endpoints must be "
            "read-only -- a writable generic AI route is a policy bypass."
        )
