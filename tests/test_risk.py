import pytest
import pandas as pd
import numpy as np
from data.risk import compute_breadth_stats, compute_risk_verdict, compute_new_highs_lows, compute_advancers_decliners


def test_breadth_stats():
    above_200 = {"A": True, "B": True, "C": True, "D": False, "E": False}
    above_50 = {"A": True, "B": False, "C": True, "D": False, "E": True}
    rsi = {"A": 40, "B": 50, "C": 60, "D": 30, "E": 70}
    stats = compute_breadth_stats(above_200, above_50, rsi)
    assert stats["pct_above_200sma"] == 60.0
    assert stats["pct_above_50sma"] == 60.0
    assert stats["avg_rsi"] == 50.0


def test_risk_verdict_elevated():
    stats = {"vix": 28, "fear_greed": 22, "put_call": 1.2,
             "pct_above_200sma": 38, "pct_above_50sma": 29, "avg_rsi": 38,
             "new_highs": 42, "new_lows": 218}
    verdict = compute_risk_verdict(stats)
    assert verdict["level"] in ("ELEVATED RISK", "EXTREME RISK")


def test_risk_verdict_low():
    stats = {"vix": 12, "fear_greed": 75, "put_call": 0.7,
             "pct_above_200sma": 72, "pct_above_50sma": 68, "avg_rsi": 55,
             "new_highs": 200, "new_lows": 30}
    verdict = compute_risk_verdict(stats)
    assert verdict["level"] in ("LOW RISK", "MODERATE")


def test_advancers_decliners():
    returns = {"A": 0.05, "B": -0.03, "C": 0.0001, "D": 0.02, "E": -0.01}
    adv, dec, unch = compute_advancers_decliners(returns)
    assert adv == 2   # A, D
    assert dec == 2   # B, E
    assert unch == 1  # C


def test_new_highs_lows():
    # Ticker at 52-week high (last price within 2% of max)
    high_series = pd.Series([100, 105, 110, 108, 109])
    # Ticker at 52-week low (last price within 2% of min)
    low_series = pd.Series([100, 95, 90, 92, 91])
    # Ticker in the middle
    mid_series = pd.Series([100, 110, 90, 100, 100])
    prices = {"H": high_series, "L": low_series, "M": mid_series}
    highs, lows = compute_new_highs_lows(prices)
    assert highs == 1  # H
    assert lows == 1   # L
