"""No AI path can reach live execution (Phases 38-45, safety rules 1-7).

The existing execution-safety invariants prove no route places an order. This
file proves the narrower, newer thing: that adding a reasoning layer did not
open a path from model output to a trade.

The threat is not that someone deliberately wires Claude to a broker. It is
that AI output is structurally *just a dict*, and a dict that reaches a
mutation path is indistinguishable from one a human typed. So the checks
here are about what the AI layer can import and what its output can reach.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from apps.api.main import create_app

ROOT = pathlib.Path(__file__).resolve().parents[2]
AI_PACKAGE = ROOT / "ai"


def _ai_modules() -> list[pathlib.Path]:
    return [p for p in AI_PACKAGE.rglob("*.py") if "__pycache__" not in p.parts]


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
    return found


def test_the_scan_sees_the_ai_package() -> None:
    """Guards every assertion below from passing over an empty list -- the
    exact way an earlier safety invariant in this repository was vacuous
    while reading like a guarantee.
    """
    modules = _ai_modules()

    assert len(modules) >= 8, f"Only {len(modules)} AI modules found; the scan is broken"
    assert any(p.name == "gateway.py" for p in modules)


def test_no_ai_module_imports_a_trading_or_portfolio_mutation_path() -> None:
    """The AI layer may reason about a portfolio. It may not change one.

    `paper_trading` and the trade repositories are the only code that moves
    a position, even a simulated one -- so the AI package must not be able
    to call them at all.
    """
    forbidden = (
        "paper_trading",
        "data.storage.portfolio_repository",
        "data.storage.trade_repository",
    )
    offenders = [
        f"{p.relative_to(ROOT).as_posix()}: {name}"
        for p in _ai_modules()
        for name in _imports(p)
        if name.startswith(forbidden)
    ]

    assert offenders == [], f"AI modules reach a mutation path: {offenders}"


def test_no_ai_module_imports_a_broker_sdk() -> None:
    broker = {
        "alpaca", "alpaca_trade_api", "ib_insync", "ibapi", "kiteconnect",
        "zerodha", "robin_stocks", "tda", "schwab", "ccxt", "binance",
    }
    offenders = [
        f"{p.relative_to(ROOT).as_posix()}: {name}"
        for p in _ai_modules()
        for name in _imports(p)
        if name.split(".")[0] in broker
    ]

    assert offenders == []


def test_no_ai_route_can_mutate_anything() -> None:
    """Every /ai endpoint is read-only.

    An administrative surface that can also write is a surface that can be
    made to write by someone who only meant to look.
    """
    paths = create_app().openapi()["paths"]
    ai_paths = {p: v for p, v in paths.items() if p.startswith("/ai")}

    assert ai_paths, "No /ai routes found; this test is not seeing the app"
    for path, operations in ai_paths.items():
        assert set(operations) <= {"get"}, f"{path} exposes {sorted(operations)}"


def test_no_ai_route_resembles_execution() -> None:
    paths = create_app().openapi()["paths"]
    forbidden = ("order", "execute", "buy", "sell", "broker", "trade/place")

    offenders = [
        p for p in paths if p.startswith("/ai") and any(w in p.lower() for w in forbidden)
    ]

    assert offenders == []


@pytest.mark.parametrize("path", ["/ai/orders", "/ai/execute", "/ai/raw", "/ai/prompt"])
def test_speculative_ai_execution_endpoints_do_not_exist(path: str) -> None:
    """Named explicitly so that adding any of them fails a test rather than
    quietly appearing in the OpenAPI schema."""
    assert path not in create_app().openapi()["paths"]


def test_the_gateway_returns_text_not_actions() -> None:
    """The interface the application sees is analyse/summarise/extract --
    three ways to get language back. There is no verb here that does
    anything to the world, which is what makes AI output safe to treat as
    untrusted analytical text.
    """
    from integrations.claude.llm_provider import LLMProvider

    methods = {
        name for name in vars(LLMProvider) if not name.startswith("_")
    }

    assert methods == {"analyze", "summarize", "extract"}
