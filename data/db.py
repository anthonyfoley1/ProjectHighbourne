"""Quarterly financials store — pandas DataFrame backed by parquet."""

import pandas as pd
from pathlib import Path

PARQUET_PATH = Path(__file__).parent.parent / "quarterly_financials.parquet"

FIELDS = [
    "revenue", "cost_of_revenue", "gross_profit", "operating_income",
    "net_income", "ebitda", "eps_diluted", "depreciation_amortization",
    "total_assets", "total_debt", "cash", "stockholders_equity",
    "operating_cash_flow", "capex", "free_cash_flow",
]

class FinancialsStore:
    def __init__(self, path=PARQUET_PATH):
        self.path = Path(path)
        if self.path.exists():
            self.df = pd.read_parquet(self.path)
        else:
            self.df = pd.DataFrame()

    def save(self):
        if not self.df.empty:
            self.df.to_parquet(self.path)

    def upsert(self, ticker, period_end, data, source="edgar"):
        """Insert or update a quarterly row."""
        period_end = pd.Timestamp(period_end)
        idx = (self.df["ticker"] == ticker) & (self.df["period_end"] == period_end)
        row = {"ticker": ticker, "period_end": period_end, "source": source}
        row.update(data)
        if idx.any():
            for k, v in row.items():
                if k in self.df.columns:
                    self.df.loc[idx, k] = v
        else:
            self.df = pd.concat([self.df, pd.DataFrame([row])], ignore_index=True)

    def bulk_upsert(self, rows):
        """Efficient batch insert: merge a list of row dicts into the store.

        Much faster than calling upsert() thousands of times because it
        builds a single DataFrame from all new rows and merges once.
        """
        if not rows:
            return
        new_df = pd.DataFrame(rows)
        new_df["period_end"] = pd.to_datetime(new_df["period_end"])

        # The incoming rows may have duplicate (ticker, period_end) keys when
        # multiple cache files contribute different fields for the same quarter.
        # Group them first so each (ticker, period_end) has one row with all fields.
        if new_df.duplicated(subset=["ticker", "period_end"], keep=False).any():
            new_df = new_df.groupby(["ticker", "period_end"], as_index=False).first()

        if self.df.empty:
            self.df = new_df
            return

        # Ensure period_end dtype matches
        if "period_end" in self.df.columns:
            self.df["period_end"] = pd.to_datetime(self.df["period_end"])

        # Merge fields: set index to (ticker, period_end), combine_first to
        # fill gaps from existing data, then reset index.
        existing = self.df.set_index(["ticker", "period_end"])
        incoming = new_df.set_index(["ticker", "period_end"])

        # For rows that exist in both, update non-null incoming values
        combined = incoming.combine_first(existing)
        self.df = combined.reset_index()

    def get_quarterly(self, ticker):
        """Get all quarterly data for a ticker, sorted by date."""
        if self.df.empty:
            return pd.DataFrame()
        mask = self.df["ticker"] == ticker
        return self.df[mask].sort_values("period_end")

    def get_field_series(self, field):
        """Get quarterly time series for a field across all tickers.
        Returns unstacked DataFrame (dates x tickers) — same format loader.py expects."""
        if self.df.empty or field not in self.df.columns:
            return pd.DataFrame()
        subset = self.df[["ticker", "period_end", field]].dropna(subset=[field])
        if subset.empty:
            return pd.DataFrame()
        pivoted = subset.pivot_table(index="period_end", columns="ticker", values=field, aggfunc="first")
        return pivoted.sort_index()

    def tickers_missing(self, field):
        """List tickers with no data for a field."""
        if self.df.empty:
            return []
        has_data = self.df.dropna(subset=[field])["ticker"].unique()
        all_tickers = self.df["ticker"].unique()
        return [t for t in all_tickers if t not in has_data]

    def coverage_stats(self):
        """Print coverage: how many tickers have each field."""
        if self.df.empty:
            print("Store is empty")
            return
        n_tickers = self.df["ticker"].nunique()
        n_rows = len(self.df)
        print(f"Store: {n_tickers} tickers, {n_rows} quarterly rows")
        for field in FIELDS:
            if field in self.df.columns:
                has = self.df[field].notna().groupby(self.df["ticker"]).any().sum()
                print(f"  {field}: {has}/{n_tickers} tickers")
