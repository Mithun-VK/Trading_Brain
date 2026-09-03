"""V1 — the frozen experiment configuration.

An experiment is only interpretable if you can say exactly what was run.
This module makes that a data structure rather than a memory: every run
carries the full configuration, and the configuration carries a content
hash, so two results can be compared only when they are actually
comparable.

The load-bearing design decision is `DataProvenance.synthetic`. TradingBrain
can generate deterministic price series, and a backtest over them produces a
CAGR, a Sharpe, and a drawdown that look exactly like real results. They are
not results. They are the output of a random number generator with a
plausible shape, and reporting them next to real ones -- or worse, without a
label -- is the single easiest way to fool yourself in this entire project.

So synthetic runs are not blocked (the machinery has to be testable), but
they can never be *certified*: `ExperimentConfig.is_certifiable` is False,
every report says so in its header, and the V-phase gate refuses to pass.
This is Rule 4 applied to validation rather than to prices.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum


class AIMode(StrEnum):
    """Which arm of the ablation this run belongs to (V5)."""

    DISABLED = "disabled"  # arm A: quant + ML only, the control group
    LOCAL_ONLY = "local_only"  # arm B: + local LLM
    FRONTIER_ONLY = "frontier_only"  # arm C: + Claude, no gate
    GATED = "gated"  # arm D: gateway decides, escalating only when warranted


class DataQuality(StrEnum):
    SYNTHETIC = "synthetic"  # generated; never evidence of edge
    VENDOR = "vendor"  # retrieved from a market data provider
    UNKNOWN = "unknown"  # provenance not recorded -- treated as synthetic


@dataclass(frozen=True)
class DataProvenance:
    """Where the prices came from, recorded so a result can never be read
    without knowing what it was computed over."""

    provider: str
    quality: DataQuality
    snapshot_id: str  # a content hash of the bars actually used
    bar_count: int
    first_bar: dt.datetime | None = None
    last_bar: dt.datetime | None = None
    tickers: tuple[str, ...] = ()
    note: str = ""

    @property
    def is_real(self) -> bool:
        return self.quality is DataQuality.VENDOR


@dataclass(frozen=True)
class CostModel:
    """Transaction costs and slippage.

    Defaults are deliberately pessimistic rather than optimistic. A backtest
    that only works at zero cost is not a strategy, and the cheapest way to
    discover that is to never have run it at zero cost.
    """

    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    # Applied on top of slippage when stressing execution (V7).
    spread_bps: float = 0.0
    # Bars of delay between signal and fill. The engine already fills at the
    # next bar's open; this is additional delay for stress testing.
    execution_delay_bars: int = 0


@dataclass(frozen=True)
class RiskLimits:
    """Constraints the strategy may not exceed.

    These are experiment parameters, not suggestions: a run that breaches
    one is reported as a breach rather than silently accepted, because a
    strategy that only works by exceeding its own risk limits has not
    actually been tested.
    """

    max_position_pct: float = 0.20  # of equity, per position
    max_portfolio_exposure: float = 1.00  # 1.0 = fully invested, no leverage
    max_leverage: float = 1.00
    max_drawdown_stop: float | None = None  # halt the run past this drawdown
    max_positions: int = 10


@dataclass(frozen=True)
class Period:
    """A named date range. Half-open [start, end) so consecutive periods
    never share a bar -- an overlap of even one day leaks."""

    name: str
    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(f"Period {self.name!r}: end must be after start")

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def contains(self, when: dt.date) -> bool:
        return self.start <= when < self.end

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class RegimeDefinition:
    """How regimes are labelled for V4.

    Recorded in the config because a regime decomposition is only meaningful
    against a stated definition -- "performance in a bull market" means
    nothing until you say what made it a bull market.
    """

    trend_lookback: int = 50
    trend_threshold_pct: float = 2.0
    volatility_lookback: int = 20
    high_volatility_percentile: float = 0.80
    low_volatility_percentile: float = 0.20
    crisis_drawdown_pct: float = 20.0
    source: str = "quant.regime.detector.MarketRegimeDetector"


@dataclass(frozen=True)
class ExperimentConfig:
    """Everything that must be identical for two runs to be comparable."""

    # --- identity ---
    experiment_id: str
    strategy: str
    strategy_version: str
    frozen_at_commit: str
    description: str = ""

    # --- universe and time ---
    universe: tuple[str, ...] = ()
    timeframe: str = "1d"
    historical_period: Period | None = None
    train: Period | None = None
    validation: Period | None = None
    test: Period | None = None

    # --- mechanics ---
    initial_cash: float = 100_000.0
    costs: CostModel = field(default_factory=CostModel)
    risk: RiskLimits = field(default_factory=RiskLimits)
    position_sizing: str = "fixed_fraction"
    position_size_pct: float = 0.10
    regimes: RegimeDefinition = field(default_factory=RegimeDefinition)

    # --- AI arm ---
    ai_mode: AIMode = AIMode.DISABLED
    local_model: str = ""
    frontier_model: str = ""
    frontier_high_model: str = ""

    # --- reproducibility ---
    random_seed: int = 0
    periods_per_year: int = 252
    strategy_params: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._check_period_ordering()
        if self.ai_mode is not AIMode.DISABLED and not (
            self.local_model or self.frontier_model or self.frontier_high_model
        ):
            raise ValueError(
                f"ai_mode={self.ai_mode} but no model is named. An AI arm whose "
                "model is unrecorded cannot be reproduced or attributed."
            )

    def _check_period_ordering(self) -> None:
        """Train must end before validation begins, and validation before
        test. An overlap of one bar is data leakage, and leakage does not
        announce itself in the results -- it just makes them good.
        """
        ordered = [p for p in (self.train, self.validation, self.test) if p is not None]
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if later.start < earlier.end:
                raise ValueError(
                    f"Period {later.name!r} starts {later.start} before "
                    f"{earlier.name!r} ends {earlier.end}. Overlapping periods "
                    "leak future information into training."
                )

    @property
    def ai_enabled(self) -> bool:
        return self.ai_mode is not AIMode.DISABLED

    def to_dict(self) -> dict:
        def encode(value: object) -> object:
            if isinstance(value, Period):
                return value.to_dict()
            if isinstance(value, dt.date):
                return value.isoformat()
            if isinstance(value, StrEnum):
                return str(value)
            if dataclasses.is_dataclass(value) and not isinstance(value, type):
                return {k: encode(v) for k, v in dataclasses.asdict(value).items()}
            if isinstance(value, tuple):
                return list(value)
            if isinstance(value, dict):
                return {k: encode(v) for k, v in value.items()}
            return value

        return {f.name: encode(getattr(self, f.name)) for f in dataclasses.fields(self)}

    def fingerprint(self) -> str:
        """Content hash of the configuration.

        Two runs with the same fingerprint were configured identically. Two
        with different fingerprints are not comparable, however similar they
        look in a summary table.
        """
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def certifiable(config: ExperimentConfig, provenance: DataProvenance) -> tuple[bool, str]:
    """Whether a result from this run may be treated as evidence.

    Returns the verdict and the reason, so a refusal can always be explained
    rather than merely enforced.
    """
    if not provenance.is_real:
        return False, (
            f"Data provenance is {provenance.quality!s} (provider "
            f"{provenance.provider!r}). Metrics computed over generated prices "
            "describe the generator, not a market. This run exercises the "
            "machinery; it is not evidence of edge."
        )
    if provenance.bar_count == 0:
        return False, "No bars were used. There is nothing to certify."
    if config.test is None:
        return False, (
            "No out-of-sample test period is defined. A result measured only "
            "where the strategy was fitted is not an out-of-sample result."
        )
    return True, "Real vendor data over a defined out-of-sample period."
