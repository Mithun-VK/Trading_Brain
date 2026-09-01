from __future__ import annotations

import datetime as dt

from data.ingestion.schemas import PriceBar
from data.normalization.prices import price_bar_to_model


def test_price_bar_to_model_maps_all_fields() -> None:
    bar = PriceBar(
        ts=dt.datetime(2024, 1, 2, 16, 0, tzinfo=dt.UTC),
        open=100.0,
        high=105.0,
        low=99.0,
        close=104.0,
        volume=12345,
        interval="1d",
        source="mock",
    )

    price = price_bar_to_model(asset_id=7, bar=bar)

    assert price.asset_id == 7
    assert price.ts == bar.ts
    assert price.open == 100.0
    assert price.close == 104.0
    assert price.volume == 12345
    assert price.source == "mock"
