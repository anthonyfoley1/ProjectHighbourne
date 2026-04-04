"""SEC EDGAR XBRL API utilities for fetching financial data."""

import requests
import json
import os
import time
import pandas as pd
import numpy as np

SEC_HEADERS = {"User-Agent": "ProjectHighbourne research@example.com"}

FILING_DATES_CACHE = "edgar_filing_dates_cache.json"


def fetch_filing_dates(ticker, cik_lookup):
    """
    Fetch 10-Q and 10-K filing dates for a ticker from EDGAR.
    Returns list of {"date": "YYYY-MM-DD", "form": "10-Q"/"10-K"} sorted by date.
    Caches results locally.
    """
    cache_path = FILING_DATES_CACHE
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            cache = json.load(f)
    else:
        cache = {}

    if ticker in cache:
        return cache[ticker]

    if ticker not in cik_lookup:
        return []

    cik = cik_lookup[ticker]
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        resp = requests.get(url, headers=SEC_HEADERS)
        if resp.status_code != 200:
            cache[ticker] = []
            return []

        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])

        filings = []
        seen = set()
        for form, date in zip(forms, dates):
            if form in ("10-Q", "10-K") and date not in seen:
                filings.append({"date": date, "form": form})
                seen.add(date)

        filings.sort(key=lambda x: x["date"])
        cache[ticker] = filings

        with open(cache_path, "w") as f:
            json.dump(cache, f)

        time.sleep(0.125)
    except Exception:
        cache[ticker] = []

    return cache.get(ticker, [])


def load_cik_lookup():
    """Load ticker -> CIK mapping from SEC."""
    resp = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS)
    ticker_map = resp.json()
    return {v["ticker"]: str(v["cik_str"]).zfill(10) for v in ticker_map.values()}


def _reconcile_quarterly_with_annual(quarterly_entries, annual_entries):
    """
    Use audited 10-K annual figures to reconcile Q4 values.

    Matches annual periods to their constituent quarters using start/end dates
    (not calendar year), so this works correctly for non-calendar fiscal years.

    For each annual period where we have 3 of 4 quarters, derives the missing
    quarter as: Q_missing = Annual - sum(other 3 quarters).
    Also corrects existing Q4 if all 4 quarters are present.

    Args:
        quarterly_entries: list of {start, end, val} dicts — standalone quarters
        annual_entries: list of {start, end, val} dicts — annual periods from 10-K

    Returns:
        dict of {date_str: value} — quarterly values with Q4 reconciled
    """
    if not annual_entries:
        return {e["end"]: e["val"] for e in quarterly_entries}

    from datetime import datetime, timedelta

    result = {}
    q_by_end = {}
    for e in quarterly_entries:
        result[e["end"]] = e["val"]
        q_by_end[e["end"]] = e

    for ann in annual_entries:
        ann_start = datetime.strptime(ann["start"], "%Y-%m-%d")
        ann_end = datetime.strptime(ann["end"], "%Y-%m-%d")
        ann_val = ann["val"]

        # Find quarters that fall within this annual period
        matched_qs = []
        for e in quarterly_entries:
            q_start = datetime.strptime(e["start"], "%Y-%m-%d")
            q_end = datetime.strptime(e["end"], "%Y-%m-%d")
            # Quarter belongs to this annual if it starts on or after annual start
            # and ends on or before annual end
            if q_start >= ann_start and q_end <= ann_end:
                matched_qs.append(e)

        if len(matched_qs) == 0:
            # No quarterly data — split annual into 4 synthetic quarters
            # so rolling-4 sum still produces the correct annual total.
            # Space them ~90 days apart ending at the annual end date.
            for i in range(4):
                q_end = ann_end - timedelta(days=90 * (3 - i))
                result[q_end.strftime("%Y-%m-%d")] = ann_val / 4
        elif len(matched_qs) == 3:
            # Missing one quarter — derive it
            q_sum = sum(e["val"] for e in matched_qs)
            derived_val = ann_val - q_sum
            result[ann["end"]] = derived_val
        elif len(matched_qs) == 4:
            # All 4 present — correct the last quarter to match audited annual
            matched_qs.sort(key=lambda e: e["end"])
            last_q = matched_qs[-1]
            other_sum = sum(e["val"] for e in matched_qs[:-1])
            result[last_q["end"]] = ann_val - other_sum

    return result


# Alternative XBRL concept names — try primary first, then alternatives
# Primary + alternatives for each concept, ordered by prevalence.
# Based on empirical check across MSFT, AAPL, AMZN, GOOG, META, JPM, HD, WMT, JNJ, PG.
CONCEPT_ALTERNATIVES = {
    "Revenues": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",  # ASC 606 (post-2018), used by all major filers
        "SalesRevenueNet",                                      # pre-2018 legacy
        "SalesRevenueGoodsNet",                                 # product-only revenue
        "RevenueFromContractWithCustomerIncludingAssessedTax",  # includes sales tax
    ],
    "DepreciationDepletionAndAmortization": [
        "Depreciation",                                         # MSFT, GOOG use this (current!)
        "DepreciationAndAmortization",                          # some filers
        "DepreciationAmortizationAndAccretionNet",              # AAPL used historically
    ],
    "LongTermDebt": [
        "LongTermDebtNoncurrent",                               # all major filers have this
        "LongTermDebtAndCapitalLeaseObligations",               # GOOG
    ],
    "CashAndCashEquivalentsAtCarryingValue": [
        "CashCashEquivalentsAndShortTermInvestments",           # MSFT, GOOG (broader definition)
    ],
    "StockholdersEquity": [
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "NetIncomeLoss": [
        "NetIncomeLossAvailableToCommonStockholdersBasic",      # GOOG, META
        "ProfitLoss",
    ],
    "OperatingIncomeLoss": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ],
}


def _fetch_single_concept(ticker, cik, concept, concept_type):
    """Fetch a single concept for a single ticker from EDGAR. Returns {date: value} or {}."""
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"
    try:
        resp = requests.get(url, headers=SEC_HEADERS)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        entries = data.get("units", {}).get("USD", [])
        if concept_type == "duration":
            quarterly_entries = []
            annual_entries = []
            for e in entries:
                if e["form"] in ("10-Q", "10-K") and "frame" in e and "start" in e:
                    frame = e["frame"]
                    if "Q" in frame and not frame.endswith("I"):
                        quarterly_entries.append({"start": e["start"], "end": e["end"], "val": e["val"]})
                    elif frame.startswith("CY") and "Q" not in frame and not frame.endswith("I"):
                        annual_entries.append({"start": e["start"], "end": e["end"], "val": e["val"]})
            return _reconcile_quarterly_with_annual(quarterly_entries, annual_entries)
        else:  # instant
            by_date = {}
            for e in entries:
                if e["form"] in ("10-Q", "10-K") and "frame" in e:
                    frame = e["frame"]
                    if frame.endswith("I"):
                        by_date[e["end"]] = e["val"]
            return by_date
    except Exception:
        return {}


def fetch_concept(tickers, concept, cache_file, cik_lookup, concept_type="instant"):
    """
    Fetch a US-GAAP concept from EDGAR for a list of tickers.

    Tries the primary concept first. If a ticker's data is empty or stale
    (latest entry > 2 years old), tries alternative XBRL concept names.

    For duration concepts (income statement), fetches both quarterly and annual
    frames. Uses audited annual (10-K) figures to reconcile Q4 values:
    Q4 = Annual - Q1 - Q2 - Q3.

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

    # --- Pass 1: Fetch primary concept for uncached tickers ---
    batch_size = 50
    for i in range(0, len(remaining), batch_size):
        batch = remaining[i:i + batch_size]
        print(f"  Batch {i // batch_size + 1}/{(len(remaining) - 1) // batch_size + 1}: {len(batch)}...", end=" ")

        got = 0
        for t in batch:
            cik = cik_lookup[t]
            by_date = _fetch_single_concept(t, cik, concept, concept_type)
            cache[t] = by_date
            if by_date:
                got += 1
            time.sleep(0.125)

        with open(cache_file, "w") as f:
            json.dump(cache, f)
        print(f"got {got}/{len(batch)}")

    # --- Pass 2: Try alternative concepts for empty/stale tickers ---
    alternatives = CONCEPT_ALTERNATIVES.get(concept, [])
    if alternatives:
        from datetime import datetime as dt
        cutoff = (dt.now() - pd.Timedelta(days=730)).strftime("%Y-%m-%d")  # 2 years ago

        stale_tickers = []
        for t in tickers:
            if t not in cik_lookup:
                continue
            data = cache.get(t, {})
            if not data:
                stale_tickers.append(t)
            else:
                latest = max(data.keys()) if data else ""
                if latest < cutoff:
                    stale_tickers.append(t)

        if stale_tickers:
            print(f"  Trying alternatives for {len(stale_tickers)} stale/empty tickers...")
            fixed = 0
            for t in stale_tickers:
                cik = cik_lookup[t]
                for alt_concept in alternatives:
                    by_date = _fetch_single_concept(t, cik, alt_concept, concept_type)
                    if by_date:
                        latest = max(by_date.keys())
                        if latest >= cutoff:
                            cache[t] = by_date
                            fixed += 1
                            break
                    time.sleep(0.125)
            if fixed:
                print(f"    -> fixed {fixed} tickers with alternative concepts")
                with open(cache_file, "w") as f:
                    json.dump(cache, f)

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

    For each ticker, sums the last 4 non-null quarterly values (skipping dates
    where that ticker has no data), then forward-fills to trading dates.
    """
    unstacked = unstacked.sort_index()

    # Per-ticker: drop NaNs, rolling sum of last 4 actual quarterly values
    ttm_parts = {}
    for ticker in unstacked.columns:
        series = unstacked[ticker].dropna()
        if len(series) >= 4:
            ttm_parts[ticker] = series.rolling(window=4, min_periods=4).sum()

    if not ttm_parts:
        return pd.DataFrame(index=trading_dates)

    ttm = pd.DataFrame(ttm_parts)

    # Forward-fill to trading dates
    all_dates = ttm.index.union(trading_dates).sort_values()
    daily = ttm.reindex(all_dates).ffill()
    return daily.reindex(trading_dates)
