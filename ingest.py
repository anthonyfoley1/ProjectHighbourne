"""Standalone ingestion script — run daily to populate highbourne.db.

Usage: python3 ingest.py
"""
import sys
import os
import json
import math
import time

sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import numpy as np

from data.database import Database
from data.loader import load_tickers, load_market_data
from data.technicals import compute_rsi, compute_macd, compute_sma, macd_signal_label, ma_trend_label
from data.risk import (
    fetch_vix, compute_fear_greed, compute_breadth_stats,
    compute_new_highs_lows, compute_advancers_decliners, compute_risk_verdict,
)
from data.market_data import compute_returns, compute_52w_range, fetch_earnings_history
from data.news import fetch_market_news, fetch_company_news
from models.ticker import Ticker, Universe, compute_alert, compute_signal_label
from edgar_utils import cache_to_unstacked, build_daily_instant, build_daily_ttm
from data.db import FinancialsStore
from data.ingest import ingest_edgar, ingest_yfinance_gaps, compute_derived_fields, validate
from data.sectors import compute_sector_returns
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    db = Database()

    # ------------------------------------------------------------------
    # Step 1: Tickers
    # ------------------------------------------------------------------
    print("1. Loading tickers...")
    tickers_df = load_tickers()
    db.executemany(
        "INSERT OR REPLACE INTO tickers (symbol, name, sector) VALUES (?,?,?)",
        [(r["Ticker"], r["Name"], r["Sector"]) for _, r in tickers_df.iterrows()]
    )
    print(f"   {db.table_count('tickers')} tickers")

    symbols = tickers_df["Ticker"].tolist()
    ticker_sectors = dict(zip(tickers_df["Ticker"], tickers_df["Sector"]))
    ticker_names = dict(zip(tickers_df["Ticker"], tickers_df["Name"]))

    # ------------------------------------------------------------------
    # Step 2: Prices from yfinance
    # ------------------------------------------------------------------
    print("2. Loading prices...")
    mktcap, close = load_market_data(years=5)
    # Insert close prices into the prices table
    price_rows = []
    for ticker in close.columns:
        series = close[ticker].dropna()
        for date, val in series.items():
            price_rows.append((ticker, str(pd.Timestamp(date).date()), float(val), None))
    print(f"   Inserting {len(price_rows)} price rows...")
    BATCH = 50000
    for i in range(0, len(price_rows), BATCH):
        db.executemany(
            "INSERT OR REPLACE INTO prices (ticker, date, close, volume) VALUES (?,?,?,?)",
            price_rows[i:i + BATCH]
        )
    print(f"   {db.table_count('prices')} price rows in DB")

    # ------------------------------------------------------------------
    # Step 3: Shares outstanding from SimFin (already loaded by load_market_data)
    # ------------------------------------------------------------------
    print("3. Loading shares outstanding...")
    # mktcap = close * shares, so shares = mktcap / close for any day
    last_close = close.ffill().iloc[-1]
    last_mktcap = mktcap.ffill().iloc[-1]
    shares_rows = []
    for ticker in mktcap.columns:
        c_val = last_close.get(ticker)
        m_val = last_mktcap.get(ticker)
        if pd.notna(c_val) and pd.notna(m_val) and c_val > 0:
            shares = m_val / c_val
            shares_rows.append((ticker, float(shares)))
    db.executemany(
        "INSERT OR REPLACE INTO shares_outstanding (ticker, shares) VALUES (?,?)",
        shares_rows
    )
    print(f"   {db.table_count('shares_outstanding')} tickers with shares data")

    # ------------------------------------------------------------------
    # Step 4: Financials from EDGAR caches + SimFin + yfinance
    # ------------------------------------------------------------------
    print("4. Loading financials...")
    store = FinancialsStore()
    ingest_edgar(store)
    try:
        from data.ingest import ingest_simfin_gaps
        ingest_simfin_gaps(store)
    except Exception as e:
        print(f"   SimFin gap-fill skipped: {e}")
    ingest_yfinance_gaps(store, symbols, max_per_field=100)
    compute_derived_fields(store)
    validate(store)

    # Write financials from the store into SQLite
    if not store.df.empty:
        fin_fields = [
            "revenue", "operating_income", "net_income", "ebitda",
            "depreciation_amortization", "total_assets", "total_debt", "cash",
            "stockholders_equity", "eps_diluted", "operating_cash_flow",
            "capex", "free_cash_flow",
        ]
        fin_rows = []
        for _, row in store.df.iterrows():
            ticker = row.get("ticker")
            period_end = str(pd.Timestamp(row.get("period_end")).date()) if pd.notna(row.get("period_end")) else None
            if not ticker or not period_end:
                continue
            vals = [row.get(f) for f in fin_fields]
            vals = [None if (isinstance(v, float) and math.isnan(v)) else v for v in vals]
            source = row.get("source", "edgar")
            fin_rows.append((ticker, period_end, *vals, source))

        print(f"   Inserting {len(fin_rows)} financial rows...")
        placeholders = ",".join(["?"] * (2 + len(fin_fields) + 1))
        cols = "ticker, period_end, " + ", ".join(fin_fields) + ", source"
        for i in range(0, len(fin_rows), BATCH):
            db.executemany(
                f"INSERT OR REPLACE INTO financials ({cols}) VALUES ({placeholders})",
                fin_rows[i:i + BATCH]
            )
    print(f"   {db.table_count('financials')} financial rows in DB")

    # ------------------------------------------------------------------
    # Step 5: Compute ratios
    # ------------------------------------------------------------------
    print("5. Computing ratios...")
    trading_dates = mktcap.index
    ratio_dfs = {}

    # P/B = mktcap / stockholders_equity (instant, forward-filled)
    eq = store.get_field_series("stockholders_equity")
    if not eq.empty:
        equity_daily = build_daily_instant(eq, trading_dates)
        equity_daily = equity_daily.where(equity_daily > 0)
        common = mktcap.columns.intersection(equity_daily.columns)
        ratio_dfs["P/B"] = (mktcap[common] / equity_daily[common]).replace([np.inf, -np.inf], np.nan)

    # P/S = mktcap / revenue_ttm
    rev = store.get_field_series("revenue")
    if not rev.empty:
        rev_ttm = build_daily_ttm(rev, trading_dates)
        rev_ttm = rev_ttm.where(rev_ttm > 0)
        common = mktcap.columns.intersection(rev_ttm.columns)
        ratio_dfs["P/S"] = (mktcap[common] / rev_ttm[common]).replace([np.inf, -np.inf], np.nan)

    # P/E = mktcap / net_income_ttm
    ni = store.get_field_series("net_income")
    if not ni.empty:
        ni_ttm = build_daily_ttm(ni, trading_dates)
        ni_ttm = ni_ttm.where(ni_ttm > 0)
        common = mktcap.columns.intersection(ni_ttm.columns)
        ratio_dfs["P/E"] = (mktcap[common] / ni_ttm[common]).replace([np.inf, -np.inf], np.nan)

    # EV/EBITDA = (mktcap + debt - cash) / ebitda_ttm
    ebitda_q = store.get_field_series("ebitda")
    if ebitda_q.empty:
        oi = store.get_field_series("operating_income")
        dna = store.get_field_series("depreciation_amortization")
        if not oi.empty:
            common_eb = oi.columns.intersection(dna.columns) if not dna.empty else oi.columns
            ebitda_q = oi[common_eb] + dna[common_eb].fillna(0) if not dna.empty else oi

    if not ebitda_q.empty:
        ebitda_ttm = build_daily_ttm(ebitda_q, trading_dates)
        ebitda_ttm = ebitda_ttm.where(ebitda_ttm > 0)
        debt_q = store.get_field_series("total_debt")
        cash_q = store.get_field_series("cash")
        debt_daily = build_daily_instant(debt_q, trading_dates) if not debt_q.empty else pd.DataFrame(index=trading_dates)
        cash_daily = build_daily_instant(cash_q, trading_dates) if not cash_q.empty else pd.DataFrame(index=trading_dates)
        ev_tickers = mktcap.columns.intersection(ebitda_ttm.columns)
        ev_df = mktcap[ev_tickers].copy()
        debt_overlap = ev_tickers.intersection(debt_daily.columns)
        ev_df[debt_overlap] = ev_df[debt_overlap] + debt_daily[debt_overlap].fillna(0)
        cash_overlap = ev_tickers.intersection(cash_daily.columns)
        ev_df[cash_overlap] = ev_df[cash_overlap] - cash_daily[cash_overlap].fillna(0)
        ratio_dfs["EV/EBITDA"] = (ev_df / ebitda_ttm[ev_tickers]).replace([np.inf, -np.inf], np.nan)

    # Build Universe with ratio data for screener
    universe = Universe()
    for sym in symbols:
        t = Ticker(sym, sector=ticker_sectors.get(sym))
        for ratio_name, rdf in ratio_dfs.items():
            if sym in rdf.columns:
                series = rdf[sym].dropna()
                if len(series) > 0:
                    t.set_ratio(ratio_name, series)
        universe.add_ticker(t)

    print(f"   Ratios computed: {', '.join(f'{k}: {len(v.columns)} tickers' for k, v in ratio_dfs.items())}")

    # ------------------------------------------------------------------
    # Step 6: Compute technicals
    # ------------------------------------------------------------------
    print("6. Computing technicals...")
    tech_data = {}
    for sym in close.columns:
        prices = close[sym].dropna()
        if len(prices) < 50:
            continue
        try:
            rsi = compute_rsi(prices)
            macd_line, signal_line, _hist = compute_macd(prices)
            sma200 = compute_sma(prices, 200)
            sma50 = compute_sma(prices, 50)

            last_rsi = float(rsi.iloc[-1]) if not rsi.empty else 50.0
            macd_label = macd_signal_label(macd_line, signal_line)
            last_sma200 = float(sma200.iloc[-1]) if not sma200.empty and pd.notna(sma200.iloc[-1]) else float('nan')
            last_sma50 = float(sma50.iloc[-1]) if not sma50.empty and pd.notna(sma50.iloc[-1]) else float('nan')
            last_price = float(prices.iloc[-1])
            trend = ma_trend_label(last_price, last_sma200)
            ret_1d, ret_3d = compute_returns(prices)

            tech_data[sym] = {
                "rsi": last_rsi,
                "macd_label": macd_label,
                "ma_trend": trend,
                "sma200": last_sma200,
                "sma50": last_sma50,
                "ret_1d": ret_1d,
                "ret_3d": ret_3d,
                "price": last_price,
            }
        except Exception:
            continue
    print(f"   Technicals for {len(tech_data)} tickers")

    # ------------------------------------------------------------------
    # Step 7: Build screener
    # ------------------------------------------------------------------
    print("7. Building screener...")
    screener_rows = []
    ratio_order = ["P/E", "P/S", "P/B", "EV/EBITDA"]

    for sym in symbols:
        t = universe.get(sym)
        if t is None:
            continue
        td = tech_data.get(sym)
        if td is None:
            continue

        # Find the most extreme z-score across all ratios
        best_z = None
        best_ratio = None
        for rn in ratio_order:
            s = t.stats(rn, window_days=2 * 365)
            if s is not None:
                z = s["z_score"]
                if best_z is None or abs(z) > abs(best_z):
                    best_z = z
                    best_ratio = rn

        if best_z is None:
            continue

        rsi_val = td["rsi"]
        macd_label = td["macd_label"]
        ma_trend = td["ma_trend"]
        ret_1d = td["ret_1d"]
        ret_3d = td["ret_3d"]
        price = td["price"]

        alert = compute_alert(best_z, rsi_val, macd_label, ma_trend)
        signal = compute_signal_label(best_z, alert["type"])

        prices = close[sym].dropna() if sym in close.columns else pd.Series(dtype=float)
        low_52w, high_52w, pct_52w = compute_52w_range(prices)

        rv_sig = f"{best_ratio} z={best_z:+.2f}"

        screener_rows.append((
            sym,
            ticker_names.get(sym, ""),
            ticker_sectors.get(sym, ""),
            rv_sig,
            round(best_z, 4),
            round(rsi_val, 1),
            macd_label,
            round(ret_1d * 100, 2),
            round(ret_3d * 100, 2),
            signal,
            alert["type"],
            alert["reason"],
            ma_trend,
            round(price, 2),
            round(low_52w, 2) if low_52w is not None else None,
            round(high_52w, 2) if high_52w is not None else None,
            round(pct_52w, 4) if pct_52w is not None else None,
            None,  # short_interest
        ))

    db.execute("DELETE FROM screener")
    db.executemany(
        """INSERT OR REPLACE INTO screener
           (symbol, name, sector, rv_sig, z_score, rsi, macd,
            ret_1d, ret_3d, signal, alert_type, alert_reason,
            ma_trend, price, low_52w, high_52w, pct_52w, short_interest)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        screener_rows
    )
    print(f"   {db.table_count('screener')} tickers in screener")

    # ------------------------------------------------------------------
    # Step 8: Market risk
    # ------------------------------------------------------------------
    print("8. Computing market risk...")
    vix = fetch_vix()

    above_200sma = {}
    above_50sma = {}
    rsi_values = {}
    returns_1d = {}
    prices_dict = {}

    for sym, td in tech_data.items():
        rsi_values[sym] = td["rsi"]
        returns_1d[sym] = td["ret_1d"]
        if sym in close.columns:
            prices_dict[sym] = close[sym].dropna()
        if not math.isnan(td["sma200"]):
            above_200sma[sym] = td["price"] >= td["sma200"]
        if not math.isnan(td["sma50"]):
            above_50sma[sym] = td["price"] >= td["sma50"]

    breadth = compute_breadth_stats(above_200sma, above_50sma, rsi_values)
    new_highs, new_lows = compute_new_highs_lows(prices_dict)
    advancers, decliners, unchanged = compute_advancers_decliners(returns_1d)

    fg = compute_fear_greed(breadth, vix.get("value"), new_highs, new_lows)

    verdict = compute_risk_verdict({
        "vix": vix.get("value", 0),
        "fear_greed": fg.get("value", 50),
        "pct_above_200sma": breadth["pct_above_200sma"],
        "pct_above_50sma": breadth["pct_above_50sma"],
        "avg_rsi": breadth["avg_rsi"],
        "new_highs": new_highs,
        "new_lows": new_lows,
    })

    today = datetime.now().strftime("%Y-%m-%d")
    db.execute(
        """INSERT OR REPLACE INTO market_risk
           (date, vix, vix_change, fear_greed, fear_greed_label,
            pct_above_200sma, pct_above_50sma, avg_rsi,
            new_highs, new_lows, advancers, decliners, unchanged,
            verdict_level, verdict_color, verdict_guidance)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            today,
            vix.get("value"), vix.get("change"),
            fg.get("value"), fg.get("label"),
            breadth["pct_above_200sma"], breadth["pct_above_50sma"], breadth["avg_rsi"],
            new_highs, new_lows,
            advancers, decliners, unchanged,
            verdict["level"], verdict["color"], verdict["guidance"],
        )
    )
    print(f"   VIX={vix.get('value')}, F&G={fg.get('value')} ({fg.get('label')}), Verdict={verdict['level']}")

    # ------------------------------------------------------------------
    # Step 9: News
    # ------------------------------------------------------------------
    print("9. Fetching news...")
    db.execute("DELETE FROM news")
    fetched_at = datetime.now().isoformat()

    market_news = fetch_market_news(limit=15)
    if market_news:
        db.executemany(
            "INSERT INTO news (ticker, headline, source, url, age, fetched_at) VALUES (?,?,?,?,?,?)",
            [
                (None, n.get("headline", ""), n.get("source", ""), n.get("url", "#"),
                 n.get("age", ""), fetched_at)
                for n in market_news
            ]
        )
    print(f"   {len(market_news)} market news articles")

    top_movers = sorted(screener_rows, key=lambda r: abs(r[4]) if r[4] is not None else 0, reverse=True)[:20]
    company_news_count = 0
    for row in top_movers:
        sym = row[0]
        try:
            articles = fetch_company_news(sym, days_back=3, limit=3)
            if articles:
                db.executemany(
                    "INSERT INTO news (ticker, headline, source, url, age, fetched_at) VALUES (?,?,?,?,?,?)",
                    [
                        (sym, a.get("headline", ""), a.get("source", ""), a.get("url", "#"),
                         a.get("age", ""), fetched_at)
                        for a in articles
                    ]
                )
                company_news_count += len(articles)
        except Exception:
            continue
    print(f"   {company_news_count} company news articles for top {len(top_movers)} movers")

    # ------------------------------------------------------------------
    # Step 10: Earnings (for top movers)
    # ------------------------------------------------------------------
    print("10. Fetching earnings...")
    earnings_count = 0
    for row in top_movers:
        sym = row[0]
        try:
            history = fetch_earnings_history(sym)
            if not history:
                continue
            prices = close[sym].dropna() if sym in close.columns else pd.Series(dtype=float)
            earn_rows = []
            for rec in history:
                quarter = rec.get("quarter", "")
                actual = rec.get("actual")
                estimate = rec.get("estimate")
                surprise_pct = rec.get("surprise_pct")

                px_move_3d = None
                if not prices.empty and quarter:
                    try:
                        q_date = pd.Timestamp(quarter)
                        mask = prices.index >= q_date
                        if mask.any():
                            idx_start = prices.index[mask][0]
                            pos = prices.index.get_loc(idx_start)
                            if pos + 3 < len(prices):
                                p_start = float(prices.iloc[pos])
                                p_end = float(prices.iloc[pos + 3])
                                px_move_3d = round((p_end - p_start) / p_start * 100, 2)
                    except Exception:
                        pass

                earn_rows.append((sym, quarter, actual, estimate, surprise_pct, px_move_3d))

            if earn_rows:
                db.executemany(
                    "INSERT OR REPLACE INTO earnings (ticker, quarter, actual, estimate, surprise_pct, px_move_3d) VALUES (?,?,?,?,?,?)",
                    earn_rows
                )
                earnings_count += len(earn_rows)
        except Exception:
            continue
    print(f"   {earnings_count} earnings records for top {len(top_movers)} movers")

    # ------------------------------------------------------------------
    # Sector stats
    # ------------------------------------------------------------------
    print("   Computing sector stats...")
    sector_returns = compute_sector_returns(returns_1d, ticker_sectors)
    if sector_returns:
        db.executemany(
            "INSERT OR REPLACE INTO sector_stats (sector, date, median_return) VALUES (?,?,?)",
            [(sector, today, ret) for sector, ret in sector_returns.items()]
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\nDone! Database: {os.path.getsize(db.path) / 1e6:.1f} MB")
    db.close()


if __name__ == "__main__":
    main()
