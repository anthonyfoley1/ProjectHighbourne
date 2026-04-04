"""Pure functions for computing technical indicators from price Series."""

import math
import pandas as pd
import numpy as np


def compute_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """RSI using exponential moving average of gains/losses. Returns Series 0-100."""
    delta = prices.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_macd(
    prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple:
    """Returns (macd_line, signal_line, histogram) as pd.Series."""
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_sma(prices: pd.Series, window: int) -> pd.Series:
    """Simple moving average."""
    return prices.rolling(window=window).mean()


def detect_crossovers(
    fast: pd.Series, slow: pd.Series
) -> tuple[list, list]:
    """Detect where fast crosses above (golden) or below (death) slow.
    Returns (golden_dates, death_dates) as lists of index values."""
    diff = fast - slow
    sign = np.sign(diff)
    shift = sign.shift(1)

    golden_mask = (sign > 0) & (shift <= 0)
    death_mask = (sign < 0) & (shift >= 0)

    golden_dates = list(fast.index[golden_mask])
    death_dates = list(fast.index[death_mask])
    return golden_dates, death_dates


def macd_signal_label(macd_line: pd.Series, signal_line: pd.Series) -> str:
    """Return 'Bull', 'Bear', or 'Flat' based on current MACD vs signal relationship."""
    last_macd = macd_line.iloc[-1]
    last_signal = signal_line.iloc[-1]
    if last_macd > last_signal:
        return "Bull"
    elif last_macd < last_signal:
        return "Bear"
    return "Flat"


def rsi_label(rsi_value: float) -> str:
    """Return 'OVERBOUGHT' if >= 70, 'OVERSOLD' if <= 30, else ''."""
    if rsi_value >= 70:
        return "OVERBOUGHT"
    elif rsi_value <= 30:
        return "OVERSOLD"
    return ""


def ma_trend_label(price: float, sma_200: float) -> str:
    """Return 'Above' or 'Below' based on price vs 200-day SMA. 'N/A' if either is NaN."""
    if math.isnan(price) or math.isnan(sma_200):
        return "N/A"
    if price >= sma_200:
        return "Above"
    return "Below"


def compute_bollinger_bands(prices, period=20, std_dev=2):
    """Compute Bollinger Bands. Returns (upper, middle, lower) as pd.Series."""
    middle = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


# Adaptive overlay parameters lookup based on time period
OVERLAY_PARAMS = {
    "1D": {"short_sma": 5, "long_sma": 20, "bb_period": 10, "bb_std": 1.5},
    "5D": {"short_sma": 5, "long_sma": 20, "bb_period": 10, "bb_std": 1.5},
    "1M": {"short_sma": 10, "long_sma": 30, "bb_period": 10, "bb_std": 1.5},
    "3M": {"short_sma": 20, "long_sma": 50, "bb_period": 20, "bb_std": 2.0},
    "YTD": {"short_sma": 50, "long_sma": 200, "bb_period": 20, "bb_std": 2.0},
    "6M": {"short_sma": 50, "long_sma": 200, "bb_period": 20, "bb_std": 2.0},
    "1Y": {"short_sma": 50, "long_sma": 200, "bb_period": 20, "bb_std": 2.0},
    "2Y": {"short_sma": 100, "long_sma": 200, "bb_period": 50, "bb_std": 2.0},
    "5Y": {"short_sma": 100, "long_sma": 200, "bb_period": 50, "bb_std": 2.0},
    "MAX": {"short_sma": 200, "long_sma": 500, "bb_period": 100, "bb_std": 2.5},
}
