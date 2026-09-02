"""Signal rules.

Each rule inspects a `SignalContext` and either returns a signal or None.
Rules are ordered by severity in `engine.py`; a rule only fires when its
conditions genuinely hold, and every condition it consulted is recorded as
evidence -- including the ones that argued *against* firing, and the ones it
could not evaluate.

Recording contradicting and unknown evidence is the point. A signal that
only lists what supports it is advocacy, not analysis.
"""

from __future__ import annotations

import datetime as dt

from brain.signals.context import SignalContext
from brain.signals.schemas import (
    Evidence,
    EvidenceKind,
    EvidenceStance,
    GeneratedSignal,
    SignalCategory,
    build_signal,
)

# Thresholds. Configuration, not magic numbers scattered through the rules.
THESIS_STALE_DAYS = 45
RESEARCH_QUEUE_TRIGGER_SCORE = 0.6
ACCEPTABLE_PE = 35.0
DRAWDOWN_EXIT_REVIEW = -0.20
RSI_OVERBOUGHT = 75.0


def _align(value: dt.datetime, reference: dt.datetime) -> dt.datetime:
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value


def _regime_evidence(context: SignalContext, wanted_trend: str) -> Evidence:
    if context.regime is None:
        return Evidence(
            kind=EvidenceKind.REGIME,
            detail="No market regime observation on record.",
            stance=EvidenceStance.UNKNOWN,
        )
    trend = context.regime.regime
    return Evidence(
        kind=EvidenceKind.REGIME,
        detail=f"Market trend regime is {trend} (descriptive, not predictive).",
        stance=(
            EvidenceStance.SUPPORTS if trend == wanted_trend else EvidenceStance.CONTRADICTS
        ),
        value=trend,
    )


def thesis_review_rule(context: SignalContext) -> GeneratedSignal | None:
    """A thesis that is weakened, invalidated, or long unreviewed."""
    thesis = context.thesis
    if thesis is None:
        return None

    assessment = thesis.current_assessment
    evidence: list[Evidence] = []

    if assessment in ("THESIS_INVALIDATED", "THESIS_WEAKENED"):
        evidence.append(
            Evidence(
                kind=EvidenceKind.THESIS,
                detail=f"Thesis '{thesis.title}' is currently {assessment}.",
                value=assessment,
            )
        )
        reasoning = (
            f"The active thesis is {assessment}; its conclusions should be "
            "re-examined before any further action."
        )
    else:
        last_reviewed = thesis.last_reviewed_at
        days = (
            THESIS_STALE_DAYS + 1
            if last_reviewed is None
            else (context.now - _align(last_reviewed, context.now)).days
        )
        if days <= THESIS_STALE_DAYS:
            return None
        evidence.append(
            Evidence(
                kind=EvidenceKind.THESIS,
                detail=f"Thesis '{thesis.title}' has not been reviewed in {days} days.",
                value=float(days),
            )
        )
        reasoning = "An intact but long-unreviewed thesis is itself a risk."

    if context.is_held:
        evidence.append(
            Evidence(
                kind=EvidenceKind.POSITION,
                detail="A paper position is open against this thesis.",
            )
        )

    return build_signal(
        asset_id=context.asset.id,
        ticker=context.ticker,
        category=SignalCategory.THESIS_REVIEW,
        reasoning=reasoning,
        evidence=evidence,
        rule="thesis_review",
    )


def exit_review_rule(context: SignalContext) -> GeneratedSignal | None:
    """A held position whose original premise may no longer hold.

    Names a *review*, not a sale: the human decides what to do (Rule 7).
    """
    if not context.is_held:
        return None

    evidence: list[Evidence] = []
    triggers = 0

    thesis = context.thesis
    if thesis is not None and thesis.current_assessment == "THESIS_INVALIDATED":
        triggers += 1
        evidence.append(
            Evidence(
                kind=EvidenceKind.THESIS,
                detail="The thesis behind this position is invalidated.",
                value="THESIS_INVALIDATED",
            )
        )

    position = context.position
    assert position is not None
    average_cost = float(position.average_cost)
    last_close = context.quant.last_close
    if last_close is not None and average_cost > 0:
        move = last_close / average_cost - 1
        if move <= DRAWDOWN_EXIT_REVIEW:
            triggers += 1
            evidence.append(
                Evidence(
                    kind=EvidenceKind.POSITION,
                    detail=f"Position is {move:.1%} below average cost.",
                    value=round(move, 4),
                )
            )
        else:
            evidence.append(
                Evidence(
                    kind=EvidenceKind.POSITION,
                    detail=f"Position is {move:.1%} versus average cost.",
                    stance=EvidenceStance.CONTRADICTS,
                    value=round(move, 4),
                )
            )
    else:
        evidence.append(
            Evidence(
                kind=EvidenceKind.POSITION,
                detail="No current price available to value this position.",
                stance=EvidenceStance.UNKNOWN,
            )
        )

    above_trend = context.quant.above_long_trend
    if above_trend is False:
        triggers += 1
        evidence.append(
            Evidence(
                kind=EvidenceKind.QUANT,
                detail="Price is below its 200-period moving average.",
                value=context.quant.sma_200,
            )
        )
    elif above_trend is None:
        evidence.append(
            Evidence(
                kind=EvidenceKind.QUANT,
                detail="Insufficient history for a 200-period trend reference.",
                stance=EvidenceStance.UNKNOWN,
            )
        )

    if triggers == 0:
        return None

    return build_signal(
        asset_id=context.asset.id,
        ticker=context.ticker,
        category=SignalCategory.EXIT_REVIEW,
        reasoning=(
            "The premise for holding this position may no longer hold. "
            "Review the exit decision -- this is not an instruction to sell."
        ),
        evidence=evidence,
        rule="exit_review",
    )


def reduce_rule(context: SignalContext) -> GeneratedSignal | None:
    """Held, thesis still intact, but conditions have deteriorated."""
    if not context.is_held:
        return None

    thesis = context.thesis
    if thesis is not None and thesis.current_assessment in (
        "THESIS_INVALIDATED",
        "THESIS_WEAKENED",
    ):
        # A broken thesis is an EXIT_REVIEW/THESIS_REVIEW matter, not a trim.
        return None

    evidence: list[Evidence] = []
    triggers = 0

    if context.regime is not None:
        if context.regime.risk_regime == "RISK_OFF":
            triggers += 1
            evidence.append(
                Evidence(
                    kind=EvidenceKind.REGIME,
                    detail="Market risk regime is RISK_OFF.",
                    value="RISK_OFF",
                )
            )
        if context.regime.regime == "BEARISH":
            triggers += 1
            evidence.append(
                Evidence(
                    kind=EvidenceKind.REGIME,
                    detail="Market trend regime is BEARISH.",
                    value="BEARISH",
                )
            )
    else:
        evidence.append(
            Evidence(
                kind=EvidenceKind.REGIME,
                detail="No market regime observation on record.",
                stance=EvidenceStance.UNKNOWN,
            )
        )

    momentum = context.quant.momentum_20d
    if momentum is not None and momentum < 0:
        triggers += 1
        evidence.append(
            Evidence(
                kind=EvidenceKind.QUANT,
                detail=f"20-period momentum is negative ({momentum:.1%}).",
                value=round(momentum, 4),
            )
        )
    elif momentum is None:
        evidence.append(
            Evidence(
                kind=EvidenceKind.QUANT,
                detail="Insufficient history for a momentum reading.",
                stance=EvidenceStance.UNKNOWN,
            )
        )

    if triggers == 0:
        return None

    if thesis is not None:
        evidence.append(
            Evidence(
                kind=EvidenceKind.THESIS,
                detail=f"Thesis remains {thesis.current_assessment}.",
                stance=EvidenceStance.CONTRADICTS,
                value=thesis.current_assessment,
            )
        )

    return build_signal(
        asset_id=context.asset.id,
        ticker=context.ticker,
        category=SignalCategory.REDUCE,
        reasoning=(
            "Conditions have deteriorated while the thesis is still intact. "
            "Consider whether position size remains appropriate."
        ),
        evidence=evidence,
        rule="reduce",
    )


def accumulate_rule(context: SignalContext) -> GeneratedSignal | None:
    """The spec's worked example:

        thesis intact + bullish regime + positive momentum + acceptable
        valuation  ->  ACCUMULATE

    All four are required. Valuation that is *unknown* does not block the
    signal but is recorded as unknown evidence, which lowers confidence --
    a missing number must never read as a passing grade (Rule 4).
    """
    thesis = context.thesis
    if thesis is None or thesis.current_assessment not in (
        "THESIS_INTACT",
        "THESIS_STRENGTHENED",
    ):
        return None

    if context.regime is None or context.regime.regime != "BULLISH":
        return None

    if context.quant.positive_momentum is not True:
        return None

    pe = context.pe_ratio
    if pe is not None and pe > ACCEPTABLE_PE:
        return None

    evidence = [
        Evidence(
            kind=EvidenceKind.THESIS,
            detail=f"Thesis '{thesis.title}' is {thesis.current_assessment}.",
            value=thesis.current_assessment,
        ),
        _regime_evidence(context, "BULLISH"),
        Evidence(
            kind=EvidenceKind.QUANT,
            detail=f"20-period momentum is positive ({context.quant.momentum_20d:.1%}).",
            value=round(context.quant.momentum_20d or 0.0, 4),
        ),
    ]

    if pe is None:
        evidence.append(
            Evidence(
                kind=EvidenceKind.VALUATION,
                detail="No P/E on record; valuation could not be assessed.",
                stance=EvidenceStance.UNKNOWN,
            )
        )
    else:
        evidence.append(
            Evidence(
                kind=EvidenceKind.VALUATION,
                detail=f"P/E of {pe:.1f} is within the acceptable threshold "
                f"({ACCEPTABLE_PE:.0f}).",
                value=pe,
            )
        )

    rsi_value = context.quant.rsi_14
    if rsi_value is not None and rsi_value > RSI_OVERBOUGHT:
        evidence.append(
            Evidence(
                kind=EvidenceKind.QUANT,
                detail=f"RSI(14) of {rsi_value:.0f} is extended.",
                stance=EvidenceStance.CONTRADICTS,
                value=round(rsi_value, 2),
            )
        )

    return build_signal(
        asset_id=context.asset.id,
        ticker=context.ticker,
        category=SignalCategory.ACCUMULATE,
        reasoning=(
            "Thesis intact, bullish regime, positive momentum and no valuation "
            "objection. Consider whether adding fits your plan -- this is not "
            "an instruction to buy."
        ),
        evidence=evidence,
        rule="accumulate",
    )


def research_rule(context: SignalContext) -> GeneratedSignal | None:
    """A high-priority item is already queued by the research intelligence."""
    if not context.queue_entries:
        return None

    top = context.queue_entries[0]
    if float(top.score) < RESEARCH_QUEUE_TRIGGER_SCORE:
        return None

    evidence = [
        Evidence(
            kind=EvidenceKind.RESEARCH,
            detail=(
                f"Research queue entry '{top.change_type}' scored "
                f"{float(top.score):.2f}."
            ),
            value=round(float(top.score), 4),
        )
    ]
    for reason in list(top.reasons or [])[:4]:
        evidence.append(
            Evidence(kind=EvidenceKind.RESEARCH, detail=str(reason))
        )

    return build_signal(
        asset_id=context.asset.id,
        ticker=context.ticker,
        category=SignalCategory.RESEARCH,
        reasoning="A high-priority change was detected and is awaiting research.",
        evidence=evidence,
        rule="research",
    )


def watch_rule(context: SignalContext) -> GeneratedSignal | None:
    """Lowest-severity fallback: something tracked is worth an eye on."""
    if not (context.is_watched or context.is_held):
        return None

    evidence: list[Evidence] = []

    if context.is_watched:
        evidence.append(
            Evidence(kind=EvidenceKind.RESEARCH, detail="Asset is on a watchlist.")
        )
    if context.is_held:
        evidence.append(
            Evidence(kind=EvidenceKind.POSITION, detail="A paper position is open.")
        )

    if context.latest_research is None:
        evidence.append(
            Evidence(
                kind=EvidenceKind.RESEARCH,
                detail="No research document on record for this asset.",
                stance=EvidenceStance.UNKNOWN,
            )
        )

    if context.regime is not None:
        evidence.append(
            Evidence(
                kind=EvidenceKind.REGIME,
                detail=(
                    f"Current regime: {context.regime.regime} / "
                    f"{context.regime.volatility_regime} / {context.regime.risk_regime}."
                ),
                value=context.regime.regime,
            )
        )

    if context.quant.last_close is None:
        evidence.append(
            Evidence(
                kind=EvidenceKind.QUANT,
                detail="No price history stored for this asset.",
                stance=EvidenceStance.UNKNOWN,
            )
        )

    return build_signal(
        asset_id=context.asset.id,
        ticker=context.ticker,
        category=SignalCategory.WATCH,
        reasoning="Tracked asset with nothing more urgent flagged.",
        evidence=evidence,
        rule="watch",
    )


# Ordered most severe first. The engine takes the first rule that fires,
# so a broken thesis is never reported as a routine WATCH.
RULES = (
    thesis_review_rule,
    exit_review_rule,
    reduce_rule,
    accumulate_rule,
    research_rule,
    watch_rule,
)
