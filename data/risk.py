"""
Risk metrics module — market-level risk indicators and composite scoring.
"""

import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Pure computation functions (testable, no network)
# ---------------------------------------------------------------------------

def compute_breadth_stats(
    above_200sma: dict, above_50sma: dict, rsi_values: dict
) -> dict:
    """Compute market breadth from pre-computed per-ticker stats.

    Args:
        above_200sma: {ticker: bool} — whether each ticker is above its 200-day SMA.
        above_50sma:  {ticker: bool} — whether each ticker is above its 50-day SMA.
        rsi_values:   {ticker: float} — RSI value for each ticker.

    Returns:
        dict with keys pct_above_200sma, pct_above_50sma, avg_rsi (all rounded to 1 decimal).
    """
    total_200 = len(above_200sma)
    total_50 = len(above_50sma)
    total_rsi = len(rsi_values)

    pct_200 = round(sum(above_200sma.values()) / total_200 * 100, 1) if total_200 else 0.0
    pct_50 = round(sum(above_50sma.values()) / total_50 * 100, 1) if total_50 else 0.0
    avg_rsi = round(sum(rsi_values.values()) / total_rsi, 1) if total_rsi else 0.0

    return {
        "pct_above_200sma": pct_200,
        "pct_above_50sma": pct_50,
        "avg_rsi": avg_rsi,
    }


def compute_new_highs_lows(prices_dict: dict) -> tuple:
    """Count stocks at 52-week highs (within 2% of max) or lows (within 2% of min).

    Args:
        prices_dict: {ticker: pd.Series of close prices}

    Returns:
        (new_highs, new_lows)
    """
    new_highs = 0
    new_lows = 0

    for _ticker, series in prices_dict.items():
        if series is None or len(series) == 0:
            continue
        hi = series.max()
        lo = series.min()
        last = series.iloc[-1]

        if hi > 0 and last >= hi * 0.98:
            new_highs += 1
        if lo > 0 and last <= lo * 1.02:
            new_lows += 1

    return new_highs, new_lows


def compute_advancers_decliners(returns_1d: dict) -> tuple:
    """Count advancers (>0.1%), decliners (<-0.1%), unchanged.

    Args:
        returns_1d: {ticker: float} — 1-day return as a decimal (e.g. 0.05 = 5%).

    Returns:
        (advancers, decliners, unchanged)
    """
    adv = 0
    dec = 0
    unch = 0

    threshold = 0.001  # 0.1%

    for _ticker, ret in returns_1d.items():
        if ret > threshold:
            adv += 1
        elif ret < -threshold:
            dec += 1
        else:
            unch += 1

    return adv, dec, unch


def compute_risk_verdict(stats: dict) -> dict:
    """Composite risk scoring from aggregated market indicators.

    Args:
        stats: dict with keys vix, fear_greed, put_call, pct_above_200sma,
               pct_above_50sma, avg_rsi, new_highs, new_lows.

    Returns:
        {level: str, color: str, guidance: str}

    Scoring: each risky signal adds 1 point.
        0-1 -> LOW RISK
        2-3 -> MODERATE
        4-5 -> ELEVATED RISK
        6+  -> EXTREME RISK
    """
    score = 0

    # VIX > 20 is elevated
    if stats.get("vix", 0) > 20:
        score += 1
    # VIX > 30 is very elevated
    if stats.get("vix", 0) > 30:
        score += 1

    # Fear & Greed below 25 is extreme fear
    if stats.get("fear_greed", 50) < 25:
        score += 1

    # Put/call ratio above 1.0 signals bearish hedging
    if stats.get("put_call", 0.8) > 1.0:
        score += 1

    # Fewer than 50% of stocks above 200 SMA
    if stats.get("pct_above_200sma", 50) < 50:
        score += 1

    # Fewer than 40% of stocks above 50 SMA
    if stats.get("pct_above_50sma", 50) < 40:
        score += 1

    # Average RSI below 40 (oversold territory)
    if stats.get("avg_rsi", 50) < 40:
        score += 1

    # More new lows than new highs
    if stats.get("new_lows", 0) > stats.get("new_highs", 0):
        score += 1

    # Map score to level
    if score <= 1:
        level = "LOW RISK"
        color = "#00ff00"
        guidance = "Market conditions are favorable. Standard positioning appropriate."
    elif score <= 3:
        level = "MODERATE"
        color = "#ffff00"
        guidance = "Some caution warranted. Consider tightening stops."
    elif score <= 5:
        level = "ELEVATED RISK"
        color = "#ff4444"
        guidance = "Risk is elevated. Reduce position sizes and hedge."
    else:
        level = "EXTREME RISK"
        color = "#880000"
        guidance = "Extreme risk environment. Defensive positioning recommended."

    return {"level": level, "color": color, "guidance": guidance}


# ---------------------------------------------------------------------------
# Fetch functions (network-dependent, no unit tests)
# ---------------------------------------------------------------------------

def fetch_vix() -> dict:
    """Fetch VIX from yfinance ('^VIX').

    Returns:
        {value: float, change: float} or {value: None, change: None} on error.
    """
    try:
        import yfinance as yf

        vix = yf.Ticker("^VIX")
        hist = vix.history(period="2d")
        if hist.empty or len(hist) < 1:
            return {"value": None, "change": None}

        current = round(float(hist["Close"].iloc[-1]), 2)
        if len(hist) >= 2:
            prev = float(hist["Close"].iloc[-2])
            change = round(current - prev, 2)
        else:
            change = 0.0

        return {"value": current, "change": change}
    except Exception:
        return {"value": None, "change": None}


def fetch_fear_greed() -> dict:
    """Scrape CNN Fear & Greed index.

    Returns:
        {value: int (0-100), label: str} or {value: None, label: 'N/A'} on error.
    """
    try:
        import requests

        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        score = data.get("fear_and_greed", {}).get("score")
        rating = data.get("fear_and_greed", {}).get("rating", "N/A")

        if score is not None:
            return {"value": int(round(score)), "label": rating}
        return {"value": None, "label": "N/A"}
    except Exception:
        return {"value": None, "label": "N/A"}
