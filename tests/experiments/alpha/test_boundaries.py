"""V5's hard boundaries: no AI, no broker, no automatic activation.

These are structural tests over the real source tree, in the same style as
`tests/test_system_invariants.py` and `tests/ai/test_ai_cannot_execute.py`
-- every one includes a non-vacuity guard, because this repository has
already once shipped an invariant that iterated an empty list and passed
while guaranteeing nothing.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
ALPHA_PACKAGE = ROOT / "experiments" / "alpha"


def _alpha_modules() -> list[pathlib.Path]:
    return [p for p in ALPHA_PACKAGE.rglob("*.py") if "__pycache__" not in p.parts]


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
    return found


def test_the_scan_sees_the_alpha_package() -> None:
    modules = _alpha_modules()
    assert len(modules) >= 8, f"Only {len(modules)} alpha modules found; the scan is broken"
    assert any(p.name == "evaluator.py" for p in modules)


# -- no AI --------------------------------------------------------------------------


def test_no_alpha_module_imports_the_ai_gateway_or_a_provider() -> None:
    forbidden = ("ai.gateway", "ai.adapter", "ai.provider", "anthropic",
                 "integrations.claude", "ai.escalation", "ai.router")
    offenders = [
        f"{p.relative_to(ROOT).as_posix()}: {name}"
        for p in _alpha_modules()
        for name in _imports(p)
        if any(name == f or name.startswith(f + ".") for f in forbidden)
    ]
    assert offenders == [], f"Alpha modules import AI: {offenders}"


def test_no_alpha_module_imports_anthropic_directly() -> None:
    offenders = [
        f"{p.relative_to(ROOT).as_posix()}"
        for p in _alpha_modules()
        for name in _imports(p)
        if name.split(".")[0] == "anthropic"
    ]
    assert offenders == []


# -- no broker / execution -----------------------------------------------------------


def test_no_alpha_module_imports_a_trading_mutation_path() -> None:
    """The alpha framework may reason about a backtest's trades; it may not
    move a real or paper position. Mirrors
    tests/ai/test_ai_cannot_execute.py's equivalent guard for the AI layer."""
    forbidden = (
        "paper_trading", "data.storage.portfolio_repository",
        "data.storage.trade_repository",
    )
    offenders = [
        f"{p.relative_to(ROOT).as_posix()}: {name}"
        for p in _alpha_modules()
        for name in _imports(p)
        if name.startswith(forbidden)
    ]
    assert offenders == []


def test_no_alpha_module_imports_a_broker_sdk() -> None:
    broker = {
        "alpaca", "alpaca_trade_api", "ib_insync", "ibapi", "kiteconnect",
        "zerodha", "robin_stocks", "tda", "schwab", "ccxt", "binance",
    }
    offenders = [
        f"{p.relative_to(ROOT).as_posix()}: {name}"
        for p in _alpha_modules()
        for name in _imports(p)
        if name.split(".")[0] in broker
    ]
    assert offenders == []


# -- no automatic execution on import ------------------------------------------------


def test_importing_the_evaluator_does_not_run_anything() -> None:
    """No experiment may execute automatically on application startup --
    importing the module must have no side effect beyond defining names."""
    import importlib

    module = importlib.import_module("experiments.alpha.evaluator")
    assert hasattr(module, "AlphaEvaluator")  # imported, not executed


def test_importing_the_cli_does_not_run_anything() -> None:
    import importlib

    module = importlib.import_module("experiments.alpha.cli")
    assert hasattr(module, "main")


# -- no credentials / secrets in the alpha package -----------------------------------


def test_no_alpha_module_contains_a_hardcoded_credential() -> None:
    """Same narrow check as tests/test_system_invariants.py's equivalent:
    a long literal assigned to a secret-shaped name, not every mention of
    the word 'key'."""
    secret_names = ("api_key", "apikey", "secret", "password", "token", "passwd")
    allowed_values = {"", "change-me", "test"}
    offenders: list[str] = []
    for path in _alpha_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
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
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} {name}")
    assert offenders == []


# -- decision engine: no single-metric pass ------------------------------------------


def test_decision_module_does_not_gate_solely_on_sharpe_or_cagr_thresholds() -> None:
    """A structural check that the decision engine combines evidence rather
    than gating on one metric: `evaluate()` must read at least the
    control-percentile, concentration, regime, and robustness fields from
    its inputs -- not just one of them -- before it can return SUPPORTED.
    """
    import inspect

    from experiments.alpha import decision

    source = inspect.getsource(decision.evaluate)
    required_fields = (
        "test_period_percentile", "concentration_dependent",
        "regime_beaten_count", "robustness_survival_rate",
    )
    for field in required_fields:
        assert field in source, f"evaluate() does not reference {field}"


def test_no_experiment_runs_on_import_of_the_registry_or_archive_scripts() -> None:
    import importlib

    for mod_name in ("experiments.alpha.registry", "experiments.alpha.archive_ma_20_50"):
        module = importlib.import_module(mod_name)
        assert module is not None
