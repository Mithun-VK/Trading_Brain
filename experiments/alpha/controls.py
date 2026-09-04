"""V5 — mandatory controls.

Every alpha candidate gets a buy-and-hold benchmark, a matched random-entry
control, and a concentration analysis at minimum (per the phase brief's
control matrix); walk-forward and regime controls live in their own modules
because they are substantial enough to warrant one.

This module adds nothing new to concentration analysis --
`experiments.trade_analysis.concentration` and `.by_ticker` already do the
real work, built and tested in V4. What is new here is the **verdict**:
whether removing the largest contributor(s) collapses the result, which
V4.1 did by hand for MA 20/50 and this module makes a reusable, automatic
check for any future hypothesis.
"""

from __future__ import annotations

from dataclasses import dataclass

from experiments import trade_analysis
from experiments.trade_analysis import TradeRecord

# Below this relative Sharpe retention, removing the top contributor(s) is
# reported as collapsing the result, not merely weakening it. Chosen before
# any hypothesis in this framework has been evaluated, per the same
# materiality-floor discipline used in V4's regime decomposition.
COLLAPSE_RETENTION_THRESHOLD = 0.5


@dataclass(frozen=True)
class ConcentrationVerdict:
    """Whether the result survives removing its biggest contributor(s).

    `full_sharpe`/`without_top_sharpe` are supplied by the caller (the
    evaluator re-runs the strategy on the reduced universe through the
    same engine) -- this module does not itself run a backtest.
    """

    total_pnl: float
    top_1_share: float | None
    top_3_share: float | None
    top_5_share: float | None
    top_contributor: str | None
    top_contributor_share: float | None
    full_sharpe: float | None
    sharpe_excluding_top: float | None
    sharpe_retention: float | None  # sharpe_excluding_top / full_sharpe
    concentration_dependent: bool
    reason: str

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def analyze(
    records: list[TradeRecord],
    *,
    full_sharpe: float | None,
    sharpe_excluding_top: float | None,
) -> ConcentrationVerdict:
    """Combine V4's concentration primitives with a pass/fail verdict.

    `full_sharpe` and `sharpe_excluding_top` come from two actual backtest
    runs (full universe, and the universe minus its largest P&L
    contributor) -- this function only interprets them, so the verdict is
    always about a number the engine produced, never an estimate.
    """
    conc = trade_analysis.concentration(records)
    by_ticker = trade_analysis.by_ticker(records)
    top_3 = top_n_share(records, 3)

    top_contributor = None
    top_contributor_share = None
    if by_ticker and conc.get("total_pnl"):
        top_contributor = max(by_ticker, key=lambda t: by_ticker[t]["total_pnl"])
        total = conc["total_pnl"]
        top_contributor_share = (
            round(by_ticker[top_contributor]["total_pnl"] / total, 4) if total else None
        )

    retention = None
    if full_sharpe is not None and sharpe_excluding_top is not None and full_sharpe != 0:
        retention = round(sharpe_excluding_top / full_sharpe, 4)

    dependent = False
    reasons: list[str] = []
    if retention is not None and retention < COLLAPSE_RETENTION_THRESHOLD:
        dependent = True
        reasons.append(
            f"Sharpe retains only {retention:.0%} of its value with the top "
            f"contributor removed (below the {COLLAPSE_RETENTION_THRESHOLD:.0%} floor)."
        )
    if sharpe_excluding_top is not None and sharpe_excluding_top <= 0 and (
        full_sharpe is not None and full_sharpe > 0
    ):
        dependent = True
        reasons.append("Sharpe turns non-positive once the top contributor is removed.")
    if top_contributor_share is not None and top_contributor_share > 0.5:
        dependent = True
        reasons.append(
            f"{top_contributor} alone supplies {top_contributor_share:.0%} of total P&L."
        )

    reason = "; ".join(reasons) if reasons else (
        "Result is not concentration-dependent on the single largest contributor."
    )

    return ConcentrationVerdict(
        total_pnl=conc.get("total_pnl", 0.0),
        top_1_share=conc.get("top_1_share_of_pnl"),
        top_3_share=top_3,
        top_5_share=conc.get("top_5_share_of_pnl"),
        top_contributor=top_contributor,
        top_contributor_share=top_contributor_share,
        full_sharpe=full_sharpe,
        sharpe_excluding_top=sharpe_excluding_top,
        sharpe_retention=retention,
        concentration_dependent=dependent,
        reason=reason,
    )


def top_n_share(records: list[TradeRecord], n: int) -> float | None:
    """P&L share of the top-n trades by size -- generalises V4's
    top-1/top-5/top-10 to an arbitrary n (top-3, per this phase's brief)."""
    if not records:
        return None
    pnls = sorted((r.pnl for r in records), reverse=True)
    total = sum(pnls)
    if total == 0 or n > len(pnls):
        return None
    return round(sum(pnls[:n]) / total, 4)
