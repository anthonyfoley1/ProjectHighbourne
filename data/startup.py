"""Startup data pipeline -- pre-computes all data at app launch.

Call init() once from app.py before running the server.
Pages import the module-level variables directly.
"""

from data.loader import load_tickers, load_market_data, compute_all_ratios
from data.market_data import compute_returns, compute_52w_range
from data.technicals import (
    compute_rsi, compute_macd, compute_sma,
    macd_signal_label, ma_trend_label,
)
from data.risk import (
    fetch_vix, fetch_fear_greed, compute_fear_greed, compute_breadth_stats,
    compute_new_highs_lows, compute_advancers_decliners, compute_risk_verdict,
)
from data.sectors import (
    compute_sector_returns, compute_sector_normalized_series, SECTOR_COLORS,
)
from models.ticker import Universe, Ticker, compute_alert, compute_signal_label
import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Module-level variables -- populated by init()
# ---------------------------------------------------------------------------
universe: Universe = None
screener_df: pd.DataFrame = pd.DataFrame()
risk_stats: dict = {}
sector_data: dict = {}
price_cache: dict = {}
ticker_info_cache: dict = {}
ticker_sector: dict = {}
ticker_name: dict = {}
close_prices: pd.DataFrame = pd.DataFrame()


def init():
    """Load all data, build Universe, compute technicals / screener / risk."""
    global universe, screener_df, risk_stats, sector_data
    global price_cache, ticker_info_cache, ticker_sector, ticker_name, close_prices

    # ------------------------------------------------------------------
    # 1. Load tickers
    # ------------------------------------------------------------------
    print("Loading tickers...")
    tickers_df = load_tickers()
    ticker_sector = dict(zip(tickers_df["Ticker"], tickers_df["Sector"]))
    ticker_name = dict(zip(tickers_df["Ticker"], tickers_df["Name"]))

    # ------------------------------------------------------------------
    # 2. Load market data (SimFin)
    # ------------------------------------------------------------------
    print("Loading market data...")
    mktcap, close_prices = load_market_data(years=5)

    # ------------------------------------------------------------------
    # 3. Compute valuation ratios
    # ------------------------------------------------------------------
    print("Computing ratios...")
    ratio_dfs = compute_all_ratios(mktcap)

    # ------------------------------------------------------------------
    # 4. Build Universe
    # ------------------------------------------------------------------
    print("Building universe...")
    universe = Universe()
    for sym, sector in ticker_sector.items():
        t = Ticker(sym, sector=sector)
        for ratio_name, ratio_df in ratio_dfs.items():
            if sym in ratio_df.columns:
                t.set_ratio(ratio_name, ratio_df[sym].dropna())
        universe.add_ticker(t)

    # ------------------------------------------------------------------
    # 5. Build price_cache
    # ------------------------------------------------------------------
    print("Building price cache...")
    price_cache = {}
    for sym in close_prices.columns:
        price_cache[sym] = close_prices[sym].dropna()

    # ------------------------------------------------------------------
    # 6. Compute technicals & 7. Build screener_df
    # ------------------------------------------------------------------
    print("Computing technicals...")
    screener_rows = []
    above_200sma = {}
    above_50sma = {}
    rsi_values = {}
    returns_1d = {}

    for sym in universe.symbols:
        prices = price_cache.get(sym)
        if prices is None or len(prices) < 50:
            continue

        # Technicals
        rsi_series = compute_rsi(prices, 14)
        macd_line, signal_line, _ = compute_macd(prices, 12, 26, 9)
        sma50 = compute_sma(prices, 50)
        sma200 = compute_sma(prices, 200)

        ret_1d, ret_3d = compute_returns(prices)
        low_52w, high_52w, pct_52w = compute_52w_range(prices)

        current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50.0
        current_macd = macd_line.iloc[-1] if not macd_line.empty else 0.0
        current_signal = signal_line.iloc[-1] if not signal_line.empty else 0.0
        current_sma50 = sma50.iloc[-1] if not sma50.empty else np.nan
        current_sma200 = sma200.iloc[-1] if not sma200.empty else np.nan
        current_price = prices.iloc[-1]

        macd_sig = macd_signal_label(macd_line, signal_line)
        ma_trend = ma_trend_label(current_price, current_sma200)

        # Collect breadth data
        if not np.isnan(current_sma200):
            above_200sma[sym] = current_price >= current_sma200
        if not np.isnan(current_sma50):
            above_50sma[sym] = current_price >= current_sma50
        if not np.isnan(current_rsi):
            rsi_values[sym] = float(current_rsi)
        returns_1d[sym] = ret_1d

        # Find most extreme z-score across ratios
        best_z = 0.0
        best_ratio = None
        for ratio_name in ["P/E", "P/S", "P/B", "EV/EBITDA"]:
            ticker_obj = universe.get(sym)
            if ticker_obj is None:
                continue
            try:
                s = ticker_obj.stats(ratio_name)
                if s and s["z_score"] is not None:
                    if abs(s["z_score"]) > abs(best_z):
                        best_z = s["z_score"]
                        best_ratio = ratio_name
            except Exception:
                continue

        # Alert / signal
        alert = compute_alert(best_z, current_rsi, macd_sig, ma_trend)
        signal = compute_signal_label(best_z, alert["type"])

        screener_rows.append({
            "symbol": sym,
            "name": ticker_name.get(sym, ""),
            "sector": ticker_sector.get(sym, "Unknown"),
            "rv_sig": best_ratio,
            "z_score": round(best_z, 2),
            "rsi": round(float(current_rsi), 1),
            "macd": round(float(current_macd), 4),
            "ret_1d": round(ret_1d * 100, 2),
            "ret_3d": round(ret_3d * 100, 2),
            "signal": signal,
            "alert_type": alert["type"],
            "alert_reason": alert["reason"],
            "ma_trend": ma_trend,
            "low_52w": low_52w,
            "high_52w": high_52w,
            "pct_52w": round(pct_52w, 3) if pct_52w is not None else None,
            "price": round(float(current_price), 2),
        })

    screener_df = pd.DataFrame(screener_rows).sort_values("z_score", ascending=True)
    print(f"  Screener built: {len(screener_df)} tickers")

    # ------------------------------------------------------------------
    # 8. Risk stats
    # ------------------------------------------------------------------
    print("Computing risk stats...")
    vix = {"value": None, "change": None}
    fear_greed = {"value": None, "label": "N/A"}
    try:
        vix = fetch_vix()
    except Exception:
        print("  Warning: fetch_vix failed, using defaults")
    try:
        fear_greed = fetch_fear_greed()
    except Exception:
        print("  Warning: fetch_fear_greed failed, using defaults")

    breadth = compute_breadth_stats(above_200sma, above_50sma, rsi_values)
    adv, dec, unch = compute_advancers_decliners(returns_1d)
    new_highs, new_lows = compute_new_highs_lows(price_cache)

    # If CNN scrape failed, compute our own fear/greed from breadth data
    if fear_greed.get("value") is None:
        fear_greed = compute_fear_greed(breadth, vix.get("value"), new_highs, new_lows)
        print(f"  Computed Fear & Greed: {fear_greed['value']} ({fear_greed['label']})")

    risk_input = {
        "vix": vix.get("value") or 0,
        "fear_greed": fear_greed.get("value") or 50,
        "pct_above_200sma": breadth["pct_above_200sma"],
        "pct_above_50sma": breadth["pct_above_50sma"],
        "avg_rsi": breadth["avg_rsi"],
        "new_highs": new_highs,
        "new_lows": new_lows,
    }
    verdict = compute_risk_verdict(risk_input)

    risk_stats = {
        "vix": vix,
        "fear_greed": fear_greed,
        "breadth": breadth,
        "advancers": adv,
        "decliners": dec,
        "unchanged": unch,
        "new_highs": new_highs,
        "new_lows": new_lows,
        "verdict": verdict,
    }

    # ------------------------------------------------------------------
    # 9. Sector data
    # ------------------------------------------------------------------
    print("Computing sector data...")
    sector_returns = compute_sector_returns(returns_1d, ticker_sector)

    # Build sector -> [tickers] mapping
    sector_tickers_map = {}
    for sym, sec in ticker_sector.items():
        sector_tickers_map.setdefault(sec, []).append(sym)

    sector_norm = compute_sector_normalized_series(sector_tickers_map, price_cache)

    sector_data = {
        "returns": sector_returns,
        "normalized": sector_norm,
        "colors": SECTOR_COLORS,
    }

    print("Startup complete.")
