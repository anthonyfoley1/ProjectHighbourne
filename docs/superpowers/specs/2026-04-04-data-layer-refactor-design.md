# Data Layer Refactor — Normalized Quarterly Database

## Problem

The current data pipeline has structural issues:

1. **EDGAR XBRL tag mismatches** — ~30% of companies report under alternative XBRL tags (e.g., `RevenueFromContractWithCustomerExcludingAssessedTax` instead of `Revenues`). The yfinance fallback patches this but is slow and limited to 200 tickers.

2. **No clean quarterly database** — Financial data goes directly from raw EDGAR JSON → unstacked DataFrame → TTM rolling sum → daily ratio. There's no intermediate layer where you can inspect or validate quarterly values per ticker.

3. **TTM computed at the wrong layer** — TTM rolling sums happen during data loading, tangled with caching and forward-filling logic. TTM should be a clean computation on top of validated quarterly data.

4. **Can't switch between quarterly and annual views** — Everything is hardcoded to TTM. No ability to view single-quarter trends or annual snapshots.

5. **Data source blending risk** — The yfinance fallback adds complexity. Need a clear per-ticker flag indicating the data source.

## Solution

A **normalized quarterly DataFrame** saved as a parquet file. Clean, validated quarterly values per ticker per period. All downstream computations (TTM, ratios, z-scores) reference this DataFrame.

```
Data Sources (EDGAR, yfinance)
    ↓ fetch + normalize
Quarterly DataFrame (parquet on disk)
    ↓ query/slice
Computation Layer (TTM, ratios)
    ↓
Dashboard (charts, screener)
```

## DataFrame Schema

### `quarterly_financials.parquet`

MultiIndex: `(ticker, period_end)` — one row per ticker per quarter.

```
Columns:
    period          str     'Q1 2024', 'Q2 2024', etc.
    fiscal_year     int     2024
    fiscal_qtr      int     1, 2, 3, or 4

    # Income Statement (duration — summed for TTM)
    revenue                     float
    cost_of_revenue             float
    gross_profit                float
    operating_income            float
    net_income                  float
    ebitda                      float
    eps_diluted                 float
    depreciation_amortization   float

    # Balance Sheet (instant — forward-filled)
    total_assets                float
    total_debt                  float
    cash                        float
    stockholders_equity         float

    # Cash Flow (duration — summed for TTM)
    operating_cash_flow         float
    capex                       float
    free_cash_flow              float

    # Metadata
    source          str     'edgar' or 'yfinance'
```

## Data Ingestion

### Step 1: EDGAR → quarterly rows

For each ticker, for each EDGAR concept:
1. Fetch quarterly entries (10-Q) and annual entries (10-K)
2. Reconcile Q4 using existing `_reconcile_quarterly_with_annual()` logic
3. Map to standardized field names
4. Insert into `financials` table with `source='edgar'`

**EDGAR concept → field mapping:**
| EDGAR Concept | DB Field |
|---|---|
| `Revenues` | `revenue` |
| `RevenueFromContractWithCustomerExcludingAssessedTax` | `revenue` (alt tag) |
| `NetIncomeLoss` | `net_income` |
| `OperatingIncomeLoss` | `operating_income` |
| `StockholdersEquity` | `stockholders_equity` |
| `LongTermDebt` + `ShortTermBorrowings` | `total_debt` |
| `CashAndCashEquivalentsAtCarryingValue` | `cash` |
| `DepreciationDepletionAndAmortization` | `depreciation_amortization` |

Try the primary concept first. If empty, try known alternatives. This solves the DASH revenue problem at the source.

### Step 2: yfinance fallback

For tickers where EDGAR returned no data for a field:
1. Fetch from yfinance (`quarterly_income_stmt`, `quarterly_balance_sheet`, `quarterly_cashflow`)
2. Insert into `financials` with `source='yfinance'`
3. **Never mix**: if EDGAR has any data for a field/ticker, don't touch it with yfinance

### Step 3: Derived fields

After ingestion, compute derived fields for each row:
```python
gross_profit = revenue - cost_of_revenue  (if not directly available)
ebitda = operating_income + depreciation_amortization
free_cash_flow = operating_cash_flow - capex
```

## Validation Step

After ingestion, run quality checks before the data feeds into ratio calculations:

```python
def validate_quarterly(store):
    """Flag and optionally null out suspect data points."""

    # 1. Revenue drop >80% QoQ — likely bad data or restatement
    #    Flag row, null the value, log warning

    # 2. Negative values where they shouldn't be
    #    - revenue < 0 → null
    #    - stockholders_equity < 0 → null (for P/B purposes)
    #    - total_assets < 0 → null

    # 3. Gap detection — missing quarters in the middle of a series
    #    e.g., Q1 2023, Q3 2023 (Q2 missing) → log warning
    #    Don't null anything, just flag for review

    # 4. Extreme outliers — values >10x the ticker's median for that field
    #    Likely a units mismatch (thousands vs millions)
    #    Flag and null

    # Returns: DataFrame of flagged rows with reason
```

This catches garbage data before it hits the ratio calculations. Print a summary at startup: "Validated 2,219 tickers — flagged 43 suspect data points across 28 tickers."

## Computation Layer

### TTM (Trailing Twelve Months)

```python
def get_ttm(ticker, field, as_of_date=None):
    """Sum the last 4 quarterly values for a duration field."""
    # Query last 4 rows from financials where period_end <= as_of_date
    # Return sum
```

For **daily ratio time series**, the approach stays the same as now:
1. Get all quarterly values for a ticker
2. Rolling sum of last 4 = TTM at each quarter end
3. Forward-fill to daily trading dates
4. Market Cap / TTM = daily ratio

The difference: the quarterly values now come from a clean, validated SQLite table instead of being parsed from raw EDGAR JSON on every startup.

### Balance Sheet (instant) fields

For fields like `stockholders_equity`, `total_debt`, `cash`:
- No TTM needed — these are point-in-time values
- Forward-fill the latest quarterly value to daily trading dates

### Ratio Calculations

Same as current, but sourced from the database:

```python
P/B = Market Cap / Stockholders' Equity           (instant, forward-filled)
P/S = Market Cap / Revenue (TTM)                   (rolling 4Q sum)
P/E = Market Cap / Net Income (TTM)                (rolling 4Q sum, only when > 0)
EV/EBITDA = Enterprise Value / EBITDA (TTM)        (rolling 4Q sum, only when > 0)

Enterprise Value = Market Cap + Total Debt - Cash  (all instant, forward-filled)
EBITDA = Operating Income + D&A                    (rolling 4Q sum)
```

**Key rules:**
- P/E: skip periods where Net Income TTM <= 0 (negative earnings → meaningless P/E)
- EV/EBITDA: skip periods where EBITDA TTM <= 0 (negative EBITDA → meaningless ratio)
- P/S: skip periods where Revenue TTM <= 0
- P/B: skip periods where Equity <= 0

## New Module: `data/db.py`

```python
"""Quarterly financials store — pandas DataFrame backed by parquet."""

import pandas as pd
from pathlib import Path

PARQUET_PATH = Path(__file__).parent.parent / "quarterly_financials.parquet"

class FinancialsStore:
    def __init__(self, path=PARQUET_PATH):
        self.path = path
        if path.exists():
            self.df = pd.read_parquet(path)
        else:
            self.df = pd.DataFrame()

    def save(self):
        """Persist to disk."""
        self.df.to_parquet(self.path)

    def upsert(self, ticker, period_end, data, source):
        """Insert or update a quarterly row."""

    def get_quarterly(self, ticker, field=None):
        """Get quarterly data for a ticker."""

    def get_field_series(self, field, tickers=None):
        """Get quarterly time series for a field across tickers.
        Returns unstacked DataFrame (dates x tickers) — 
        same format compute_all_ratios expects."""

    def tickers_missing(self, field):
        """List tickers with no data for a field."""

    def coverage_stats(self):
        """Print how many tickers have each field."""
```

## New Module: `data/ingest.py`

```python
"""Data ingestion pipeline — EDGAR + yfinance → SQLite."""

class Ingester:
    def __init__(self, db: FinancialsDB):
        self.db = db

    def ingest_edgar(self, tickers, cik_lookup):
        """Fetch all EDGAR data and insert into DB."""
        # For each concept, try primary + alternative XBRL tags
        # Insert with source='edgar'

    def ingest_yfinance_fallback(self, tickers, max_per_field=200):
        """Fill missing data from yfinance."""
        # For each field, find tickers with no data in store
        # Fetch from yfinance, upsert with source='yfinance'

    def full_refresh(self, tickers, cik_lookup):
        """Run complete ingestion pipeline."""
        self.ingest_edgar(tickers, cik_lookup)
        self.ingest_yfinance_fallback(tickers)
        self.store.save()  # persist to parquet
```

## Modified: `data/loader.py`

Simplify dramatically. Instead of the current 386-line file with EDGAR parsing, cache loading, and yfinance fallback:

```python
def compute_all_ratios(mktcap, store: FinancialsStore):
    """Compute P/B, P/S, P/E, EV/EBITDA from the quarterly store."""
    trading_dates = mktcap.index

    # Get quarterly data from store (already clean and normalized)
    equity = store.get_field_series("stockholders_equity")
    revenue = store.get_field_series("revenue")
    net_income = store.get_field_series("net_income")
    # ... etc

    # Build daily series using existing forward-fill and TTM logic
    # (reuse build_daily_instant, build_daily_ttm from edgar_utils.py)
```

## Migration Path

1. **Build `data/db.py` and `data/ingest.py`** — new modules, don't touch existing code
2. **Run initial ingestion** — populate parquet from existing EDGAR cache files + yfinance fallback
3. **Modify `data/loader.py`** — switch `compute_all_ratios` to read from parquet store instead of JSON caches
4. **Verify** — same ratio outputs as before (within floating point tolerance)
5. **Remove old code** — delete JSON cache loading, yfinance fallback hacks

The existing EDGAR cache JSON files become the initial seed for the parquet store, then are no longer needed at runtime.

## Benefits

1. **Inspect any ticker's quarterly data** — `SELECT * FROM financials WHERE ticker='DASH'`
2. **Know the data source** — `source` column tells you edgar vs yfinance
3. **Switch views** — quarterly, annual (sum 4 Qs), TTM — all from the same data
4. **Fix data issues** — manually correct bad values without refetching
5. **Faster startup** — parquet reads are faster than parsing JSON + yfinance API calls
6. **Future: financial analysis tables** — the detail page's I/S, B/S, C/F tabs can query directly from the store
7. **Future: earnings surprise** — store EPS estimates alongside actuals
8. **Future: DuPont ROE** — all components available in the same table

## What Stays the Same

- SimFin for daily prices and market cap (no change)
- `models/ticker.py` — Ticker and Universe classes (no change)
- `data/technicals.py` — technical indicators (no change)
- `data/risk.py` — risk metrics (no change)
- Chart rendering logic (no change)
- TTM rolling sum approach — same math, cleaner input data
