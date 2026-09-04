"""V5 — the one example hypothesis: cross-sectional momentum.

Exists solely to prove the framework runs a real, non-MA hypothesis through
all nine stages end to end. It is not offered as a promising strategy, and
this module does not optimize it -- see `docs/research/momentum_xs_v1/` for
whatever the evaluator actually found.

**Economic mechanism.** Cross-sectional momentum (Jegadeesh & Titman 1993
and a large subsequent literature) holds that securities with the strongest
trailing 3-12 month returns continue to outperform over the following
1-3 months, attributed to gradual information diffusion and underreaction --
investors update on new information slowly enough that a name's recent
relative strength carries forward for a while before mean-reverting. This
is a distinct mechanism from MA 20/50's single-name trend-following: it is
a *cross-sectional* claim (rank names against each other) rather than a
*time-series* claim (is this one name trending).

**Ex-ante parameters**, chosen from the literature before any backtest of
this hypothesis ran:

- `lookback_days=126` — roughly 6 trading months, the middle of the
  literature's standard 3-12 month formation window.
- `rebalance_days=21` — roughly one trading month, the literature's
  standard rebalance frequency.
- `top_k=3` — long the top third of a 10-name universe; a round number
  inside the "top 3-5" range in typical decile-based literature designs,
  scaled down for a small universe.

None of these were fit on this universe's data.
"""

from __future__ import annotations

from backtesting.market_view import MarketView
from backtesting.schemas import SignalAction, StrategySignal
from backtesting.strategy import Strategy
from experiments.alpha.hypothesis import AlphaHypothesis
from experiments.alpha.schema import HypothesisMetadata, ParameterRecord, ParameterSet

HYPOTHESIS_ID = "momentum_xs_v1"


def default_metadata(researcher: str = "V5 framework validation") -> HypothesisMetadata:
    return HypothesisMetadata(
        hypothesis_id=HYPOTHESIS_ID,
        hypothesis_name="Cross-Sectional Momentum (Top-3, 126d/21d)",
        economic_mechanism=(
            "Securities with the strongest trailing 6-month return continue to "
            "outperform their peers over the following month, attributed to "
            "gradual diffusion of information and investor underreaction "
            "(Jegadeesh & Titman 1993 and the subsequent momentum literature)."
        ),
        expected_direction="long the strongest trailing-return names, flat the rest",
        expected_holding_period="~1 month per rebalance, positions may persist across several",
        expected_market_behavior=(
            "Expected to work best when cross-sectional dispersion is high and "
            "trends persist (e.g. a sector rotation or a sustained bull market); "
            "expected to fail in a sharp reversal, where yesterday's winners are "
            "today's losers, and in a low-dispersion sideways market where "
            "ranking is mostly noise."
        ),
        required_features=("trailing_126d_return",),
        known_failure_modes=(
            "Momentum crashes: a sharp market reversal after a drawdown "
            "punishes exactly the names that were recent winners.",
            "Low-dispersion regimes where the cross-sectional ranking is "
            "dominated by noise rather than signal.",
            "Concentration in whichever single name is driving universe-wide "
            "returns (the same failure mode V4.1 found in MA 20/50 via NVDA).",
            "Small universe (10 names): 'top 3' is a coarse cut that a single "
            "name entering or leaving materially changes.",
        ),
        falsification_criteria=(
            "Does not beat matched random entry (Stage 4) at the 95th percentile "
            "on the primary metric in TEST.",
            "Sharpe does not survive removing the largest P&L contributor "
            "(Stage 5, concentration-dependent).",
            "Does not beat regime-matched random entry in a majority of the "
            "HMM's modeled regimes (Stage 7).",
            "Does not survive 2x/3x cost or slippage stress (Stage 8).",
        ),
        researcher=researcher,
        data_dependencies=("yahoo_daily_ohlcv",),
    )


def default_parameters() -> ParameterSet:
    return ParameterSet(parameters=(
        ParameterRecord(
            name="lookback_days", value=126, source="prior literature",
            justification=(
                "Middle of the momentum literature's standard 3-12 month "
                "formation window (Jegadeesh & Titman 1993)."
            ),
            frozen_before_test=True, selected_after_observation=False,
        ),
        ParameterRecord(
            name="rebalance_days", value=21, source="prior literature",
            justification="Standard ~1-month rebalance frequency in the momentum literature.",
            frozen_before_test=True, selected_after_observation=False,
        ),
        ParameterRecord(
            name="top_k", value=3, source="prior literature, scaled for a 10-name universe",
            justification=(
                "Top-third of a 10-name universe; inside the 'top 3-5' range "
                "typical of small cross-sectional momentum designs."
            ),
            frozen_before_test=True, selected_after_observation=False,
        ),
    ))


class CrossSectionalMomentumStrategy(Strategy):
    """Ranks the universe by trailing return every `rebalance_days` bars;
    holds the top `top_k` equal-weighted, flat otherwise.

    Deterministic given the same bars: ranking uses only `view.closes()`,
    which is itself already sliced to bars at or before the current
    timestep (`MarketView`'s whole contract), so there is no path for this
    strategy to see a future price.
    """

    name = "cross_sectional_momentum"

    def __init__(
        self,
        *,
        lookback_days: int = 126,
        rebalance_days: int = 21,
        top_k: int = 3,
        tickers: list[str] | None = None,
        permute_ranking: bool = False,
        rng_seed: int = 0,
    ) -> None:
        self.lookback_days = lookback_days
        self.rebalance_days = rebalance_days
        self.top_k = top_k
        self.tickers = tickers
        # Placebo hook: shuffles which ticker's momentum score is attributed
        # to which ticker at each rebalance, severing the signal's actual
        # information content while preserving the exact same trade
        # structure (same rebalance dates, same number of longs, same
        # holding pattern) -- the feature-permutation placebo this
        # hypothesis exposes via build_placebo_strategy().
        self.permute_ranking = permute_ranking
        self._rng_seed = rng_seed
        self._bars_seen = 0
        self._held: set[str] = set()

    def on_start(self) -> None:
        self._bars_seen = 0
        self._held = set()

    def on_bar(self, view: MarketView) -> list[StrategySignal]:
        universe = self.tickers if self.tickers is not None else view.tickers
        self._bars_seen += 1

        # Rebalance only every `rebalance_days` bars. Off-rebalance bars
        # hold whatever was set on the last rebalance -- momentum is a
        # medium-horizon signal, not a daily one, and rebalancing daily
        # would just be noise trading dressed as the hypothesis.
        if self._bars_seen % self.rebalance_days != 1:
            return []

        scores: dict[str, float] = {}
        for ticker in universe:
            if not view.is_current(ticker):
                continue
            closes = view.closes(ticker, lookback=self.lookback_days + 1)
            if len(closes) < self.lookback_days + 1:
                continue
            start, end = closes[0], closes[-1]
            if start > 0:
                scores[ticker] = (end - start) / start

        if len(scores) < self.top_k:
            return []  # not enough history yet to rank the full universe

        if self.permute_ranking:
            import random

            rng = random.Random(self._rng_seed + self._bars_seen)
            values = list(scores.values())
            rng.shuffle(values)
            scores = dict(zip(scores.keys(), values, strict=True))

        ranked = sorted(scores, key=lambda t: scores[t], reverse=True)
        target = set(ranked[: self.top_k])

        signals: list[StrategySignal] = []
        for ticker in self._held - target:
            signals.append(
                StrategySignal(ticker=ticker, action=SignalAction.SELL, reason="left top-k")
            )
        for ticker in target - self._held:
            signals.append(
                StrategySignal(
                    ticker=ticker, action=SignalAction.BUY,
                    strength=1.0 / self.top_k, reason="entered top-k",
                )
            )
        self._held = target
        return signals


class CrossSectionalMomentumHypothesis(AlphaHypothesis):
    def __init__(
        self, *, tickers: list[str], metadata: HypothesisMetadata | None = None,
        parameters: ParameterSet | None = None,
    ) -> None:
        super().__init__(metadata or default_metadata(), parameters or default_parameters())
        self.tickers = tickers

    def build_strategy(self) -> Strategy:
        values = self.parameters.as_values()
        return CrossSectionalMomentumStrategy(
            lookback_days=int(values["lookback_days"]),
            rebalance_days=int(values["rebalance_days"]),
            top_k=int(values["top_k"]),
            tickers=self.tickers,
        )

    def build_placebo_strategy(self, rng) -> Strategy:  # type: ignore[override]
        values = self.parameters.as_values()
        return CrossSectionalMomentumStrategy(
            lookback_days=int(values["lookback_days"]),
            rebalance_days=int(values["rebalance_days"]),
            top_k=int(values["top_k"]),
            tickers=self.tickers,
            permute_ranking=True,
            rng_seed=rng.randint(0, 2**31 - 1),
        )
