# Highbourne Terminal v2 — Dashboard Design Spec

## Overview

Evolve the existing relative valuation Dash app into a multi-view Bloomberg-style investment dashboard. The dashboard helps answer three questions: **What is cheap/rich?** (relative valuation), **What is overbought/oversold?** (technical analysis), and **Where should I deploy capital?** (composite signals + market risk context).

The dashboard flows top-down: **Market risk** -> **Sector rotation** -> **Individual opportunity**.

## Architecture Approach

**Extend in place** — add to the existing Dash app rather than rewriting. New modules for technicals, market data, and risk metrics. Refactor into multi-page Dash app when the third major subsystem (fundamentals or portfolio) is added.

## Visual Design

**Bloomberg terminal aesthetic:**
- Black background (#000), orange headers/borders (#ff8c00)
- Monospace font (Lucida Console / Monaco / Courier New)
- Color coding: green (#00ff00) positive, red (#ff4444) negative, yellow (#ffff00) tickers/highlights, white (#e0e0e0) body text, gray (#999) secondary text, cyan (#00bcd4) current values, orange (#ff8c00) labels/headers, purple (#bb86fc) RSI
- Max-width 1100px container with side margins — don't stretch edge-to-edge
- Function key bar at bottom (F1-F4) for navigation between views

**Cell flash behavior:** When a significant event occurs (price moves >2%, alert threshold crossed, large volume spike, earnings released), the affected cell background double-flashes yellow (#ffff00 at ~30% opacity) then fades back. Brief enough to catch peripheral vision, not distracting.

---

## View 1: Home Page (Scanner)

The landing page. Scan the entire R3000 universe at a glance, spot what's flagged, click to drill into detail.

### Search Bar (header, top left)
- Bloomberg-style text input next to the title
- Type a ticker symbol -> autocomplete dropdown -> Enter jumps directly to that ticker's detail view
- Yellow text on black background, monospace

### Alert Banner (top)
- Bloomberg-style horizontal strip with orange border
- Shows convergence alerts: tickers where RV + technical signals align
- Format: `INTC P/E -2.1σ + RSI 24 oversold`
- Green for buy-zone convergence, red for sell-zone convergence

### Filter Bar
- **Sector dropdown** (All / Technology / Health Care / etc.)
- **View toggle**: Cheap | Rich | All
- Dynamic ticker count (updates based on active filters, e.g., "Showing 2,556 tickers" or "Showing 312 tickers") and last-updated timestamp
- No ratio or time window selector — the system automatically picks the most extreme ratio signal per ticker

### Screener Table
Columns (with headers):
1. Signal icon (green dot = buy zone, red dot = sell zone, blank = no alert)
2. **Ticker** (white, bold)
3. **Sector** (gray)
4. **RV SIG** — which ratio flagged it (P/E, P/S, P/B, EV/EBITDA)
5. **Z-Score** — most extreme z-score across all ratios
6. **RSI** (14-day)
7. **MACD** — Bull/Bear/Flat
8. **1D %** — 1-day return
9. **3D %** — 3-day return
10. **Signal** — composite badge: BUY / CHEAP / FAIR / RICH / SELL
11. **vs Peers** — stock return vs sector return
12. **52W Range** — horizontal bar with cyan dot showing current price position
13. **PT (Avg)** — consensus analyst price target + % upside/downside
14. **Next ER** — next expected earnings date (orange `!` when within 7 days)
15. **90D Chart** — sparkline mini chart

**News headline row** beneath each ticker — most recent headline as a blue hyperlink with source and timestamp.

**Gainers/Losers bar** directly below the screener table — horizontal split bar showing advancers vs decliners count from R3000.

Alert rows get colored background (green tint for buy, red tint for sell) and left border accent.

Click any row -> opens Detail View for that ticker.

### Today's Movers Panel
Two side-by-side panels below the screener:
- **Top Gainers** (green top border) — shows 5 at a time, auto-rotates to next 5 every 5 seconds
- **Top Losers** (red top border) — same rotation
- Columns: rank, ticker (white), name, last price, change %
- Progress dots at bottom indicate which page is showing
- Click any ticker to open detail view

### Market Movers Scatter Plot
**1-Day Performance vs Relative Volume (10d)** — scatter plot with:
- Y-axis: 1-day return (%)
- X-axis: relative volume vs 10-day average
- Dots clustered around center; outliers (high volume + big move) labeled with ticker
- Labeled outliers are color-coded green (up) or red (down)
- Click any labeled dot to open detail view

### Risk Dashboard (sidebar panel, right of scatter plot)
Market-level barometers — "should I be deploying capital right now?"
- **VIX** — current value + change, with color gradient gauge bar (Low -> Extreme)
- **CNN Fear & Greed Index** — scraped value (0-100) with gauge bar, plus classification label
- **Put/Call Ratio** — with bullish/bearish label
- **New 52W Highs/Lows** — count comparison
- **% Above 200d SMA** — R3000 breadth
- **% Above 50d SMA** — R3000 breadth
- **Avg RSI (R3000)** — universe-wide momentum
- **Overall risk verdict badge** — composite assessment: LOW RISK (green) / MODERATE (yellow) / ELEVATED RISK (red) / EXTREME RISK (dark red) with brief guidance text

All breadth/RSI stats computed from the R3000 universe (consistent with the screener). VIX pulled from yfinance (`^VIX`).

### Sector Performance Breakdown
Two-panel layout below movers:

**Left — Sector Table:**
- Columns: Sector (with color swatch), Return, **EPS Growth contribution**, **Multiple Expansion contribution**, 52W Range
- Return ≈ EPS Growth + Multiple Expansion — shows whether rally is driven by real earnings or just P/E re-rating
- Time period toggles: 1M / 3M / YTD / 1Y / 3Y
- Footer explaining column abbreviations

**Right — Normalized Performance Chart:**
- Color-coded line per sector, normalized to 0% at start
- Toggleable sector tags at top — click to deselect/reselect sectors
- Chart y-axis rescales to fit visible lines when sectors are toggled off
- Return labels on right edge of each line
- Same time period toggle as the table (synced)

---

## View 2: Detail View (per-ticker)

Deep-dive into a single stock. Accessed by clicking a row in the scanner.

### Navigation
- **"BACK TO SCANNER"** button (top left, yellow text)
- Function key bar at bottom

### Ticker Header Bar
Single-line bar with:
- Ticker symbol (large, white, bold)
- Company name | Sector | Sub-industry
- Current price + daily % change
- Volume
- Market cap
- YTD return %
- 1Y return %
- Next earnings date
- **OVERWEIGHT / MARKET WEIGHT / UNDERWEIGHT** badge (top right)
  - Green background for overweight, gray for market weight, red for underweight
  - Derived from composite of RV z-score, technical signals, and peer performance

### Company Description + Key Competitors
Side-by-side layout:
- **Left**: Company description paragraph (gray text, ~2-3 sentences)
- **Right (200px panel)**: 5 key competitors as clickable links
  - Each shows ticker (white, bold) + abbreviated name + arrow
  - Click opens that ticker's detail view
  - Hover highlights the row

### Recent News
- 3 most recent headlines as **blue hyperlinks**
- Source and timestamp right-aligned per row

### Stock Price Chart + Market Data (two-column)
**Left — Stock Price Chart:**
- Line chart with area fill (cyan)
- Clickable time period buttons: 1D | 5D | 1M | 3M | **YTD** | 6M | 1Y | 2Y | 5Y | MAX
- Y-axis price labels, X-axis date labels

**Right — Market Data Table (260px):**
- Last, VWAP, Open, Prev Close
- Day High/Low, 52wk High/Low
- Beta 3Y
- Market Cap ($M), Total Enterprise Value ($M)
- Volume, Avg 3M Daily Volume
- Shares Outstanding, Float (%)
- Institutional Ownership (%)
- Short Interest / Short Int % of ShOut
- Dividend Yield (%)
- Analyst PT Avg + % upside/downside
- Next Earnings date

### Earnings Surprise Chart
Modeled after Bloomberg/FactSet surprise charts:
- Y-axis: EPS ($)
- X-axis: fiscal quarters (5 quarters shown)
- **Filled green circles** = actual EPS (beat estimate)
- **Filled red circles** = actual EPS (missed estimate)
- **Hollow circles** = consensus estimate
- Most recent quarter: larger circle with glow effect
- Selected quarter callout at top: "FQ4'25 | Actual: $0.30 ▲ 275% | Estimate: $0.08"
- **Hover on any actual dot** shows tooltip with:
  - Quarter + date
  - Actual vs estimate
  - Surprise %
  - **3-day price reaction** after earnings

### Financial Analysis Table
- Toggle tabs: **Income Statement** | **Balance Sheet** | **Cash Flow** | **DuPont ROE**
- 5-year lookback (FY columns)
- Most recent year highlighted in yellow
- Key metrics per tab:
  - **I/S**: Revenue, YoY Growth, Gross Profit, Gross Margin, Operating Income, Op Margin, Net Income, EPS
  - **B/S**: Total Assets, Total Debt, Cash, Stockholders' Equity, Debt/Equity, Current Ratio
  - **C/F**: Operating Cash Flow, CapEx, Free Cash Flow, FCF Margin, Buybacks, Dividends
  - **DuPont**: Net Margin, Asset Turnover, Equity Multiplier, ROE decomposition
- Green/red color coding for YoY improvements/declines

### Stat Cards Row
Horizontal cards showing at-a-glance:
- RV Ratio (which ratio is most extreme)
- Current value
- Mean
- Z-Score
- RSI (14) with OVERSOLD/OVERBOUGHT label
- MACD signal (Bullish/Bearish)
- MA Trend (Above/Below 200d)

### RV Controls
- Ratio dropdown (P/E, P/S, P/B, EV/EBITDA)
- Window toggle: 5Y | 2Y | 6M

### RV Chart (existing, enhanced)
- Ratio time series (white line)
- Mean (orange dashed)
- +/- 1σ bands (yellow dashed)
- +/- 2σ bands (dark yellow dashed)
- Band fill gradient
- Current value dot (cyan) with label
- **Earnings markers on the chart line**: green `E` box for 10-Q, orange `E` box for 10-K
  - Correct cadence: Q1 (green), Q2 (green), Q3 (green), Annual (orange), repeat
- Y-axis labels with ratio values
- σ labels on right edge

### Technical Analysis Panel (stacked below RV, independent time axes)

**Price + Moving Averages (1Y default):**
- Close price (white), 50d SMA (orange dashed), 200d SMA (red dashed)
- Annotated crossovers: "Golden Cross" (green badge), "Death Cross" (red badge)
- Y-axis price labels

**RSI (14) — 6M default:**
- Purple line
- Colored zones: overbought (>70, red tint), oversold (<30, green tint)
- Labeled threshold lines with values
- Current value badge: "24 — OVERSOLD" (green) or "78 — OVERBOUGHT" (red)

**MACD (12, 26, 9) — 6M default:**
- MACD line (cyan), Signal line (orange dashed)
- Histogram bars: green when MACD > Signal, red when MACD < Signal
- Annotated crossover points: "Bearish Cross" / "Bullish Cross"
- Current state badge: "CONVERGING — WATCH FOR BULLISH CROSS"
- Zero line labeled

Each technical sub-chart uses its own appropriate time range — not locked to the RV window.

---

## Data Sources

| Data | Source | Notes |
|------|--------|-------|
| Fundamental ratios (P/E, P/S, P/B, EV/EBITDA) | SEC EDGAR (existing) | Cached in JSON files |
| Daily OHLCV prices | **yfinance** (new) | Free, no API key |
| Market cap, shares outstanding | SimFin (existing) + yfinance | |
| Technical indicators (RSI, MACD, SMA) | Computed from yfinance prices | pandas/numpy |
| Analyst price targets | yfinance | `Ticker.info` |
| Next earnings date | yfinance | `Ticker.calendar` |
| Company description | yfinance | `Ticker.info['longBusinessSummary']` |
| Competitor tickers | yfinance | `Ticker.info['industry']` peers |
| News headlines | yfinance | `Ticker.news` — links as hyperlinks |
| Earnings surprise (EPS actual vs est) | yfinance | `Ticker.earnings_history` |
| Filing dates (10-Q/10-K) | EDGAR (existing) | `edgar_filing_dates_cache.json` |
| VIX | yfinance (`^VIX`) | |
| CNN Fear & Greed | Web scrape | Fallback: compute own composite |
| Financial statements (I/S, B/S, C/F) | EDGAR (existing) + yfinance | |
| Sector returns / breadth | Computed from R3000 universe | Using existing Tickers.csv |

## New Modules

| Module | Location | Purpose |
|--------|----------|---------|
| `data/technicals.py` | New | Compute RSI, MACD, SMA from price data |
| `data/market_data.py` | New | yfinance wrapper: OHLCV, analyst targets, earnings, news, company info |
| `data/risk.py` | New | Market-level metrics: VIX, breadth, fear/greed, put/call |
| `data/sectors.py` | New | Sector return attribution (EPS growth vs multiple expansion) |
| `models/ticker.py` | Extended | Add technical indicator series, earnings surprise data |

## Alert Logic

A **BUY alert** fires when: RV z-score < -1.5 AND at least one of (RSI < 30, MACD bullish crossover, golden cross).

A **SELL alert** fires when: RV z-score > +1.5 AND at least one of (RSI > 70, MACD bearish crossover, death cross).

## Overweight/Underweight Logic

Composite scoring based on:
- RV z-score (cheap = positive points, rich = negative)
- Technical signals (oversold + bullish momentum = positive)
- Peer underperformance (lagging sector = potential catch-up)
- Analyst upside (high PT upside = positive)

Thresholds: score > X = OVERWEIGHT, score < -X = UNDERWEIGHT, else MARKET WEIGHT. Exact thresholds to be calibrated after initial implementation.

## Mockup References

All mockups saved in `.superpowers/brainstorm/` directory:
- Home page (Bloomberg style): `16-home-bloomberg-v2.html`
- Detail view (Bloomberg style): `19-detail-bloomberg-v3.html`
