from __future__ import annotations

import math

import pytest

from quant.indicators.moving_average import ema, sma
from quant.indicators.oscillators import macd, rsi
from quant.indicators.returns import log_returns, max_drawdown, simple_returns, volatility
from quant.indicators.volatility import atr, bollinger_bands
from quant.indicators.volume import vwap


def test_sma_basic() -> None:
    result = sma([1, 2, 3, 4, 5], period=3)

    assert result == [None, None, 2, 3, 4]


def test_sma_rejects_non_positive_period() -> None:
    with pytest.raises(ValueError):
        sma([1, 2, 3], period=0)


def test_ema_basic() -> None:
    result = ema([1, 2, 3, 4, 5], period=3)

    assert result == [None, None, 2, 3, 4]


def test_ema_insufficient_data_returns_all_none() -> None:
    assert ema([1, 2], period=5) == [None, None]


def test_rsi_all_gains_is_100() -> None:
    values = list(range(1, 20))

    result = rsi(values, period=14)

    assert result[14] == 100.0


def test_rsi_all_losses_is_0() -> None:
    values = list(range(20, 1, -1))

    result = rsi(values, period=14)

    assert result[14] == 0.0


def test_macd_constant_series_is_zero_after_warmup() -> None:
    values = [50.0] * 40

    macd_line, signal_line, histogram = macd(values, fast=12, slow=26, signal=9)

    assert macd_line[-1] == pytest.approx(0.0)
    assert signal_line[-1] == pytest.approx(0.0)
    assert histogram[-1] == pytest.approx(0.0)


def test_macd_histogram_equals_macd_minus_signal() -> None:
    values = [50 + i * 0.5 for i in range(60)]

    macd_line, signal_line, histogram = macd(values)

    for m, s, h in zip(macd_line, signal_line, histogram, strict=True):
        if m is not None and s is not None:
            assert h == pytest.approx(m - s)
        else:
            assert h is None


def test_atr_basic() -> None:
    high = [10, 10, 10]
    low = [8, 8, 8]
    close = [9, 9, 9]

    result = atr(high, low, close, period=2)

    assert result == [None, 2, 2]


def test_bollinger_bands_symmetric_around_middle() -> None:
    values = [1, 2, 3, 4, 5, 4, 3, 2, 1]

    upper, middle, lower = bollinger_bands(values, period=3, num_std=1.0)

    for u, m, low_val in zip(upper, middle, lower, strict=True):
        if m is not None:
            assert u - m == pytest.approx(m - low_val)
            assert u > m > low_val or u == m == low_val


def test_vwap_basic() -> None:
    high = low = close = [10, 20]
    volume = [100, 100]

    result = vwap(high, low, close, volume)

    assert result == [10, 15]


def test_simple_returns() -> None:
    assert simple_returns([100, 110, 99]) == pytest.approx([0.1, -0.1])


def test_log_returns() -> None:
    result = log_returns([100, 100 * math.e])

    assert result == pytest.approx([1.0])


def test_volatility_annualization() -> None:
    import statistics

    returns = [0.01, -0.02, 0.015, 0.005]
    raw = statistics.stdev(returns)

    assert volatility(returns, annualize=False) == pytest.approx(raw)
    assert volatility(returns, annualize=True) == pytest.approx(raw * math.sqrt(252))


def test_max_drawdown() -> None:
    values = [100, 120, 90, 95, 130, 80]

    assert max_drawdown(values) == pytest.approx(-50 / 130)


def test_max_drawdown_empty() -> None:
    assert max_drawdown([]) == 0.0
