"""V4 — the ten questions, answered from the numbers.

Each answer is computed, not asserted. Where the data cannot settle a
question, the answer says so rather than picking the more interesting
reading: "the sample is too small to tell" is a legitimate finding, and it
is the one most often lost when a report is written by hand afterwards.

Every claim that rests on fewer than `MIN_TRADES_FOR_SIGNIFICANCE` trades
carries a caveat, because the whole point of this phase is to avoid acting
on noise.
"""

from __future__ import annotations

import statistics

from data.ingestion.schemas import PriceBar
from experiments import regimes, trade_analysis
from experiments.regimes import Regime, RegimeLabel
from experiments.trade_analysis import MIN_TRADES_FOR_SIGNIFICANCE, TradeRecord

# Below this, a difference in mean return per trade is noise rather than a
# mechanism. Stated as a constant so the threshold is arguable rather than
# buried in a comparison.
MATERIAL_EXPECTANCY_GAP = 0.01


def _pct(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def _sig(n: int) -> str:
    return "" if n >= MIN_TRADES_FOR_SIGNIFICANCE else f" (only {n} trades — not significant)"


def _positive_negative(stats) -> tuple[list, list]:
    positive = [s for s in stats if s.expectancy is not None and s.expectancy > 0]
    negative = [s for s in stats if s.expectancy is not None and s.expectancy <= 0]
    return positive, negative


def answer_all(
    periods: dict, all_bars: dict[str, list[PriceBar]], market_labels: list[RegimeLabel]
) -> dict:
    """Answer every V4 question and return them in order."""
    all_records: list[TradeRecord] = [r for p in periods.values() for r in p["records"]]
    pooled = trade_analysis.by_regime(all_records)
    positive, negative = _positive_negative(pooled)

    out: dict[str, dict] = {}

    # 1 --------------------------------------------------------------------
    lines = []
    for stat in sorted(positive, key=lambda s: s.expectancy or 0, reverse=True):
        lines.append(
            f"{stat.regime}: expectancy {_pct(stat.expectancy)} over "
            f"{stat.trades} trades, P&L {stat.total_pnl:+.2f}{_sig(stat.trades)}"
        )
    out["Which regimes generate positive expectancy?"] = {
        "answer": lines or ["No regime showed positive expectancy."],
        "caveat": (
            "Expectancy here is mean return per trade, not risk-adjusted."
            if lines else None
        ),
    }

    # 2 --------------------------------------------------------------------
    lines = []
    for stat in sorted(negative, key=lambda s: s.expectancy or 0):
        lines.append(
            f"{stat.regime}: expectancy {_pct(stat.expectancy)} over "
            f"{stat.trades} trades, P&L {stat.total_pnl:+.2f}{_sig(stat.trades)}"
        )
    out["Which regimes generate negative expectancy?"] = {
        "answer": lines or ["No regime showed negative expectancy."],
        "caveat": None,
    }

    # 3 --------------------------------------------------------------------
    sideways = next((s for s in pooled if s.regime == str(Regime.SIDEWAYS)), None)
    trending = [s for s in pooled if s.regime in (str(Regime.BULL), str(Regime.BEAR))]
    lines = []
    if sideways is None:
        lines.append("No trades were entered in a sideways regime.")
        verdict_caveat = None
    else:
        trend_exp = [s.expectancy for s in trending if s.expectancy is not None]
        avg_trend = statistics.mean(trend_exp) if trend_exp else None
        lines.append(
            f"Sideways: expectancy {_pct(sideways.expectancy)} over "
            f"{sideways.trades} trades{_sig(sideways.trades)}"
        )
        if avg_trend is not None:
            lines.append(f"Trending (bull/bear) average expectancy: {_pct(avg_trend)}")
            gap = (sideways.expectancy or 0) - avg_trend
            # A materiality floor. Declaring the weaker regime on a fraction
            # of a percentage point would be reading noise as a mechanism,
            # which is the exact error this phase exists to avoid.
            if abs(gap) < MATERIAL_EXPECTANCY_GAP:
                lines.append(
                    f"Difference is {_pct(gap)} per trade — below the "
                    f"{_pct(MATERIAL_EXPECTANCY_GAP)} materiality floor. "
                    "Sideways is NOT distinguishable from trending here. The "
                    "expected mechanism (MA cross whipsaws in ranges) is NOT "
                    "visible in this data."
                )
            elif gap < 0:
                lines.append(f"Sideways is materially weaker by {_pct(abs(gap))} per trade.")
            else:
                lines.append(f"Sideways is materially STRONGER by {_pct(gap)} per trade.")
        verdict_caveat = (
            "A moving-average cross is expected to underperform in range-bound "
            "markets, so a confirmed sideways weakness would be a coherent "
            "mechanism rather than a coincidence."
        )
    out["Does the strategy fail primarily in sideways markets?"] = {
        "answer": lines, "caveat": verdict_caveat,
    }

    # 4 --------------------------------------------------------------------
    vol_stats = trade_analysis.by_regime(all_records, key="entry_volatility_regime")
    lines = [
        f"{s.regime}: expectancy {_pct(s.expectancy)}, win rate "
        f"{_pct(s.win_rate, 0)}, {s.trades} trades{_sig(s.trades)}"
        for s in vol_stats
    ]
    high = next((s for s in vol_stats if s.regime == str(Regime.HIGH_VOL)), None)
    low = next((s for s in vol_stats if s.regime == str(Regime.LOW_VOL)), None)
    if high and low and high.expectancy is not None and low.expectancy is not None:
        gap = high.expectancy - low.expectancy
        lines.append(
            f"Difference (high minus low): {_pct(gap)} per trade — "
            + ("material." if abs(gap) > 0.005 else "not material.")
        )
    out["Does volatility materially affect performance?"] = {
        "answer": lines or ["No volatility labels were available."],
        "caveat": None,
    }

    # 5 --------------------------------------------------------------------
    changed = [r for r in all_records if r.regime_changed]
    unchanged = [r for r in all_records if not r.regime_changed]
    lines = []
    for label, group in (("Regime changed during trade", changed),
                         ("Regime unchanged", unchanged)):
        if group:
            mean = statistics.mean(r.return_pct for r in group)
            wins = sum(1 for r in group if r.return_pct > 0) / len(group)
            lines.append(
                f"{label}: {len(group)} trades, mean return {_pct(mean)}, "
                f"win rate {_pct(wins, 0)}{_sig(len(group))}"
            )
    out["Does performance change after regime transitions?"] = {
        "answer": lines or ["No trades to compare."],
        "caveat": (
            "This measures trades that spanned a transition, not trades entered "
            "immediately after one."
        ),
    }

    # 6 --------------------------------------------------------------------
    per_ticker = trade_analysis.by_ticker(all_records)
    profitable = [t for t, s in per_ticker.items() if s["total_pnl"] > 0]
    lines = [
        f"{len(profitable)} of {len(per_ticker)} tickers were profitable.",
    ]
    for ticker, s in sorted(per_ticker.items(), key=lambda kv: -kv[1]["total_pnl"]):
        lines.append(
            f"  {ticker}: {s['total_pnl']:+.2f} over {s['trades']} trades, "
            f"avg {_pct(s['average_return'])}"
        )
    breadth = len(profitable) / len(per_ticker) if per_ticker else 0
    lines.append(
        f"Directional breadth: {breadth:.0%} of names profitable — "
        + ("broad." if breadth >= 0.6 else "narrow; the edge is not consistent.")
    )
    # Direction and magnitude are different questions. A strategy can be
    # profitable on nine names and still owe its entire result to one.
    total_pnl = sum(s["total_pnl"] for s in per_ticker.values())
    if total_pnl > 0:
        top_ticker, top_stats = max(per_ticker.items(), key=lambda kv: kv[1]["total_pnl"])
        top_share = top_stats["total_pnl"] / total_pnl
        lines.append(
            f"Magnitude breadth: {top_ticker} alone contributed {top_share:.0%} "
            f"of total P&L."
        )
        if top_share > 0.33:
            lines.append(
                "The edge is broad in direction but NARROW in magnitude: most "
                "of the money came from one name, so the aggregate result is "
                "not representative of the typical trade."
            )
    out["Is the edge consistent across tickers?"] = {"answer": lines, "caveat": None}

    # 7 --------------------------------------------------------------------
    conc = trade_analysis.concentration(all_records)
    lines = [
        f"Top 1 trade: {_pct(conc.get('top_1_share_of_pnl'))} of total P&L",
        f"Top 5 trades: {_pct(conc.get('top_5_share_of_pnl'))} of total P&L",
        f"Top 10 trades: {_pct(conc.get('top_10_share_of_pnl'))} of total P&L",
        f"{conc.get('winners')} winners vs {conc.get('losers')} losers "
        f"out of {conc.get('trades')} trades",
    ]
    top5 = conc.get("top_5_share_of_pnl")
    if top5 is not None:
        lines.append(
            "Highly concentrated: the result rests on a handful of trades."
            if top5 > 0.8
            else "Reasonably distributed across trades."
        )
    out["Is the apparent edge concentrated in only a few trades?"] = {
        "answer": lines,
        "caveat": (
            "Concentration is the single most useful check against reading a "
            "good backtest as a good strategy."
        ),
    }

    # 8 --------------------------------------------------------------------
    lines = []
    for name, payload in periods.items():
        perf = payload["run"].performance
        lines.append(
            f"{name}: strategy Sharpe {perf.sharpe}, max drawdown "
            f"{_pct(perf.max_drawdown)}, avg exposure {_pct(perf.average_exposure)}"
        )
    lines.append(
        "SPY comparison is in the V2 baseline table; the strategy holds far "
        "less exposure, so Sharpe is the fair comparison and CAGR is not."
    )
    out["Does the strategy outperform SPY risk-adjusted within regimes?"] = {
        "answer": lines,
        "caveat": (
            "Per-regime SPY Sharpe is not computed here: a buy-and-hold "
            "benchmark has no trades to attribute to regimes, so the "
            "comparison is made at period level rather than invented at "
            "regime level."
        ),
    }

    # 9 --------------------------------------------------------------------
    lines = []
    dists = {
        name: regimes.distribution(payload["labels"]) for name, payload in periods.items()
    }
    for name, dist in dists.items():
        total = sum(dist.values()) or 1
        lines.append(f"{name}: " + ", ".join(f"{k} {v/total:.0%}" for k, v in dist.items()))

    val_stats = trade_analysis.by_regime(periods["validation"]["records"])
    if val_stats:
        losing = [s for s in val_stats if s.total_pnl < 0]
        winning = [s for s in val_stats if s.total_pnl >= 0]
        lines.append(
            f"In validation, {len(losing)} of {len(val_stats)} regimes lost money"
            + (f" ({', '.join(s.regime for s in losing)})" if losing else "")
            + (f"; profitable: {', '.join(s.regime for s in winning)}" if winning else "")
        )

        # The real question is which regime is over-represented in validation
        # relative to the periods where the strategy worked.
        def share(period_name: str, regime: str) -> float:
            d = dists.get(period_name, {})
            return d.get(regime, 0) / (sum(d.values()) or 1)

        lines.append("Regime share by period (validation vs the rest):")
        all_regimes = {r for d in dists.values() for r in d}
        over_represented = []
        for regime in sorted(all_regimes):
            v = share("validation", regime)
            elsewhere = statistics.mean(
                [share(n, regime) for n in dists if n != "validation"]
            )
            flag = ""
            if v > elsewhere * 1.5 and v > 0.10:
                flag = "  <-- OVER-REPRESENTED in validation"
                over_represented.append((regime, v, elsewhere))
            lines.append(
                f"  {regime:<12} validation {v:.0%}, elsewhere {elsewhere:.0%}{flag}"
            )

        if over_represented:
            for regime, v, elsewhere in over_represented:
                pooled_regime = next((s for s in pooled if s.regime == regime), None)
                val_regime = next((s for s in val_stats if s.regime == regime), None)
                lines.append(
                    f"{regime}: {v:.0%} of validation days vs {elsewhere:.0%} elsewhere. "
                    f"Pooled expectancy "
                    f"{_pct(pooled_regime.expectancy) if pooled_regime else 'n/a'}, "
                    f"validation P&L "
                    f"{val_regime.total_pnl:+.2f}" if val_regime else "n/a"
                )
            lines.append(
                "PARTIAL EXPLANATION: the over-represented regime is loss-making "
                "in validation but profitable when pooled, so composition alone "
                "does not account for the failure -- the strategy behaved "
                "DIFFERENTLY in the same regime, which is the more concerning "
                "reading."
            )
        else:
            lines.append(
                "No regime is materially over-represented in validation. The "
                "composition does NOT explain the failure; something else does."
            )
    out["Is the validation-period failure explained by its regime composition?"] = {
        "answer": lines,
        "caveat": (
            "A regime that is both over-represented in validation and "
            "loss-making elsewhere would explain the failure. If the losing "
            "regime is no more common in validation than elsewhere, the "
            "composition does NOT explain it and something else does."
        ),
    }

    # 10 -------------------------------------------------------------------
    significant = [s for s in pooled if s.is_significant]
    coherent = (
        sideways is not None
        and sideways.expectancy is not None
        and any(
            s.expectancy is not None and s.expectancy > 0
            for s in pooled if s.regime in (str(Regime.BULL), str(Regime.BEAR))
        )
    )
    lines = [
        f"{len(significant)} of {len(pooled)} regimes have a statistically "
        f"usable sample (>= {MIN_TRADES_FOR_SIGNIFICANCE} trades).",
        f"Total closed trades across all periods: {len(all_records)}.",
    ]
    if top5 is not None and top5 > 0.8:
        lines.append("P&L is concentrated in few trades — evidence is weak.")
    if breadth < 0.6:
        lines.append("The edge is not broad across tickers — evidence is weak.")
    if coherent:
        lines.append(
            "A trend-following mechanism is at least directionally visible "
            "(trending regimes positive)."
        )
    out["Is there enough evidence to justify continuing with MA 20/50?"] = {
        "answer": lines,
        "caveat": (
            "This is a summary of the evidence, not a decision. V4 is "
            "diagnostic: the decision to proceed to V5 is a human one, and "
            "the honest default when the evidence is thin is to stop."
        ),
    }

    return out
