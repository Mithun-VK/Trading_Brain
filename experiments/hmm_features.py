"""Experiment 3 — HMM feature construction, causally.

Everything the HMM sees must be computable at bar t from bars 1..t and
nothing later. This module produces exactly that: a matrix of
market-level features, one row per bar, each row using only a trailing
window ending at that bar.

**What is deliberately excluded**, per the phase brief: no MA signal, no
crossover state, no trade outcome, no future return, no future drawdown, no
strategy P&L. The regime model must be able to describe the market on days
the MA strategy never traded, or it is not a model of the market -- it is a
restatement of the strategy's own history.

**Standardisation is the second place look-ahead hides.** Fitting a scaler
on the full 2016-2026 series and then using it to standardise 2017 values
means every 2017 z-score is computed against a standard deviation that
includes 2020's crash and 2023's rally -- information a 2017 observer did
not have. `causal_features` never computes a global mean or stdev; each
row's raw values are stored, and standardisation (when used) is fit only on
the training prefix at the point it is used, in `hmm_regime.py`.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from data.ingestion.schemas import PriceBar

FEATURE_NAMES = (
    "daily_return",
    "realised_vol_20d",
    "return_60d",
    "drawdown",
    "downside_vol_20d",
)


@dataclass(frozen=True)
class FeatureRow:
    date: dt.date
    values: tuple[float, ...]  # aligned to FEATURE_NAMES
    usable: bool  # False until every feature's lookback is satisfied

    def as_dict(self) -> dict[str, float]:
        return dict(zip(FEATURE_NAMES, self.values, strict=True))


def _log_returns(closes: list[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        out.append(math.log(cur / prev) if prev > 0 and cur > 0 else 0.0)
    return out


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var)


def causal_features(
    bars: list[PriceBar],
    *,
    vol_window: int = 20,
    momentum_window: int = 60,
) -> list[FeatureRow]:
    """Build the feature matrix as an explicit forward pass.

    Implemented as a loop over an expanding prefix rather than a vectorised
    rolling-window calculation, for the same reason `regimes.label_series`
    is: a vectorised rolling window is where a centred or backward-leaking
    window creeps in unnoticed. Each row here is built from
    `closes[:i+1]` alone.
    """
    ordered = sorted(bars, key=lambda b: b.ts)
    closes = [b.close for b in ordered]
    returns = _log_returns(closes)

    min_lookback = max(vol_window, momentum_window) + 1
    rows: list[FeatureRow] = []
    peak = float("-inf")

    for i, bar in enumerate(ordered):
        price = closes[i]
        peak = max(peak, price)
        drawdown = (price - peak) / peak if peak > 0 else 0.0

        usable = i >= min_lookback
        if not usable:
            rows.append(
                FeatureRow(date=bar.ts.date(), values=(0.0,) * len(FEATURE_NAMES), usable=False)
            )
            continue

        daily_return = returns[i]

        vol_slice = returns[max(0, i - vol_window + 1) : i + 1]
        realised_vol = _stdev(vol_slice) * math.sqrt(252)

        downside = [r for r in vol_slice if r < 0]
        downside_vol = _stdev(downside) * math.sqrt(252) if len(downside) >= 2 else 0.0

        start_price = closes[i - momentum_window]
        return_60d = (price - start_price) / start_price if start_price > 0 else 0.0

        rows.append(
            FeatureRow(
                date=bar.ts.date(),
                values=(daily_return, realised_vol, return_60d, drawdown, downside_vol),
                usable=True,
            )
        )

    return rows


def usable_prefix(rows: list[FeatureRow]) -> list[FeatureRow]:
    """Rows whose full lookback is satisfied. The unusable prefix is
    dropped rather than zero-filled -- a zero-filled row would tell the HMM
    that the market was flat and calm before it actually observed anything.
    """
    return [r for r in rows if r.usable]
