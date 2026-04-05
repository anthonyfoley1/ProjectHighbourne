"""Data loading layer — reads cached EDGAR/SimFin data into DataFrames."""

import json
import os
import pandas as pd
import numpy as np
import simfin as sf
from simfin.names import *
from datetime import datetime, timedelta

import importlib
import edgar_utils
importlib.reload(edgar_utils)
from edgar_utils import (
    cache_to_unstacked, build_daily_instant, build_daily_ttm,
    fetch_filing_dates, load_cik_lookup,
)

import yfinance as yf

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CACHE_FILES = {
    "equity": os.path.join(PROJECT_ROOT, "edgar_equity_cache.json"),
    "debt": os.path.join(PROJECT_ROOT, "edgar_debt_cache.json"),
    "cash": os.path.join(PROJECT_ROOT, "edgar_cash_cache.json"),
    "revenue": os.path.join(PROJECT_ROOT, "edgar_revenue_cache.json"),
    "net_income": os.path.join(PROJECT_ROOT, "edgar_netincome_cache.json"),
    "op_income": os.path.join(PROJECT_ROOT, "edgar_opincome_cache.json"),
    "dna": os.path.join(PROJECT_ROOT, "edgar_dna_cache.json"),
}

_cik_lookup = None


def _load_cache(name):
    path = CACHE_FILES[name]
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


# ---------------------------------------------------------------------------
# yfinance fallback for missing EDGAR data
# ---------------------------------------------------------------------------

# Map from our internal field names to yfinance column names
_YF_INCOME_FIELDS = {
    "revenue": "Total Revenue",
    "net_income": "Net Income",
    "op_income": "Operating Income",
    "ebitda": "EBITDA",
}

_YF_BALANCE_FIELDS = {
    "equity": "Stockholders Equity",
    "debt": "Total Debt",
    "cash": "Cash And Cash Equivalents",
}

# D&A isn't directly on a single statement in yfinance — skip for now
_YF_CASHFLOW_FIELDS = {
    "dna": "Depreciation And Amortization",
}


def _yf_quarterly_data(symbol, field):
    """Fetch quarterly data from yfinance for a single field.

    Returns a dict of {date_str: value} matching the EDGAR cache format,
    or an empty dict on failure.
    """
    tk = yf.Ticker(symbol)

    if field in _YF_INCOME_FIELDS:
        stmt = tk.quarterly_income_stmt
        col_name = _YF_INCOME_FIELDS[field]
    elif field in _YF_BALANCE_FIELDS:
        stmt = tk.quarterly_balance_sheet
        col_name = _YF_BALANCE_FIELDS[field]
    elif field in _YF_CASHFLOW_FIELDS:
        stmt = tk.quarterly_cashflow
        col_name = _YF_CASHFLOW_FIELDS[field]
    else:
        return {}

    if stmt is None or stmt.empty or col_name not in stmt.index:
        return {}

    row = stmt.loc[col_name]
    result = {}
    for date_col, val in row.items():
        if pd.notna(val):
            date_str = pd.Timestamp(date_col).strftime("%Y-%m-%d")
            result[date_str] = float(val)
    return result


# Cache yfinance results across fields to avoid redundant API calls
_yf_ticker_cache = {}


def _get_yf_ticker(symbol):
    """Return a cached yf.Ticker object."""
    if symbol not in _yf_ticker_cache:
        _yf_ticker_cache[symbol] = yf.Ticker(symbol)
    return _yf_ticker_cache[symbol]


def _yf_quarterly_data_cached(symbol, field):
    """Fetch quarterly data from yfinance using a shared Ticker object cache.

    For income-statement and cash-flow fields, also pulls the annual
    statement and derives synthetic quarters for fiscal years that have
    no quarterly data (annual_value / 4).  This extends the history
    beyond the ~5 quarters that yfinance provides natively, ensuring
    TTM rolling sums can cover the full trading-date range.
    """
    tk = _get_yf_ticker(symbol)

    if field in _YF_INCOME_FIELDS:
        q_stmt = tk.quarterly_income_stmt
        a_stmt = tk.income_stmt
        col_name = _YF_INCOME_FIELDS[field]
    elif field in _YF_BALANCE_FIELDS:
        q_stmt = tk.quarterly_balance_sheet
        a_stmt = None  # balance sheet items are instant; no TTM needed
        col_name = _YF_BALANCE_FIELDS[field]
    elif field in _YF_CASHFLOW_FIELDS:
        q_stmt = tk.quarterly_cashflow
        a_stmt = tk.cashflow
        col_name = _YF_CASHFLOW_FIELDS[field]
    else:
        return {}

    result = {}

    # 1. Collect quarterly data
    if q_stmt is not None and not q_stmt.empty and col_name in q_stmt.index:
        row = q_stmt.loc[col_name]
        for date_col, val in row.items():
            if pd.notna(val):
                date_str = pd.Timestamp(date_col).strftime("%Y-%m-%d")
                result[date_str] = float(val)

    # 2. For duration fields, derive synthetic quarters from annual data
    #    for years not covered by quarterly data.
    if a_stmt is not None and not a_stmt.empty and col_name in a_stmt.index:
        from datetime import timedelta
        q_dates = set(result.keys())
        a_row = a_stmt.loc[col_name]
        for date_col, val in a_row.items():
            if pd.notna(val):
                ann_end = pd.Timestamp(date_col)
                # Check if any quarterly data falls within this annual period
                # (roughly: within 365 days before the annual end date)
                ann_start = ann_end - timedelta(days=370)
                has_quarterly = any(
                    ann_start <= pd.Timestamp(d) <= ann_end for d in q_dates
                )
                if not has_quarterly:
                    # Split annual into 4 synthetic quarters
                    q_val = float(val) / 4
                    for i in range(4):
                        q_end = ann_end - timedelta(days=90 * (3 - i))
                        q_date_str = q_end.strftime("%Y-%m-%d")
                        if q_date_str not in result:
                            result[q_date_str] = q_val

    return result


def _fill_missing_from_yfinance(unstacked_df, all_tickers, field_name,
                                mktcap_cols=None, mktcap_df=None,
                                edgar_cache=None, max_tickers=200):
    """Fill missing tickers in an unstacked DataFrame using yfinance.

    Only fills tickers that are COMPLETELY missing from EDGAR — never
    partially fills a ticker that already has some data.

    Prioritization (highest to lowest):
      1. Tickers present in EDGAR cache with empty data AND have mktcap
         (known XBRL tag mismatches — most likely to benefit from fallback)
      2. Other tickers with mktcap data
      3. Everything else

    Within each priority group, tickers are sorted by market cap (largest
    first) so that the most important names are filled within the cap.
    """
    missing = [
        t for t in all_tickers
        if t not in unstacked_df.columns or unstacked_df[t].dropna().empty
    ]
    if not missing:
        return unstacked_df

    mktcap_set = set(mktcap_cols) if mktcap_cols is not None else set()
    edgar_empty = set()
    if edgar_cache is not None:
        edgar_empty = {t for t in missing if t in edgar_cache and not edgar_cache[t]}

    # Get latest market cap for each ticker to sort within priority groups.
    # Use the last valid (non-NaN) value per ticker so that tickers with
    # stale SimFin data still get ranked by size.
    latest_mc = {}
    if mktcap_df is not None:
        missing_in_mc = [t for t in missing if t in mktcap_df.columns]
        if missing_in_mc:
            last_valid = mktcap_df[missing_in_mc].ffill().iloc[-1]
            for t in missing_in_mc:
                v = last_valid.get(t)
                if pd.notna(v):
                    latest_mc[t] = v

    def _sort_key(t):
        has_mc = t in mktcap_set
        is_edgar_empty = t in edgar_empty
        # Primary: priority group (lower = higher priority)
        if is_edgar_empty and has_mc:
            pri = 0
        elif has_mc:
            pri = 1
        else:
            pri = 2
        # Secondary: negative market cap so largest sorts first
        mc = -latest_mc.get(t, 0)
        return (pri, mc)

    missing.sort(key=_sort_key)

    batch = missing[:max_tickers]
    print(f"  yfinance {field_name}: filling {len(batch)}/{len(missing)} missing tickers...")
    filled = 0
    # Collect all yfinance data first, then merge via pd.concat to avoid
    # DataFrame fragmentation from repeated .loc assignments.
    new_data = {}
    for sym in batch:
        try:
            yf_data = _yf_quarterly_data_cached(sym, field_name)
            if yf_data:
                new_data[sym] = {pd.Timestamp(d): v for d, v in yf_data.items()}
                filled += 1
        except Exception:
            continue
    if new_data:
        patch = pd.DataFrame(new_data)
        unstacked_df = unstacked_df.combine_first(patch)
    if filled:
        print(f"    -> filled {filled} tickers")

    return unstacked_df


def get_cik_lookup():
    global _cik_lookup
    if _cik_lookup is None:
        _cik_lookup = load_cik_lookup()
    return _cik_lookup


def load_tickers():
    """Load Russell 3000 tickers with sector info, excluding Energy."""
    path = os.path.join(PROJECT_ROOT, "Tickers.csv")
    df = pd.read_csv(path)
    df = df[df["Sector"] != "Energy"]
    df["Ticker"] = df["Ticker"].astype(str).str.strip()
    return df


def load_market_data(years=5):
    """Load daily close prices from yfinance, shares from SimFin, compute market cap."""
    import json as _json

    # 1. Get close prices from yfinance (current data)
    tickers_df = load_tickers()
    symbols = tickers_df["Ticker"].tolist()

    cache_path = os.path.join(PROJECT_ROOT, "cache", "yf_close.parquet")
    cache_meta = os.path.join(PROJECT_ROOT, "cache", "yf_close_meta.json")
    os.makedirs(os.path.join(PROJECT_ROOT, "cache"), exist_ok=True)

    use_cache = False
    if os.path.exists(cache_path) and os.path.exists(cache_meta):
        with open(cache_meta) as f:
            meta = _json.load(f)
        saved = datetime.fromisoformat(meta["saved_at"])
        if datetime.now() - saved < timedelta(hours=20):
            use_cache = True

    if use_cache:
        print("  Loading cached yfinance prices...")
        close = pd.read_parquet(cache_path)
    else:
        import time as _time
        BATCH_SIZE = 200
        PAUSE_SECS = 10
        MAX_RETRIES = 2
        print(f"  Downloading {len(symbols)} tickers from yfinance in batches of {BATCH_SIZE}...")
        close_dict = {}

        def _extract_close(raw_df, syms):
            """Extract close prices from a yf.download result."""
            extracted = {}
            if len(syms) == 1:
                sym = syms[0]
                if "Close" in raw_df.columns:
                    s = raw_df["Close"].dropna()
                    if len(s) > 0:
                        extracted[sym] = s
            else:
                for sym in syms:
                    try:
                        if sym in raw_df.columns.get_level_values(0):
                            s = raw_df[sym]["Close"].dropna()
                            if len(s) > 0:
                                extracted[sym] = s
                    except Exception:
                        continue
            return extracted

        def _download_batch(syms, label=""):
            """Download a batch, return dict of extracted close prices."""
            try:
                raw = yf.download(syms, period=f"{years}y", group_by="ticker", threads=True, progress=False)
                return _extract_close(raw, syms)
            except Exception as e:
                print(f"    {label} download error: {e}")
                return {}

        for i in range(0, len(symbols), BATCH_SIZE):
            batch = [s for s in symbols[i : i + BATCH_SIZE] if s]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"    Batch {batch_num}/{total_batches} ({len(batch)} tickers)...")
            result = _download_batch(batch, f"Batch {batch_num}")
            close_dict.update(result)

            # Identify tickers that failed (not in result)
            missed = [s for s in batch if s not in result]
            for retry in range(MAX_RETRIES):
                if not missed:
                    break
                print(f"    Retrying {len(missed)} missed tickers (attempt {retry + 1})...")
                _time.sleep(15)
                retry_result = _download_batch(missed, f"Retry {retry + 1}")
                close_dict.update(retry_result)
                missed = [s for s in missed if s not in retry_result]

            # Pause between batches to avoid rate limiting
            if i + BATCH_SIZE < len(symbols):
                _time.sleep(PAUSE_SECS)

        close = pd.DataFrame(close_dict)
        close.to_parquet(cache_path)
        with open(cache_meta, "w") as f:
            _json.dump({"saved_at": datetime.now().isoformat()}, f)
        print(f"  Got prices for {len(close.columns)} tickers")

    # 2. Get shares outstanding from SimFin (share counts are stable year-to-year)
    sf.set_api_key("4e0d0ff7-a1af-4333-9f4b-55d97e801b35")
    sf.set_data_dir("~/simfin_data/")
    df_prices = sf.load_shareprices(market="us", variant="daily")
    shares_df = df_prices["Shares Outstanding"].unstack("Ticker")
    # Use the latest shares outstanding for each ticker
    latest_shares = shares_df.ffill().iloc[-1]

    # 3. Compute market cap = close * shares outstanding
    common = close.columns.intersection(latest_shares.index)
    mktcap = close[common].multiply(latest_shares[common], axis=1)
    mktcap = mktcap.dropna(axis=1, how="all")

    return mktcap, close


def get_filing_dates(ticker):
    """Get filing dates for E markers on chart."""
    cik = get_cik_lookup()
    return fetch_filing_dates(ticker, cik)


def compute_all_ratios(mktcap, store=None, ticker_list=None):
    """Compute P/B, P/S, P/E, EV/EBITDA from the quarterly store.

    Args:
        mktcap: DataFrame of market cap with tickers as columns.
        store: FinancialsStore instance. If None, loads from default parquet.
        ticker_list: unused, kept for backward compatibility.
    """
    from data.db import FinancialsStore

    if store is None:
        store = FinancialsStore()

    trading_dates = mktcap.index

    # --- Price-to-Book ---
    eq = store.get_field_series("stockholders_equity")
    if not eq.empty:
        equity_daily = build_daily_instant(eq, trading_dates)
        # Clean: mask negative/zero equity
        equity_daily = equity_daily.where(equity_daily > 0)
        common = mktcap.columns.intersection(equity_daily.columns)
        pb_df = (mktcap[common] / equity_daily[common]).replace([np.inf, -np.inf], np.nan)
    else:
        pb_df = pd.DataFrame(index=trading_dates)

    # --- Price-to-Sales (TTM) ---
    rev = store.get_field_series("revenue")
    if not rev.empty:
        rev_ttm = build_daily_ttm(rev, trading_dates)
        rev_ttm = rev_ttm.where(rev_ttm > 0)
        common = mktcap.columns.intersection(rev_ttm.columns)
        ps_df = (mktcap[common] / rev_ttm[common]).replace([np.inf, -np.inf], np.nan)
    else:
        ps_df = pd.DataFrame(index=trading_dates)

    # --- Price-to-Earnings (TTM) ---
    ni = store.get_field_series("net_income")
    if not ni.empty:
        ni_ttm = build_daily_ttm(ni, trading_dates)
        ni_ttm = ni_ttm.where(ni_ttm > 0)
        common = mktcap.columns.intersection(ni_ttm.columns)
        pe_df = (mktcap[common] / ni_ttm[common]).replace([np.inf, -np.inf], np.nan)
    else:
        pe_df = pd.DataFrame(index=trading_dates)

    # --- EV/EBITDA (TTM) ---
    ebitda_q = store.get_field_series("ebitda")
    # If ebitda not available, compute from operating_income + D&A
    if ebitda_q.empty:
        oi = store.get_field_series("operating_income")
        dna = store.get_field_series("depreciation_amortization")
        if not oi.empty:
            common_eb = oi.columns.intersection(dna.columns) if not dna.empty else oi.columns
            ebitda_q = oi[common_eb] + dna[common_eb].fillna(0) if not dna.empty else oi

    if not ebitda_q.empty:
        ebitda_ttm = build_daily_ttm(ebitda_q, trading_dates)
        ebitda_ttm = ebitda_ttm.where(ebitda_ttm > 0)

        debt = store.get_field_series("total_debt")
        cash = store.get_field_series("cash")
        debt_daily = build_daily_instant(debt, trading_dates) if not debt.empty else pd.DataFrame(index=trading_dates)
        cash_daily = build_daily_instant(cash, trading_dates) if not cash.empty else pd.DataFrame(index=trading_dates)

        ev_tickers = mktcap.columns.intersection(ebitda_ttm.columns)
        ev_df = mktcap[ev_tickers].copy()
        debt_overlap = ev_tickers.intersection(debt_daily.columns)
        ev_df[debt_overlap] = ev_df[debt_overlap] + debt_daily[debt_overlap].fillna(0)
        cash_overlap = ev_tickers.intersection(cash_daily.columns)
        ev_df[cash_overlap] = ev_df[cash_overlap] - cash_daily[cash_overlap].fillna(0)
        ev_ebitda_df = (ev_df / ebitda_ttm[ev_tickers]).replace([np.inf, -np.inf], np.nan)
    else:
        ev_ebitda_df = pd.DataFrame(index=trading_dates)

    return {
        "P/B": pb_df,
        "P/S": ps_df,
        "P/E": pe_df,
        "EV/EBITDA": ev_ebitda_df,
    }
