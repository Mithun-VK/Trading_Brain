"""Event-driven escalation (Phase 42).

The property under test is a negative one: the gate's default answer is
*no*. Most of these tests assert that a plausible-looking event does NOT
buy a frontier call, because that is the direction this system fails in --
an escalation policy that quietly says yes to everything costs money while
looking like governance.
"""

from __future__ import annotations

import datetime as dt

import pytest

from ai.escalation import (
    MATERIALITY_THRESHOLD,
    NON_ESCALATING,
    THESIS_MATERIALITY_THRESHOLD,
    EscalationOutcome,
    TriggerKind,
    evaluate,
    evaluate_all,
)
from ai.schemas import AITier, RiskClass
from brain.research.change_detection import ChangeType, DetectedChange

NOW = dt.datetime(2026, 3, 15, 12, 0, tzinfo=dt.UTC)


def _change(change_type: ChangeType, magnitude: float = 0.9) -> DetectedChange:
    return DetectedChange(
        asset_id=1,
        ticker="AAPL",
        change_type=change_type,
        magnitude=magnitude,
        detected_at=NOW,
        detail={"note": "fixture"},
    )


# -- the refusals ---------------------------------------------------------------


@pytest.mark.parametrize("change_type", sorted(NON_ESCALATING))
def test_quantitative_events_never_escalate_however_large(change_type) -> None:
    """A price shock at maximum magnitude is still a price shock.

    The deterministic layer already reports it; a language model would only
    restate it more expensively.
    """
    trigger = evaluate(_change(change_type, magnitude=1.0))

    assert trigger.outcome is EscalationOutcome.DETERMINISTIC_ONLY
    assert not trigger.escalate
    assert trigger.tier is None


def test_an_immaterial_change_is_recorded_but_not_escalated() -> None:
    trigger = evaluate(_change(ChangeType.EARNINGS_RELEASE, magnitude=0.2))

    assert trigger.outcome is EscalationOutcome.NO_ACTION
    assert not trigger.escalate
    assert "below the" in trigger.reason


def test_the_threshold_is_a_real_boundary() -> None:
    """Just under does not escalate; at the threshold does. Guards against
    the check being written with the wrong comparison."""
    under = evaluate(_change(ChangeType.EARNINGS_RELEASE, MATERIALITY_THRESHOLD - 0.01))
    at = evaluate(_change(ChangeType.EARNINGS_RELEASE, MATERIALITY_THRESHOLD))

    assert not under.escalate
    assert at.escalate


def test_a_refusal_still_explains_itself() -> None:
    """A declined escalation must be visible as a decision, not as an
    absence of one -- otherwise 'we never called Claude' is indistinguishable
    from 'the gate silently broke'."""
    trigger = evaluate(_change(ChangeType.LARGE_MOVE))

    assert trigger.reason
    assert trigger.to_dict()["escalate"] is False


# -- the escalations ------------------------------------------------------------


def test_a_thesis_contradiction_goes_to_the_high_reasoning_tier() -> None:
    """The one event whose conclusion can invalidate a held position."""
    trigger = evaluate(_change(ChangeType.THESIS_VIOLATION, magnitude=0.8))

    assert trigger.kind is TriggerKind.THESIS_CONTRADICTION
    assert trigger.outcome is EscalationOutcome.FRONTIER_HIGH
    assert trigger.tier is AITier.FRONTIER_HIGH
    assert trigger.risk is RiskClass.HIGH


def test_a_thesis_contradiction_has_a_lower_bar_than_other_events() -> None:
    """Missing one is costlier than paying for one, so the bar is lower --
    but it is still a bar, not an open door."""
    magnitude = (THESIS_MATERIALITY_THRESHOLD + MATERIALITY_THRESHOLD) / 2

    assert evaluate(_change(ChangeType.THESIS_VIOLATION, magnitude)).escalate
    assert not evaluate(_change(ChangeType.EARNINGS_RELEASE, magnitude)).escalate
    assert not evaluate(
        _change(ChangeType.THESIS_VIOLATION, THESIS_MATERIALITY_THRESHOLD - 0.01)
    ).escalate


def test_a_material_earnings_release_reaches_the_standard_frontier_tier() -> None:
    trigger = evaluate(_change(ChangeType.EARNINGS_RELEASE, magnitude=0.9))

    assert trigger.outcome is EscalationOutcome.FRONTIER
    assert trigger.tier is AITier.FRONTIER


def test_contradictory_evidence_lifts_a_standard_event_to_high_reasoning() -> None:
    plain = evaluate(_change(ChangeType.EARNINGS_RELEASE, 0.9))
    conflicted = evaluate(_change(ChangeType.EARNINGS_RELEASE, 0.9), has_contradictions=True)

    assert plain.outcome is EscalationOutcome.FRONTIER
    assert conflicted.outcome is EscalationOutcome.FRONTIER_HIGH
    assert "contradict" in conflicted.reason


def test_an_unmapped_change_type_defaults_to_no_action() -> None:
    """Closed-set behaviour: adding a ChangeType does not silently grant it
    the ability to spend money."""
    unmapped = [
        c for c in ChangeType
        if c not in NON_ESCALATING and evaluate(_change(c)).kind is None
    ]
    for change_type in unmapped:
        assert evaluate(_change(change_type)).outcome is EscalationOutcome.NO_ACTION


# -- batch ----------------------------------------------------------------------


def test_evaluate_all_returns_refusals_too() -> None:
    """The suppressed calls are the operationally interesting half."""
    triggers = evaluate_all([
        _change(ChangeType.THESIS_VIOLATION, 0.9),
        _change(ChangeType.PRICE_SHOCK, 1.0),
        _change(ChangeType.EARNINGS_RELEASE, 0.1),
    ])

    assert len(triggers) == 3
    assert sum(1 for t in triggers if t.escalate) == 1


def test_evaluate_all_orders_by_materiality() -> None:
    triggers = evaluate_all([
        _change(ChangeType.EARNINGS_RELEASE, 0.7),
        _change(ChangeType.THESIS_VIOLATION, 0.95),
    ])

    assert triggers[0].materiality == 0.95


def test_an_empty_batch_is_not_an_error() -> None:
    assert evaluate_all([]) == []


# -- the property that matters most ---------------------------------------------


def test_escalation_cannot_invoke_a_model() -> None:
    """This module classifies; it does not call. Nothing here can spend
    money on its own, which is why it is safe to run over every detected
    change on every scan.

    Checked by parsing imports rather than grepping the text -- the prose in
    this file discusses the gateway at length, and a substring check would
    match its own docstring.
    """
    import ast
    import pathlib

    import ai.escalation as module

    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")

    forbidden = {"ai.gateway", "ai.adapter", "ai.provider", "anthropic"}
    assert not (imported & forbidden), f"escalation.py imports {imported & forbidden}"
