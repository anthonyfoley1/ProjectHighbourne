"""DefeatBeta API wrapper -- primary data source for Highbourne Terminal.

Provides pre-computed financial ratios, prices, and fundamentals via DuckDB.
Falls back gracefully (returns None / empty dict) if the API is unavailable.

Usage:
    from data.defeatbeta import get_prices, get_ratios, get_fundamentals

    prices = get_prices('MSFT')            # pd.DataFrame or None
    ratios = get_ratios('MSFT')            # dict of {ratio_name: pd.Series} or {}
    fundamentals = get_fundamentals('MSFT')  # dict or {}
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from utils.logger import log
from defeatbeta_api.data.ticker import Ticker
from defeatbeta_api.client.duckdb_client import Configuration

# Optimized config — on-disk cache, persistent connections, metadata caching
_CONFIG = Configuration(
    memory_limit="80%",
    http_keep_alive=True,
    http_timeout=60,
    http_retries=3,
    cache_httpfs_type="on_disk",
    parquet_metadata_cache=True,
)

# ---------------------------------------------------------------------------
# Ticker-object cache (one instance per symbol, lightweight)
# ---------------------------------------------------------------------------

_ticker_cache: Dict[str, Ticker] = {}


def _get_ticker(symbol: str) -> Optional[Ticker]:
    """Get or create a DefeatBeta Ticker object.  Cached per symbol."""
    if symbol not in _ticker_cache:
        try:
            import logging as _logging
            _ticker_cache[symbol] = Ticker(symbol, log_level=_logging.WARNING, config=_CONFIG)
        except Exception:
            return None
    return _ticker_cache[symbol]


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def get_prices(symbol: str) -> Optional[pd.DataFrame]:
    """Get daily OHLCV prices.

    Returns a DataFrame indexed by DatetimeIndex (``report_date``) with
    columns ``open``, ``close``, ``high``, ``low``, ``volume``, or *None*
    if the data is unavailable.
    """
    t = _get_ticker(symbol)
    if t is None:
        return None
    try:
        df = t.price()
        if df is None or df.empty:
            return None
        df["report_date"] = pd.to_datetime(df["report_date"])
        df = df.set_index("report_date").sort_index()
        return df
    except Exception:
        return None


def get_close_prices(symbol: str) -> Optional[pd.Series]:
    """Get the close-price series.  Returns ``pd.Series`` or *None*."""
    df = get_prices(symbol)
    if df is None or "close" not in df.columns:
        return None
    return df["close"]


# ---------------------------------------------------------------------------
# Valuation ratios
# ---------------------------------------------------------------------------

_MIN_POINTS = 10  # require at least this many observations


def get_ratios(symbol: str) -> Dict[str, pd.Series]:
    """Get pre-computed valuation-ratio history.

    Returns ``{ratio_name: pd.Series}`` where the Series is indexed by
    ``report_date``.  An empty dict is returned on failure.
    """
    t = _get_ticker(symbol)
    if t is None:
        return {}

    result: Dict[str, pd.Series] = {}

    # P/B -------------------------------------------------------------------
    try:
        pb = t.pb_ratio()
        if pb is not None and not pb.empty and "pb_ratio" in pb.columns:
            pb["report_date"] = pd.to_datetime(pb["report_date"])
            s = pb.set_index("report_date")["pb_ratio"].dropna().sort_index()
            if len(s) > _MIN_POINTS:
                result["P/B"] = s
    except Exception:
        pass

    # P/S -------------------------------------------------------------------
    try:
        ps = t.ps_ratio()
        if ps is not None and not ps.empty and "ps_ratio" in ps.columns:
            ps["report_date"] = pd.to_datetime(ps["report_date"])
            s = ps.set_index("report_date")["ps_ratio"].dropna().sort_index()
            if len(s) > _MIN_POINTS:
                result["P/S"] = s
    except Exception:
        pass

    # P/E (extracted from PEG ratio data which includes ``ttm_pe``) ---------
    try:
        peg = t.peg_ratio()
        if peg is not None and not peg.empty and "ttm_pe" in peg.columns:
            peg["report_date"] = pd.to_datetime(peg["report_date"])
            s = peg.set_index("report_date")["ttm_pe"].dropna().sort_index()
            s = s[s > 0]  # exclude negative P/E
            if len(s) > _MIN_POINTS:
                result["P/E"] = s
    except Exception:
        pass

    # EV/EBITDA --------------------------------------------------------------
    try:
        ev_eb = t.enterprise_to_ebitda()
        if ev_eb is not None and not ev_eb.empty and "ev_to_ebitda" in ev_eb.columns:
            ev_eb["report_date"] = pd.to_datetime(ev_eb["report_date"])
            s = ev_eb.set_index("report_date")["ev_to_ebitda"].dropna().sort_index()
            s = s[s > 0]
            if len(s) > _MIN_POINTS:
                result["EV/EBITDA"] = s
    except Exception:
        pass

    return result


def get_peg(symbol: str) -> Optional[pd.DataFrame]:
    """Get PEG-ratio history.  Returns a DatetimeIndex DataFrame or *None*."""
    t = _get_ticker(symbol)
    if t is None:
        return None
    try:
        peg = t.peg_ratio()
        if peg is not None and not peg.empty:
            peg["report_date"] = pd.to_datetime(peg["report_date"])
            return peg.set_index("report_date").sort_index()
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------

def get_fundamentals(symbol: str) -> Dict[str, pd.DataFrame]:
    """Get key fundamental metrics (ROE, ROIC, WACC, TTM EPS).

    Returns ``{metric_name: pd.DataFrame}`` -- one entry per metric that
    is successfully retrieved.
    """
    t = _get_ticker(symbol)
    if t is None:
        return {}

    result: Dict[str, pd.DataFrame] = {}

    for method, key in [("roe", "roe"), ("roic", "roic"),
                        ("wacc", "wacc"), ("ttm_eps", "ttm_eps")]:
        try:
            df = getattr(t, method)()
            if df is not None and not df.empty:
                result[key] = df
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Company info, officers, news, industry ratios
# ---------------------------------------------------------------------------

def get_company_info(symbol):
    """Get company info: description, officers, industry, etc."""
    t = _get_ticker(symbol)
    if t is None:
        return {}
    try:
        info = t.info()
        # info returns a DataFrame or dict -- check the format
        return info if info is not None else {}
    except Exception:
        return {}

def get_officers(symbol):
    """Get company officers/executives."""
    t = _get_ticker(symbol)
    if t is None:
        return []
    try:
        officers = t.officers()
        if officers is not None:
            return officers
        return []
    except Exception:
        return []

def get_news(symbol):
    """Get news for a ticker from DefeatBeta."""
    t = _get_ticker(symbol)
    if t is None:
        return []
    try:
        news = t.news()
        if news is not None:
            return news
        return []
    except Exception:
        return []

def get_industry_ratios(symbol):
    """Get industry-level comparison ratios."""
    t = _get_ticker(symbol)
    if t is None:
        return {}
    result = {}
    for method, key in [
        ("industry_pb_ratio", "P/B"),
        ("industry_ps_ratio", "P/S"),
        ("industry_ttm_pe", "P/E"),
        ("industry_roe", "ROE"),
        ("industry_roic", "ROIC"),
    ]:
        try:
            df = getattr(t, method)()
            if df is not None and not df.empty:
                result[key] = df
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """Return *True* if the DefeatBeta API is responsive."""
    try:
        t = Ticker("AAPL")
        p = t.price()
        return p is not None and not p.empty
    except Exception:
        return False
