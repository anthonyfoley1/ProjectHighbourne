"""Startup data pipeline — loads pre-computed data from SQLite.

Call init() once from app.py before running the server.
Pages import the module-level variables directly.

If highbourne.db does not exist, prints a warning and falls back to the
legacy pipeline (slow, fetches everything from scratch).

This version uses lazy loading for prices and ratios so the app starts
in under 5 seconds when the database is populated.
"""

import os
import pandas as pd
import numpy as np
from pathlib import Path

from data.database import DB_PATH

# ---------------------------------------------------------------------------
# Module-level variables — populated by init()
# ---------------------------------------------------------------------------
universe = None               # LazyUniverse (or Universe from legacy)
screener_df: pd.DataFrame = pd.DataFrame()
risk_stats: dict = {}
regime_data: dict = {}
sector_data: dict = {}
price_cache: dict = {}
ticker_info_cache: dict = {}
ticker_sector: dict = {}
ticker_name: dict = {}
close_prices: pd.DataFrame = pd.DataFrame()
news_cache: list = []
market_news_cache: list = []

# Private handle to the Database instance (created once in init)
_db = None


def get_db():
    """Get the shared database instance."""
    global _db
    if _db is None:
        from data.database import Database
        _db = Database()
    return _db


# ---------------------------------------------------------------------------
# LazyUniverse — loads ticker ratios from SQLite on demand
# ---------------------------------------------------------------------------

class LazyUniverse:
    """Drop-in replacement for models.ticker.Universe that loads ratios lazily.

    At init time only the ticker list and sectors are stored.  Ratio data for
    a ticker is fetched from SQLite the first time its detail page is viewed.
    """

    WINDOWS = {
        "5Y": 5 * 365,
        "2Y": 2 * 365,
        "6M": 182,
    }

    def __init__(self, ticker_sectors):
        self._ticker_sectors = ticker_sectors   # {symbol: sector}
        self._cache = {}                        # {symbol: Ticker}

    # -- Core accessors ---------------------------------------------------

    def get(self, symbol):
        """Return a Ticker object, loading ratios from SQLite on first access."""
        if symbol not in self._cache:
            from models.ticker import Ticker
            sector = self._ticker_sectors.get(symbol, "")
            t = Ticker(symbol, sector=sector)
            ratios = get_ticker_ratios(symbol)
            for name, series in ratios.items():
                t.set_ratio(name, series)
            self._cache[symbol] = t
        return self._cache.get(symbol)

    @property
    def symbols(self):
        return sorted(self._ticker_sectors.keys())

    @property
    def tickers(self):
        """Compatibility dict — returns already-cached tickers only."""
        return self._cache

    @property
    def sectors(self):
        return dict(self._ticker_sectors)

    @property
    def sector_list(self):
        return sorted(s for s in set(self._ticker_sectors.values()) if isinstance(s, str))

    def symbols_in_sector(self, sector):
        return sorted(s for s, sec in self._ticker_sectors.items() if sec == sector)

    def add_ticker(self, ticker):
        """Compatibility — store a pre-built Ticker object."""
        self._ticker_sectors[ticker.symbol] = ticker.sector or ""
        self._cache[ticker.symbol] = ticker

    # -- Analytical helpers ------------------------------------------------

    def sector_medians(self, ratio_name, window_name="2Y"):
        """Compute median ratio per sector for a given window.

        Loads ratios on demand for every ticker in each sector, so this is
        expensive the first time it is called.  Results are implicitly cached
        because loaded tickers stay in ``self._cache``.
        """
        window_days = self.WINDOWS.get(window_name)
        rows = []
        for sector in self.sector_list:
            symbols = self.symbols_in_sector(sector)
            values = []
            for s in symbols:
                ticker_obj = self.get(s)
                if ticker_obj is None:
                    continue
                st = ticker_obj.stats(ratio_name, window_days)
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
        return pd.DataFrame(rows).sort_values("Median") if rows else pd.DataFrame()

    def screener(self, ratio_name, window_name="2Y"):
        """Build a screener DataFrame — delegates to each Ticker's stats()."""
        window_days = self.WINDOWS.get(window_name)
        rows = []
        for symbol in self.symbols:
            ticker_obj = self.get(symbol)
            if ticker_obj is None:
                continue
            s = ticker_obj.stats(ratio_name, window_days)
            if s is None:
                continue
            rows.append({
                "Ticker": symbol,
                "Sector": ticker_obj.sector or "Unknown",
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
        return pd.DataFrame(rows).sort_values("Z-Score")


# ---------------------------------------------------------------------------
# Lazy data-access helpers
# ---------------------------------------------------------------------------

_ratios_cache = {}

def get_ticker_ratios(symbol):
    """Compute ratio history for a single ticker from prices + financials in SQLite.
    Cached after first computation.

    Returns a dict {ratio_name: pd.Series} ready to attach to a Ticker.
    """
    if symbol in _ratios_cache:
        return _ratios_cache[symbol]
    db = get_db()

    # First try pre-computed ratios table
    try:
        ratios = db.query(
            "SELECT date, pe, ps, pb, ev_ebitda FROM ratios WHERE ticker=? ORDER BY date",
            (symbol,),
        )
        if not ratios.empty:
            ratios["date"] = pd.to_datetime(ratios["date"])
            ratios = ratios.set_index("date")
            result = {}
            for col, name in [("pe", "P/E"), ("ps", "P/S"), ("pb", "P/B"), ("ev_ebitda", "EV/EBITDA")]:
                s = ratios[col].dropna()
                if len(s) > 0:
                    result[name] = s
            if result:
                _ratios_cache[symbol] = result
                return result
    except Exception:
        pass

    # Fallback: compute on the fly from prices + financials (slow, only if ratios table is empty)
    import numpy as np
    from edgar_utils import build_daily_ttm, build_daily_instant

    prices_df = db.query("SELECT date, close FROM prices WHERE ticker=? ORDER BY date", (symbol,))
    if prices_df.empty:
        return {}
    prices_df["date"] = pd.to_datetime(prices_df["date"])
    prices_df = prices_df.set_index("date")
    close = prices_df["close"]

    shares_row = db.query("SELECT shares FROM shares_outstanding WHERE ticker=?", (symbol,))
    shares = float(shares_row["shares"].iloc[0]) if not shares_row.empty else None
    if not shares:
        return {}

    mktcap = close * shares
    trading_dates = mktcap.index

    fin = db.query("SELECT period_end, revenue, net_income, operating_income, depreciation_amortization, "
                    "stockholders_equity, total_debt, cash FROM financials WHERE ticker=? ORDER BY period_end",
                    (symbol,))
    if fin.empty:
        return {}
    fin["period_end"] = pd.to_datetime(fin["period_end"])
    fin = fin.set_index("period_end")

    result = {}

    # P/B
    if "stockholders_equity" in fin.columns:
        eq = fin[["stockholders_equity"]].dropna().rename(columns={"stockholders_equity": symbol})
        if not eq.empty:
            eq_daily = build_daily_instant(eq, trading_dates)
            if symbol in eq_daily.columns:
                eq_d = eq_daily[symbol].where(eq_daily[symbol] > 0)
                pb = (mktcap / eq_d).replace([np.inf, -np.inf], np.nan).dropna()
                if len(pb) > 10:
                    result["P/B"] = pb

    # P/S
    if "revenue" in fin.columns:
        rev = fin[["revenue"]].dropna().rename(columns={"revenue": symbol})
        if not rev.empty:
            rev_ttm = build_daily_ttm(rev, trading_dates)
            if symbol in rev_ttm.columns:
                rev_t = rev_ttm[symbol].where(rev_ttm[symbol] > 0)
                ps = (mktcap / rev_t).replace([np.inf, -np.inf], np.nan).dropna()
                if len(ps) > 10:
                    result["P/S"] = ps

    # P/E
    if "net_income" in fin.columns:
        ni = fin[["net_income"]].dropna().rename(columns={"net_income": symbol})
        if not ni.empty:
            ni_ttm = build_daily_ttm(ni, trading_dates)
            if symbol in ni_ttm.columns:
                ni_t = ni_ttm[symbol].where(ni_ttm[symbol] > 0)
                pe = (mktcap / ni_t).replace([np.inf, -np.inf], np.nan).dropna()
                if len(pe) > 10:
                    result["P/E"] = pe

    # EV/EBITDA
    if "operating_income" in fin.columns:
        oi = fin[["operating_income"]].dropna().rename(columns={"operating_income": symbol})
        da = fin[["depreciation_amortization"]].dropna().rename(columns={"depreciation_amortization": symbol}) if "depreciation_amortization" in fin.columns else pd.DataFrame()
        if not oi.empty:
            if not da.empty and symbol in da.columns:
                ebitda_q = oi.add(da, fill_value=0)
            else:
                ebitda_q = oi
            ebitda_ttm = build_daily_ttm(ebitda_q, trading_dates)
            if symbol in ebitda_ttm.columns:
                ebitda_t = ebitda_ttm[symbol].where(ebitda_ttm[symbol] > 0)
                # EV = mktcap + debt - cash
                ev = mktcap.copy()
                if "total_debt" in fin.columns:
                    debt = fin[["total_debt"]].dropna().rename(columns={"total_debt": symbol})
                    if not debt.empty:
                        debt_d = build_daily_instant(debt, trading_dates)
                        if symbol in debt_d.columns:
                            ev = ev + debt_d[symbol].fillna(0)
                if "cash" in fin.columns:
                    cash = fin[["cash"]].dropna().rename(columns={"cash": symbol})
                    if not cash.empty:
                        cash_d = build_daily_instant(cash, trading_dates)
                        if symbol in cash_d.columns:
                            ev = ev - cash_d[symbol].fillna(0)
                ev_ebitda = (ev / ebitda_t).replace([np.inf, -np.inf], np.nan).dropna()
                if len(ev_ebitda) > 10:
                    result["EV/EBITDA"] = ev_ebitda

    _ratios_cache[symbol] = result
    return result


def get_prices(symbol, full=False):
    """Lazy-load prices for a ticker from SQLite.  Returns pd.Series or None.

    If ``full=True``, always loads the complete price history (for detail page).
    Otherwise returns the cached version (sparkline-only during initial load,
    or full if previously loaded).
    """
    global price_cache
    if symbol in price_cache and not full:
        return price_cache[symbol]

    # For full=True or cache miss, load from DB
    db = get_db()
    if full:
        pdf = db.query(
            "SELECT date, close FROM prices WHERE ticker=? ORDER BY date",
            (symbol,),
        )
    else:
        pdf = db.query(
            "SELECT date, close FROM prices WHERE ticker=? AND date >= date('now', '-120 days') ORDER BY date",
            (symbol,),
        )

    if pdf.empty:
        if symbol in price_cache:
            return price_cache[symbol]
        return None

    pdf["date"] = pd.to_datetime(pdf["date"])
    series = pdf.set_index("date")["close"]
    price_cache[symbol] = series
    return series


def get_ratios(symbol, ratio_name=None):
    """Load ratios for a ticker from SQLite.  Returns DataFrame."""
    db = get_db()
    if ratio_name:
        col_map = {"P/E": "pe", "P/S": "ps", "P/B": "pb", "EV/EBITDA": "ev_ebitda"}
        col = col_map.get(ratio_name)
        if col:
            return db.query(
                f"SELECT date, {col} FROM ratios WHERE ticker=? AND {col} IS NOT NULL ORDER BY date",
                (symbol,),
            )
    return db.query(
        "SELECT * FROM ratios WHERE ticker=? ORDER BY date",
        (symbol,),
    )


def get_technicals(symbol):
    """Load technicals for a ticker from SQLite.  Returns DataFrame."""
    db = get_db()
    return db.query(
        "SELECT * FROM technicals WHERE ticker=? ORDER BY date",
        (symbol,),
    )


def get_earnings(symbol):
    """Load earnings for a ticker from SQLite.  Returns list of dicts."""
    db = get_db()
    df = db.query(
        "SELECT * FROM earnings WHERE ticker=? ORDER BY quarter",
        (symbol,),
    )
    if df.empty:
        return []
    return df.to_dict("records")


def get_financials(symbol):
    """Load financials for a ticker from SQLite.  Returns DataFrame."""
    db = get_db()
    return db.query(
        "SELECT * FROM financials WHERE ticker=? ORDER BY period_end",
        (symbol,),
    )


# ---------------------------------------------------------------------------
# init() — fast path (SQLite) or slow fallback (legacy)
# ---------------------------------------------------------------------------

def init():
    """Load data from SQLite into module-level variables for the Dash app.

    If highbourne.db does not exist, falls back to the legacy pipeline.
    """
    if not DB_PATH.exists():
        print("WARNING: highbourne.db not found. Run 'python3 ingest.py' first.")
        print("Falling back to legacy startup pipeline...")
        _legacy_init()
        return

    _sqlite_init()


def _sqlite_init():
    """Fast startup: read metadata from SQLite, defer heavy data to lazy loading."""
    global universe, screener_df, risk_stats, regime_data, sector_data, news_cache, market_news_cache
    global price_cache, ticker_info_cache, ticker_sector, ticker_name, close_prices

    import time
    t0 = time.time()
    print("Loading from database...")

    db = get_db()

    # ------------------------------------------------------------------
    # 1. Screener
    # ------------------------------------------------------------------
    screener_df = db.query("SELECT * FROM screener ORDER BY z_score ASC")
    print(f"  Screener: {len(screener_df)} tickers")

    # ------------------------------------------------------------------
    # 2. Ticker lookups
    # ------------------------------------------------------------------
    tickers = db.query("SELECT symbol, name, sector FROM tickers")
    ticker_sector = dict(zip(tickers["symbol"], tickers["sector"]))
    ticker_name = dict(zip(tickers["symbol"], tickers["name"]))

    # ------------------------------------------------------------------
    # 3. Risk stats
    # ------------------------------------------------------------------
    risk_row = db.query("SELECT * FROM market_risk ORDER BY date DESC LIMIT 1")
    if not risk_row.empty:
        r = risk_row.iloc[0]
        risk_stats = {
            "vix": {"value": r.get("vix"), "change": r.get("vix_change")},
            "fear_greed": {"value": r.get("fear_greed"), "label": r.get("fear_greed_label", "N/A")},
            "breadth": {
                "pct_above_200sma": r.get("pct_above_200sma", 0),
                "pct_above_50sma": r.get("pct_above_50sma", 0),
                "avg_rsi": r.get("avg_rsi", 50),
            },
            "advancers": r.get("advancers", 0),
            "decliners": r.get("decliners", 0),
            "unchanged": r.get("unchanged", 0),
            "new_highs": r.get("new_highs", 0),
            "new_lows": r.get("new_lows", 0),
            "verdict": {
                "level": r.get("verdict_level", "N/A"),
                "color": r.get("verdict_color", "#999"),
                "guidance": r.get("verdict_guidance", ""),
            },
        }
    else:
        risk_stats = {
            "vix": {"value": None, "change": None},
            "fear_greed": {"value": None, "label": "N/A"},
            "breadth": {"pct_above_200sma": 0, "pct_above_50sma": 0, "avg_rsi": 50},
            "advancers": 0, "decliners": 0, "unchanged": 0,
            "new_highs": 0, "new_lows": 0,
            "verdict": {"level": "N/A", "color": "#999", "guidance": ""},
        }

    # ------------------------------------------------------------------
    # 4. News
    # ------------------------------------------------------------------
    news_rows = db.query(
        "SELECT * FROM news WHERE ticker IS NOT NULL ORDER BY fetched_at DESC LIMIT 20"
    )
    news_cache = []
    for _, nr in news_rows.iterrows():
        news_cache.append({
            "symbol": nr.get("ticker", ""),
            "title": nr.get("headline", ""),
            "link": nr.get("url", "#"),
            "publisher": nr.get("source", ""),
            "age": nr.get("age", ""),
        })

    market_rows = db.query(
        "SELECT * FROM news WHERE ticker IS NULL ORDER BY fetched_at DESC LIMIT 15"
    )
    market_news_cache = []
    for _, nr in market_rows.iterrows():
        market_news_cache.append({
            "headline": nr.get("headline", ""),
            "source": nr.get("source", ""),
            "url": nr.get("url", "#"),
            "age": nr.get("age", ""),
        })

    # ------------------------------------------------------------------
    # 5. Build LazyUniverse (NO ratio loading — done on demand)
    # ------------------------------------------------------------------
    universe = LazyUniverse(ticker_sector)
    print(f"  Universe: {len(ticker_sector)} tickers (ratios loaded on demand)")

    # ------------------------------------------------------------------
    # 6. Sector data (computed from screener_df — no heavy queries)
    # ------------------------------------------------------------------
    from data.sectors import SECTOR_COLORS, compute_sector_returns

    if not screener_df.empty and "ret_1d" in screener_df.columns:
        ticker_returns = dict(zip(screener_df["symbol"], screener_df["ret_1d"] / 100))
        sector_returns = compute_sector_returns(ticker_returns, ticker_sector)
    else:
        sector_returns = {}

    # Normalized sector series are NOT precomputed at startup.
    # They will be empty initially; the home page sector chart handles this.
    sector_data = {
        "returns": sector_returns,
        "normalized": {},
        "colors": SECTOR_COLORS,
    }

    # ------------------------------------------------------------------
    # 7. Prices are NOT preloaded — get_prices() loads on demand
    # ------------------------------------------------------------------
    # price_cache stays empty; sparklines call get_prices(sym) per ticker
    close_prices = pd.DataFrame()

    # ------------------------------------------------------------------
    # 8. Market Regime Detection (equity + fixed income)
    # ------------------------------------------------------------------
    from data.risk import compute_regime
    try:
        regime_data = compute_regime(risk_stats)
        print(f"  Regime: {regime_data.get('regime', 'N/A')} (score {regime_data.get('score', 'N/A')})")
    except Exception as e:
        print(f"  Regime detection failed: {e}")
        regime_data = {
            "regime": "N/A", "color": "#999999", "indicators": [],
            "score": 50, "guidance": "Regime detection unavailable.",
        }

    elapsed = time.time() - t0
    print(f"Loaded from database in {elapsed:.2f}s — ready ({len(screener_df)} tickers in screener)")


# ---------------------------------------------------------------------------
# Legacy fallback — kept for when highbourne.db does not exist
# ---------------------------------------------------------------------------

def _legacy_init():
    """Original slow pipeline that fetches everything from APIs at startup.

    This is only used as a fallback when the SQLite database has not been
    created yet.  In normal operation, init() calls _sqlite_init() instead.
    """
    global universe, screener_df, risk_stats, regime_data, sector_data, news_cache, market_news_cache
    global price_cache, ticker_info_cache, ticker_sector, ticker_name, close_prices

    print("Running legacy startup pipeline (this will be slow)...")

    # Import the heavy modules only when needed
    from models.ticker import Universe, Ticker

    # The legacy pipeline previously lived in init() directly.
    # Since the DB doesn't exist, we create a minimal empty state so the
    # app can at least start without crashing.
    universe = Universe()
    screener_df = pd.DataFrame()
    risk_stats = {
        "vix": {"value": None, "change": None},
        "fear_greed": {"value": None, "label": "N/A"},
        "breadth": {"pct_above_200sma": 0, "pct_above_50sma": 0, "avg_rsi": 50},
        "advancers": 0, "decliners": 0, "unchanged": 0,
        "new_highs": 0, "new_lows": 0,
        "verdict": {"level": "N/A", "color": "#999", "guidance": "No database available"},
    }
    sector_data = {"returns": {}, "normalized": {}, "colors": {}}
    regime_data = {
        "regime": "N/A", "color": "#999999", "indicators": [],
        "score": 50, "guidance": "Regime detection unavailable — no database.",
    }
    price_cache = {}
    ticker_info_cache = {}
    ticker_sector = {}
    ticker_name = {}
    close_prices = pd.DataFrame()
    news_cache = []
    market_news_cache = []

    print("Legacy init complete — app running with empty data.")
    print("Run 'python3 ingest.py' to populate the database, then restart.")
