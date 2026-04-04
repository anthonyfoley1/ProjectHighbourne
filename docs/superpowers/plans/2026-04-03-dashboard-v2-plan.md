# Highbourne Terminal v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the existing Dash RV app into a Bloomberg-style multi-view investment dashboard with technical analysis, market risk barometers, and sector rotation analysis.

**Architecture:** Extend the existing Plotly Dash app in place. Add four new data modules (`data/market_data.py`, `data/technicals.py`, `data/risk.py`, `data/sectors.py`), extend the `Ticker` model, and restructure `app.py` into a multi-page layout with Home (scanner) and Detail views. All new price data sourced from yfinance with local caching.

**Tech Stack:** Python 3.11, Plotly Dash, yfinance, pandas, numpy, existing EDGAR pipeline

**Spec:** `docs/superpowers/specs/2026-04-03-dashboard-v2-design.md`
**Mockups:** `.superpowers/brainstorm/53524-1775259052/content/16-home-bloomberg-v2.html` (home), `19-detail-bloomberg-v3.html` (detail)

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `data/market_data.py` | yfinance wrapper: batch OHLCV download, ticker info (description, PT, earnings dates, news, competitors), caching to disk |
| `data/technicals.py` | Compute RSI(14), MACD(12,26,9), SMA(50), SMA(200) from price Series. Pure functions, no side effects |
| `data/risk.py` | Market-level metrics: VIX fetch, breadth stats (% above SMA, new highs/lows, avg RSI), Fear & Greed scrape, put/call ratio, composite risk verdict |
| `data/sectors.py` | Sector return computation, EPS growth vs multiple expansion attribution, normalized performance series |
| `data/cache.py` | Unified cache manager — read/write parquet/JSON caches with staleness checks |
| `tests/test_technicals.py` | Tests for RSI, MACD, SMA computation |
| `tests/test_market_data.py` | Tests for yfinance data fetching and caching |
| `tests/test_risk.py` | Tests for risk metrics computation |
| `tests/test_sectors.py` | Tests for sector attribution |
| `tests/test_alerts.py` | Tests for alert and composite scoring logic |
| `pages/__init__.py` | Package init for multi-page layout |
| `pages/home.py` | Home page layout and callbacks (scanner, movers, scatter, risk, sectors) |
| `pages/detail.py` | Detail view layout and callbacks (all per-ticker charts and tables) |
| `theme.py` | Bloomberg color constants, CSS styles, shared Dash components (stat cards, gauge bars, function key bar) |

### Modified Files
| File | Changes |
|------|---------|
| `models/ticker.py` | Add technical indicator storage, alert logic, composite score, earnings surprise data to Ticker class. Add alert/scoring methods to Universe class |
| `app.py` | Gut the existing single-page layout. Replace with multi-page Dash app shell (URL routing, shared header with search bar, function key bar). Move existing tab content into `pages/` |
| `data/loader.py` | Add yfinance price loading alongside SimFin. Add functions to load ticker info (description, competitors, etc.) |

---

## Phase 1: Data Infrastructure

### Task 1: Cache Manager

**Files:**
- Create: `data/cache.py`
- Test: `tests/test_cache.py`

- [ ] **Step 1: Write failing test for cache read/write**

```python
# tests/test_cache.py
import pandas as pd
import tempfile, os
from data.cache import CacheManager

def test_cache_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        cm = CacheManager(d)
        df = pd.DataFrame({"A": [1, 2, 3]}, index=pd.date_range("2025-01-01", periods=3))
        cm.save("test_prices", df)
        loaded = cm.load("test_prices")
        pd.testing.assert_frame_equal(df, loaded)

def test_cache_staleness():
    with tempfile.TemporaryDirectory() as d:
        cm = CacheManager(d, max_age_hours=0)  # immediately stale
        df = pd.DataFrame({"A": [1]})
        cm.save("test", df)
        assert cm.is_stale("test") is True

def test_cache_missing_returns_none():
    with tempfile.TemporaryDirectory() as d:
        cm = CacheManager(d)
        assert cm.load("nonexistent") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/anthonyfoley/Documents/CPSC_Courses/ProjectHighbourne && python -m pytest tests/test_cache.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement CacheManager**

```python
# data/cache.py
import os
import json
import pandas as pd
from datetime import datetime, timedelta

class CacheManager:
    def __init__(self, cache_dir, max_age_hours=20):
        self.cache_dir = cache_dir
        self.max_age_hours = max_age_hours
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, key):
        return os.path.join(self.cache_dir, f"{key}.parquet")

    def _meta_path(self, key):
        return os.path.join(self.cache_dir, f"{key}.meta.json")

    def save(self, key, df):
        df.to_parquet(self._path(key))
        with open(self._meta_path(key), "w") as f:
            json.dump({"saved_at": datetime.now().isoformat()}, f)

    def load(self, key):
        path = self._path(key)
        if not os.path.exists(path):
            return None
        return pd.read_parquet(path)

    def is_stale(self, key):
        meta = self._meta_path(key)
        if not os.path.exists(meta):
            return True
        with open(meta) as f:
            saved_at = datetime.fromisoformat(json.loads(f.read())["saved_at"])
        return datetime.now() - saved_at > timedelta(hours=self.max_age_hours)

    def save_json(self, key, data):
        path = os.path.join(self.cache_dir, f"{key}.json")
        with open(path, "w") as f:
            json.dump(data, f)
        with open(self._meta_path(key), "w") as f:
            json.dump({"saved_at": datetime.now().isoformat()}, f)

    def load_json(self, key):
        path = os.path.join(self.cache_dir, f"{key}.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cache.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add data/cache.py tests/test_cache.py
git commit -m "feat: add CacheManager for parquet/JSON disk caching with staleness checks"
```

---

### Task 2: yfinance Market Data Module

**Files:**
- Create: `data/market_data.py`
- Test: `tests/test_market_data.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_market_data.py
import pandas as pd
from data.market_data import (
    fetch_bulk_prices, fetch_ticker_info, compute_returns,
    compute_52w_range, compute_relative_volume
)

def test_compute_returns():
    prices = pd.Series([100, 102, 101, 105, 103], 
                       index=pd.date_range("2025-01-01", periods=5))
    ret_1d, ret_3d = compute_returns(prices)
    assert abs(ret_1d - ((103 - 105) / 105)) < 0.001
    assert abs(ret_3d - ((103 - 101) / 101)) < 0.001

def test_compute_52w_range():
    prices = pd.Series(range(10, 110), 
                       index=pd.date_range("2024-01-01", periods=100))
    low, high, pct = compute_52w_range(prices)
    assert low == 10
    assert high == 109
    assert 0 <= pct <= 1

def test_compute_relative_volume():
    vol = pd.Series([100]*10 + [250],
                    index=pd.date_range("2025-01-01", periods=11))
    rv = compute_relative_volume(vol, lookback=10)
    assert rv == 2.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_data.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement market data module**

```python
# data/market_data.py
import yfinance as yf
import pandas as pd
import numpy as np
from data.cache import CacheManager

PROJECT_ROOT = __file__.rsplit("/", 2)[0]
cache = CacheManager(f"{PROJECT_ROOT}/cache")

def fetch_bulk_prices(tickers, period="2y"):
    """Batch download OHLCV for all tickers. Returns dict of DataFrames keyed by ticker."""
    if cache.load("bulk_prices") is not None and not cache.is_stale("bulk_prices"):
        return cache.load("bulk_prices")
    
    data = yf.download(tickers, period=period, group_by="ticker", threads=True)
    cache.save("bulk_prices", data)
    return data

def fetch_single_prices(ticker, period="2y"):
    """Fetch OHLCV for a single ticker."""
    t = yf.Ticker(ticker)
    return t.history(period=period)

def fetch_ticker_info(symbol):
    """Fetch company info: description, PT, earnings date, news, sector, industry."""
    t = yf.Ticker(symbol)
    info = t.info or {}
    
    result = {
        "description": info.get("longBusinessSummary", ""),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "pt_avg": info.get("targetMeanPrice"),
        "pt_low": info.get("targetLowPrice"),
        "pt_high": info.get("targetHighPrice"),
        "market_cap": info.get("marketCap"),
        "enterprise_value": info.get("enterpriseValue"),
        "beta": info.get("beta"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "float_shares": info.get("floatShares"),
        "inst_ownership": info.get("heldPercentInstitutions"),
        "short_ratio": info.get("shortPercentOfFloat"),
        "dividend_yield": info.get("dividendYield"),
        "prev_close": info.get("previousClose"),
        "open": info.get("open"),
        "day_high": info.get("dayHigh"),
        "day_low": info.get("dayLow"),
        "volume": info.get("volume"),
        "avg_volume_3m": info.get("averageVolume"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
    }
    
    # Earnings date
    try:
        cal = t.calendar
        if cal is not None and "Earnings Date" in cal:
            result["next_earnings"] = str(cal["Earnings Date"][0])
        else:
            result["next_earnings"] = None
    except Exception:
        result["next_earnings"] = None
    
    # News
    try:
        news = t.news or []
        result["news"] = [
            {"title": n.get("title", ""), "link": n.get("link", ""), 
             "publisher": n.get("publisher", ""), "timestamp": n.get("providerPublishTime", 0)}
            for n in news[:5]
        ]
    except Exception:
        result["news"] = []
    
    return result

def fetch_earnings_history(symbol):
    """Fetch earnings surprise data: actual vs estimate EPS per quarter."""
    t = yf.Ticker(symbol)
    try:
        eh = t.earnings_history
        if eh is None or eh.empty:
            return []
        records = []
        for _, row in eh.iterrows():
            records.append({
                "quarter": str(row.name) if hasattr(row, 'name') else "",
                "actual": row.get("epsActual"),
                "estimate": row.get("epsEstimate"),
                "surprise_pct": row.get("surprisePercent"),
            })
        return records
    except Exception:
        return []

def fetch_competitors(symbol, universe_tickers, ticker_sectors):
    """Find 5 tickers in the same sector, sorted by market cap proximity."""
    sector = ticker_sectors.get(symbol)
    if not sector:
        return []
    same_sector = [t for t in universe_tickers if ticker_sectors.get(t) == sector and t != symbol]
    return same_sector[:5]

def compute_returns(prices):
    """Compute 1-day and 3-day returns from a price Series."""
    if len(prices) < 4:
        return 0.0, 0.0
    ret_1d = (prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2]
    ret_3d = (prices.iloc[-1] - prices.iloc[-4]) / prices.iloc[-4]
    return float(ret_1d), float(ret_3d)

def compute_52w_range(prices):
    """Compute 52-week low, high, and current percentile position."""
    last_52w = prices.last("252D") if hasattr(prices, 'last') else prices.iloc[-252:]
    if len(last_52w) == 0:
        return None, None, None
    low = float(last_52w.min())
    high = float(last_52w.max())
    current = float(last_52w.iloc[-1])
    pct = (current - low) / (high - low) if high != low else 0.5
    return low, high, pct

def compute_relative_volume(volume, lookback=10):
    """Compute current volume relative to trailing average."""
    if len(volume) < lookback + 1:
        return 1.0
    avg = volume.iloc[-(lookback+1):-1].mean()
    if avg == 0:
        return 1.0
    return float(volume.iloc[-1] / avg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_market_data.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add data/market_data.py tests/test_market_data.py
git commit -m "feat: add yfinance market data module with returns, 52W range, relative volume"
```

---

### Task 3: Technical Indicators Module

**Files:**
- Create: `data/technicals.py`
- Test: `tests/test_technicals.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_technicals.py
import pandas as pd
import numpy as np
from data.technicals import compute_rsi, compute_macd, compute_sma, detect_crossovers

def test_rsi_bounds():
    """RSI should always be between 0 and 100."""
    prices = pd.Series(np.random.lognormal(0, 0.02, 200).cumprod())
    rsi = compute_rsi(prices, period=14)
    assert rsi.dropna().between(0, 100).all()

def test_rsi_overbought():
    """Steadily rising prices should produce RSI > 70."""
    prices = pd.Series(range(100, 200))
    rsi = compute_rsi(prices, period=14)
    assert rsi.iloc[-1] > 70

def test_rsi_oversold():
    """Steadily falling prices should produce RSI < 30."""
    prices = pd.Series(range(200, 100, -1))
    rsi = compute_rsi(prices, period=14)
    assert rsi.iloc[-1] < 30

def test_macd_components():
    """MACD should return macd_line, signal_line, histogram as Series."""
    prices = pd.Series(np.random.lognormal(0, 0.02, 200).cumprod())
    macd_line, signal_line, histogram = compute_macd(prices)
    assert len(macd_line) == len(prices)
    assert len(signal_line) == len(prices)
    assert len(histogram) == len(prices)

def test_macd_histogram_is_difference():
    """Histogram should equal MACD line minus signal line."""
    prices = pd.Series(np.random.lognormal(0, 0.02, 200).cumprod())
    macd_line, signal_line, histogram = compute_macd(prices)
    diff = macd_line - signal_line
    pd.testing.assert_series_equal(histogram, diff, check_names=False)

def test_sma():
    prices = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
    sma = compute_sma(prices, window=3)
    assert sma.iloc[-1] == 9.0  # (8+9+10)/3

def test_detect_crossovers():
    fast = pd.Series([1, 2, 3, 4, 5, 4, 3, 2, 1], dtype=float)
    slow = pd.Series([3, 3, 3, 3, 3, 3, 3, 3, 3], dtype=float)
    golden, death = detect_crossovers(fast, slow)
    assert len(golden) > 0  # fast crosses above slow
    assert len(death) > 0   # fast crosses below slow
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_technicals.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement technicals module**

```python
# data/technicals.py
import pandas as pd
import numpy as np

def compute_rsi(prices, period=14):
    """Compute Relative Strength Index."""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_macd(prices, fast=12, slow=26, signal=9):
    """Compute MACD line, signal line, and histogram."""
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def compute_sma(prices, window):
    """Compute Simple Moving Average."""
    return prices.rolling(window=window).mean()

def detect_crossovers(fast, slow):
    """Detect golden crosses (fast > slow) and death crosses (fast < slow).
    Returns (golden_dates, death_dates) as lists of index values."""
    above = fast > slow
    cross = above.astype(int).diff()
    golden = cross[cross == 1].index.tolist()
    death = cross[cross == -1].index.tolist()
    return golden, death

def macd_signal_label(macd_line, signal_line):
    """Return 'Bull', 'Bear', or 'Flat' based on current MACD vs signal."""
    if len(macd_line) < 2:
        return "Flat"
    current_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
    prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
    if current_diff > 0 and current_diff > prev_diff:
        return "Bull"
    elif current_diff < 0 and current_diff < prev_diff:
        return "Bear"
    elif current_diff > 0:
        return "Bull"
    elif current_diff < 0:
        return "Bear"
    return "Flat"

def rsi_label(rsi_value):
    """Return descriptive label for RSI value."""
    if rsi_value >= 70:
        return "OVERBOUGHT"
    elif rsi_value <= 30:
        return "OVERSOLD"
    return ""

def ma_trend_label(price, sma_200):
    """Return trend label based on price vs 200-day SMA."""
    if pd.isna(sma_200) or pd.isna(price):
        return "N/A"
    return "Above" if price > sma_200 else "Below"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_technicals.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add data/technicals.py tests/test_technicals.py
git commit -m "feat: add technical indicators module — RSI, MACD, SMA, crossover detection"
```

---

### Task 4: Risk Metrics Module

**Files:**
- Create: `data/risk.py`
- Test: `tests/test_risk.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_risk.py
import pandas as pd
import numpy as np
from data.risk import (
    compute_breadth_stats, compute_risk_verdict,
    compute_new_highs_lows
)

def test_breadth_stats():
    """Breadth should compute % above SMA and avg RSI."""
    # 10 stocks, some above/below their 200d SMA
    prices_above_sma = {f"TICK{i}": True for i in range(6)}
    prices_above_sma.update({f"TICK{i}": False for i in range(6, 10)})
    rsi_values = {f"TICK{i}": 40 + i * 3 for i in range(10)}
    
    stats = compute_breadth_stats(prices_above_sma, rsi_values)
    assert stats["pct_above_200sma"] == 60.0
    assert stats["avg_rsi"] == pytest.approx(53.5)

def test_risk_verdict_elevated():
    stats = {
        "vix": 28, "fear_greed": 22, "put_call": 1.2,
        "pct_above_200sma": 38, "pct_above_50sma": 29, "avg_rsi": 38,
        "new_highs": 42, "new_lows": 218
    }
    verdict = compute_risk_verdict(stats)
    assert verdict["level"] in ("ELEVATED RISK", "EXTREME RISK")
    assert "color" in verdict

def test_risk_verdict_low():
    stats = {
        "vix": 12, "fear_greed": 75, "put_call": 0.7,
        "pct_above_200sma": 72, "pct_above_50sma": 68, "avg_rsi": 55,
        "new_highs": 200, "new_lows": 30
    }
    verdict = compute_risk_verdict(stats)
    assert verdict["level"] in ("LOW RISK", "MODERATE")

def test_new_highs_lows():
    # 5 stocks with price histories
    prices = {}
    for i in range(5):
        p = pd.Series(np.random.lognormal(0, 0.02, 260).cumprod(),
                      index=pd.date_range("2024-01-01", periods=260))
        prices[f"TICK{i}"] = p
    highs, lows = compute_new_highs_lows(prices)
    assert isinstance(highs, int)
    assert isinstance(lows, int)

import pytest
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_risk.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement risk module**

```python
# data/risk.py
import yfinance as yf
import pandas as pd
import numpy as np
import requests

def fetch_vix():
    """Fetch current VIX value and daily change."""
    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="5d")
        if len(hist) < 2:
            return {"value": None, "change": None}
        current = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])
        return {"value": round(current, 1), "change": round(current - prev, 1)}
    except Exception:
        return {"value": None, "change": None}

def fetch_fear_greed():
    """Fetch CNN Fear & Greed Index. Returns dict with value (0-100) and label."""
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        score = data.get("fear_and_greed", {}).get("score", None)
        rating = data.get("fear_and_greed", {}).get("rating", "")
        if score is not None:
            return {"value": round(float(score)), "label": rating.upper().replace(" ", " ")}
    except Exception:
        pass
    return {"value": None, "label": "N/A"}

def compute_breadth_stats(above_200sma, above_50sma, rsi_values):
    """Compute market breadth from pre-computed per-ticker stats.
    
    Args:
        above_200sma: dict {ticker: bool}
        above_50sma: dict {ticker: bool}
        rsi_values: dict {ticker: float}
    Returns: dict with pct_above_200sma, pct_above_50sma, avg_rsi
    """
    n = len(above_200sma) or 1
    pct_200 = sum(above_200sma.values()) / n * 100
    pct_50 = sum(above_50sma.values()) / n * 100
    rsi_vals = [v for v in rsi_values.values() if v is not None and not np.isnan(v)]
    avg_rsi = np.mean(rsi_vals) if rsi_vals else 50.0
    return {
        "pct_above_200sma": round(pct_200, 1),
        "pct_above_50sma": round(pct_50, 1),
        "avg_rsi": round(avg_rsi, 1),
    }

def compute_new_highs_lows(prices_dict):
    """Count stocks at 52-week highs or lows.
    
    Args:
        prices_dict: dict {ticker: pd.Series of close prices}
    Returns: (new_highs, new_lows)
    """
    highs, lows = 0, 0
    for ticker, prices in prices_dict.items():
        if len(prices) < 20:
            continue
        last_252 = prices.iloc[-252:] if len(prices) >= 252 else prices
        current = prices.iloc[-1]
        if current >= last_252.max() * 0.98:  # within 2% of 52w high
            highs += 1
        if current <= last_252.min() * 1.02:  # within 2% of 52w low
            lows += 1
    return highs, lows

def compute_advancers_decliners(returns_1d):
    """Count advancers, decliners, unchanged from 1-day return dict.
    
    Args:
        returns_1d: dict {ticker: float}
    Returns: (advancers, decliners, unchanged)
    """
    adv = sum(1 for r in returns_1d.values() if r > 0.001)
    dec = sum(1 for r in returns_1d.values() if r < -0.001)
    unch = len(returns_1d) - adv - dec
    return adv, dec, unch

def compute_risk_verdict(stats):
    """Compute composite risk assessment from all risk metrics.
    
    Args:
        stats: dict with vix, fear_greed, put_call, pct_above_200sma, 
               pct_above_50sma, avg_rsi, new_highs, new_lows
    Returns: dict with level, color, guidance
    """
    score = 0  # higher = more risk
    
    vix = stats.get("vix") or 15
    if vix > 30: score += 3
    elif vix > 25: score += 2
    elif vix > 20: score += 1
    
    fg = stats.get("fear_greed") or 50
    if fg < 20: score += 3
    elif fg < 35: score += 2
    elif fg < 45: score += 1
    
    pc = stats.get("put_call") or 1.0
    if pc > 1.2: score += 2
    elif pc > 1.0: score += 1
    
    pct200 = stats.get("pct_above_200sma") or 50
    if pct200 < 30: score += 2
    elif pct200 < 45: score += 1
    
    avg_rsi = stats.get("avg_rsi") or 50
    if avg_rsi < 35: score += 2
    elif avg_rsi < 45: score += 1
    
    hl_ratio = (stats.get("new_lows") or 1) / max(stats.get("new_highs") or 1, 1)
    if hl_ratio > 4: score += 2
    elif hl_ratio > 2: score += 1
    
    if score >= 10:
        return {"level": "EXTREME RISK", "color": "#880000", "guidance": "capital preservation mode"}
    elif score >= 7:
        return {"level": "ELEVATED RISK", "color": "#ff4444", "guidance": "defensive posture"}
    elif score >= 4:
        return {"level": "MODERATE", "color": "#ffff00", "guidance": "selective deployment"}
    else:
        return {"level": "LOW RISK", "color": "#00ff00", "guidance": "favorable conditions"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_risk.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add data/risk.py tests/test_risk.py
git commit -m "feat: add risk metrics module — VIX, Fear & Greed, breadth, composite verdict"
```

---

### Task 5: Sector Analysis Module

**Files:**
- Create: `data/sectors.py`
- Test: `tests/test_sectors.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sectors.py
import pandas as pd
import numpy as np
from data.sectors import compute_sector_returns, compute_return_attribution, compute_normalized_performance

def test_sector_returns():
    """Sector return should be the median return of constituent tickers."""
    ticker_returns = {"AAPL": 0.15, "MSFT": 0.20, "GOOG": 0.10, "JPM": 0.05, "BAC": 0.08}
    ticker_sectors = {"AAPL": "Tech", "MSFT": "Tech", "GOOG": "Tech", "JPM": "Fins", "BAC": "Fins"}
    result = compute_sector_returns(ticker_returns, ticker_sectors)
    assert abs(result["Tech"] - 0.15) < 0.001  # median of 0.10, 0.15, 0.20
    assert abs(result["Fins"] - 0.065) < 0.001  # median of 0.05, 0.08

def test_return_attribution():
    """Return attribution should decompose into EPS growth + multiple expansion."""
    # If P/E went from 20 to 22 and EPS grew from 5 to 6:
    # Total return = (22*6)/(20*5) - 1 = 32%
    # EPS contribution = 6/5 - 1 = 20%
    # Multiple contribution = 22/20 - 1 = 10%
    # (Approximately — the cross term makes it not exactly additive)
    eps_growth = 0.20
    multiple_expansion = 0.10
    total, eps_contrib, mult_contrib = compute_return_attribution(
        pe_start=20, pe_end=22, eps_start=5, eps_end=6
    )
    assert eps_contrib > 0
    assert mult_contrib > 0
    assert abs(total - (eps_contrib + mult_contrib)) < 0.05  # approximately additive

def test_normalized_performance():
    """Normalized series should start at 0 and show cumulative returns."""
    prices = pd.Series([100, 105, 110, 108, 115],
                       index=pd.date_range("2025-01-01", periods=5))
    norm = compute_normalized_performance(prices)
    assert norm.iloc[0] == 0.0
    assert abs(norm.iloc[-1] - 0.15) < 0.001  # 15% total return
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sectors.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement sectors module**

```python
# data/sectors.py
import pandas as pd
import numpy as np

def compute_sector_returns(ticker_returns, ticker_sectors):
    """Compute median return per sector.
    
    Args:
        ticker_returns: dict {ticker: float} — period return per stock
        ticker_sectors: dict {ticker: str} — sector assignment
    Returns: dict {sector: median_return}
    """
    sector_rets = {}
    for ticker, ret in ticker_returns.items():
        sector = ticker_sectors.get(ticker)
        if sector:
            sector_rets.setdefault(sector, []).append(ret)
    return {s: float(np.median(rets)) for s, rets in sector_rets.items()}

def compute_return_attribution(pe_start, pe_end, eps_start, eps_end):
    """Decompose total return into EPS growth and multiple expansion.
    
    Uses the decomposition: Total ≈ EPS Growth + Multiple Expansion
    (ignoring the small cross-term for simplicity)
    
    Returns: (total_return, eps_contribution, multiple_contribution)
    """
    if pe_start == 0 or eps_start == 0:
        return 0, 0, 0
    total = (pe_end * eps_end) / (pe_start * eps_start) - 1
    eps_growth = eps_end / eps_start - 1
    mult_expansion = pe_end / pe_start - 1
    return float(total), float(eps_growth), float(mult_expansion)

def compute_sector_attribution(sector_tickers, pe_start_dict, pe_end_dict, eps_start_dict, eps_end_dict):
    """Compute return attribution for each sector.
    
    Args:
        sector_tickers: dict {sector: [tickers]}
        pe_start_dict, pe_end_dict: dict {ticker: P/E ratio}
        eps_start_dict, eps_end_dict: dict {ticker: EPS}
    Returns: dict {sector: {total, eps_growth, mult_expansion}}
    """
    result = {}
    for sector, tickers in sector_tickers.items():
        totals, eps_gs, mult_es = [], [], []
        for t in tickers:
            pe_s = pe_start_dict.get(t)
            pe_e = pe_end_dict.get(t)
            eps_s = eps_start_dict.get(t)
            eps_e = eps_end_dict.get(t)
            if all(v and v > 0 for v in [pe_s, pe_e, eps_s, eps_e]):
                total, eg, me = compute_return_attribution(pe_s, pe_e, eps_s, eps_e)
                totals.append(total)
                eps_gs.append(eg)
                mult_es.append(me)
        if totals:
            result[sector] = {
                "total": round(float(np.median(totals)) * 100, 1),
                "eps_growth": round(float(np.median(eps_gs)) * 100, 1),
                "mult_expansion": round(float(np.median(mult_es)) * 100, 1),
            }
    return result

def compute_normalized_performance(prices):
    """Normalize a price series to start at 0% return."""
    if len(prices) == 0:
        return prices
    return (prices / prices.iloc[0] - 1)

def compute_sector_normalized_series(sector_tickers, price_dict):
    """Compute normalized performance series per sector (median of constituents).
    
    Args:
        sector_tickers: dict {sector: [tickers]}
        price_dict: dict {ticker: pd.Series of close prices}
    Returns: dict {sector: pd.Series of normalized median performance}
    """
    result = {}
    for sector, tickers in sector_tickers.items():
        norm_series = []
        for t in tickers:
            if t in price_dict and len(price_dict[t]) > 0:
                norm = compute_normalized_performance(price_dict[t])
                norm_series.append(norm)
        if norm_series:
            combined = pd.concat(norm_series, axis=1)
            result[sector] = combined.median(axis=1)
    return result

SECTOR_COLORS = {
    "Technology": "#00ff00",
    "Industrials": "#ff8c00",
    "Health Care": "#ffff00",
    "Materials": "#bb86fc",
    "Financials": "#00bcd4",
    "Consumer Staples": "#e91e63",
    "Communication": "#ff4444",
    "Consumer Discretionary": "#999999",
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sectors.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add data/sectors.py tests/test_sectors.py
git commit -m "feat: add sector analysis module — returns, EPS vs multiple attribution, normalized perf"
```

---

## Phase 2: Model Extensions

### Task 6: Extend Ticker Model with Technicals and Alerts

**Files:**
- Modify: `models/ticker.py`
- Test: `tests/test_alerts.py`

- [ ] **Step 1: Write failing tests for alert logic**

```python
# tests/test_alerts.py
from models.ticker import Ticker, compute_alert, compute_composite_score

def test_buy_alert():
    """BUY alert fires when RV z-score < -1.5 AND RSI < 30."""
    alert = compute_alert(z_score=-2.0, rsi=25, macd_signal="Bull", ma_trend="Below")
    assert alert["type"] == "BUY"

def test_sell_alert():
    """SELL alert fires when RV z-score > +1.5 AND RSI > 70."""
    alert = compute_alert(z_score=2.0, rsi=75, macd_signal="Bear", ma_trend="Above")
    assert alert["type"] == "SELL"

def test_no_alert():
    """No alert when signals don't converge."""
    alert = compute_alert(z_score=-0.5, rsi=50, macd_signal="Flat", ma_trend="Above")
    assert alert["type"] is None

def test_composite_overweight():
    score = compute_composite_score(z_score=-2.0, rsi=25, macd_signal="Bull", 
                                     peer_return=-0.15, pt_upside=0.50)
    assert score["label"] == "OVERWEIGHT"

def test_composite_underweight():
    score = compute_composite_score(z_score=2.5, rsi=78, macd_signal="Bear",
                                     peer_return=0.20, pt_upside=-0.25)
    assert score["label"] == "UNDERWEIGHT"

def test_signal_label():
    from models.ticker import compute_signal_label
    assert compute_signal_label(-2.0, "BUY") == "BUY"
    assert compute_signal_label(-1.2, None) == "CHEAP"
    assert compute_signal_label(0.3, None) == "FAIR"
    assert compute_signal_label(1.2, None) == "RICH"
    assert compute_signal_label(2.0, "SELL") == "SELL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_alerts.py -v`
Expected: FAIL — functions not found

- [ ] **Step 3: Add alert and scoring functions to models/ticker.py**

Add the following functions at the end of `models/ticker.py`:

```python
# Add to models/ticker.py after the Universe class

def compute_alert(z_score, rsi, macd_signal, ma_trend):
    """Determine if a BUY or SELL alert should fire.
    
    BUY: z_score < -1.5 AND (RSI < 30 OR MACD bullish OR golden cross equivalent)
    SELL: z_score > +1.5 AND (RSI > 70 OR MACD bearish OR death cross equivalent)
    """
    if z_score < -1.5 and (rsi < 30 or macd_signal == "Bull"):
        return {"type": "BUY", "reason": f"z={z_score:.1f} + RSI {rsi:.0f}"}
    if z_score > 1.5 and (rsi > 70 or macd_signal == "Bear"):
        return {"type": "SELL", "reason": f"z={z_score:.1f} + RSI {rsi:.0f}"}
    return {"type": None, "reason": ""}

def compute_composite_score(z_score, rsi, macd_signal, peer_return, pt_upside):
    """Compute OVERWEIGHT / MARKET WEIGHT / UNDERWEIGHT from composite signals."""
    score = 0
    
    # RV: cheap = positive
    if z_score < -1.5: score += 3
    elif z_score < -0.5: score += 1
    elif z_score > 1.5: score -= 3
    elif z_score > 0.5: score -= 1
    
    # Technicals: oversold + bullish = positive
    if rsi < 30: score += 2
    elif rsi > 70: score -= 2
    if macd_signal == "Bull": score += 1
    elif macd_signal == "Bear": score -= 1
    
    # Peer underperformance = catch-up potential
    if peer_return < -0.10: score += 1
    elif peer_return > 0.15: score -= 1
    
    # Analyst upside
    if pt_upside and pt_upside > 0.30: score += 1
    elif pt_upside and pt_upside < -0.15: score -= 1
    
    if score >= 4:
        return {"label": "OVERWEIGHT", "color": "#00ff00", "score": score}
    elif score <= -4:
        return {"label": "UNDERWEIGHT", "color": "#ff4444", "score": score}
    return {"label": "MARKET WEIGHT", "color": "#999999", "score": score}

def compute_signal_label(z_score, alert_type):
    """Compute the signal badge label: BUY/CHEAP/FAIR/RICH/SELL."""
    if alert_type == "BUY":
        return "BUY"
    if alert_type == "SELL":
        return "SELL"
    if z_score < -0.75:
        return "CHEAP"
    if z_score > 0.75:
        return "RICH"
    return "FAIR"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_alerts.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add models/ticker.py tests/test_alerts.py
git commit -m "feat: add alert logic, composite scoring, and signal labels to ticker model"
```

---

## Phase 3: Bloomberg Theme and Multi-Page Layout

### Task 7: Bloomberg Theme Module

**Files:**
- Create: `theme.py`

- [ ] **Step 1: Create theme constants and shared components**

```python
# theme.py
"""Bloomberg-style theme constants and shared Dash components."""
from dash import html

# Color palette
C = {
    "bg": "#000000",
    "panel": "#0a0a0a",
    "header": "#1a1a1a",
    "border": "#333333",
    "orange": "#ff8c00",
    "green": "#00ff00",
    "red": "#ff4444",
    "yellow": "#ffff00",
    "white": "#e0e0e0",
    "gray": "#999999",
    "dim": "#777777",
    "cyan": "#00bcd4",
    "purple": "#bb86fc",
    "pink": "#e91e63",
}

FONT_FAMILY = "'Lucida Console', 'Monaco', 'Courier New', monospace"

# Base stylesheet
STYLESHEET = {
    "fontFamily": FONT_FAMILY,
    "backgroundColor": C["bg"],
    "color": C["white"],
    "fontSize": "11px",
    "padding": "8px",
}

CONTAINER_STYLE = {
    "maxWidth": "1100px",
    "margin": "0 auto",
}

def header_bar(title="HIGHBOURNE TERMINAL", subtitle="", timestamp=""):
    return html.Div([
        html.Div([
            html.Span(title, style={"color": C["orange"], "fontSize": "14px", 
                                      "fontWeight": "bold", "letterSpacing": "1px"}),
            html.Span(f" {subtitle}", style={"color": C["gray"], "fontSize": "10px"}),
            html.Span([
                html.Input(
                    id="search-bar",
                    type="text",
                    placeholder="Search ticker...",
                    style={"background": C["bg"], "border": f"1px solid #444",
                           "color": C["yellow"], "fontFamily": FONT_FAMILY,
                           "fontSize": "10px", "padding": "2px 8px", "width": "140px",
                           "marginLeft": "16px"}
                )
            ]),
        ]),
        html.Div(timestamp, style={"color": C["gray"], "fontSize": "10px"}),
    ], style={"background": C["header"], "borderBottom": f"2px solid {C['orange']}",
              "padding": "4px 8px", "display": "flex", "justifyContent": "space-between",
              "alignItems": "center", "marginBottom": "6px"})

def function_key_bar(active_key="F1"):
    keys = [("F1", "HOME"), ("F2", "SCREENER"), ("F3", "SECTORS"), ("F4", "DETAIL")]
    items = []
    for key, label in keys:
        items.append(html.Span([
            html.Span(key, style={"background": "#444", "color": C["yellow"],
                                   "padding": "0 4px", "marginRight": "3px", "fontWeight": "bold"}),
            label
        ], style={"color": C["yellow"]}))
    items.append(html.Div(style={"flex": "1"}))
    items.append(html.Span("HIGHBOURNE v2.0", style={"color": C["gray"]}))
    return html.Div(items, style={
        "background": C["header"], "borderTop": f"1px solid #333",
        "padding": "3px 8px", "marginTop": "8px", "display": "flex",
        "gap": "16px", "fontSize": "9px"
    })

def stat_card(label, value, color=None):
    return html.Div([
        html.Div(label, style={"color": C["orange"], "fontSize": "8px",
                                "textTransform": "uppercase", "letterSpacing": "0.5px"}),
        html.Div(value, style={"fontSize": "14px", "fontWeight": "bold",
                                "marginTop": "2px", "color": color or C["white"]}),
    ], style={"flex": "1", "background": "#111", "border": "1px solid #333", "padding": "4px 6px"})

def gauge_bar(value, min_val=0, max_val=100, colors=None):
    """Horizontal gauge bar with a needle marker."""
    if colors is None:
        colors = ["#005500", "#338800", "#888800", "#884400", "#880000"]
    pct = max(0, min(100, (value - min_val) / (max_val - min_val) * 100))
    segments = []
    width = 100 / len(colors)
    for i, color in enumerate(colors):
        segments.append(html.Div(style={
            "position": "absolute", "left": f"{i*width}%", "top": "0",
            "height": "100%", "width": f"{width}%", "background": color
        }))
    segments.append(html.Div(style={
        "position": "absolute", "left": f"{pct}%", "top": "-2px",
        "width": "3px", "height": "18px", "background": C["yellow"],
        "borderRadius": "1px", "zIndex": "2"
    }))
    return html.Div(segments, style={
        "position": "relative", "height": "14px", "background": "#111",
        "borderRadius": "2px", "margin": "4px 0 8px 0", "overflow": "hidden"
    })

# CSS for cell flash animation (inject via app.index_string or external stylesheet)
FLASH_CSS = """
@keyframes cellFlash {
    0% { background-color: transparent; }
    15% { background-color: rgba(255, 255, 0, 0.3); }
    30% { background-color: transparent; }
    45% { background-color: rgba(255, 255, 0, 0.3); }
    60% { background-color: transparent; }
}
.cell-flash {
    animation: cellFlash 1s ease-out;
}
"""
```

- [ ] **Step 2: Commit**

```bash
git add theme.py
git commit -m "feat: add Bloomberg theme module — colors, shared components, flash CSS"
```

---

### Task 8: Multi-Page App Shell

**Files:**
- Modify: `app.py`
- Create: `pages/__init__.py`
- Create: `pages/home.py` (stub)
- Create: `pages/detail.py` (stub)

- [ ] **Step 1: Create pages package**

```python
# pages/__init__.py
```

- [ ] **Step 2: Create stub home page**

```python
# pages/home.py
from dash import html, dcc, callback, Input, Output
from theme import C, CONTAINER_STYLE, header_bar, function_key_bar

def layout():
    return html.Div([
        header_bar("HIGHBOURNE TERMINAL", "EQUITY SCANNER"),
        html.Div("Scanner coming soon...", style={"color": C["gray"], "padding": "20px"}),
        function_key_bar("F1"),
    ], style=CONTAINER_STYLE)
```

- [ ] **Step 3: Create stub detail page**

```python
# pages/detail.py
from dash import html, dcc, callback, Input, Output
from theme import C, CONTAINER_STYLE, header_bar, function_key_bar

def layout(symbol="AAPL"):
    return html.Div([
        header_bar("HIGHBOURNE TERMINAL", "DETAIL VIEW"),
        html.Div(f"Detail view for {symbol} coming soon...", 
                 style={"color": C["gray"], "padding": "20px"}),
        function_key_bar("F4"),
    ], style=CONTAINER_STYLE)
```

- [ ] **Step 4: Restructure app.py as multi-page shell**

Replace the contents of `app.py` with the multi-page routing shell. **Preserve the existing data loading logic** (lines 40-70 of original app.py) in a new `data/startup.py` module, and keep the original `app.py` backed up as `app_v1_backup.py` before overwriting.

```bash
cp app.py app_v1_backup.py
```

Then write new `app.py`:

```python
# app.py — Multi-page Dash shell
import dash
from dash import html, dcc, Input, Output, State
from theme import C, FONT_FAMILY, STYLESHEET, CONTAINER_STYLE, FLASH_CSS
import pages.home as home
import pages.detail as detail

app = dash.Dash(__name__, suppress_callback_exceptions=True)

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Highbourne Terminal</title>
        {%css%}
        <style>
            body { margin: 0; padding: 0; }
            ''' + FLASH_CSS + '''
        </style>
    </head>
    <body style="background: #000; font-family: ''' + FONT_FAMILY + ''';">
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    html.Div(id="page-content", style=STYLESHEET),
], style={"backgroundColor": C["bg"], "minHeight": "100vh"})

@app.callback(Output("page-content", "children"), Input("url", "pathname"))
def display_page(pathname):
    if pathname and pathname.startswith("/detail/"):
        symbol = pathname.split("/detail/")[-1].upper()
        return detail.layout(symbol)
    return home.layout()

# Search bar navigation
@app.callback(
    Output("url", "pathname"),
    Input("search-bar", "n_submit"),
    State("search-bar", "value"),
    prevent_initial_call=True
)
def search_navigate(n_submit, value):
    if value:
        return f"/detail/{value.upper().strip()}"
    return "/"

if __name__ == "__main__":
    app.run(debug=True, port=8050)
```

- [ ] **Step 5: Verify the app starts**

Run: `cd /Users/anthonyfoley/Documents/CPSC_Courses/ProjectHighbourne && python app.py`
Expected: App starts at http://localhost:8050, shows "Scanner coming soon..." on home page

- [ ] **Step 6: Commit**

```bash
git add app.py app_v1_backup.py pages/__init__.py pages/home.py pages/detail.py theme.py
git commit -m "feat: restructure app as multi-page Dash shell with Bloomberg theme"
```

---

## Phase 4: Home Page (Scanner)

### Task 9: Data Loading and Startup Pipeline

**Files:**
- Create: `data/startup.py`

This module pre-computes all data needed by both pages at app startup. It loads prices, computes technicals for all tickers, builds the screener dataframe with all columns, and computes risk/sector metrics.

- [ ] **Step 1: Create startup data pipeline**

```python
# data/startup.py
"""Pre-compute all dashboard data at startup. Called once, results stored in module-level variables."""
import pandas as pd
import numpy as np
from data.loader import load_tickers, load_market_data, compute_all_ratios, get_filing_dates
from data.market_data import (
    fetch_single_prices, fetch_ticker_info, compute_returns, 
    compute_52w_range, compute_relative_volume
)
from data.technicals import (
    compute_rsi, compute_macd, compute_sma, 
    macd_signal_label, rsi_label, ma_trend_label, detect_crossovers
)
from data.risk import (
    fetch_vix, fetch_fear_greed, compute_breadth_stats,
    compute_new_highs_lows, compute_advancers_decliners, compute_risk_verdict
)
from data.sectors import (
    compute_sector_returns, compute_sector_attribution,
    compute_normalized_performance, compute_sector_normalized_series, SECTOR_COLORS
)
from models.ticker import Universe, Ticker, compute_alert, compute_composite_score, compute_signal_label

# Module-level data stores — populated by init()
universe = None
screener_df = None
risk_stats = None
sector_data = None
price_cache = {}  # {ticker: pd.Series}
ticker_info_cache = {}  # {ticker: dict}

def init():
    """Load all data and compute all derived metrics. Call once at startup."""
    global universe, screener_df, risk_stats, sector_data, price_cache, ticker_info_cache
    
    print("Loading tickers...")
    ticker_sector = load_tickers()
    symbols = list(ticker_sector.keys())
    
    print("Loading market data (SimFin)...")
    mktcap, close_prices = load_market_data(years=5)
    
    print("Computing ratios...")
    ratio_dfs = compute_all_ratios(mktcap)
    
    # Build Universe (existing logic from app.py lines 55-68)
    universe = Universe()
    for sym, sector in ticker_sector.items():
        t = Ticker(sym, sector)
        for ratio_name, df in ratio_dfs.items():
            if sym in df.columns:
                series = df[sym].dropna()
                if len(series) > 0:
                    t.set_ratio(ratio_name, series)
        universe.add_ticker(t)
    
    print("Loading yfinance prices for technicals...")
    # Use close_prices from SimFin as primary source, supplement with yfinance for missing
    for sym in symbols:
        if sym in close_prices.columns:
            price_cache[sym] = close_prices[sym].dropna()
    
    print("Computing technicals and building screener...")
    screener_rows = []
    above_200sma = {}
    above_50sma = {}
    rsi_values = {}
    returns_1d = {}
    
    for sym in symbols:
        prices = price_cache.get(sym)
        if prices is None or len(prices) < 50:
            continue
        
        ticker_obj = universe.get(sym)
        if ticker_obj is None:
            continue
        
        # Find most extreme z-score across all ratios
        best_z = None
        best_ratio = None
        for ratio_name in ["P/E", "P/S", "P/B", "EV/EBITDA"]:
            try:
                s = ticker_obj.stats(ratio_name)
                if s and s.get("z_score") is not None:
                    z = s["z_score"]
                    if best_z is None or abs(z) > abs(best_z):
                        best_z = z
                        best_ratio = ratio_name
            except Exception:
                continue
        
        if best_z is None:
            continue
        
        # Technicals
        rsi_series = compute_rsi(prices)
        rsi_val = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 and not pd.isna(rsi_series.iloc[-1]) else 50
        
        macd_line, signal_line, histogram = compute_macd(prices)
        macd_label = macd_signal_label(macd_line, signal_line)
        
        sma_50 = compute_sma(prices, 50)
        sma_200 = compute_sma(prices, 200)
        ma_label = ma_trend_label(prices.iloc[-1], sma_200.iloc[-1] if len(sma_200) > 0 else None)
        
        ret_1d, ret_3d = compute_returns(prices)
        low_52w, high_52w, pct_52w = compute_52w_range(prices)
        
        # Breadth tracking
        above_200sma[sym] = ma_label == "Above"
        above_50sma[sym] = prices.iloc[-1] > sma_50.iloc[-1] if len(sma_50) > 0 and not pd.isna(sma_50.iloc[-1]) else False
        rsi_values[sym] = rsi_val
        returns_1d[sym] = ret_1d
        
        # Alert
        alert = compute_alert(best_z, rsi_val, macd_label, ma_label)
        signal = compute_signal_label(best_z, alert["type"])
        
        screener_rows.append({
            "symbol": sym,
            "sector": ticker_sector.get(sym, ""),
            "rv_sig": best_ratio,
            "z_score": round(best_z, 2),
            "rsi": round(rsi_val, 0),
            "macd": macd_label,
            "ret_1d": round(ret_1d * 100, 1),
            "ret_3d": round(ret_3d * 100, 1),
            "signal": signal,
            "alert_type": alert["type"],
            "alert_reason": alert["reason"],
            "ma_trend": ma_label,
            "low_52w": low_52w,
            "high_52w": high_52w,
            "pct_52w": pct_52w,
            "price": float(prices.iloc[-1]),
        })
    
    screener_df = pd.DataFrame(screener_rows).sort_values("z_score")
    
    print("Computing risk metrics...")
    vix = fetch_vix()
    fg = fetch_fear_greed()
    adv, dec, unch = compute_advancers_decliners(returns_1d)
    highs, lows = compute_new_highs_lows(price_cache)
    breadth = compute_breadth_stats(above_200sma, above_50sma, rsi_values)
    
    risk_stats = {
        "vix": vix["value"],
        "vix_change": vix["change"],
        "fear_greed": fg["value"],
        "fear_greed_label": fg["label"],
        "put_call": None,  # Would need options data source
        "pct_above_200sma": breadth["pct_above_200sma"],
        "pct_above_50sma": breadth["pct_above_50sma"],
        "avg_rsi": breadth["avg_rsi"],
        "new_highs": highs,
        "new_lows": lows,
        "advancers": adv,
        "decliners": dec,
        "unchanged": unch,
    }
    risk_stats["verdict"] = compute_risk_verdict(risk_stats)
    
    print("Computing sector data...")
    sector_tickers = {}
    for sym, sect in ticker_sector.items():
        sector_tickers.setdefault(sect, []).append(sym)
    
    period_returns = {sym: returns_1d.get(sym, 0) for sym in symbols}
    sector_returns = compute_sector_returns(period_returns, ticker_sector)
    sector_norm = compute_sector_normalized_series(sector_tickers, price_cache)
    
    sector_data = {
        "returns": sector_returns,
        "normalized": sector_norm,
        "colors": SECTOR_COLORS,
    }
    
    print(f"Startup complete. {len(screener_df)} tickers loaded.")
```

- [ ] **Step 2: Commit**

```bash
git add data/startup.py
git commit -m "feat: add startup data pipeline — loads prices, computes technicals, builds screener"
```

---

### Task 10: Home Page — Scanner Table and Alert Banner

**Files:**
- Modify: `pages/home.py`

- [ ] **Step 1: Implement home page layout with screener table, alert banner, filters, movers, scatter plot, risk dashboard, and sector breakdown**

This is a large layout file. Implement the full home page layout using Dash components, referencing the mockup at `.superpowers/brainstorm/53524-1775259052/content/16-home-bloomberg-v2.html`. Use `data/startup.py` module-level variables for data.

Key components to implement:
- Alert banner (html.Div with orange border)
- Filter bar (sector dropdown, cheap/rich/all toggle)
- DataTable with all 15 columns from the spec
- Gainers/Losers bar below table
- Today's Movers carousel (use dcc.Interval for 5s rotation)
- Market movers scatter plot (plotly scatter)
- Risk dashboard panel
- Sector performance table + normalized chart

Each component should be a function returning a Dash component, called from `layout()`.

- [ ] **Step 2: Add callbacks for interactivity**

Key callbacks:
- Filter bar → update screener table
- Sector dropdown → filter table rows
- Cheap/Rich/All → filter by z_score sign
- dcc.Interval → rotate movers carousel
- Sector tags → toggle chart traces
- Row click → navigate to `/detail/{symbol}`

- [ ] **Step 3: Wire up app.py to call startup.init() and import home page**

Update `app.py` to call `data.startup.init()` before `app.run()`:

```python
# Add to bottom of app.py, before if __name__
import data.startup as startup
startup.init()
```

- [ ] **Step 4: Verify the home page renders**

Run: `python app.py`
Expected: Home page loads at localhost:8050 with real data in the screener table

- [ ] **Step 5: Commit**

```bash
git add pages/home.py app.py
git commit -m "feat: implement home page — scanner table, alert banner, movers, risk dashboard, sectors"
```

---

## Phase 5: Detail View

### Task 11: Detail Page — Full Implementation

**Files:**
- Modify: `pages/detail.py`

- [ ] **Step 1: Implement detail page layout**

Build the full detail view referencing mockup `19-detail-bloomberg-v3.html`. Components:
- Back nav button
- Ticker header bar (price, returns, market cap, next ER, overweight badge)
- Company description + competitors panel
- News section (hyperlinked)
- Stock price chart (plotly line with area fill, time period buttons)
- Market data table (right sidebar)
- Earnings surprise chart (plotly scatter with hover tooltips)
- Financial analysis table (tabs for I/S, B/S, C/F, DuPont)
- Stat cards row
- RV chart (port existing logic from `app_v1_backup.py` lines 232-347)
- TA panels: Price+MAs, RSI, MACD (stacked plotly subplots)

- [ ] **Step 2: Add callbacks**

Key callbacks:
- Time period buttons → update stock price chart range
- Ratio dropdown / window toggle → update RV chart
- Financial table tabs → switch table content
- Competitor links → navigate to `/detail/{competitor}`
- Back button → navigate to `/`

- [ ] **Step 3: Port the existing RV chart logic**

Copy the RV chart callback logic from `app_v1_backup.py` (lines 232-347) into a helper function in `pages/detail.py`. Adapt it to work with the new data pipeline (using `data.startup.universe` instead of the old global `universe` variable). Preserve the earnings E marker logic with correct 10-Q (green) / 10-K (orange) cadence.

- [ ] **Step 4: Verify detail page renders**

Run: `python app.py`, navigate to `http://localhost:8050/detail/AAPL`
Expected: Full detail view renders with real data

- [ ] **Step 5: Commit**

```bash
git add pages/detail.py
git commit -m "feat: implement detail view — all charts, market data, earnings surprise, financials"
```

---

## Phase 6: Polish

### Task 12: Cell Flash Animation and Interval Refresh

**Files:**
- Modify: `pages/home.py`

- [ ] **Step 1: Add dcc.Interval for periodic data refresh (60s)**

```python
dcc.Interval(id="refresh-interval", interval=60*1000, n_intervals=0)
```

- [ ] **Step 2: Add callback that compares current prices to previous snapshot and applies flash CSS class to changed cells**

Use a `dcc.Store` to hold the previous price snapshot. On each interval tick, compare new prices to stored prices. If any cell changed by >2%, add the `cell-flash` class to that row temporarily.

- [ ] **Step 3: Test the flash behavior**

Open the app, wait for interval tick, verify cells flash when data changes.

- [ ] **Step 4: Commit**

```bash
git add pages/home.py
git commit -m "feat: add cell flash animation on significant price changes"
```

---

### Task 13: Install Dependencies and Final Verification

- [ ] **Step 1: Install yfinance**

```bash
pip install yfinance requests
```

- [ ] **Step 2: Create tests/__init__.py**

```python
# tests/__init__.py
```

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v
```
Expected: All tests pass

- [ ] **Step 4: Run the app end-to-end**

```bash
python app.py
```

Verify:
- Home page loads with screener data
- Alert banner shows convergence signals
- Movers carousel rotates
- Scatter plot renders
- Risk dashboard shows VIX, Fear & Greed
- Sector breakdown renders with chart
- Click a row → detail view loads
- Detail view shows all charts
- Search bar navigates to ticker
- Back button returns to scanner

- [ ] **Step 5: Commit**

```bash
git add tests/__init__.py requirements.txt
git commit -m "feat: finalize Highbourne Terminal v2 — all views working"
```
