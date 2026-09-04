"""V2 — running an experiment and recording what it actually was.

The runner's job is not to produce a number. It is to produce a number
*together with everything needed to know whether the number means anything*:
which config, which data, which arm, and whether the result is certifiable.

The one rule enforced here rather than documented: a run over synthetic data
is executed and reported, but never certified. The machinery has to be
runnable without a market data subscription, so the run is allowed; the
conclusion is not.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import random
from dataclasses import dataclass, field

from backtesting.engine import BacktestEngine
from backtesting.schemas import BacktestConfig, BacktestResult
from backtesting.sizing import FixedFractionSizer
from backtesting.strategy import Strategy
from config.logging import get_logger
from data.ingestion.schemas import PriceBar
from experiments import metrics
from experiments.config import (
    DataProvenance,
    DataQuality,
    ExperimentConfig,
    certifiable,
)

logger = get_logger("experiments")


def snapshot_bars(bars_by_ticker: dict[str, list[PriceBar]]) -> str:
    """A content hash of the exact bars used.

    Two runs claiming to be over "the same data" are only comparable if this
    matches. A vendor silently revising a price, a corporate action applied
    later, or one extra day of history all change it -- which is the point.
    """
    digest = hashlib.sha256()
    for ticker in sorted(bars_by_ticker):
        digest.update(ticker.encode())
        for bar in sorted(bars_by_ticker[ticker], key=lambda b: b.ts):
            digest.update(
                f"{bar.ts.isoformat()}|{bar.open}|{bar.high}|{bar.low}|"
                f"{bar.close}|{bar.volume}".encode()
            )
    return digest.hexdigest()[:16]


def describe_data(
    bars_by_ticker: dict[str, list[PriceBar]], *, provider: str
) -> DataProvenance:
    """Build provenance from the bars themselves.

    Quality is derived from the bars' recorded `source`, not from what the
    caller claims: a caller that mislabels synthetic data as vendor data is
    exactly the failure this guard exists to catch.
    """
    sources = {bar.source for bars in bars_by_ticker.values() for bar in bars}
    synthetic_markers = {"mock", "synthetic", "fake", "generated", "test"}

    if not sources:
        quality = DataQuality.UNKNOWN
    elif any(s.lower() in synthetic_markers for s in sources):
        quality = DataQuality.SYNTHETIC
    else:
        quality = DataQuality.VENDOR

    all_bars = [b for bars in bars_by_ticker.values() for b in bars]
    stamps = sorted(b.ts for b in all_bars)

    return DataProvenance(
        provider=provider,
        quality=quality,
        snapshot_id=snapshot_bars(bars_by_ticker),
        bar_count=len(all_bars),
        first_bar=stamps[0] if stamps else None,
        last_bar=stamps[-1] if stamps else None,
        tickers=tuple(sorted(bars_by_ticker)),
        note=f"bar sources: {sorted(sources) or 'none'}",
    )


@dataclass
class ExperimentRun:
    """One arm of one experiment, with its verdict attached."""

    config: ExperimentConfig
    provenance: DataProvenance
    performance: metrics.PerformanceRecord
    result: BacktestResult | None = None
    period_name: str = "full"
    certified: bool = False
    certification_reason: str = ""
    limit_breaches: list[str] = field(default_factory=list)
    started_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))

    @property
    def config_fingerprint(self) -> str:
        return self.config.fingerprint()

    def headline(self) -> dict:
        """The figures a summary table would show -- never without the
        certification verdict beside them."""
        return {
            "experiment": self.config.experiment_id,
            "arm": str(self.config.ai_mode),
            "period": self.period_name,
            "certified": self.certified,
            "certification_reason": self.certification_reason,
            "data_quality": str(self.provenance.quality),
            "snapshot": self.provenance.snapshot_id,
            "config_fingerprint": self.config_fingerprint,
            "cagr": self.performance.cagr,
            "sharpe": self.performance.sharpe,
            "max_drawdown": self.performance.max_drawdown,
            "trades": self.performance.trade_count,
            "notes": list(self.performance.notes),
            "limit_breaches": list(self.limit_breaches),
        }


def run(
    config: ExperimentConfig,
    strategy: Strategy,
    bars_by_ticker: dict[str, list[PriceBar]],
    *,
    provider: str = "unknown",
    period: str = "full",
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    provenance: DataProvenance | None = None,
) -> ExperimentRun:
    """Execute one arm and return it with its verdict.

    `random.seed` is set from the config so that any stochastic component --
    none today, but the ablation arms and Monte Carlo phases will have them
    -- is reproducible from the configuration alone.

    `provenance` may be precomputed and passed in. A Monte Carlo sweep calls
    this thousands of times over the *same* bars with only the strategy
    varying -- hashing the whole window fresh on every trial was, at one
    point, the single largest cost in the run loop. Precomputing it once per
    period and passing it through changes nothing about what is certified,
    since the provenance is a pure function of the bars and the bars do not
    change between trials; it only stops recomputing something that cannot
    have changed.
    """
    random.seed(config.random_seed)

    if provenance is None:
        provenance = describe_data(bars_by_ticker, provider=provider)
    # The sizer comes from the config. Before this it did not: the engine's
    # default 10% fraction was used regardless of what the experiment
    # declared, so `position_size_pct` was a setting that did nothing --
    # and a "buy and hold SPY" benchmark was really "hold 10% SPY, 90%
    # cash", which understated its return by roughly an order of magnitude.
    engine = BacktestEngine(
        BacktestConfig(
            initial_cash=config.initial_cash,
            commission_bps=config.costs.commission_bps,
            slippage_bps=config.costs.slippage_bps + config.costs.spread_bps,
            periods_per_year=config.periods_per_year,
        ),
        sizer=FixedFractionSizer(fraction=config.position_size_pct),
    )

    result = engine.run(strategy, bars_by_ticker, start=start, end=end)
    performance = metrics.compute(result)
    ok, reason = certifiable(config, provenance)

    run_record = ExperimentRun(
        config=config,
        provenance=provenance,
        performance=performance,
        result=result,
        period_name=period,
        certified=ok,
        certification_reason=reason,
        limit_breaches=metrics.breaches(performance, config.risk),
    )

    logger.info(
        "experiment_run",
        operation=config.experiment_id,
        status="certified" if ok else "uncertified",
        arm=str(config.ai_mode),
        period=period,
        data_quality=str(provenance.quality),
        trades=performance.trade_count,
        config_fingerprint=config.fingerprint(),
    )
    if not ok:
        logger.warning(
            "experiment_not_certifiable",
            operation=config.experiment_id,
            status="uncertified",
            reason=reason,
        )
    return run_record
