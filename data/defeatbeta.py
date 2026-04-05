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

from defeatbeta_api.data.ticker import Ticker

# ---------------------------------------------------------------------------
# Ticker-object cache (one instance per symbol, lightweight)
# ---------------------------------------------------------------------------

_ticker_cache: Dict[str, Ticker] = {}


def _get_ticker(symbol: str) -> Optional[Ticker]:
    """Get or create a DefeatBeta Ticker object.  Cached per symbol."""
    if symbol not in _ticker_cache:
        try:
            _ticker_cache[symbol] = Ticker(symbol)
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
