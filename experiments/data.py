"""Market data for experiments: fetch once, cache, reuse.

Two reasons this exists rather than calling the provider directly.

**Reproducibility.** An experiment's snapshot hash must be stable. Yahoo
adjusts history — splits, dividends, the occasional revision — so fetching
fresh on every run silently changes the dataset underneath a comparison.
Once cached, a run is reproducible from disk.

**Courtesy.** Yahoo's endpoint is unofficial and unmetered by good manners
alone. Re-downloading ten years of daily bars on every ablation arm is both
slow and rude.

The cache is content-addressed by ticker, range, and interval, and the
resulting bars carry `source="yahoo"` — which the certification rule reads
as vendor data, not synthetic.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

from config.logging import get_logger
from data.ingestion.schemas import PriceBar
from data.ingestion.yahoo_provider import YahooFinanceProvider

logger = get_logger("experiments")

CACHE_DIR = pathlib.Path("experiments/.cache")


def _cache_path(ticker: str, start: dt.date, end: dt.date, interval: str) -> pathlib.Path:
    safe = ticker.replace("/", "_").replace("^", "IDX_")
    return CACHE_DIR / f"{safe}_{start:%Y%m%d}_{end:%Y%m%d}_{interval}.json"


def _write(path: pathlib.Path, bars: list[PriceBar]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "ts": b.ts.isoformat(), "open": b.open, "high": b.high, "low": b.low,
            "close": b.close, "volume": b.volume, "interval": b.interval, "source": b.source,
        }
        for b in bars
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read(path: pathlib.Path) -> list[PriceBar]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        PriceBar(
            ts=dt.datetime.fromisoformat(r["ts"]), open=r["open"], high=r["high"],
            low=r["low"], close=r["close"], volume=r["volume"],
            interval=r["interval"], source=r["source"],
        )
        for r in raw
    ]


def load(
    tickers: list[str],
    start: dt.date,
    end: dt.date,
    *,
    interval: str = "1d",
    refresh: bool = False,
    timeout: float = 30.0,
) -> dict[str, list[PriceBar]]:
    """Load bars for each ticker, fetching only what is not cached.

    A ticker that cannot be fetched is **omitted with a warning**, never
    substituted with generated data — the whole point of using a real
    provider is lost the moment a gap is filled in silently.
    """
    provider = YahooFinanceProvider(timeout=timeout)
    out: dict[str, list[PriceBar]] = {}
    failed: list[str] = []

    try:
        for ticker in tickers:
            path = _cache_path(ticker, start, end, interval)
            if path.exists() and not refresh:
                out[ticker] = _read(path)
                continue
            try:
                bars = provider.get_historical_prices(ticker, start=start, end=end,
                                                      interval=interval)
            except Exception as exc:  # noqa: BLE001 -- one bad ticker must not end the run
                logger.warning(
                    "experiment_data_fetch_failed",
                    operation="load", status="error",
                    ticker=ticker, error=type(exc).__name__,
                )
                failed.append(ticker)
                continue
            if not bars:
                failed.append(ticker)
                continue
            _write(path, bars)
            out[ticker] = bars
    finally:
        provider.close()

    if failed:
        logger.warning(
            "experiment_data_incomplete",
            operation="load", status="degraded",
            requested=len(tickers), loaded=len(out), missing=failed,
        )
    return out


def align(bars_by_ticker: dict[str, list[PriceBar]]) -> dict[str, list[PriceBar]]:
    """Sort each series and drop duplicate timestamps.

    Keeps the *first* bar at any timestamp rather than the last: a duplicate
    usually means the same session appeared twice, and preferring the later
    copy would quietly adopt a revision mid-series.
    """
    cleaned: dict[str, list[PriceBar]] = {}
    for ticker, bars in bars_by_ticker.items():
        seen: set[dt.datetime] = set()
        ordered: list[PriceBar] = []
        for bar in sorted(bars, key=lambda b: b.ts):
            if bar.ts in seen:
                continue
            seen.add(bar.ts)
            ordered.append(bar)
        cleaned[ticker] = ordered
    return cleaned


def coverage(bars_by_ticker: dict[str, list[PriceBar]]) -> dict[str, object]:
    """What was actually loaded, for the experiment record."""
    if not bars_by_ticker:
        return {"tickers": 0, "bars": 0, "first": None, "last": None}
    stamps = [b.ts for bars in bars_by_ticker.values() for b in bars]
    return {
        "tickers": len(bars_by_ticker),
        "bars": len(stamps),
        "first": min(stamps).date().isoformat(),
        "last": max(stamps).date().isoformat(),
        "per_ticker": {t: len(b) for t, b in sorted(bars_by_ticker.items())},
    }
