"""SEC EDGAR XBRL API utilities for fetching financial data."""

import requests
import json
import os
import time
import pandas as pd
import numpy as np

SEC_HEADERS = {"User-Agent": "ProjectHighbourne research@example.com"}


def load_cik_lookup():
    """Load ticker -> CIK mapping from SEC."""
    resp = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS)
    ticker_map = resp.json()
    return {v["ticker"]: str(v["cik_str"]).zfill(10) for v in ticker_map.values()}


def fetch_concept(tickers, concept, cache_file, cik_lookup, concept_type="instant"):
    """
    Fetch a US-GAAP concept from EDGAR for a list of tickers.

    Args:
        tickers: list of ticker strings
        concept: EDGAR XBRL concept name (e.g. 'StockholdersEquity', 'Revenues')
        cache_file: path to JSON cache file
        cik_lookup: dict of ticker -> CIK
        concept_type: 'instant' for balance sheet items, 'duration' for income/cash flow items

    Returns:
        dict of {ticker: {date_str: value}}
    """
    if os.path.exists(cache_file):
        with open(cache_file, "r") as f:
            cache = json.load(f)
    else:
        cache = {}

    remaining = [t for t in tickers if t not in cache and t in cik_lookup]
    cached = sum(1 for t in tickers if t in cache)
    no_cik = sum(1 for t in tickers if t not in cik_lookup)

    print(f"[{concept}] Total: {len(tickers)} | Cached: {cached} | No CIK: {no_cik} | To fetch: {len(remaining)}")

    batch_size = 50
    for i in range(0, len(remaining), batch_size):
        batch = remaining[i:i + batch_size]
        print(f"  Batch {i // batch_size + 1}/{(len(remaining) - 1) // batch_size + 1}: {len(batch)}...", end=" ")

        got = 0
        for t in batch:
            cik = cik_lookup[t]
            url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"
            try:
                resp = requests.get(url, headers=SEC_HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    entries = data.get("units", {}).get("USD", [])
                    by_date = {}
                    for e in entries:
                        if e["form"] in ("10-Q", "10-K") and "frame" in e:
                            frame = e["frame"]
                            # For duration concepts, only keep quarterly frames (CY2024Q1, not CY2024)
                            # For instant concepts, keep quarterly instant frames (CY2024Q1I)
                            if concept_type == "duration":
                                if "Q" in frame and not frame.endswith("I"):
                                    by_date[e["end"]] = e["val"]
                            else:  # instant
                                if frame.endswith("I"):
                                    by_date[e["end"]] = e["val"]
                    cache[t] = by_date
                    if by_date:
                        got += 1
                else:
                    cache[t] = {}
            except Exception:
                cache[t] = {}

            time.sleep(0.125)

        with open(cache_file, "w") as f:
            json.dump(cache, f)
        print(f"got {got}/{len(batch)}")

    has_data = sum(1 for t in tickers if cache.get(t))
    print(f"  Result: {has_data}/{len(tickers)} tickers with data\n")
    return cache


def cache_to_unstacked(cache):
    """Convert a {ticker: {date: val}} cache dict to an unstacked DataFrame."""
    records = []
    for ticker, reports in cache.items():
        if reports:
            for date_str, value in reports.items():
                records.append({"Ticker": ticker, "Date": pd.Timestamp(date_str), "Value": float(value)})
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records).set_index(["Ticker", "Date"])["Value"]
    return df.unstack("Ticker")


def build_daily_instant(unstacked, trading_dates):
    """Forward-fill an instant (balance sheet) concept to daily trading dates."""
    all_dates = unstacked.index.union(trading_dates).sort_values()
    daily = unstacked.reindex(all_dates).ffill()
    return daily.reindex(trading_dates)


def build_daily_ttm(unstacked, trading_dates):
    """
    Convert quarterly duration data to trailing-twelve-month (TTM) daily values.

    Sums the last 4 quarterly values, then forward-fills to trading dates.
    """
    # Sort by date
    unstacked = unstacked.sort_index()

    # Rolling sum of last 4 quarters
    ttm = unstacked.rolling(window=4, min_periods=4).sum()

    # Forward-fill to trading dates
    all_dates = ttm.index.union(trading_dates).sort_values()
    daily = ttm.reindex(all_dates).ffill()
    return daily.reindex(trading_dates)
