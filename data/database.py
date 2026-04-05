"""SQLite database layer for Highbourne Terminal."""

import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "highbourne.db"


class Database:
    def __init__(self, path=None):
        self.path = str(path or DB_PATH)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        c = self.conn.cursor()

        c.execute("""CREATE TABLE IF NOT EXISTS tickers (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            sector TEXT,
            industry TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS prices (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL,
            volume REAL,
            PRIMARY KEY (ticker, date)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS shares_outstanding (
            ticker TEXT PRIMARY KEY,
            shares REAL
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS financials (
            ticker TEXT NOT NULL,
            period_end TEXT NOT NULL,
            revenue REAL,
            operating_income REAL,
            net_income REAL,
            ebitda REAL,
            depreciation_amortization REAL,
            total_assets REAL,
            total_debt REAL,
            cash REAL,
            stockholders_equity REAL,
            eps_diluted REAL,
            operating_cash_flow REAL,
            capex REAL,
            free_cash_flow REAL,
            source TEXT DEFAULT 'edgar',
            PRIMARY KEY (ticker, period_end)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS screener (
            symbol TEXT PRIMARY KEY,
            name TEXT, sector TEXT,
            rv_sig TEXT, z_score REAL,
            rsi REAL, macd TEXT,
            ret_1d REAL, ret_3d REAL,
            signal TEXT, alert_type TEXT, alert_reason TEXT,
            ma_trend TEXT, price REAL,
            low_52w REAL, high_52w REAL, pct_52w REAL,
            short_interest REAL
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS market_risk (
            date TEXT PRIMARY KEY,
            vix REAL, vix_change REAL,
            fear_greed INTEGER, fear_greed_label TEXT,
            pct_above_200sma REAL, pct_above_50sma REAL,
            avg_rsi REAL,
            new_highs INTEGER, new_lows INTEGER,
            advancers INTEGER, decliners INTEGER, unchanged INTEGER,
            verdict_level TEXT, verdict_color TEXT, verdict_guidance TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS earnings (
            ticker TEXT NOT NULL,
            quarter TEXT NOT NULL,
            actual REAL, estimate REAL,
            surprise_pct REAL, px_move_3d REAL,
            PRIMARY KEY (ticker, quarter)
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT,
            headline TEXT, source TEXT, url TEXT,
            age TEXT, fetched_at TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS sector_stats (
            sector TEXT NOT NULL,
            date TEXT NOT NULL,
            median_return REAL,
            PRIMARY KEY (sector, date)
        )""")

        self.conn.commit()

    def query(self, sql, params=None):
        return pd.read_sql_query(sql, self.conn, params=params or [])

    def execute(self, sql, params=None):
        self.conn.execute(sql, params or [])
        self.conn.commit()

    def executemany(self, sql, params_list):
        self.conn.executemany(sql, params_list)
        self.conn.commit()

    def table_count(self, table):
        r = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return r[0] if r else 0

    def close(self):
        self.conn.close()


def get_db():
    """Get or create the global database instance."""
    return Database()
