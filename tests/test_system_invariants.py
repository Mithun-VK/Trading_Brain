"""System-wide invariants (Phase 33).

These are the properties no single unit test can protect, because they are
about the *whole* application rather than any one module: they hold only if
every part agrees. Each one is a rule that a plausible, well-intentioned
future change could break without breaking anything else.

They are written against the assembled app and the real source tree, not
against mocks -- an invariant checked against a double is an invariant about
the double.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from apps.api.main import create_app

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

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
)


def _source_files() -> list[pathlib.Path]:
    return [
        path
        for directory in SOURCE_DIRS
        for path in (REPO_ROOT / directory).rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _routes() -> list[APIRoute]:
    return [r for r in create_app().routes if isinstance(r, APIRoute)]


# -- Rule 7 / Rule 8: no execution path can exist --------------------------------


def test_no_route_looks_like_an_order_placement_endpoint() -> None:
    """The middleware guard blocks four known prefixes. This is the broader
    claim: no registered route anywhere resembles execution.

    A guard on a path list only protects the paths someone thought of.
    """
    forbidden = ("order", "execute", "/buy", "/sell", "broker", "brokerage")

    offenders = [
        r.path for r in _routes() if any(word in r.path.lower() for word in forbidden)
    ]

    assert offenders == [], f"Routes resembling execution were registered: {offenders}"


def test_no_broker_sdk_is_importable_from_source() -> None:
    """No broker client library is imported anywhere in the tree.

    Parsed with `ast` rather than grepped, so a mention inside a docstring
    or a comment -- of which this repository has many, deliberately -- does
    not trip it. Only real imports count.
    """
    broker_packages = {
        "alpaca", "alpaca_trade_api", "ib_insync", "ibapi", "kiteconnect",
        "zerodha", "robin_stocks", "tda", "schwab", "oandapyV20", "ccxt",
        "binance", "coinbase",
    }
    offenders: list[str] = []

    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for name in names:
                if name in broker_packages:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {name}")

    assert offenders == [], f"Broker SDK imports found: {offenders}"


@pytest.mark.parametrize("path", ["/orders", "/execute", "/buy", "/sell"])
@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
def test_execution_paths_are_blocked_for_every_method(
    client: TestClient, path: str, method: str
) -> None:
    """The guard is prefix-based and method-agnostic. Blocking only POST
    would leave `PUT /orders/1` reachable if a router were ever added."""
    response = getattr(client, method)(path)

    assert response.status_code == 403


def test_execution_paths_are_blocked_on_subpaths(client: TestClient) -> None:
    assert client.post("/orders/123/cancel").status_code == 403
    assert client.get("/execute/anything").status_code == 403


# -- Rule 4: generated data must never pass as real ------------------------------


def test_a_synthetic_provider_can_never_be_a_fallback() -> None:
    """A synthetic primary is a deliberate local choice. A synthetic
    *fallback* is something you land in by accident, inheriting invented
    numbers with no marker that they are invented."""
    from data.ingestion.errors import ProviderError
    from data.ingestion.mock_provider import MockProvider
    from data.ingestion.registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.register("mock", MockProvider, synthetic=True)
    registry.register("real", MockProvider, synthetic=False)

    registry.set_fallbacks(["real"])  # a real provider is fine

    with pytest.raises(ProviderError, match="synthetic"):
        registry.set_fallbacks(["mock"])


# -- Rule 10: a claim without traceable evidence is not served -------------------


def test_no_signal_category_is_an_execution_instruction() -> None:
    """`SignalCategory` is a closed enum, and none of its members may name an
    action the system cannot take. This is the invariant behind the closed
    enum, asserted independently of it."""
    from brain.signals.schemas import FORBIDDEN_CATEGORIES, SignalCategory

    assert FORBIDDEN_CATEGORIES
    for member in SignalCategory:
        assert str(member).upper() not in FORBIDDEN_CATEGORIES


def test_a_signal_cannot_be_constructed_without_evidence() -> None:
    """Rule 10 is enforced at construction, so an evidence-free signal cannot
    exist to be stored or served -- not merely filtered on the way out."""
    from brain.signals.schemas import GeneratedSignal, SignalCategory, SignalError

    with pytest.raises(SignalError, match="no evidence"):
        GeneratedSignal(
            asset_id=1,
            ticker="AAPL",
            category=SignalCategory.WATCH,
            reasoning="looks interesting",
            evidence=[],
        )


# -- secrets ---------------------------------------------------------------------


def test_no_source_file_contains_a_hardcoded_credential() -> None:
    """Assignment of a long literal to a secret-shaped name.

    Deliberately narrow: it looks for `x = "<12+ chars>"` where the name is
    secret-shaped, which is the shape of an actual leak, rather than for the
    word 'key' anywhere -- a check that fires constantly is a check that
    gets suppressed.
    """
    secret_names = ("api_key", "apikey", "secret", "password", "token", "passwd")
    allowed_values = {"", "change-me", "test", "sk-test"}
    offenders: list[str] = []

    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                continue
            value = node.value.value
            if len(value) < 12 or value in allowed_values:
                continue
            for target in node.targets:
                name = getattr(target, "id", "") or getattr(target, "attr", "")
                if any(s in name.lower() for s in secret_names):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {name}")

    assert offenders == [], f"Possible hardcoded credentials: {offenders}"


def test_the_repository_ignores_every_secret_bearing_path() -> None:
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    for pattern in (".env", ".venv", "node_modules", ".obsidian"):
        assert pattern in ignored, f"{pattern} is not gitignored"


def test_env_example_carries_no_real_values() -> None:
    """`.env.example` is tracked, so anything filled in here is published."""
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    for line in text.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if any(s in name.lower() for s in ("key", "token", "secret", "password")):
            assert value.strip() in {"", "change-me"}, f"{name} has a value in .env.example"


# -- documentation honesty -------------------------------------------------------


def test_the_security_document_records_gaps_not_just_controls() -> None:
    """The spec asked for no invented security layer. A security document
    listing only strengths is the written form of exactly that."""
    text = (REPO_ROOT / "docs" / "security.md").read_text(encoding="utf-8").lower()

    assert "known gaps" in text
    assert "rate limiting" in text
