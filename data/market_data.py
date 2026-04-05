"""
Market data helpers: pure computation functions and yfinance fetch wrappers.
"""

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None  # fetch functions will fail gracefully if yfinance is not installed


# ---------------------------------------------------------------------------
# Pure computation functions
# ---------------------------------------------------------------------------

def compute_returns(prices: pd.Series) -> tuple[float, float]:
    """Compute 1-day and 3-day returns from a price Series.

    1d = (last - second_to_last) / second_to_last
    3d = (last - fourth_to_last) / fourth_to_last

    Returns (0.0, 0.0) if fewer than 4 prices.
    """
    if len(prices) < 4:
        return 0.0, 0.0
    last = prices.iloc[-1]
    ret_1d = (last - prices.iloc[-2]) / prices.iloc[-2]
    ret_3d = (last - prices.iloc[-3]) / prices.iloc[-3]
    return ret_1d, ret_3d


def compute_52w_range(prices: pd.Series) -> tuple[float | None, float | None, float | None]:
    """Compute 52-week low, high, and current percentile position (0-1).

    Uses the last 252 trading days of the series.
    Returns (None, None, None) if the series is empty.
    """
    if prices.empty:
        return None, None, None
    window = prices.iloc[-252:]
    low = float(window.min())
    high = float(window.max())
    current = float(window.iloc[-1])
    if high == low:
        pct = 0.5
    else:
        pct = (current - low) / (high - low)
    return low, high, pct


def compute_relative_volume(volume: pd.Series, lookback: int = 10) -> float:
    """Current volume relative to trailing lookback-day average.

    Returns 1.0 if insufficient data.
    """
    if len(volume) < lookback + 1:
        return 1.0
    trailing_avg = volume.iloc[-(lookback + 1):-1].mean()
    if trailing_avg == 0:
        return 1.0
    return float(volume.iloc[-1] / trailing_avg)


# ---------------------------------------------------------------------------
# Fetch functions (require yfinance; not unit tested)
# ---------------------------------------------------------------------------

def fetch_ticker_info(symbol: str) -> dict:
    """Fetch ticker info from yfinance.

    Returns a dict with: description, sector, industry, PT, market_cap, beta,
    shares_outstanding, float, inst_ownership, short_ratio, div_yield,
    prev_close, open, day_high, day_low, volume, avg_volume_3m,
    52w_high, 52w_low, next_earnings, news.
    """
    ticker = yf.Ticker(symbol)
    info = ticker.info or {}

    # Gather news
    try:
        news_raw = ticker.news or []
        news = [
            {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "publisher": item.get("publisher", ""),
                "timestamp": item.get("providerPublishTime"),
            }
            for item in news_raw
        ]
    except Exception:
        news = []

    # Attempt to get next earnings date
    try:
        cal = ticker.calendar
        if isinstance(cal, dict):
            next_earnings = cal.get("Earnings Date", [None])[0]
        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            next_earnings = cal.iloc[0, 0]
        else:
            next_earnings = None
    except Exception:
        next_earnings = None

    # Forward estimates
    forward_eps = info.get("forwardEps")
    forward_pe = info.get("forwardPE")
    earnings_growth = info.get("earningsGrowth")
    revenue_growth = info.get("revenueGrowth")

    return {
        "description": info.get("longBusinessSummary"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "PT": info.get("targetMeanPrice"),
        "market_cap": info.get("marketCap"),
        "beta": info.get("beta"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "float": info.get("floatShares"),
        "inst_ownership": info.get("heldPercentInstitutions"),
        "short_ratio": info.get("shortRatio"),
        "div_yield": info.get("dividendYield"),
        "prev_close": info.get("previousClose"),
        "open": info.get("open"),
        "day_high": info.get("dayHigh"),
        "day_low": info.get("dayLow"),
        "volume": info.get("volume"),
        "avg_volume_3m": info.get("averageVolume"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "next_earnings": next_earnings,
        "news": news,
        # Company details
        "website": info.get("website"),
        "city": info.get("city"),
        "state": info.get("state"),
        "country": info.get("country"),
        "fullTimeEmployees": info.get("fullTimeEmployees"),
        "companyOfficers": info.get("companyOfficers", []),
        # Forward estimates
        "forward_eps": forward_eps,
        "forward_pe": forward_pe,
        "earnings_growth": earnings_growth,
        "revenue_growth": revenue_growth,
    }


def fetch_earnings_history(symbol: str) -> list[dict]:
    """Fetch earnings surprise history from yfinance.

    Returns a list of dicts: {quarter, actual, estimate, surprise_pct}.
    """
    ticker = yf.Ticker(symbol)
    try:
        earnings = ticker.earnings_history
        if earnings is None or (hasattr(earnings, "empty") and earnings.empty):
            return []
        records = []
        for _, row in earnings.iterrows():
            actual = row.get("epsActual")
            estimate = row.get("epsEstimate")
            surprise_pct = row.get("surprisePercent")
            records.append({
                "quarter": str(row.get("quarter", row.name)),
                "actual": actual,
                "estimate": estimate,
                "surprise_pct": surprise_pct,
            })
        return records
    except Exception:
        return []


def fetch_competitors(symbol: str, universe_tickers: list, ticker_sectors: dict,
                      info: dict = None) -> list[str]:
    """Return up to 5 peer tickers, prioritizing same industry + similar market cap.

    Uses the industry from the already-fetched ticker info (no extra API calls).
    Falls back to sector if industry matching finds fewer than 3 peers.
    """
    target_sector = ticker_sectors.get(symbol)
    if not target_sector:
        return []

    # Get industry from the info dict (already fetched for the detail page)
    target_industry = (info or {}).get("industry", "")
    target_mktcap = (info or {}).get("market_cap", 0) or 0

    same_sector = [t for t in universe_tickers if t != symbol and ticker_sectors.get(t) == target_sector]
    if not same_sector:
        return []

    # If we know the industry, try to find same-industry peers from Tickers.csv
    # Since we don't have industry in the CSV, use a simple heuristic:
    # Sort same-sector tickers by market cap proximity (from screener data)
    try:
        import data.startup as startup
        screener = startup.screener_df
        if not screener.empty:
            sector_df = screener[screener["sector"] == target_sector]
            sector_df = sector_df[sector_df["symbol"] != symbol]
            if target_mktcap > 0 and "price" in sector_df.columns:
                # Use price as rough proxy for size similarity
                target_price = target_mktcap / 1e9  # rough scale
                sector_df = sector_df.copy()
                sector_df["_size_diff"] = (sector_df["price"] - target_price).abs()
                sector_df = sector_df.sort_values("_size_diff")
            return sector_df["symbol"].head(5).tolist()
    except Exception:
        pass

    return same_sector[:5]
