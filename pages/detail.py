"""Detail page — per-ticker deep-dive view for the Highbourne Terminal."""

from datetime import datetime, timedelta
from dash import html, dcc, callback, Input, Output, State, no_update
import plotly.graph_objects as go
import pandas as pd
import numpy as np

import data.startup as startup
from data.market_data import fetch_ticker_info, fetch_earnings_history, fetch_competitors, compute_52w_range, compute_returns
from data.technicals import compute_rsi, compute_macd, compute_sma, detect_crossovers, macd_signal_label, rsi_label, ma_trend_label
from data.loader import get_filing_dates
from models.ticker import compute_alert, compute_composite_score, compute_signal_label
from theme import C, FONT_FAMILY, CONTAINER_STYLE, header_bar, function_key_bar, stat_card

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RATIO_NAMES = ["P/E", "P/S", "P/B", "EV/EBITDA"]
WINDOW_MAP = {"5Y": 5 * 365, "2Y": 2 * 365, "6M": 182}
WINDOW_OPTIONS = [{"label": w, "value": w} for w in WINDOW_MAP]

PRICE_PERIODS = {
    "1D": 1, "5D": 5, "1M": 21, "3M": 63, "YTD": None,
    "6M": 126, "1Y": 252, "2Y": 504, "5Y": 1260, "MAX": None,
}

PANEL_STYLE = {
    "backgroundColor": C["panel"],
    "border": f"1px solid {C['border']}",
    "padding": "10px",
    "marginBottom": "8px",
    "fontFamily": FONT_FAMILY,
}

CHART_LAYOUT = dict(
    paper_bgcolor="#0a0a0a",
    plot_bgcolor="#0a0a0a",
    font=dict(family=FONT_FAMILY, color=C["gray"], size=10),
    margin=dict(l=50, r=60, t=35, b=35),
    showlegend=False,
    hovermode="x unified",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fmt(val, fmt_str=".2f", prefix="", suffix="", fallback="N/A"):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return fallback
    return f"{prefix}{val:{fmt_str}}{suffix}"


def _fmt_large(val, fallback="N/A"):
    if val is None:
        return fallback
    if val >= 1e12:
        return f"${val/1e12:.2f}T"
    if val >= 1e9:
        return f"${val/1e9:.2f}B"
    if val >= 1e6:
        return f"${val/1e6:.1f}M"
    return f"${val:,.0f}"


def _fmt_pct(val, fallback="N/A"):
    if val is None:
        return fallback
    return f"{val*100:.1f}%"


def _metric_row(label, value, color=C["white"]):
    return html.Div(
        style={"display": "flex", "justifyContent": "space-between", "padding": "2px 0",
               "borderBottom": f"1px solid {C['border']}", "fontSize": "10px", "fontFamily": FONT_FAMILY},
        children=[
            html.Span(label, style={"color": C["gray"]}),
            html.Span(value, style={"color": color, "fontWeight": "bold"}),
        ],
    )


def _empty_fig(msg="No data"):
    fig = go.Figure()
    fig.update_layout(
        **CHART_LAYOUT,
        annotations=[dict(text=msg, x=0.5, y=0.5, xref="paper", yref="paper",
                          showarrow=False, font=dict(size=14, color=C["gray"]))],
    )
    return fig


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
def layout(symbol="AAPL"):
    """Build the detail page layout. Safe to call before startup.init()."""
    ts = datetime.now().strftime("%H:%M:%S")

    # Guard: if startup hasn't run yet
    if startup.universe is None:
        return html.Div([
            header_bar("HIGHBOURNE TERMINAL", "DETAIL VIEW", ts),
            html.Div("Loading... please wait for data initialization.",
                     style={"color": C["gray"], "padding": "40px", "fontFamily": FONT_FAMILY}),
            function_key_bar("F4"),
        ], style=CONTAINER_STYLE)

    symbol = symbol.upper()
    ticker_obj = startup.universe.get(symbol)
    prices = startup.price_cache.get(symbol)

    if ticker_obj is None:
        return html.Div([
            header_bar("HIGHBOURNE TERMINAL", "DETAIL VIEW", ts),
            html.A("◄ BACK TO SCANNER", href="/",
                   style={"color": C["yellow"], "textDecoration": "none",
                          "border": "1px solid #444", "padding": "2px 6px",
                          "background": "#111", "fontSize": "10px"}),
            html.Div(f"Ticker {symbol} not found in universe.",
                     style={"color": C["red"], "padding": "20px", "fontFamily": FONT_FAMILY}),
            function_key_bar("F4"),
        ], style=CONTAINER_STYLE)

    # ----- Fetch yfinance data for this ticker -----
    try:
        info = fetch_ticker_info(symbol)
    except Exception:
        info = {}

    # ----- Compute key stats -----
    sector = startup.ticker_sector.get(symbol, "Unknown")
    industry = info.get("industry", "")
    company_name = info.get("description", "")[:80] if info.get("description") else symbol
    # yfinance info doesn't have a short name field in our wrapper; use symbol
    price_val = float(prices.iloc[-1]) if prices is not None and not prices.empty else None
    prev_close = info.get("prev_close")
    daily_chg = None
    daily_chg_pct = None
    if price_val is not None and prev_close is not None and prev_close != 0:
        daily_chg = price_val - prev_close
        daily_chg_pct = daily_chg / prev_close

    volume = info.get("volume")
    mkt_cap = info.get("market_cap")
    next_er = info.get("next_earnings")

    # Returns
    ytd_ret = None
    y1_ret = None
    if prices is not None and len(prices) > 252:
        ytd_start = prices.index[prices.index >= pd.Timestamp(datetime(datetime.now().year, 1, 1))]
        if len(ytd_start) > 0:
            ytd_ret = (price_val - float(prices.loc[ytd_start[0]])) / float(prices.loc[ytd_start[0]])
        y1_ret = (price_val - float(prices.iloc[-252])) / float(prices.iloc[-252])

    # Composite score / badge
    best_z = 0.0
    for rn in RATIO_NAMES:
        s = ticker_obj.stats(rn)
        if s and abs(s["z_score"]) > abs(best_z):
            best_z = s["z_score"]

    rsi_series = compute_rsi(prices, 14) if prices is not None and len(prices) > 20 else pd.Series(dtype=float)
    current_rsi = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0
    macd_line, signal_line, histogram = compute_macd(prices) if prices is not None and len(prices) > 30 else (pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float))
    macd_sig = macd_signal_label(macd_line, signal_line) if not macd_line.empty else "Flat"
    sma200 = compute_sma(prices, 200) if prices is not None and len(prices) > 200 else pd.Series(dtype=float)
    ma_trend = ma_trend_label(price_val or 0.0, float(sma200.iloc[-1]) if not sma200.empty else float('nan'))

    pt_upside = 0.0
    if info.get("PT") and price_val:
        pt_upside = (info["PT"] - price_val) / price_val

    composite = compute_composite_score(best_z, current_rsi, macd_sig, 0.0, pt_upside)

    # Color for daily change
    chg_color = C["green"] if daily_chg and daily_chg >= 0 else C["red"]

    # ----- Build sections -----

    # 1. Header + back nav
    sec_header = html.Div([
        header_bar("HIGHBOURNE TERMINAL", "DETAIL VIEW", ts),
        html.Div([
            html.A("◄ BACK TO SCANNER", href="/",
                   style={"color": C["yellow"], "textDecoration": "none",
                          "border": "1px solid #444", "padding": "2px 6px",
                          "background": "#111", "fontSize": "10px"}),
        ], style={"marginBottom": "6px", "marginTop": "4px"}),
    ])

    # 2. Ticker header bar
    header_items = [
        html.Span(symbol, style={"color": C["white"], "fontSize": "20px", "fontWeight": "bold", "marginRight": "10px"}),
        html.Span(f" | {sector} | {industry}" if industry else f" | {sector}",
                  style={"color": C["gray"], "fontSize": "11px", "marginRight": "16px"}),
    ]
    if price_val is not None:
        header_items.append(
            html.Span(f"${price_val:.2f}", style={"color": C["white"], "fontSize": "16px", "fontWeight": "bold", "marginRight": "8px"})
        )
    if daily_chg is not None:
        header_items.append(
            html.Span(f"{daily_chg:+.2f} ({daily_chg_pct*100:+.1f}%)",
                      style={"color": chg_color, "fontSize": "12px", "marginRight": "16px"})
        )
    if volume:
        header_items.append(html.Span(f"Vol: {volume:,.0f}", style={"color": C["gray"], "fontSize": "10px", "marginRight": "10px"}))
    if mkt_cap:
        header_items.append(html.Span(f"MCap: {_fmt_large(mkt_cap)}", style={"color": C["gray"], "fontSize": "10px", "marginRight": "10px"}))
    if ytd_ret is not None:
        header_items.append(html.Span(f"YTD: {ytd_ret*100:+.1f}%",
                                      style={"color": C["green"] if ytd_ret >= 0 else C["red"], "fontSize": "10px", "marginRight": "10px"}))
    if y1_ret is not None:
        header_items.append(html.Span(f"1Y: {y1_ret*100:+.1f}%",
                                      style={"color": C["green"] if y1_ret >= 0 else C["red"], "fontSize": "10px", "marginRight": "10px"}))
    if next_er:
        header_items.append(html.Span(f"ER: {next_er}", style={"color": C["yellow"], "fontSize": "10px", "marginRight": "10px"}))

    # Composite badge
    header_items.append(
        html.Span(composite["label"],
                  style={"color": composite["color"], "fontSize": "10px", "fontWeight": "bold",
                         "border": f"1px solid {composite['color']}", "padding": "1px 6px",
                         "marginLeft": "auto"})
    )

    sec_ticker_header = html.Div(
        header_items,
        style={"display": "flex", "alignItems": "center", "flexWrap": "wrap",
               "backgroundColor": "#111", "border": f"1px solid {C['border']}",
               "padding": "8px 12px", "marginBottom": "8px", "fontFamily": FONT_FAMILY},
    )

    # 3. Description + competitors
    description_text = info.get("description", "No description available.")
    try:
        competitors = fetch_competitors(symbol, startup.universe.symbols, startup.ticker_sector)
    except Exception:
        competitors = []

    comp_links = [html.Div(
        html.A(c, href=f"/detail/{c}", style={"color": C["cyan"], "textDecoration": "none", "fontSize": "11px"}),
        style={"marginBottom": "4px"},
    ) for c in competitors]

    sec_desc = html.Div(
        style={"display": "flex", "gap": "10px", "marginBottom": "8px"},
        children=[
            html.Div(
                html.P(description_text, style={"color": C["gray"], "fontSize": "10px", "lineHeight": "1.5", "margin": 0}),
                style={**PANEL_STYLE, "flex": "1", "marginBottom": 0},
            ),
            html.Div([
                html.Div("PEERS", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                         "letterSpacing": "1px", "marginBottom": "6px"}),
                *comp_links,
            ] if comp_links else [
                html.Div("No peers", style={"color": C["gray"], "fontSize": "10px"}),
            ], style={**PANEL_STYLE, "width": "200px", "flexShrink": "0", "marginBottom": 0}),
        ],
    )

    # 4. Recent news
    news_items = info.get("news", [])[:3]
    if news_items:
        news_children = [
            html.Div("RECENT NEWS", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                           "letterSpacing": "1px", "marginBottom": "4px"}),
        ]
        for n in news_items:
            link = n.get("link", "#")
            title = n.get("title", "Untitled")
            pub = n.get("publisher", "")
            news_children.append(
                html.Div([
                    html.A(title, href=link, target="_blank",
                           style={"color": "#6699cc", "textDecoration": "none", "fontSize": "10px"}),
                    html.Span(f"  - {pub}" if pub else "", style={"color": C["gray"], "fontSize": "9px"}),
                ], style={"marginBottom": "3px"})
            )
        sec_news = html.Div(news_children, style={**PANEL_STYLE, "marginBottom": "8px"})
    else:
        sec_news = html.Div()

    # 5. Price chart + market data
    sec_price = html.Div(
        style={"display": "flex", "gap": "10px", "marginBottom": "8px"},
        children=[
            html.Div([
                dcc.RadioItems(
                    id="price-period",
                    options=[{"label": p, "value": p} for p in PRICE_PERIODS],
                    value="1Y",
                    inline=True,
                    inputStyle={"marginRight": "3px"},
                    labelStyle={"marginRight": "8px", "color": C["gray"], "fontSize": "9px", "cursor": "pointer"},
                    style={"marginBottom": "4px"},
                ),
                dcc.Graph(id="price-chart", config={"displayModeBar": False},
                          style={"height": "280px"}),
            ], style={**PANEL_STYLE, "flex": "1", "marginBottom": 0}),
            html.Div(
                _build_market_data_table(info, prices),
                style={**PANEL_STYLE, "width": "260px", "flexShrink": "0", "marginBottom": 0,
                       "overflowY": "auto", "maxHeight": "340px"},
            ),
        ],
    )

    # 6. Earnings surprise chart
    sec_earnings = html.Div([
        html.Div("EARNINGS SURPRISE", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                             "letterSpacing": "1px", "marginBottom": "4px"}),
        dcc.Graph(id="earnings-chart", figure=_build_earnings_chart(symbol),
                  config={"displayModeBar": False}, style={"height": "220px"}),
    ], style=PANEL_STYLE)

    # 7. Financial analysis placeholder
    sec_financials = html.Div([
        dcc.Tabs(
            id="fin-tabs",
            value="is",
            children=[
                dcc.Tab(label="I/S", value="is", style={"fontSize": "9px", "padding": "4px"},
                        selected_style={"fontSize": "9px", "padding": "4px", "backgroundColor": C["orange"], "color": "#000"}),
                dcc.Tab(label="B/S", value="bs", style={"fontSize": "9px", "padding": "4px"},
                        selected_style={"fontSize": "9px", "padding": "4px", "backgroundColor": C["orange"], "color": "#000"}),
                dcc.Tab(label="C/F", value="cf", style={"fontSize": "9px", "padding": "4px"},
                        selected_style={"fontSize": "9px", "padding": "4px", "backgroundColor": C["orange"], "color": "#000"}),
                dcc.Tab(label="DuPont ROE", value="dupont", style={"fontSize": "9px", "padding": "4px"},
                        selected_style={"fontSize": "9px", "padding": "4px", "backgroundColor": C["orange"], "color": "#000"}),
            ],
            style={"height": "28px"},
        ),
        html.Div("Financial data loading... (requires additional EDGAR processing)",
                 style={"color": C["gray"], "fontSize": "10px", "padding": "20px", "textAlign": "center"}),
    ], style=PANEL_STYLE)

    # 8. Stat cards row
    sma50 = compute_sma(prices, 50) if prices is not None and len(prices) > 50 else pd.Series(dtype=float)
    default_ratio = "P/E"
    rv_stats = ticker_obj.stats(default_ratio)
    rv_current = _fmt(rv_stats["current"], ".2f", suffix="x") if rv_stats else "N/A"
    rv_mean = _fmt(rv_stats["mean"], ".2f", suffix="x") if rv_stats else "N/A"
    rv_z = _fmt(rv_stats["z_score"], "+.2f") if rv_stats else "N/A"
    z_val = rv_stats["z_score"] if rv_stats else 0
    z_color = C["green"] if z_val < -0.5 else C["red"] if z_val > 0.5 else C["white"]

    macd_label = macd_sig
    rsi_lbl = rsi_label(current_rsi)
    rsi_color = C["red"] if rsi_lbl == "OVERBOUGHT" else C["green"] if rsi_lbl == "OVERSOLD" else C["white"]
    ma_color = C["green"] if ma_trend == "Above" else C["red"] if ma_trend == "Below" else C["gray"]

    sec_stat_cards = html.Div(
        style={"display": "flex", "gap": "4px", "marginBottom": "8px"},
        children=[
            stat_card("RV Ratio", default_ratio),
            stat_card("Current", rv_current),
            stat_card("Mean", rv_mean, C["orange"]),
            stat_card("Z-Score", rv_z, z_color),
            stat_card("RSI", f"{current_rsi:.0f}", rsi_color),
            stat_card("MACD", macd_label, C["green"] if macd_label == "Bull" else C["red"] if macd_label == "Bear" else C["gray"]),
            stat_card("MA Trend", ma_trend, ma_color),
        ],
    )

    # 9. RV controls + chart
    sec_rv = html.Div([
        html.Div(
            style={"display": "flex", "gap": "16px", "alignItems": "center", "marginBottom": "6px"},
            children=[
                html.Div([
                    html.Label("RATIO", style={"color": C["gray"], "fontSize": "9px", "display": "block", "marginBottom": "2px"}),
                    dcc.Dropdown(
                        id="ratio-dropdown",
                        options=[{"label": r, "value": r} for r in RATIO_NAMES],
                        value="P/E",
                        style={"width": "140px", "backgroundColor": C["panel"], "fontFamily": FONT_FAMILY, "fontSize": "10px"},
                        clearable=False,
                    ),
                ]),
                html.Div([
                    html.Label("WINDOW", style={"color": C["gray"], "fontSize": "9px", "display": "block", "marginBottom": "2px"}),
                    dcc.RadioItems(
                        id="window-toggle",
                        options=WINDOW_OPTIONS,
                        value="2Y",
                        inline=True,
                        inputStyle={"marginRight": "3px"},
                        labelStyle={"marginRight": "10px", "color": C["gray"], "fontSize": "10px", "cursor": "pointer"},
                    ),
                ]),
            ],
        ),
        dcc.Graph(id="rv-chart", config={"displayModeBar": False}, style={"height": "320px"}),
    ], style=PANEL_STYLE)

    # 10. Technical analysis panels
    sec_technicals = html.Div([
        html.Div("TECHNICAL ANALYSIS", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                              "letterSpacing": "1px", "marginBottom": "4px"}),
        dcc.Graph(id="ta-price-chart", figure=_build_ta_price_chart(prices, symbol),
                  config={"displayModeBar": False}, style={"height": "260px", "marginBottom": "4px"}),
        dcc.Graph(id="ta-rsi-chart", figure=_build_ta_rsi_chart(prices, symbol),
                  config={"displayModeBar": False}, style={"height": "180px", "marginBottom": "4px"}),
        dcc.Graph(id="ta-macd-chart", figure=_build_ta_macd_chart(prices, symbol),
                  config={"displayModeBar": False}, style={"height": "180px"}),
    ], style=PANEL_STYLE)

    # 11. Function key bar
    sec_footer = function_key_bar("F4")

    return html.Div([
        sec_header,
        sec_ticker_header,
        sec_desc,
        sec_news,
        sec_price,
        sec_earnings,
        sec_financials,
        sec_stat_cards,
        sec_rv,
        sec_technicals,
        sec_footer,
    ], style=CONTAINER_STYLE)


# ---------------------------------------------------------------------------
# Static chart builders
# ---------------------------------------------------------------------------

def _build_market_data_table(info, prices):
    """Build the right-side market data panel."""
    price_val = float(prices.iloc[-1]) if prices is not None and not prices.empty else None
    low_52, high_52, _ = compute_52w_range(prices) if prices is not None and not prices.empty else (None, None, None)

    pt_avg = info.get("PT")
    pt_upside = None
    if pt_avg and price_val:
        pt_upside = (pt_avg - price_val) / price_val

    rows = [
        ("Last", _fmt(price_val, ".2f", prefix="$")),
        ("Open", _fmt(info.get("open"), ".2f", prefix="$")),
        ("Prev Close", _fmt(info.get("prev_close"), ".2f", prefix="$")),
        ("Day High", _fmt(info.get("day_high"), ".2f", prefix="$")),
        ("Day Low", _fmt(info.get("day_low"), ".2f", prefix="$")),
        ("52wk High", _fmt(high_52, ".2f", prefix="$")),
        ("52wk Low", _fmt(low_52, ".2f", prefix="$")),
        ("Beta", _fmt(info.get("beta"), ".2f")),
        ("Mkt Cap", _fmt_large(info.get("market_cap"))),
        ("Volume", f"{info['volume']:,.0f}" if info.get("volume") else "N/A"),
        ("Avg Vol", f"{info['avg_volume_3m']:,.0f}" if info.get("avg_volume_3m") else "N/A"),
        ("Shares Out", _fmt_large(info.get("shares_outstanding"))),
        ("Inst Own%", _fmt_pct(info.get("inst_ownership"))),
        ("Short Ratio", _fmt(info.get("short_ratio"), ".1f")),
        ("Div Yield%", _fmt_pct(info.get("div_yield"))),
        ("PT Avg", _fmt(pt_avg, ".2f", prefix="$")),
        ("PT Upside", _fmt_pct(pt_upside)),
        ("Next ER", str(info.get("next_earnings", "N/A")) if info.get("next_earnings") else "N/A"),
    ]

    children = [
        html.Div("MARKET DATA", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                       "letterSpacing": "1px", "marginBottom": "6px"}),
    ]
    for label, val in rows:
        children.append(_metric_row(label, val))

    return children


def _build_earnings_chart(symbol):
    """Build earnings surprise scatter chart."""
    try:
        earnings = fetch_earnings_history(symbol)
    except Exception:
        earnings = []

    if not earnings:
        return _empty_fig("No earnings data")

    fig = go.Figure()

    quarters = [e["quarter"] for e in earnings]
    actuals = [e.get("actual") for e in earnings]
    estimates = [e.get("estimate") for e in earnings]
    surprises = [e.get("surprise_pct") for e in earnings]

    # Estimate markers (hollow)
    fig.add_trace(go.Scatter(
        x=quarters, y=estimates, mode="markers",
        marker=dict(color="rgba(0,0,0,0)", size=10, line=dict(color=C["gray"], width=2)),
        name="Estimate",
        hovertemplate="Est: %{y:.2f}<extra></extra>",
    ))

    # Actual markers (filled, green=beat, red=miss)
    colors = []
    for i, e in enumerate(earnings):
        act = e.get("actual")
        est = e.get("estimate")
        if act is not None and est is not None:
            colors.append(C["green"] if act >= est else C["red"])
        else:
            colors.append(C["gray"])

    fig.add_trace(go.Scatter(
        x=quarters, y=actuals, mode="markers",
        marker=dict(color=colors, size=10),
        name="Actual",
        hovertemplate="Actual: %{y:.2f}<extra></extra>",
    ))

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=f"{symbol} EARNINGS SURPRISE", font=dict(size=11, color=C["orange"]), x=0.01),
        xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
        yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"]), title="EPS"),
    )
    return fig


def _build_ta_price_chart(prices, symbol):
    """Price + SMA 50/200 with golden/death cross annotations (1Y)."""
    if prices is None or len(prices) < 50:
        return _empty_fig("Insufficient price data")

    p1y = prices.iloc[-252:] if len(prices) >= 252 else prices
    sma50 = compute_sma(prices, 50).reindex(p1y.index)
    sma200 = compute_sma(prices, 200).reindex(p1y.index)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=p1y.index, y=p1y.values, mode="lines",
                             line=dict(color=C["white"], width=1.5), name="Close"))
    fig.add_trace(go.Scatter(x=p1y.index, y=sma50.values, mode="lines",
                             line=dict(color=C["orange"], width=1, dash="dash"), name="SMA 50"))
    fig.add_trace(go.Scatter(x=p1y.index, y=sma200.values, mode="lines",
                             line=dict(color=C["red"], width=1, dash="dash"), name="SMA 200"))

    # Detect crossovers on full series, filter to 1Y window
    if len(prices) >= 200:
        full_sma50 = compute_sma(prices, 50)
        full_sma200 = compute_sma(prices, 200)
        golden, death = detect_crossovers(full_sma50, full_sma200)
        window_start = p1y.index[0]
        for d in golden:
            if d >= window_start:
                fig.add_annotation(x=d, y=float(prices.loc[d]) if d in prices.index else None,
                                   text="GC", showarrow=True, arrowhead=2, arrowcolor=C["green"],
                                   font=dict(size=8, color=C["green"]))
        for d in death:
            if d >= window_start:
                fig.add_annotation(x=d, y=float(prices.loc[d]) if d in prices.index else None,
                                   text="DC", showarrow=True, arrowhead=2, arrowcolor=C["red"],
                                   font=dict(size=8, color=C["red"]))

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=f"{symbol} PRICE + MOVING AVERAGES (1Y)", font=dict(size=11, color=C["orange"]), x=0.01),
        xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
        yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"]), tickprefix="$"),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=8, color=C["gray"])),
    )
    return fig


def _build_ta_rsi_chart(prices, symbol):
    """RSI chart with overbought/oversold zones (6M)."""
    if prices is None or len(prices) < 30:
        return _empty_fig("Insufficient data for RSI")

    rsi = compute_rsi(prices, 14)
    rsi_6m = rsi.iloc[-126:] if len(rsi) >= 126 else rsi
    current_val = float(rsi_6m.iloc[-1]) if not rsi_6m.empty else 50.0

    fig = go.Figure()

    # Zones
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(255,68,68,0.08)", line_width=0)
    fig.add_hrect(y0=0, y1=30, fillcolor="rgba(0,255,0,0.08)", line_width=0)

    # Reference lines
    for level in [30, 50, 70]:
        fig.add_hline(y=level, line_dash="dot", line_color=C["gray"], line_width=0.5, opacity=0.5)

    # RSI line
    fig.add_trace(go.Scatter(x=rsi_6m.index, y=rsi_6m.values, mode="lines",
                             line=dict(color=C["purple"], width=1.5), name="RSI"))

    # Current annotation
    fig.add_annotation(x=rsi_6m.index[-1], y=current_val,
                       text=f"RSI: {current_val:.0f}", showarrow=True, arrowhead=2,
                       font=dict(size=9, color=C["purple"]), arrowcolor=C["purple"])

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=f"{symbol} RSI (6M)", font=dict(size=11, color=C["orange"]), x=0.01),
        xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
        yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"]),
                   range=[0, 100]),
    )
    return fig


def _build_ta_macd_chart(prices, symbol):
    """MACD chart with histogram (6M)."""
    if prices is None or len(prices) < 35:
        return _empty_fig("Insufficient data for MACD")

    macd_l, sig_l, hist = compute_macd(prices)
    n = min(126, len(macd_l))
    macd_6m = macd_l.iloc[-n:]
    sig_6m = sig_l.iloc[-n:]
    hist_6m = hist.iloc[-n:]

    fig = go.Figure()

    # Histogram
    hist_colors = [C["green"] if v >= 0 else C["red"] for v in hist_6m.values]
    fig.add_trace(go.Bar(x=hist_6m.index, y=hist_6m.values,
                         marker_color=hist_colors, name="Histogram", opacity=0.6))

    # MACD + signal
    fig.add_trace(go.Scatter(x=macd_6m.index, y=macd_6m.values, mode="lines",
                             line=dict(color=C["cyan"], width=1.5), name="MACD"))
    fig.add_trace(go.Scatter(x=sig_6m.index, y=sig_6m.values, mode="lines",
                             line=dict(color=C["orange"], width=1, dash="dash"), name="Signal"))

    # Zero line
    fig.add_hline(y=0, line_dash="dot", line_color=C["gray"], line_width=0.5)

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=f"{symbol} MACD (6M)", font=dict(size=11, color=C["orange"]), x=0.01),
        xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
        yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=8, color=C["gray"])),
        barmode="relative",
    )
    return fig


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("price-chart", "figure"),
    Input("price-period", "value"),
    State("url", "pathname"),
)
def update_price_chart(period, pathname):
    """Update price chart based on selected time period."""
    if not pathname or "/detail/" not in pathname:
        return _empty_fig()
    symbol = pathname.split("/detail/")[-1].upper()
    prices = startup.price_cache.get(symbol)
    if prices is None or prices.empty:
        return _empty_fig("No price data")

    # Slice by period
    if period == "YTD":
        start = pd.Timestamp(datetime(datetime.now().year, 1, 1))
        p = prices[prices.index >= start]
    elif period == "MAX":
        p = prices
    else:
        n_days = PRICE_PERIODS.get(period, 252)
        p = prices.iloc[-n_days:] if len(prices) >= n_days else prices

    if p.empty:
        return _empty_fig("No data for period")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=p.index, y=p.values, mode="lines",
        line=dict(color=C["cyan"], width=1.5),
        fill="tozeroy", fillcolor="rgba(0,188,212,0.08)",
        hovertemplate="%{x|%b %d, %Y}<br>$%{y:.2f}<extra></extra>",
    ))

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=f"{symbol} ({period})", font=dict(size=11, color=C["orange"]), x=0.01),
        xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
        yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"]), tickprefix="$"),
    )
    return fig


@callback(
    Output("rv-chart", "figure"),
    Input("ratio-dropdown", "value"),
    Input("window-toggle", "value"),
    State("url", "pathname"),
)
def update_rv_chart(ratio_name, window_name, pathname):
    """Update the RV chart based on ratio and window selection."""
    if not pathname or "/detail/" not in pathname:
        return _empty_fig()
    symbol = pathname.split("/detail/")[-1].upper()

    ticker_obj = startup.universe.get(symbol)
    if ticker_obj is None:
        return _empty_fig(f"{symbol} not found")

    window_days = WINDOW_MAP.get(window_name)
    series = ticker_obj.window_series(ratio_name, window_days)
    st = ticker_obj.stats(ratio_name, window_days)

    if st is None or series.empty:
        return _empty_fig(f"No {ratio_name} data for {symbol}")

    mean = st["mean"]
    std = st["std"]
    current = st["current"]

    fig = go.Figure()

    # +/- 2 sigma band (faint dark yellow)
    fig.add_hrect(y0=mean - 2 * std, y1=mean + 2 * std,
                  fillcolor="rgba(255,215,0,0.03)", line_width=0)

    # +/- 1 sigma lines (yellow dashed)
    for y_val, label in [(mean + std, f"+1\u03c3 {mean+std:.1f}"),
                         (mean - std, f"-1\u03c3 {mean-std:.1f}")]:
        fig.add_hline(y=y_val, line_dash="dash", line_color=C["yellow"], line_width=1, opacity=0.5,
                      annotation_text=label, annotation_position="right",
                      annotation_font=dict(size=9, color=C["yellow"]))

    # +/- 2 sigma lines (dark yellow, thinner)
    for y_val, label in [(mean + 2 * std, f"+2\u03c3"),
                         (mean - 2 * std, f"-2\u03c3")]:
        fig.add_hline(y=y_val, line_dash="dot", line_color="rgba(255,215,0,0.4)", line_width=0.5,
                      annotation_text=label, annotation_position="right",
                      annotation_font=dict(size=8, color="rgba(255,215,0,0.5)"))

    # Mean line (orange dashed)
    fig.add_hline(y=mean, line_dash="dash", line_color=C["orange"], line_width=1.5, opacity=0.7,
                  annotation_text=f"\u03bc {mean:.2f}", annotation_position="right",
                  annotation_font=dict(size=10, color=C["orange"]))

    # Main ratio line (white)
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values, mode="lines",
        line=dict(color=C["white"], width=1.8),
        name=ratio_name,
        hovertemplate="%{x|%b %d, %Y}<br>" + ratio_name + ": %{y:.2f}x<extra></extra>",
    ))

    # Current value dot (cyan)
    fig.add_trace(go.Scatter(
        x=[series.index[-1]], y=[current], mode="markers",
        marker=dict(color=C["cyan"], size=9, line=dict(width=2, color="#0a0a0a")),
        name=f"Current: {current:.2f}x", hoverinfo="skip",
    ))

    # Earnings "E" markers from filing dates
    try:
        filings = get_filing_dates(symbol)
    except Exception:
        filings = []

    window_start = series.index.min()
    window_end = series.index.max()

    for f in filings:
        f_date = pd.Timestamp(f["date"])
        if f_date < window_start or f_date > window_end:
            continue
        idx = series.index.get_indexer([f_date], method="nearest")[0]
        if idx < 0 or idx >= len(series):
            continue
        y_val = series.iloc[idx]
        if pd.isna(y_val):
            continue

        # 10-K = orange (annual), 10-Q = green (quarterly)
        form = f.get("form", "10-Q")
        color = C["orange"] if form == "10-K" else C["green"]

        fig.add_trace(go.Scatter(
            x=[f_date], y=[y_val],
            mode="markers+text",
            marker=dict(color=color, size=14, symbol="square", opacity=0.85,
                        line=dict(width=1, color="#0a0a0a")),
            text=["E"],
            textposition="middle center",
            textfont=dict(size=8, color="#0a0a0a", family=FONT_FAMILY),
            hovertemplate=f"{form} filed %{{x|%b %d, %Y}}<extra></extra>",
            showlegend=False,
        ))

    # Y-axis range
    y_min = max(0, min(series.min() * 0.9, mean - 2.5 * std))
    y_max = max(series.max(), mean + 2.5 * std) * 1.05

    fig.update_layout(
        **CHART_LAYOUT,
        title=dict(text=f"{symbol}  {ratio_name}", font=dict(size=14, color=C["white"]), x=0.01, y=0.97),
        xaxis=dict(gridcolor=C["border"], gridwidth=0.5, zeroline=False, showline=False,
                   range=[series.index.min(), series.index.max()],
                   tickfont=dict(size=10, color=C["gray"])),
        yaxis=dict(gridcolor=C["border"], gridwidth=0.5, zeroline=False, showline=False,
                   range=[y_min, y_max], ticksuffix="x",
                   tickfont=dict(size=10, color=C["gray"])),
        margin=dict(l=55, r=80, t=40, b=40),
    )

    return fig
