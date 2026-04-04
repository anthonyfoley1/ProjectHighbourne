"""Investment Thesis Barometer -- weighted factor scoring for conviction signals."""

from dash import html
import pandas as pd
import numpy as np

import data.startup as startup
from data.market_data import fetch_earnings_history
from data.technicals import compute_rsi, compute_macd, compute_sma, detect_crossovers, macd_signal_label
from theme import C, FONT_FAMILY


# ---------------------------------------------------------------------------
# Factor scoring helpers
# ---------------------------------------------------------------------------

def _score_valuation(ticker_obj):
    """Score 0-100 based on most extreme z-score across ratios. Low z = cheap = high score."""
    ratios = ["P/E", "P/S", "P/B", "EV/EBITDA"]
    best_z = None
    for r in ratios:
        s = ticker_obj.stats(r)
        if s and s["z_score"] is not None:
            if best_z is None or abs(s["z_score"]) > abs(best_z):
                best_z = s["z_score"]
    if best_z is None:
        return 50, "N/A"

    z = best_z
    if z < -2:
        score, label = 90, "Very Cheap"
    elif z < -1:
        score, label = 75, "Cheap"
    elif z < -0.5:
        score, label = 60, "Modest Disc."
    elif z <= 0.5:
        score, label = 50, "Fair"
    elif z <= 1:
        score, label = 40, "Slightly Rich"
    elif z <= 2:
        score, label = 25, "Rich"
    else:
        score, label = 10, "Very Rich"
    return score, label


def _score_technicals(prices, symbol):
    """Score 0-100 based on RSI, MACD, SMA200, and crossovers."""
    if prices is None or len(prices) < 30:
        return 50, "N/A"

    points = 0

    # RSI
    rsi_series = compute_rsi(prices, 14)
    rsi = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0
    if rsi < 30:
        points += 30
    elif rsi <= 70:
        points += 15
    # RSI > 70: +0

    # MACD
    macd_line, signal_line, _ = compute_macd(prices)
    macd_sig = macd_signal_label(macd_line, signal_line) if not macd_line.empty else "Flat"
    if macd_sig == "Bull":
        points += 20
    elif macd_sig == "Flat":
        points += 10
    # Bear: +0

    # SMA 200
    current_price = float(prices.iloc[-1])
    sma200 = compute_sma(prices, 200) if len(prices) > 200 else pd.Series(dtype=float)
    above_200 = False
    if not sma200.empty:
        above_200 = current_price >= float(sma200.iloc[-1])
        points += 20 if above_200 else 5

    # Golden cross detection (SMA50 crossing above SMA200 recently)
    if len(prices) > 200:
        sma50 = compute_sma(prices, 50)
        if not sma50.empty and not sma200.empty:
            crossovers = detect_crossovers(sma50, sma200)
            # Check last 20 days for golden cross
            recent = crossovers.tail(20)
            if not recent.empty and (recent > 0).any():
                points += 10

    # Normalize: max theoretical = 70+10 = 80
    score = min(100, int(points / 70 * 100))

    if score >= 70:
        label = "Bullish"
    elif score >= 40:
        label = "Neutral"
    else:
        label = "Oversold" if rsi < 35 else "Bearish"
    return score, label


def _score_momentum(prices):
    """Score 0-100 based on 90D trend, 52W range position, and 1D return."""
    if prices is None or len(prices) < 5:
        return 50, "N/A"

    points = 0
    current = float(prices.iloc[-1])

    # 90D trend
    lookback = min(len(prices), 63)
    price_90d_ago = float(prices.iloc[-lookback])
    trend_90d = (current - price_90d_ago) / price_90d_ago if price_90d_ago != 0 else 0
    if trend_90d > 0:
        points += 30
    else:
        points += 10

    # 52W range position (contrarian: bottom = bullish)
    lookback_252 = min(len(prices), 252)
    low_52w = float(prices.iloc[-lookback_252:].min())
    high_52w = float(prices.iloc[-lookback_252:].max())
    if high_52w > low_52w:
        pct_range = (current - low_52w) / (high_52w - low_52w)
    else:
        pct_range = 0.5
    if pct_range < 0.25:
        points += 25  # contrarian: near lows = opportunity
    elif pct_range > 0.75:
        points += 10
    else:
        points += 17

    # 1D return
    if len(prices) >= 2:
        ret_1d = (current - float(prices.iloc[-2])) / float(prices.iloc[-2])
        points += 10 if ret_1d > 0 else 5
    else:
        points += 7

    # Normalize: max = 30 + 25 + 10 = 65
    score = min(100, int(points / 65 * 100))

    if score >= 65:
        label = "Strong"
    elif score >= 40:
        label = "Moderate"
    else:
        label = "Weak"
    return score, label


def _score_short_interest(symbol, valuation_score, technicals_score):
    """Score 0-100 based on short interest percentage."""
    row = None
    if not startup.screener_df.empty:
        matches = startup.screener_df[startup.screener_df["symbol"] == symbol]
        if not matches.empty:
            row = matches.iloc[0]

    si = None
    if row is not None:
        si = row.get("short_interest")

    if si is None or pd.isna(si):
        return 50, "N/A"

    si = float(si)

    # Squeeze setup bonus: high SI + cheap + oversold
    if si > 10 and valuation_score >= 65 and technicals_score <= 35:
        return 70, "Squeeze?"

    if si < 5:
        score, label = 50, "Normal"
    elif si < 10:
        score, label = 45, "Sl. Elevated"
    elif si < 20:
        score, label = 35, "Elevated"
    else:
        score, label = 25, "Heavy Short"
    return score, label


def _score_analysts(info, price_val):
    """Score 0-100 based on analyst price target upside."""
    pt = info.get("PT") if info else None
    if pt is None or price_val is None or price_val <= 0:
        return 50, "N/A"

    upside = (pt - price_val) / price_val

    if upside > 0.30:
        score, label = 85, "Bullish"
    elif upside > 0.15:
        score, label = 70, "Positive"
    elif upside > 0:
        score, label = 55, "Modest"
    else:
        score, label = 30, "Bearish"
    return score, label


def _score_market_risk():
    """Score 0-100 based on startup.risk_stats verdict level."""
    risk = getattr(startup, "risk_stats", None) or {}
    verdict = risk.get("verdict", {})
    level = verdict.get("level", "MODERATE")

    level_map = {
        "LOW RISK": (80, "Low Risk"),
        "MODERATE": (55, "Moderate"),
        "ELEVATED RISK": (30, "Elevated"),
        "EXTREME RISK": (15, "Extreme"),
    }
    return level_map.get(level, (55, "Moderate"))


# ---------------------------------------------------------------------------
# Main compute function
# ---------------------------------------------------------------------------

FACTOR_WEIGHTS = {
    "Valuation":  0.30,
    "Technicals":  0.25,
    "Momentum":    0.15,
    "Short Int":   0.10,
    "Analysts":    0.10,
    "Earnings":    0.10,
}


def compute_barometer(symbol, info=None):
    """Compute 0-100 conviction score from all factors.

    Parameters
    ----------
    symbol : str
        Ticker symbol.
    info : dict, optional
        yfinance info dict (for PT).  If None some factors degrade gracefully.

    Returns
    -------
    dict with keys: composite, label, color, factors
    """
    ticker_obj = startup.universe.get(symbol) if startup.universe else None
    prices = startup.price_cache.get(symbol) if hasattr(startup, "price_cache") else None
    price_val = float(prices.iloc[-1]) if prices is not None and not prices.empty else None

    # --- Factor scores ---
    val_score, val_label = _score_valuation(ticker_obj) if ticker_obj else (50, "N/A")
    tech_score, tech_label = _score_technicals(prices, symbol)
    mom_score, mom_label = _score_momentum(prices)
    si_score, si_label = _score_short_interest(symbol, val_score, tech_score)
    ana_score, ana_label = _score_analysts(info, price_val)
    earn_score, earn_label = _score_earnings(symbol)

    factors = {
        "Valuation":  {"score": val_score,  "label": val_label,  "weight": FACTOR_WEIGHTS["Valuation"]},
        "Technicals": {"score": tech_score, "label": tech_label, "weight": FACTOR_WEIGHTS["Technicals"]},
        "Momentum":   {"score": mom_score,  "label": mom_label,  "weight": FACTOR_WEIGHTS["Momentum"]},
        "Short Int":  {"score": si_score,   "label": si_label,   "weight": FACTOR_WEIGHTS["Short Int"]},
        "Analysts":   {"score": ana_score,  "label": ana_label,  "weight": FACTOR_WEIGHTS["Analysts"]},
        "Earnings":   {"score": earn_score, "label": earn_label, "weight": FACTOR_WEIGHTS["Earnings"]},
    }

    # Weighted composite
    composite = sum(f["score"] * f["weight"] for f in factors.values())
    composite = int(round(composite))

    if composite > 65:
        label, color = "O/W", C["green"]
    elif composite >= 35:
        label, color = "M/W", C["gray"]
    else:
        label, color = "U/W", C["red"]

    return {
        "composite": composite,
        "label": label,
        "color": color,
        "factors": factors,
    }


# ---------------------------------------------------------------------------
# Visual component builder
# ---------------------------------------------------------------------------

def _bar_color(score):
    if score > 65:
        return C["green"]
    elif score >= 35:
        return C["yellow"]
    return C["red"]


def build_barometer(barometer_data):
    """Build the visual barometer HTML component for the detail page."""
    if barometer_data is None:
        return html.Div()

    composite = barometer_data["composite"]
    label = barometer_data["label"]
    color = barometer_data["color"]
    factors = barometer_data["factors"]

    # -- Header row --
    header = html.Div(
        style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "6px"},
        children=[
            html.Span("INVESTMENT THESIS", style={
                "color": C["orange"], "fontSize": "11px", "fontWeight": "bold",
                "letterSpacing": "1px", "fontFamily": FONT_FAMILY,
            }),
            html.Span(label, style={
                "color": color, "fontSize": "11px", "fontWeight": "bold",
                "border": f"1px solid {color}", "padding": "1px 8px",
                "fontFamily": FONT_FAMILY,
            }),
        ],
    )

    # -- Composite gauge bar --
    pct = max(0, min(100, composite))
    gauge = html.Div(
        style={"marginBottom": "10px"},
        children=[
            html.Div(
                style={"position": "relative", "height": "14px", "marginBottom": "4px"},
                children=[
                    # Track
                    html.Div(style={
                        "position": "absolute", "top": "5px", "left": "0", "right": "0",
                        "height": "4px", "backgroundColor": "#333", "borderRadius": "2px",
                    }),
                    # Dot marker
                    html.Div(style={
                        "position": "absolute", "top": "2px",
                        "left": f"calc({pct}% - 5px)",
                        "width": "10px", "height": "10px",
                        "borderRadius": "50%", "backgroundColor": color,
                        "border": "1px solid #fff",
                    }),
                ],
            ),
            # Labels below gauge
            html.Div(
                style={"display": "flex", "justifyContent": "space-between", "fontSize": "8px", "fontFamily": FONT_FAMILY},
                children=[
                    html.Span("U/W", style={"color": C["red"]}),
                    html.Span(str(composite), style={"color": color, "fontWeight": "bold", "fontSize": "10px"}),
                    html.Span("O/W", style={"color": C["green"]}),
                ],
            ),
        ],
    )

    # -- Per-factor rows --
    factor_rows = []
    for name, f in factors.items():
        score = f["score"]
        flabel = f["label"]
        bar_col = _bar_color(score)
        fill_pct = max(0, min(100, score))

        row = html.Div(
            style={"display": "flex", "alignItems": "center", "marginBottom": "3px", "fontSize": "9px", "fontFamily": FONT_FAMILY},
            children=[
                # Factor name
                html.Span(name, style={"color": C["gray"], "width": "70px", "flexShrink": "0"}),
                # Bar
                html.Div(
                    style={"flex": "1", "height": "8px", "backgroundColor": "#222", "borderRadius": "2px", "marginRight": "6px", "overflow": "hidden"},
                    children=[
                        html.Div(style={
                            "width": f"{fill_pct}%", "height": "100%",
                            "backgroundColor": bar_col, "borderRadius": "2px",
                        }),
                    ],
                ),
                # Score number
                html.Span(str(score), style={"color": C["white"], "width": "22px", "textAlign": "right", "marginRight": "6px", "fontWeight": "bold"}),
                # Descriptive label
                html.Span(flabel, style={"color": bar_col, "width": "70px", "textAlign": "right"}),
            ],
        )
        factor_rows.append(row)

    return html.Div([
        header,
        html.Hr(style={"borderColor": C["border"], "margin": "4px 0 8px 0"}),
        gauge,
        html.Div(factor_rows),
    ])
