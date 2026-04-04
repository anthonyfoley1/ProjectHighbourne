import pandas as pd
import numpy as np
from data.technicals import (
    compute_rsi,
    compute_macd,
    compute_sma,
    detect_crossovers,
    macd_signal_label,
    rsi_label,
    ma_trend_label,
)


def test_rsi_bounds():
    prices = pd.Series(np.random.lognormal(0, 0.02, 200).cumprod())
    rsi = compute_rsi(prices, period=14)
    assert rsi.dropna().between(0, 100).all()


def test_rsi_overbought():
    prices = pd.Series(range(100, 200), dtype=float)
    rsi = compute_rsi(prices, period=14)
    assert rsi.iloc[-1] > 70


def test_rsi_oversold():
    prices = pd.Series(range(200, 100, -1), dtype=float)
    rsi = compute_rsi(prices, period=14)
    assert rsi.iloc[-1] < 30


def test_macd_components():
    prices = pd.Series(np.random.lognormal(0, 0.02, 200).cumprod())
    macd_line, signal_line, histogram = compute_macd(prices)
    assert len(macd_line) == len(prices)
    assert len(signal_line) == len(prices)
    assert len(histogram) == len(prices)


def test_macd_histogram_is_difference():
    prices = pd.Series(np.random.lognormal(0, 0.02, 200).cumprod())
    macd_line, signal_line, histogram = compute_macd(prices)
    diff = macd_line - signal_line
    pd.testing.assert_series_equal(histogram, diff, check_names=False)


def test_sma():
    prices = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
    sma = compute_sma(prices, window=3)
    assert sma.iloc[-1] == 9.0


def test_detect_crossovers():
    fast = pd.Series([1, 2, 3, 4, 5, 4, 3, 2, 1], dtype=float)
    slow = pd.Series([3, 3, 3, 3, 3, 3, 3, 3, 3], dtype=float)
    golden, death = detect_crossovers(fast, slow)
    assert len(golden) > 0
    assert len(death) > 0


def test_rsi_label():
    assert rsi_label(75) == "OVERBOUGHT"
    assert rsi_label(25) == "OVERSOLD"
    assert rsi_label(50) == ""


def test_ma_trend_label():
    assert ma_trend_label(150, 140) == "Above"
    assert ma_trend_label(130, 140) == "Below"
    assert ma_trend_label(float("nan"), 140) == "N/A"
