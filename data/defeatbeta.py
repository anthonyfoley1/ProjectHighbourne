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
# Earnings transcripts, SEC filings, earnings calendar
# ---------------------------------------------------------------------------

def get_earnings_transcripts(symbol: str) -> list:
    """Get available earnings-call transcript metadata.

    Returns a list of dicts with keys:
        fiscal_year, fiscal_quarter, report_date
    Most-recent first.  Empty list on failure.
    """
    t = _get_ticker(symbol)
    if t is None:
        return []
    try:
        tc = t.earning_call_transcripts()
        if tc is None:
            return []
        tl = tc.get_transcripts_list()
        if tl is None or tl.empty:
            return []
        # Keep only the columns we need and convert to list of dicts
        cols = ["fiscal_year", "fiscal_quarter", "report_date"]
        out = tl[cols].copy()
        out["report_date"] = pd.to_datetime(out["report_date"]).dt.strftime("%Y-%m-%d")
        return out.sort_values("report_date", ascending=False).to_dict("records")
    except Exception:
        return []


def get_sec_filings(symbol: str, form_types=None, limit: int = 15) -> list:
    """Get recent SEC filings.

    Parameters
    ----------
    symbol : str
    form_types : list[str] or None
        Filing types to include, e.g. ``['10-K','10-Q','8-K']``.
        Defaults to ``['10-K','10-Q','8-K']``.
    limit : int
        Max rows to return (most-recent first).

    Returns list of dicts with keys:
        form_type, form_type_description, filing_date, filing_url
    """
    if form_types is None:
        form_types = ["10-K", "10-Q", "8-K"]
    t = _get_ticker(symbol)
    if t is None:
        return []
    try:
        sf = t.sec_filing()
        if sf is None or sf.empty:
            return []
        sf = sf[sf["form_type"].isin(form_types)].copy()
        sf = sf.sort_values("filing_date", ascending=False).head(limit)
        cols = ["form_type", "form_type_description", "filing_date", "filing_url"]
        return sf[cols].to_dict("records")
    except Exception:
        return []


def get_recent_earnings(symbol: str, n: int = 2) -> list:
    """Get key metrics for the last *n* earnings quarters.

    Returns a list of dicts (most-recent first) with keys:
        fiscal_year, fiscal_quarter, report_date,
        revenue, rev_yoy, eps, op_margin, px_move
    Empty list on failure.
    """
    t = _get_ticker(symbol)
    if t is None:
        return []
    try:
        # -- transcript list for quarter labels & earnings dates ---------------
        tc = t.earning_call_transcripts()
        if tc is None:
            return []
        tl = tc.get_transcripts_list()
        if tl is None or tl.empty:
            return []
        tl["report_date"] = pd.to_datetime(tl["report_date"])
        tl = tl.sort_values("report_date", ascending=False).head(n).reset_index(drop=True)

        # -- revenue YoY ------------------------------------------------------
        rev_df = t.quarterly_revenue_yoy_growth()
        if rev_df is not None and not rev_df.empty:
            rev_df["report_date"] = pd.to_datetime(rev_df["report_date"])
        else:
            rev_df = pd.DataFrame()

        # -- EPS YoY ----------------------------------------------------------
        eps_df = t.quarterly_eps_yoy_growth()
        if eps_df is not None and not eps_df.empty:
            eps_df["report_date"] = pd.to_datetime(eps_df["report_date"])
        else:
            eps_df = pd.DataFrame()

        # -- Operating margin --------------------------------------------------
        opm_df = t.quarterly_operating_margin()
        if opm_df is not None and not opm_df.empty:
            opm_df["report_date"] = pd.to_datetime(opm_df["report_date"])
        else:
            opm_df = pd.DataFrame()

        # -- Prices for Px Move ------------------------------------------------
        prices = get_prices(symbol)

        results = []
        for _, row in tl.iterrows():
            rd = row["report_date"]
            # Find the fiscal quarter-end date closest to earnings report_date
            # Revenue etc. are keyed by quarter-end, not earnings call date.
            # Quarter-end is typically ~1 month before earnings call.
            quarter_end = rd - pd.DateOffset(months=1)
            entry = {
                "fiscal_year": int(row["fiscal_year"]),
                "fiscal_quarter": int(row["fiscal_quarter"]),
                "report_date": rd.strftime("%b %d, %Y"),
                "revenue": None,
                "rev_yoy": None,
                "eps": None,
                "op_margin": None,
                "px_move": None,
            }

            # Match metrics by closest quarter-end date
            def _closest(df, target, col):
                if df.empty or col not in df.columns:
                    return None
                diffs = (df["report_date"] - target).abs()
                idx = diffs.idxmin()
                if diffs[idx].days > 60:
                    return None
                return df.loc[idx]

            rev_row = _closest(rev_df, quarter_end, "revenue")
            if rev_row is not None:
                entry["revenue"] = rev_row["revenue"]
                entry["rev_yoy"] = rev_row["yoy_growth"]

            eps_row = _closest(eps_df, quarter_end, "eps")
            if eps_row is not None:
                entry["eps"] = eps_row["eps"]

            opm_row = _closest(opm_df, quarter_end, "operating_margin")
            if opm_row is not None:
                entry["op_margin"] = opm_row["operating_margin"]

            # 3-day price reaction around earnings date
            if prices is not None and not prices.empty:
                try:
                    loc = prices.index.get_indexer([rd], method="nearest")[0]
                    # day before earnings -> 2 days after
                    pre = max(loc - 1, 0)
                    post = min(loc + 2, len(prices) - 1)
                    p0 = prices.iloc[pre]["close"]
                    p1 = prices.iloc[post]["close"]
                    if p0 and p0 > 0:
                        entry["px_move"] = (p1 - p0) / p0
                except Exception:
                    pass

            results.append(entry)
        return results
    except Exception:
        return []


def get_earnings_calendar(symbol: str):
    """Get the next upcoming earnings date.

    Returns a dict ``{"report_date": "YYYY-MM-DD", "time": "...", ...}``
    or *None* if no future date is found.
    """
    t = _get_ticker(symbol)
    if t is None:
        return None
    try:
        cal = t.calendar()
        if cal is None or cal.empty:
            return None
        cal["report_date"] = pd.to_datetime(cal["report_date"])
        today = pd.Timestamp.now().normalize()
        future = cal[cal["report_date"] >= today].sort_values("report_date")
        if future.empty:
            # Return most recent if no future date
            row = cal.sort_values("report_date", ascending=False).iloc[0]
        else:
            row = future.iloc[0]
        return {
            "report_date": row["report_date"].strftime("%Y-%m-%d"),
            "time": row.get("time", ""),
            "fiscal_quarter_ending": str(row.get("fiscal_quarter_ending", "")),
        }
    except Exception:
        return None


def get_defeatbeta_news(symbol: str, limit: int = 10) -> list:
    """Get news articles from DefeatBeta.

    Returns list of dicts with keys:
        title, publisher, report_date, link, type
    Most-recent first.
    """
    t = _get_ticker(symbol)
    if t is None:
        return []
    try:
        news_obj = t.news()
        if news_obj is None:
            return []
        nl = news_obj.get_news_list()
        if nl is None or nl.empty:
            return []
        nl = nl.sort_values("report_date", ascending=False).head(limit)
        cols = ["title", "publisher", "report_date", "link", "type"]
        return nl[cols].to_dict("records")
    except Exception:
        return []


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
