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


def compute_fear_greed(breadth_stats, vix_value, new_highs, new_lows):
    """Compute our own Fear & Greed composite from R3000 breadth data.

    Scores 0-100 where 0 = Extreme Fear, 100 = Extreme Greed.
    Based on: % above SMAs, avg RSI, VIX level, new highs vs lows ratio.
    """
    score = 50  # start neutral

    # Breadth: % above 200 SMA (0-100 range, centered at 50)
    pct200 = breadth_stats.get("pct_above_200sma", 50)
    score += (pct200 - 50) * 0.3  # contributes up to ±15

    # Breadth: % above 50 SMA
    pct50 = breadth_stats.get("pct_above_50sma", 50)
    score += (pct50 - 50) * 0.2  # contributes up to ±10

    # RSI: avg RSI (centered at 50)
    avg_rsi = breadth_stats.get("avg_rsi", 50)
    score += (avg_rsi - 50) * 0.3  # contributes up to ±15

    # VIX: lower = greed, higher = fear
    if vix_value:
        if vix_value < 15: score += 10
        elif vix_value < 20: score += 5
        elif vix_value > 30: score -= 15
        elif vix_value > 25: score -= 10
        elif vix_value > 20: score -= 5

    # New highs vs lows ratio
    total = (new_highs or 0) + (new_lows or 0)
    if total > 0:
        hl_ratio = (new_highs or 0) / total  # 0 to 1
        score += (hl_ratio - 0.5) * 20  # contributes up to ±10

    # Clamp to 0-100
    score = max(0, min(100, int(round(score))))

    # Label
    if score <= 20:
        label = "EXTREME FEAR"
    elif score <= 40:
        label = "FEAR"
    elif score <= 60:
        label = "NEUTRAL"
    elif score <= 80:
        label = "GREED"
    else:
        label = "EXTREME GREED"

    return {"value": score, "label": label}


def fetch_fear_greed() -> dict:
    """Try CNN scrape, fallback to None (will use compute_fear_greed instead)."""
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
    except Exception:
        pass
    return {"value": None, "label": "N/A"}


# ---------------------------------------------------------------------------
# Market Regime Detection — equity + fixed income composite
# ---------------------------------------------------------------------------

def compute_regime(risk_stats, prices_cache_func=None):
    """Classify current market regime using equity + fixed income indicators.

    Regimes:
    - RISK-ON: Low vol, broad participation, credit spreads tight, yield curve normal
    - RISK-OFF: High vol, narrow breadth, credit spreads wide, curve inverting
    - TRANSITION: Mixed signals, regime shifting
    - CRISIS: Extreme readings across multiple indicators

    Returns dict with:
    - regime: str (RISK-ON, RISK-OFF, TRANSITION, CRISIS)
    - color: str
    - indicators: list of {name, value, signal, color, weight, score, group}
    - score: float 0-100 (0=extreme risk-off, 100=extreme risk-on)
    - guidance: str
    """
    import yfinance as yf

    indicators = []

    # ---------------------------------------------------------------
    # EQUITY SIGNALS (60% weight)
    # ---------------------------------------------------------------

    # 1. VIX Level (15%)
    vix_val = None
    try:
        vix_data = risk_stats.get("vix", {})
        vix_val = vix_data.get("value") if isinstance(vix_data, dict) else None
    except Exception:
        pass

    if vix_val is None:
        try:
            vix_tk = yf.Ticker("^VIX")
            hist = vix_tk.history(period="2d")
            if not hist.empty:
                vix_val = float(hist["Close"].iloc[-1])
        except Exception:
            pass

    if vix_val is not None:
        if vix_val < 15:
            vix_score = 90
        elif vix_val < 20:
            vix_score = 70
        elif vix_val < 25:
            vix_score = 50
        elif vix_val < 35:
            vix_score = 30
        else:
            vix_score = 10
        vix_signal = "LOW VOL" if vix_score >= 70 else "NEUTRAL" if vix_score >= 50 else "ELEVATED" if vix_score >= 30 else "EXTREME"
        vix_color = "#00ff00" if vix_score >= 70 else "#ffff00" if vix_score >= 50 else "#ff8c00" if vix_score >= 30 else "#ff4444"
        indicators.append({
            "name": "VIX Level", "value": f"{vix_val:.1f}", "signal": vix_signal,
            "color": vix_color, "weight": 0.15, "score": vix_score, "group": "EQUITY",
        })
    else:
        indicators.append({
            "name": "VIX Level", "value": "N/A", "signal": "NO DATA",
            "color": "#999999", "weight": 0.15, "score": 50, "group": "EQUITY",
        })

    # 2. VIX Term Structure (10%)
    vix_ts_score = 50
    vix_ts_val = "N/A"
    try:
        vix_spot = yf.Ticker("^VIX").history(period="2d")
        vix3m = yf.Ticker("^VIX3M").history(period="2d")
        if not vix_spot.empty and not vix3m.empty:
            spot = float(vix_spot["Close"].iloc[-1])
            term = float(vix3m["Close"].iloc[-1])
            if term > 0:
                ratio = spot / term
                if ratio < 1.0:
                    vix_ts_score = 80
                    vix_ts_val = "Contango"
                else:
                    vix_ts_score = 20
                    vix_ts_val = "Backwrdtn"
    except Exception:
        pass

    vix_ts_signal = "RISK-ON" if vix_ts_score >= 60 else "RISK-OFF"
    vix_ts_color = "#00ff00" if vix_ts_score >= 60 else "#ff4444"
    indicators.append({
        "name": "VIX Structure", "value": vix_ts_val, "signal": vix_ts_signal,
        "color": vix_ts_color, "weight": 0.10, "score": vix_ts_score, "group": "EQUITY",
    })

    # 3. Market Breadth (15%)
    breadth = risk_stats.get("breadth", {})
    pct_200 = breadth.get("pct_above_200sma", 50) if isinstance(breadth, dict) else 50
    if pct_200 > 60:
        breadth_score = 85
    elif pct_200 > 40:
        breadth_score = 60
    elif pct_200 > 20:
        breadth_score = 35
    else:
        breadth_score = 15
    breadth_signal = "STRONG" if breadth_score >= 70 else "MODERATE" if breadth_score >= 50 else "WEAK" if breadth_score >= 30 else "POOR"
    breadth_color = "#00ff00" if breadth_score >= 70 else "#ffff00" if breadth_score >= 50 else "#ff8c00" if breadth_score >= 30 else "#ff4444"
    indicators.append({
        "name": "Mkt Breadth", "value": f"{pct_200:.0f}%", "signal": breadth_signal,
        "color": breadth_color, "weight": 0.15, "score": breadth_score, "group": "EQUITY",
    })

    # 4. Advance/Decline (10%)
    adv = risk_stats.get("advancers", 0)
    dec = risk_stats.get("decliners", 0)
    ad_total = adv + dec
    if ad_total > 0:
        ad_ratio = adv / ad_total
        ad_val = f"{ad_ratio:.2f}"
        if ad_ratio > 0.6:
            ad_score = 80
        elif ad_ratio > 0.4:
            ad_score = 50
        else:
            ad_score = 20
    else:
        ad_ratio = 0.5
        ad_val = "N/A"
        ad_score = 50
    ad_signal = "RISK-ON" if ad_score >= 70 else "NEUTRAL" if ad_score >= 40 else "RISK-OFF"
    ad_color = "#00ff00" if ad_score >= 70 else "#ffff00" if ad_score >= 40 else "#ff4444"
    indicators.append({
        "name": "Adv/Dec Ratio", "value": ad_val, "signal": ad_signal,
        "color": ad_color, "weight": 0.10, "score": ad_score, "group": "EQUITY",
    })

    # 5. Put/Call Ratio (10%)
    put_call = risk_stats.get("put_call")
    if isinstance(put_call, dict):
        pc_val = put_call.get("value")
    else:
        pc_val = put_call if isinstance(put_call, (int, float)) else None

    if pc_val is not None and pc_val > 0:
        pc_display = f"{pc_val:.2f}"
        if pc_val < 0.7:
            pc_score = 80
        elif pc_val < 1.0:
            pc_score = 50
        else:
            pc_score = 25
    else:
        pc_display = "N/A"
        pc_score = 50
    pc_signal = "BULLISH" if pc_score >= 70 else "NEUTRAL" if pc_score >= 40 else "FEARFUL"
    pc_color = "#00ff00" if pc_score >= 70 else "#ffff00" if pc_score >= 40 else "#ff4444"
    indicators.append({
        "name": "Put/Call", "value": pc_display, "signal": pc_signal,
        "color": pc_color, "weight": 0.10, "score": pc_score, "group": "EQUITY",
    })

    # ---------------------------------------------------------------
    # FIXED INCOME SIGNALS (40% weight)
    # ---------------------------------------------------------------

    # 6. Yield Curve Slope (15%)
    yc_score = 50
    yc_val = "N/A"
    try:
        tnx = yf.Ticker("^TNX").history(period="5d")
        irx = yf.Ticker("^IRX").history(period="5d")
        if not tnx.empty and not irx.empty:
            y10 = float(tnx["Close"].iloc[-1])
            y_short = float(irx["Close"].iloc[-1])
            spread = y10 - y_short
            yc_val = f"{spread:+.2f}%"
            if spread > 1.0:
                yc_score = 85
            elif spread > 0.25:
                yc_score = 70
            elif spread > 0:
                yc_score = 55
            elif spread > -0.5:
                yc_score = 30
            else:
                yc_score = 15
    except Exception:
        pass

    yc_signal = "NORMAL" if yc_score >= 65 else "FLAT" if yc_score >= 45 else "INVERTED" if yc_score >= 25 else "DEEPLY INV"
    yc_color = "#00ff00" if yc_score >= 65 else "#ffff00" if yc_score >= 45 else "#ff8c00" if yc_score >= 25 else "#ff4444"
    indicators.append({
        "name": "Yield Curve", "value": yc_val, "signal": yc_signal,
        "color": yc_color, "weight": 0.15, "score": yc_score, "group": "FIXED INCOME",
    })

    # 7. Credit Spreads proxy — HYG/IEF ratio vs 50d SMA (15%)
    cs_score = 50
    cs_val = "N/A"
    try:
        hyg_hist = yf.Ticker("HYG").history(period="90d")
        ief_hist = yf.Ticker("IEF").history(period="90d")
        if not hyg_hist.empty and not ief_hist.empty and len(hyg_hist) >= 50 and len(ief_hist) >= 50:
            # Align on common dates
            hyg_c = hyg_hist["Close"]
            ief_c = ief_hist["Close"]
            ratio = hyg_c / ief_c
            ratio = ratio.dropna()
            if len(ratio) >= 50:
                sma50 = ratio.rolling(50).mean().iloc[-1]
                current = ratio.iloc[-1]
                if sma50 > 0:
                    pct_vs_sma = (current - sma50) / sma50 * 100
                    if pct_vs_sma > 0.5:
                        cs_score = 80
                        cs_val = "Tightenng"
                    elif pct_vs_sma > -0.5:
                        cs_score = 55
                        cs_val = "Stable"
                    elif pct_vs_sma > -1.5:
                        cs_score = 30
                        cs_val = "Widening"
                    else:
                        cs_score = 15
                        cs_val = "Stress"
    except Exception:
        pass

    cs_signal = "RISK-ON" if cs_score >= 65 else "NEUTRAL" if cs_score >= 45 else "STRESS" if cs_score >= 25 else "CRISIS"
    cs_color = "#00ff00" if cs_score >= 65 else "#ffff00" if cs_score >= 45 else "#ff8c00" if cs_score >= 25 else "#ff4444"
    indicators.append({
        "name": "Credit Spreads", "value": cs_val, "signal": cs_signal,
        "color": cs_color, "weight": 0.15, "score": cs_score, "group": "FIXED INCOME",
    })

    # 8. Dollar Strength — UUP proxy (10%)
    dx_score = 50
    dx_val = "N/A"
    try:
        uup_hist = yf.Ticker("UUP").history(period="60d")
        if not uup_hist.empty and len(uup_hist) >= 20:
            uup_c = uup_hist["Close"]
            sma20 = uup_c.rolling(20).mean().iloc[-1]
            current = uup_c.iloc[-1]
            if sma20 > 0:
                pct = (current - sma20) / sma20 * 100
                if pct > 0.5:
                    dx_score = 30
                    dx_val = "Rising"
                elif pct > -0.5:
                    dx_score = 55
                    dx_val = "Stable"
                else:
                    dx_score = 70
                    dx_val = "Falling"
    except Exception:
        pass

    dx_signal = "RISK-ON" if dx_score >= 60 else "NEUTRAL" if dx_score >= 40 else "HEADWIND"
    dx_color = "#00ff00" if dx_score >= 60 else "#ffff00" if dx_score >= 40 else "#ff8c00"
    indicators.append({
        "name": "Dollar (UUP)", "value": dx_val, "signal": dx_signal,
        "color": dx_color, "weight": 0.10, "score": dx_score, "group": "FIXED INCOME",
    })

    # ---------------------------------------------------------------
    # Composite score (weighted average)
    # ---------------------------------------------------------------
    total_weight = sum(ind["weight"] for ind in indicators)
    if total_weight > 0:
        composite = sum(ind["score"] * ind["weight"] for ind in indicators) / total_weight
    else:
        composite = 50.0

    composite = round(composite, 1)

    # Regime classification
    if composite >= 75:
        regime = "RISK-ON"
        color = "#00ff00"
        guidance = ("Risk-on environment. Broad participation, low volatility, "
                    "and favorable credit conditions support equity exposure. "
                    "Lean into beta, extend duration selectively.")
    elif composite >= 50:
        regime = "TRANSITION"
        color = "#ffff00"
        guidance = ("Mixed signals — regime shifting. Monitor breadth and credit "
                    "spreads for directional confirmation. Maintain current "
                    "positioning, tighten risk limits.")
    elif composite >= 25:
        regime = "RISK-OFF"
        color = "#ff8c00"
        guidance = ("Risk-off environment. Favor quality over beta, reduce net "
                    "exposure, tighten stops. Credit stress emerging — "
                    "underweight HY, favor IG and duration.")
    else:
        regime = "CRISIS"
        color = "#ff4444"
        guidance = ("Crisis conditions across multiple indicators. Defensive "
                    "positioning required. Maximize cash, hedge tail risk, "
                    "favor Treasuries and gold. Avoid credit.")

    return {
        "regime": regime,
        "color": color,
        "indicators": indicators,
        "score": composite,
        "guidance": guidance,
    }
