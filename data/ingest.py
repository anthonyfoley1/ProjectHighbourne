"""Ingest data from EDGAR caches and yfinance into the FinancialsStore."""

import json
import pandas as pd
import yfinance as yf
from pathlib import Path
from data.db import FinancialsStore, FIELDS

PROJECT_ROOT = Path(__file__).parent.parent

EDGAR_FIELD_MAP = {
    "edgar_equity_cache.json": "stockholders_equity",
    "edgar_revenue_cache.json": "revenue",
    "edgar_netincome_cache.json": "net_income",
    "edgar_opincome_cache.json": "operating_income",
    "edgar_dna_cache.json": "depreciation_amortization",
    "edgar_debt_cache.json": "total_debt",
    "edgar_cash_cache.json": "cash",
}

YF_INCOME_MAP = {
    "revenue": "Total Revenue",
    "net_income": "Net Income",
    "operating_income": "Operating Income",
    "depreciation_amortization": "Reconciled Depreciation",
}

YF_BALANCE_MAP = {
    "stockholders_equity": "Stockholders Equity",
    "total_debt": "Total Debt",
    "cash": "Cash And Cash Equivalents",
    "total_assets": "Total Assets",
}

YF_CASHFLOW_MAP = {
    "operating_cash_flow": "Operating Cash Flow",
    "capex": "Capital Expenditure",
    "free_cash_flow": "Free Cash Flow",
}


def ingest_edgar(store):
    """Load all EDGAR JSON caches into the store using bulk_upsert for efficiency."""
    print("Ingesting EDGAR caches...")
    all_rows = []
    for cache_file, field in EDGAR_FIELD_MAP.items():
        path = PROJECT_ROOT / cache_file
        if not path.exists():
            continue
        with open(path) as f:
            cache = json.load(f)
        count = 0
        for ticker, quarters in cache.items():
            if not quarters:
                continue
            for date_str, value in quarters.items():
                all_rows.append({
                    "ticker": ticker,
                    "period_end": date_str,
                    field: float(value),
                    "source": "edgar",
                })
                count += 1
        print(f"  {field}: {count} data points from {cache_file}")
    store.bulk_upsert(all_rows)
    store.save()


def ingest_yfinance_gaps(store, tickers, max_per_field=100):
    """Fill gaps in the store from yfinance. Only fills fields that are completely
    missing for a ticker — never partially fills."""
    print("Filling gaps from yfinance...")

    all_maps = {}
    all_maps.update({f: ("income_stmt", col) for f, col in YF_INCOME_MAP.items()})
    all_maps.update({f: ("balance_sheet", col) for f, col in YF_BALANCE_MAP.items()})
    all_maps.update({f: ("cashflow", col) for f, col in YF_CASHFLOW_MAP.items()})

    for field, (stmt_type, col_name) in all_maps.items():
        if field not in store.df.columns:
            missing = tickers
        else:
            has = store.df.dropna(subset=[field])["ticker"].unique()
            missing = [t for t in tickers if t not in has]

        if not missing:
            continue

        batch = missing[:max_per_field]
        print(f"  {field}: filling {len(batch)}/{len(missing)} missing tickers...")
        rows = []
        filled = 0
        for sym in batch:
            try:
                tk = yf.Ticker(sym)
                if stmt_type == "income_stmt":
                    q = tk.quarterly_income_stmt
                elif stmt_type == "balance_sheet":
                    q = tk.quarterly_balance_sheet
                else:
                    q = tk.quarterly_cashflow

                if q is None or q.empty:
                    continue

                col_name_actual = col_name
                if col_name not in q.index:
                    # Try alternative column names
                    alt_names = _alt_col_names(col_name)
                    found = None
                    for alt in alt_names:
                        if alt in q.index:
                            found = alt
                            break
                    if not found:
                        continue
                    col_name_actual = found

                row = q.loc[col_name_actual]
                for date_col, val in row.items():
                    if pd.notna(val):
                        rows.append({
                            "ticker": sym,
                            "period_end": str(pd.Timestamp(date_col).date()),
                            field: float(val),
                            "source": "yfinance",
                        })
                        filled += 1
            except Exception:
                continue
        if rows:
            store.bulk_upsert(rows)
            print(f"    -> filled {filled} data points")

    store.save()


def _alt_col_names(col):
    """Alternative column names for yfinance fields."""
    alts = {
        "Reconciled Depreciation": ["Depreciation And Amortization", "Depreciation Amortization Depletion"],
        "Cash And Cash Equivalents": ["Cash Cash Equivalents And Short Term Investments", "Cash Financial"],
        "Total Debt": ["Long Term Debt", "Total Non Current Liabilities Net Minority Interest"],
        "Stockholders Equity": ["Total Equity Gross Minority Interest", "Common Stock Equity"],
        "Capital Expenditure": ["Purchase Of PPE"],
    }
    return alts.get(col, [])


def compute_derived_fields(store):
    """Compute derived fields: EBITDA, gross profit, FCF."""
    if store.df.empty:
        return
    print("Computing derived fields...")

    # EBITDA = Operating Income + D&A
    if "operating_income" in store.df.columns and "depreciation_amortization" in store.df.columns:
        mask = store.df["ebitda"].isna() if "ebitda" in store.df.columns else pd.Series(True, index=store.df.index)
        has_both = store.df["operating_income"].notna() & store.df["depreciation_amortization"].notna() & mask
        if has_both.any():
            store.df.loc[has_both, "ebitda"] = store.df.loc[has_both, "operating_income"] + store.df.loc[has_both, "depreciation_amortization"]
            print(f"  EBITDA: computed for {has_both.sum()} rows")

    # FCF = Operating Cash Flow - CapEx (capex is usually negative in yfinance)
    if "operating_cash_flow" in store.df.columns and "capex" in store.df.columns:
        mask = store.df["free_cash_flow"].isna() if "free_cash_flow" in store.df.columns else pd.Series(True, index=store.df.index)
        has_both = store.df["operating_cash_flow"].notna() & store.df["capex"].notna() & mask
        if has_both.any():
            store.df.loc[has_both, "free_cash_flow"] = store.df.loc[has_both, "operating_cash_flow"] + store.df.loc[has_both, "capex"]
            print(f"  FCF: computed for {has_both.sum()} rows")

    store.save()


def validate(store):
    """Flag and null out suspect data points."""
    if store.df.empty:
        return
    print("Validating data...")
    flagged = 0

    # Negative revenue -> null
    if "revenue" in store.df.columns:
        bad = store.df["revenue"] < 0
        if bad.any():
            store.df.loc[bad, "revenue"] = None
            flagged += bad.sum()

    # Negative equity -> null (for P/B)
    if "stockholders_equity" in store.df.columns:
        bad = store.df["stockholders_equity"] < 0
        if bad.any():
            store.df.loc[bad, "stockholders_equity"] = None
            flagged += bad.sum()

    # Extreme outliers: values >20x ticker median
    for field in ["revenue", "net_income", "operating_income", "ebitda"]:
        if field not in store.df.columns:
            continue
        grouped = store.df.groupby("ticker")[field]
        medians = grouped.transform("median")
        bad = (store.df[field].abs() > medians.abs() * 20) & store.df[field].notna() & (medians.abs() > 0)
        if bad.any():
            store.df.loc[bad, field] = None
            flagged += bad.sum()

    if flagged:
        print(f"  Flagged and nulled {flagged} suspect values")
        store.save()
    else:
        print("  No issues found")


def full_refresh(tickers):
    """Run complete ingestion pipeline."""
    store = FinancialsStore()
    ingest_edgar(store)
    ingest_yfinance_gaps(store, tickers, max_per_field=100)
    compute_derived_fields(store)
    validate(store)
    store.coverage_stats()
    return store
