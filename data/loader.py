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
    """Load SimFin prices and compute market cap for the lookback period."""
    sf.set_api_key("4e0d0ff7-a1af-4333-9f4b-55d97e801b35")
    sf.set_data_dir("~/simfin_data/")

    df_prices = sf.load_shareprices(market="us", variant="daily")
    cutoff = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d")
    prices = df_prices[df_prices.index.get_level_values("Date") >= cutoff].copy()

    mktcap = (prices["Close"] * prices["Shares Outstanding"]).unstack("Ticker")
    mktcap = mktcap.loc[:, mktcap.columns.notna()]

    # Store close prices for key metrics
    close = prices["Close"].unstack("Ticker")
    close = close.loc[:, close.columns.notna()]

    return mktcap, close


def get_filing_dates(ticker):
    """Get filing dates for E markers on chart."""
    cik = get_cik_lookup()
    return fetch_filing_dates(ticker, cik)


def compute_all_ratios(mktcap):
    """Compute P/B, P/S, P/E, EV/EBITDA from cached EDGAR data."""
    trading_dates = mktcap.index

    # --- Price-to-Book ---
    eq_unstacked = cache_to_unstacked(_load_cache("equity"))
    equity_daily = build_daily_instant(eq_unstacked, trading_dates)
    bad_mask = equity_daily.isna() | (equity_daily <= 0)
    last_bad = bad_mask.apply(lambda col: col[col].index.max() if col.any() else pd.NaT)
    for t in equity_daily.columns:
        if pd.notna(last_bad[t]):
            equity_daily.loc[:last_bad[t], t] = np.nan
    common = mktcap.columns.intersection(equity_daily.columns)
    pb_df = (mktcap[common] / equity_daily[common]).replace([np.inf, -np.inf], np.nan)

    # --- Price-to-Sales (TTM) ---
    rev_unstacked = cache_to_unstacked(_load_cache("revenue"))
    revenue_ttm = build_daily_ttm(rev_unstacked, trading_dates)
    revenue_ttm = revenue_ttm.where(revenue_ttm > 0)
    common = mktcap.columns.intersection(revenue_ttm.columns)
    ps_df = (mktcap[common] / revenue_ttm[common]).replace([np.inf, -np.inf], np.nan)

    # --- Price-to-Earnings (TTM) ---
    ni_unstacked = cache_to_unstacked(_load_cache("net_income"))
    ni_ttm = build_daily_ttm(ni_unstacked, trading_dates)
    ni_ttm = ni_ttm.where(ni_ttm > 0)
    common = mktcap.columns.intersection(ni_ttm.columns)
    pe_df = (mktcap[common] / ni_ttm[common]).replace([np.inf, -np.inf], np.nan)

    # --- EV/EBITDA (TTM) ---
    debt_daily = build_daily_instant(
        cache_to_unstacked(_load_cache("debt")), trading_dates
    )
    cash_daily = build_daily_instant(
        cache_to_unstacked(_load_cache("cash")), trading_dates
    )
    oi_unstacked = cache_to_unstacked(_load_cache("op_income"))
    dna_unstacked = cache_to_unstacked(_load_cache("dna"))
    common_ebitda = oi_unstacked.columns.intersection(dna_unstacked.columns)
    ebitda_q = oi_unstacked[common_ebitda] + dna_unstacked[common_ebitda].fillna(0)
    ebitda_ttm = build_daily_ttm(ebitda_q, trading_dates)
    ebitda_ttm = ebitda_ttm.where(ebitda_ttm > 0)

    ev_tickers = mktcap.columns.intersection(ebitda_ttm.columns)
    ev_df = mktcap[ev_tickers].copy()
    debt_overlap = ev_tickers.intersection(debt_daily.columns)
    ev_df[debt_overlap] = ev_df[debt_overlap] + debt_daily[debt_overlap].fillna(0)
    cash_overlap = ev_tickers.intersection(cash_daily.columns)
    ev_df[cash_overlap] = ev_df[cash_overlap] - cash_daily[cash_overlap].fillna(0)
    ev_ebitda_df = (ev_df / ebitda_ttm[ev_tickers]).replace([np.inf, -np.inf], np.nan)

    return {
        "P/B": pb_df,
        "P/S": ps_df,
        "P/E": pe_df,
        "EV/EBITDA": ev_ebitda_df,
    }
