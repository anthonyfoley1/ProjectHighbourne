"""Ticker and Universe classes for valuation analysis."""

import pandas as pd
import numpy as np
from datetime import timedelta


class Ticker:
    """A single stock with its valuation ratios over time."""

    def __init__(self, symbol, sector=None):
        self.symbol = symbol
        self.sector = sector
        self.ratios = {}  # {"P/B": pd.Series, "P/S": pd.Series, ...}

    def set_ratio(self, name, series):
        self.ratios[name] = series

    def get_ratio(self, name):
        return self.ratios.get(name, pd.Series(dtype=float))

    def stats(self, ratio_name, window_days=None):
        """
        Compute mean, std, current value, z-score for a ratio.
        If window_days is set, only use data within that window.
        Stats are computed ONLY on the window — no data leakage.
        """
        series = self.get_ratio(ratio_name).dropna()
        if series.empty:
            return None

        if window_days:
            cutoff = series.index.max() - timedelta(days=window_days)
            series = series[series.index >= cutoff]

        if len(series) < 10:
            return None

        current = series.iloc[-1]
        mean = series.mean()
        std = series.std()
        z = (current - mean) / std if std > 0 else 0.0

        return {
            "current": current,
            "mean": mean,
            "std": std,
            "z_score": z,
            "low": series.min(),
            "high": series.max(),
            "pct_from_mean": (current - mean) / mean * 100 if mean != 0 else 0,
        }

    def window_series(self, ratio_name, window_days=None):
        """Get ratio series sliced to a time window."""
        series = self.get_ratio(ratio_name).dropna()
        if series.empty:
            return series
        if window_days:
            cutoff = series.index.max() - timedelta(days=window_days)
            series = series[series.index >= cutoff]
        return series


class Universe:
    """Collection of all tickers with cross-sectional analysis."""

    WINDOWS = {
        "5Y": 5 * 365,
        "2Y": 2 * 365,
        "6M": 182,
    }

    def __init__(self):
        self.tickers = {}  # {symbol: Ticker}
        self.sectors = {}  # {symbol: sector_name}

    def add_ticker(self, ticker):
        self.tickers[ticker.symbol] = ticker
        if ticker.sector:
            self.sectors[ticker.symbol] = ticker.sector

    def get(self, symbol):
        return self.tickers.get(symbol)

    @property
    def symbols(self):
        return sorted(self.tickers.keys())

    @property
    def sector_list(self):
        return sorted(set(self.sectors.values()))

    def symbols_in_sector(self, sector):
        return sorted(s for s, sec in self.sectors.items() if sec == sector)

    def screener(self, ratio_name, window_name="2Y"):
        """
        Build a screener DataFrame: one row per ticker with z-score stats.
        Sorted by z-score (most negative = cheapest first).
        """
        window_days = self.WINDOWS.get(window_name)
        rows = []
        for symbol, ticker in self.tickers.items():
            s = ticker.stats(ratio_name, window_days)
            if s is None:
                continue
            rows.append({
                "Ticker": symbol,
                "Sector": ticker.sector or "Unknown",
                "Current": round(s["current"], 2),
                "Mean": round(s["mean"], 2),
                "Std": round(s["std"], 2),
                "Z-Score": round(s["z_score"], 2),
                "Low": round(s["low"], 2),
                "High": round(s["high"], 2),
                "% from Mean": round(s["pct_from_mean"], 1),
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows).sort_values("Z-Score")
        return df

    def sector_medians(self, ratio_name, window_name="2Y"):
        """Compute median ratio per sector for a given window."""
        window_days = self.WINDOWS.get(window_name)
        rows = []
        for sector in self.sector_list:
            symbols = self.symbols_in_sector(sector)
            values = []
            for s in symbols:
                ticker = self.get(s)
                if ticker is None:
                    continue
                st = ticker.stats(ratio_name, window_days)
                if st:
                    values.append(st["current"])
            if values:
                rows.append({
                    "Sector": sector,
                    "Median": round(np.median(values), 2),
                    "Count": len(values),
                    "25th": round(np.percentile(values, 25), 2),
                    "75th": round(np.percentile(values, 75), 2),
                })
        return pd.DataFrame(rows).sort_values("Median")


# ---------------------------------------------------------------------------
# Standalone alert / scoring functions (Task 6)
# ---------------------------------------------------------------------------

def compute_alert(z_score, rsi, macd_signal, ma_trend):
    """Compute BUY/SELL alert based on z-score, RSI, and MACD signal.

    BUY:  z_score < -1.5 AND (RSI < 30 OR macd_signal == 'Bull')
    SELL: z_score >  1.5 AND (RSI > 70 OR macd_signal == 'Bear')
    Returns: {type: 'BUY'|'SELL'|None, reason: str}
    """
    if z_score < -1.5 and (rsi < 30 or macd_signal == "Bull"):
        reasons = []
        reasons.append(f"z={z_score:.2f}")
        if rsi < 30:
            reasons.append(f"RSI={rsi}")
        if macd_signal == "Bull":
            reasons.append("MACD Bull")
        return {"type": "BUY", "reason": ", ".join(reasons)}

    if z_score > 1.5 and (rsi > 70 or macd_signal == "Bear"):
        reasons = []
        reasons.append(f"z={z_score:.2f}")
        if rsi > 70:
            reasons.append(f"RSI={rsi}")
        if macd_signal == "Bear":
            reasons.append("MACD Bear")
        return {"type": "SELL", "reason": ", ".join(reasons)}

    return {"type": None, "reason": ""}


def compute_composite_score(z_score, rsi, macd_signal, peer_return, pt_upside):
    """Composite scoring for OVERWEIGHT / MARKET WEIGHT / UNDERWEIGHT.

    Score points:
      z < -1.5 -> +3,  z < -0.5 -> +1,  z > 1.5 -> -3,  z > 0.5 -> -1
      RSI < 30 -> +2,  RSI > 70 -> -2
      MACD Bull -> +1, Bear -> -1
      peer_return < -0.10 -> +1,  > 0.15 -> -1
      pt_upside > 0.30 -> +1,  < -0.15 -> -1

    score >= 4  -> OVERWEIGHT  (#00ff00)
    score <= -4 -> UNDERWEIGHT (#ff4444)
    else        -> MARKET WEIGHT (#999999)

    Returns: {label, color, score}
    """
    score = 0

    # z-score contribution
    if z_score < -1.5:
        score += 3
    elif z_score < -0.5:
        score += 1
    elif z_score > 1.5:
        score -= 3
    elif z_score > 0.5:
        score -= 1

    # RSI
    if rsi < 30:
        score += 2
    elif rsi > 70:
        score -= 2

    # MACD
    if macd_signal == "Bull":
        score += 1
    elif macd_signal == "Bear":
        score -= 1

    # Peer return
    if peer_return < -0.10:
        score += 1
    elif peer_return > 0.15:
        score -= 1

    # Price-target upside
    if pt_upside > 0.30:
        score += 1
    elif pt_upside < -0.15:
        score -= 1

    if score >= 4:
        return {"label": "OVERWEIGHT", "color": "#00ff00", "score": score}
    elif score <= -4:
        return {"label": "UNDERWEIGHT", "color": "#ff4444", "score": score}
    else:
        return {"label": "MARKET WEIGHT", "color": "#999999", "score": score}


def compute_signal_label(z_score, alert_type):
    """Signal badge for display.

    If alert_type is BUY or SELL, return that string.
    Otherwise: z < -0.75 -> CHEAP, z > 0.75 -> RICH, else FAIR.
    """
    if alert_type in ("BUY", "SELL"):
        return alert_type
    if z_score < -0.75:
        return "CHEAP"
    if z_score > 0.75:
        return "RICH"
    return "FAIR"
