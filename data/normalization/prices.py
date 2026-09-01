"""Raw provider data -> `models.Price` rows. The only place that should
construct a `Price` ORM instance from provider output, so the mapping is
defined once.
"""

from __future__ import annotations

from data.ingestion.schemas import PriceBar
from models.price import Price


def price_bar_to_model(asset_id: int, bar: PriceBar) -> Price:
    return Price(
        asset_id=asset_id,
        ts=bar.ts,
        interval=bar.interval,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        source=bar.source,
    )
