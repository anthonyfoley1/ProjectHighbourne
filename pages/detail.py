"""Detail page -- per-ticker deep-dive view for the Highbourne Terminal."""

from datetime import datetime
from dash import html, dcc, callback, Input, Output, State
import plotly.graph_objects as go
import pandas as pd
import numpy as np

import data.startup as startup
from data.market_data import (
    fetch_ticker_info, fetch_earnings_history, fetch_competitors,
    compute_52w_range, compute_returns,
)
from data.technicals import (
    compute_rsi, compute_macd, compute_sma, detect_crossovers,
    macd_signal_label, rsi_label, ma_trend_label,
)
from data.loader import get_filing_dates
from models.ticker import compute_alert, compute_composite_score, compute_signal_label
from theme import C, FONT_FAMILY, CONTAINER_STYLE, header_bar, function_key_bar, stat_card
from components.charts import make_chart_layout, empty_fig
from utils.formatters import fmt_val, fmt_large, fmt_pct, fmt_price, fmt_date_friendly, fmt_volume

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metric_row(label, value, color=C["white"]):
    return html.Div(
        style={
            "display": "flex", "justifyContent": "space-between", "padding": "2px 0",
            "borderBottom": f"1px solid {C['border']}", "fontSize": "10px", "fontFamily": FONT_FAMILY,
        },
        children=[
            html.Span(label, style={"color": C["gray"]}),
            html.Span(value, style={"color": color, "fontWeight": "bold"}),
        ],
    )


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def layout(symbol="AAPL"):
    """Build the detail page layout. Safe to call before startup.init()."""
    ts = datetime.now().strftime("%H:%M:%S")

    # Guard: startup hasn't run yet
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
            _back_link(),
            html.Div(f"Ticker {symbol} not found in universe.",
                     style={"color": C["red"], "padding": "20px", "fontFamily": FONT_FAMILY}),
            function_key_bar("F4"),
        ], style=CONTAINER_STYLE)

    # ----- Fetch yfinance data -----
    try:
        info = fetch_ticker_info(symbol)
    except Exception:
        info = {}

    # ----- Compute key stats -----
    sector = startup.ticker_sector.get(symbol, "Unknown")
    industry = info.get("industry", "")
    price_val = float(prices.iloc[-1]) if prices is not None and not prices.empty else None
    prev_close = info.get("prev_close")
    daily_chg = None
    daily_chg_pct = None
    if price_val is not None and prev_close is not None and prev_close != 0:
        daily_chg = price_val - prev_close
        daily_chg_pct = daily_chg / prev_close

    volume = info.get("volume")
    mkt_cap = info.get("market_cap")

    # Earnings date
    next_er = fmt_date_friendly(info.get("next_earnings")) if info.get("next_earnings") else None

    # Returns
    ytd_ret, y1_ret = _compute_period_returns(prices, price_val)

    # Composite score
    best_z = _find_best_z(ticker_obj)
    rsi_series = compute_rsi(prices, 14) if prices is not None and len(prices) > 20 else pd.Series(dtype=float)
    current_rsi = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0
    macd_line, signal_line, histogram = (
        compute_macd(prices) if prices is not None and len(prices) > 30
        else (pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float))
    )
    macd_sig = macd_signal_label(macd_line, signal_line) if not macd_line.empty else "Flat"
    sma200 = compute_sma(prices, 200) if prices is not None and len(prices) > 200 else pd.Series(dtype=float)
    ma_trend = ma_trend_label(price_val or 0.0, float(sma200.iloc[-1]) if not sma200.empty else float('nan'))

    pt_upside = 0.0
    if info.get("PT") and price_val:
        pt_upside = (info["PT"] - price_val) / price_val

    composite = compute_composite_score(best_z, current_rsi, macd_sig, 0.0, pt_upside)
    chg_color = C["green"] if daily_chg and daily_chg >= 0 else C["red"]

    # ----- Build sections -----

    sec_header = html.Div([
        header_bar("HIGHBOURNE TERMINAL", "DETAIL VIEW", ts),
        html.Div([_back_link()], style={"marginBottom": "6px", "marginTop": "4px"}),
    ])

    sec_ticker_header = _build_ticker_header(
        symbol, sector, industry, price_val, daily_chg, daily_chg_pct,
        chg_color, volume, mkt_cap, ytd_ret, y1_ret, next_er, composite,
    )

    sec_desc = _build_description(info, symbol)
    sec_news = _build_news(info)
    sec_price = _build_price_section(info, prices)
    sec_earnings = _build_earnings_section(symbol)
    sec_financials = _build_financials_placeholder()

    # Stat cards
    sma50 = compute_sma(prices, 50) if prices is not None and len(prices) > 50 else pd.Series(dtype=float)
    rv_stats = ticker_obj.stats("P/E")
    rv_current = fmt_val(rv_stats["current"], ".2f", suffix="x") if rv_stats else "N/A"
    rv_mean = fmt_val(rv_stats["mean"], ".2f", suffix="x") if rv_stats else "N/A"
    rv_z = fmt_val(rv_stats["z_score"], "+.2f") if rv_stats else "N/A"
    z_val = rv_stats["z_score"] if rv_stats else 0
    z_color = C["green"] if z_val < -0.5 else C["red"] if z_val > 0.5 else C["white"]
    rsi_lbl = rsi_label(current_rsi)
    rsi_color = C["red"] if rsi_lbl == "OVERBOUGHT" else C["green"] if rsi_lbl == "OVERSOLD" else C["white"]
    ma_color = C["green"] if ma_trend == "Above" else C["red"] if ma_trend == "Below" else C["gray"]

    sec_stat_cards = html.Div(
        style={"display": "flex", "gap": "4px", "marginBottom": "8px"},
        children=[
            stat_card("RV Ratio", "P/E"),
            stat_card("Current", rv_current),
            stat_card("Mean", rv_mean, C["orange"]),
            stat_card("Z-Score", rv_z, z_color),
            stat_card("RSI", f"{current_rsi:.0f}", rsi_color),
            stat_card("MACD", macd_sig,
                      C["green"] if macd_sig == "Bull" else C["red"] if macd_sig == "Bear" else C["gray"]),
            stat_card("MA Trend", ma_trend, ma_color),
        ],
    )

    sec_rv = _build_rv_controls()
    sec_technicals = _build_technicals_section(prices, symbol)

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
        function_key_bar("F4"),
    ], style=CONTAINER_STYLE)


# ---------------------------------------------------------------------------
# Layout sub-builders
# ---------------------------------------------------------------------------

def _back_link():
    return html.A("\u25c4 BACK TO SCANNER", href="/",
                  style={"color": C["yellow"], "textDecoration": "none",
                         "border": "1px solid #444", "padding": "2px 6px",
                         "background": "#111", "fontSize": "10px"})


def _compute_period_returns(prices, price_val):
    """Compute YTD and 1-year returns."""
    ytd_ret = y1_ret = None
    if prices is not None and len(prices) > 252:
        ytd_start = prices.index[prices.index >= pd.Timestamp(datetime(datetime.now().year, 1, 1))]
        if len(ytd_start) > 0:
            ytd_ret = (price_val - float(prices.loc[ytd_start[0]])) / float(prices.loc[ytd_start[0]])
        y1_ret = (price_val - float(prices.iloc[-252])) / float(prices.iloc[-252])
    return ytd_ret, y1_ret


def _find_best_z(ticker_obj):
    """Find the most extreme z-score across all standard ratios."""
    best_z = 0.0
    for rn in RATIO_NAMES:
        s = ticker_obj.stats(rn)
        if s and abs(s["z_score"]) > abs(best_z):
            best_z = s["z_score"]
    return best_z


def _build_ticker_header(symbol, sector, industry, price_val, daily_chg,
                          daily_chg_pct, chg_color, volume, mkt_cap,
                          ytd_ret, y1_ret, next_er, composite):
    """Top bar with symbol, price, change, and composite badge."""
    items = [
        html.Span(symbol, style={"color": C["white"], "fontSize": "20px", "fontWeight": "bold", "marginRight": "10px"}),
        html.Span(f" | {sector} | {industry}" if industry else f" | {sector}",
                  style={"color": C["gray"], "fontSize": "11px", "marginRight": "16px"}),
    ]
    if price_val is not None:
        items.append(html.Span(fmt_price(price_val), style={
            "color": C["white"], "fontSize": "16px", "fontWeight": "bold", "marginRight": "8px",
        }))
    if daily_chg is not None:
        items.append(html.Span(
            f"{daily_chg:+.2f} ({daily_chg_pct * 100:+.1f}%)",
            style={"color": chg_color, "fontSize": "12px", "marginRight": "16px"},
        ))
    if volume:
        items.append(html.Span(f"Vol: {fmt_volume(volume)}", style={
            "color": C["gray"], "fontSize": "10px", "marginRight": "10px",
        }))
    if mkt_cap:
        items.append(html.Span(f"MCap: {fmt_large(mkt_cap)}", style={
            "color": C["gray"], "fontSize": "10px", "marginRight": "10px",
        }))
    if ytd_ret is not None:
        items.append(html.Span(f"YTD: {fmt_pct(ytd_ret)}", style={
            "color": C["green"] if ytd_ret >= 0 else C["red"], "fontSize": "10px", "marginRight": "10px",
        }))
    if y1_ret is not None:
        items.append(html.Span(f"1Y: {fmt_pct(y1_ret)}", style={
            "color": C["green"] if y1_ret >= 0 else C["red"], "fontSize": "10px", "marginRight": "10px",
        }))
    if next_er:
        items.append(html.Span(f"ER: {next_er}", style={
            "color": C["yellow"], "fontSize": "10px", "marginRight": "10px",
        }))
    items.append(html.Span(composite["label"], style={
        "color": composite["color"], "fontSize": "10px", "fontWeight": "bold",
        "border": f"1px solid {composite['color']}", "padding": "1px 6px", "marginLeft": "auto",
    }))

    return html.Div(items, style={
        "display": "flex", "alignItems": "center", "flexWrap": "wrap",
        "backgroundColor": "#111", "border": f"1px solid {C['border']}",
        "padding": "8px 12px", "marginBottom": "8px", "fontFamily": FONT_FAMILY,
    })


def _build_description(info, symbol):
    """Description text + competitors panel."""
    description_text = info.get("description", "No description available.")
    try:
        competitors = fetch_competitors(symbol, startup.universe.symbols, startup.ticker_sector)
    except Exception:
        competitors = []

    comp_links = [html.Div(
        html.A(c, href=f"/detail/{c}", style={"color": C["cyan"], "textDecoration": "none", "fontSize": "11px"}),
        style={"marginBottom": "4px"},
    ) for c in competitors]

    peers_content = ([
        html.Div("PEERS", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                  "letterSpacing": "1px", "marginBottom": "6px"}),
        *comp_links,
    ] if comp_links else [
        html.Div("No peers", style={"color": C["gray"], "fontSize": "10px"}),
    ])

    return html.Div(
        style={"display": "flex", "gap": "10px", "marginBottom": "8px"},
        children=[
            html.Div(
                html.P(description_text, style={"color": C["gray"], "fontSize": "10px", "lineHeight": "1.5", "margin": 0}),
                style={**PANEL_STYLE, "flex": "1", "marginBottom": 0},
            ),
            html.Div(peers_content, style={**PANEL_STYLE, "width": "200px", "flexShrink": "0", "marginBottom": 0}),
        ],
    )


def _build_news(info):
    """Recent news section."""
    news_items = info.get("news", [])[:3]
    if not news_items:
        return html.Div()

    children = [
        html.Div("RECENT NEWS", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                        "letterSpacing": "1px", "marginBottom": "4px"}),
    ]
    for n in news_items:
        link = n.get("link", "#")
        title = n.get("title", "Untitled")
        pub = n.get("publisher", "")
        children.append(html.Div([
            html.A(title, href=link, target="_blank",
                   style={"color": "#6699cc", "textDecoration": "none", "fontSize": "10px"}),
            html.Span(f"  - {pub}" if pub else "", style={"color": C["gray"], "fontSize": "9px"}),
        ], style={"marginBottom": "3px"}))
    return html.Div(children, style={**PANEL_STYLE, "marginBottom": "8px"})


def _build_price_section(info, prices):
    """Price chart + market data table side by side."""
    return html.Div(
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
                dcc.Graph(id="price-chart", config={"displayModeBar": False}, style={"height": "280px"}),
            ], style={**PANEL_STYLE, "flex": "1", "marginBottom": 0}),
            html.Div(
                _build_market_data_table(info, prices),
                style={**PANEL_STYLE, "width": "260px", "flexShrink": "0", "marginBottom": 0,
                       "overflowY": "auto", "maxHeight": "340px"},
            ),
        ],
    )


def _build_market_data_table(info, prices):
    """Right-side market data panel."""
    price_val = float(prices.iloc[-1]) if prices is not None and not prices.empty else None
    low_52, high_52, _ = compute_52w_range(prices) if prices is not None and not prices.empty else (None, None, None)

    pt_avg = info.get("PT")
    pt_upside = None
    if pt_avg and price_val:
        pt_upside = (pt_avg - price_val) / price_val

    next_er = fmt_date_friendly(info.get("next_earnings")) if info.get("next_earnings") else "N/A"

    rows = [
        ("Last", fmt_price(price_val)),
        ("Open", fmt_price(info.get("open"))),
        ("Prev Close", fmt_price(info.get("prev_close"))),
        ("Day High", fmt_price(info.get("day_high"))),
        ("Day Low", fmt_price(info.get("day_low"))),
        ("52wk High", fmt_price(high_52)),
        ("52wk Low", fmt_price(low_52)),
        ("Beta", fmt_val(info.get("beta"), ".2f")),
        ("Mkt Cap", fmt_large(info.get("market_cap"))),
        ("Volume", fmt_volume(info.get("volume"))),
        ("Avg Vol", fmt_volume(info.get("avg_volume_3m"))),
        ("Shares Out", fmt_large(info.get("shares_outstanding"))),
        ("Inst Own%", fmt_pct(info.get("inst_ownership"))),
        ("Short Ratio", fmt_val(info.get("short_ratio"), ".1f")),
        ("Div Yield%", fmt_pct(info.get("div_yield"))),
        ("PT Avg", fmt_price(pt_avg)),
        ("PT Upside", fmt_pct(pt_upside)),
        ("Next ER", next_er),
    ]

    children = [
        html.Div("MARKET DATA", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                        "letterSpacing": "1px", "marginBottom": "6px"}),
    ]
    for label, val in rows:
        children.append(_metric_row(label, val))
    return children


def _build_earnings_section(symbol):
    """Earnings surprise chart section."""
    return html.Div([
        html.Div("EARNINGS SURPRISE", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                              "letterSpacing": "1px", "marginBottom": "4px"}),
        dcc.Graph(id="earnings-chart", figure=_build_earnings_chart(symbol),
                  config={"displayModeBar": False}, style={"height": "220px"}),
    ], style=PANEL_STYLE)


def _build_financials_placeholder():
    """Placeholder for financials tabs."""
    tab_style = {"fontSize": "9px", "padding": "4px"}
    tab_selected = {"fontSize": "9px", "padding": "4px", "backgroundColor": C["orange"], "color": "#000"}
    return html.Div([
        dcc.Tabs(
            id="fin-tabs", value="is",
            children=[
                dcc.Tab(label="I/S", value="is", style=tab_style, selected_style=tab_selected),
                dcc.Tab(label="B/S", value="bs", style=tab_style, selected_style=tab_selected),
                dcc.Tab(label="C/F", value="cf", style=tab_style, selected_style=tab_selected),
                dcc.Tab(label="DuPont ROE", value="dupont", style=tab_style, selected_style=tab_selected),
            ],
            style={"height": "28px"},
        ),
        html.Div("Financial data loading... (requires additional EDGAR processing)",
                 style={"color": C["gray"], "fontSize": "10px", "padding": "20px", "textAlign": "center"}),
    ], style=PANEL_STYLE)


def _build_rv_controls():
    """Ratio dropdown + window toggle + RV chart placeholder."""
    return html.Div([
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


def _build_technicals_section(prices, symbol):
    """Technical analysis charts: price+MA, RSI, MACD."""
    return html.Div([
        html.Div("TECHNICAL ANALYSIS", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                               "letterSpacing": "1px", "marginBottom": "4px"}),
        dcc.Graph(id="ta-price-chart", figure=_build_ta_price_chart(prices, symbol),
                  config={"displayModeBar": False}, style={"height": "260px", "marginBottom": "4px"}),
        dcc.Graph(id="ta-rsi-chart", figure=_build_ta_rsi_chart(prices, symbol),
                  config={"displayModeBar": False}, style={"height": "180px", "marginBottom": "4px"}),
        dcc.Graph(id="ta-macd-chart", figure=_build_ta_macd_chart(prices, symbol),
                  config={"displayModeBar": False}, style={"height": "180px"}),
    ], style=PANEL_STYLE)


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def _build_earnings_chart(symbol):
    """Earnings surprise scatter chart."""
    try:
        earnings = fetch_earnings_history(symbol)
    except Exception:
        earnings = []
    if not earnings:
        return empty_fig("No earnings data")

    fig = go.Figure()
    quarters = [e["quarter"] for e in earnings]
    actuals = [e.get("actual") for e in earnings]
    estimates = [e.get("estimate") for e in earnings]

    # Estimate markers (hollow)
    fig.add_trace(go.Scatter(
        x=quarters, y=estimates, mode="markers",
        marker=dict(color="rgba(0,0,0,0)", size=10, line=dict(color=C["gray"], width=2)),
        name="Estimate",
        hovertemplate="Est: %{y:.2f}<extra></extra>",
    ))

    # Actual markers with beat/miss coloring
    prices = startup.price_cache.get(symbol)
    colors = []
    hover_texts = []
    for e in earnings:
        act = e.get("actual")
        est = e.get("estimate")
        surp = e.get("surprise_pct")
        beat = act is not None and est is not None and act >= est
        colors.append(C["green"] if beat else C["red"] if act is not None else C["gray"])

        # 3-day price reaction
        price_reaction = ""
        q_date = e.get("quarter")
        if q_date and prices is not None and len(prices) > 5:
            try:
                er_date = pd.Timestamp(q_date)
                mask = prices.index >= er_date
                if mask.any():
                    idx_start = prices.index[mask][0]
                    pos = prices.index.get_loc(idx_start)
                    if pos + 3 < len(prices):
                        p_start = float(prices.iloc[pos])
                        p_end = float(prices.iloc[pos + 3])
                        ret_3d = (p_end - p_start) / p_start * 100
                        ret_color = "green" if ret_3d >= 0 else "red"
                        price_reaction = f"<br>3-Day Price: <span style='color:{ret_color}'>{ret_3d:+.1f}%</span>"
            except Exception:
                pass

        surp_str = f"<br>Surprise: {surp:+.1f}%" if surp is not None else ""
        act_str = f"Actual: {act:.2f}" if act is not None else "N/A"
        est_str = f"<br>Estimate: {est:.2f}" if est is not None else ""
        hover_texts.append(act_str + est_str + surp_str + price_reaction)

    fig.add_trace(go.Scatter(
        x=quarters, y=actuals, mode="markers",
        marker=dict(color=colors, size=12),
        name="Actual",
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover_texts,
    ))

    fig.update_layout(
        **make_chart_layout(
            title=dict(text=f"{symbol} EARNINGS SURPRISE", font=dict(size=11, color=C["orange"]), x=0.01),
            xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
            yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"]), title="EPS"),
        ),
    )
    return fig


def _build_ta_price_chart(prices, symbol):
    """Price + SMA 50/200 with golden/death cross annotations (1Y)."""
    if prices is None or len(prices) < 50:
        return empty_fig("Insufficient price data")

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
        **make_chart_layout(
            title=dict(text=f"{symbol} PRICE + MOVING AVERAGES (1Y)", font=dict(size=11, color=C["orange"]), x=0.01),
            xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
            yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"]), tickprefix="$"),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                        font=dict(size=8, color=C["gray"])),
        ),
    )
    return fig


def _build_ta_rsi_chart(prices, symbol):
    """RSI chart with overbought/oversold zones (6M)."""
    if prices is None or len(prices) < 30:
        return empty_fig("Insufficient data for RSI")

    rsi = compute_rsi(prices, 14)
    rsi_6m = rsi.iloc[-126:] if len(rsi) >= 126 else rsi
    current_val = float(rsi_6m.iloc[-1]) if not rsi_6m.empty else 50.0

    fig = go.Figure()
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(255,68,68,0.08)", line_width=0)
    fig.add_hrect(y0=0, y1=30, fillcolor="rgba(0,255,0,0.08)", line_width=0)
    for level in [30, 50, 70]:
        fig.add_hline(y=level, line_dash="dot", line_color=C["gray"], line_width=0.5, opacity=0.5)
    fig.add_trace(go.Scatter(x=rsi_6m.index, y=rsi_6m.values, mode="lines",
                             line=dict(color=C["purple"], width=1.5), name="RSI"))
    fig.add_annotation(x=rsi_6m.index[-1], y=current_val,
                       text=f"RSI: {current_val:.0f}", showarrow=True, arrowhead=2,
                       font=dict(size=9, color=C["purple"]), arrowcolor=C["purple"])

    fig.update_layout(
        **make_chart_layout(
            title=dict(text=f"{symbol} RSI (6M)", font=dict(size=11, color=C["orange"]), x=0.01),
            xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
            yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"]), range=[0, 100]),
        ),
    )
    return fig


def _build_ta_macd_chart(prices, symbol):
    """MACD chart with histogram (6M)."""
    if prices is None or len(prices) < 35:
        return empty_fig("Insufficient data for MACD")

    macd_l, sig_l, hist = compute_macd(prices)
    n = min(126, len(macd_l))
    macd_6m = macd_l.iloc[-n:]
    sig_6m = sig_l.iloc[-n:]
    hist_6m = hist.iloc[-n:]

    fig = go.Figure()
    hist_colors = [C["green"] if v >= 0 else C["red"] for v in hist_6m.values]
    fig.add_trace(go.Bar(x=hist_6m.index, y=hist_6m.values,
                         marker_color=hist_colors, name="Histogram", opacity=0.6))
    fig.add_trace(go.Scatter(x=macd_6m.index, y=macd_6m.values, mode="lines",
                             line=dict(color=C["cyan"], width=1.5), name="MACD"))
    fig.add_trace(go.Scatter(x=sig_6m.index, y=sig_6m.values, mode="lines",
                             line=dict(color=C["orange"], width=1, dash="dash"), name="Signal"))
    fig.add_hline(y=0, line_dash="dot", line_color=C["gray"], line_width=0.5)

    fig.update_layout(
        **make_chart_layout(
            title=dict(text=f"{symbol} MACD (6M)", font=dict(size=11, color=C["orange"]), x=0.01),
            xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
            yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                        font=dict(size=8, color=C["gray"])),
            barmode="relative",
        ),
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
        return empty_fig()
    symbol = pathname.split("/detail/")[-1].upper()
    prices = startup.price_cache.get(symbol)
    if prices is None or prices.empty:
        return empty_fig("No price data")

    if period == "YTD":
        start = pd.Timestamp(datetime(datetime.now().year, 1, 1))
        p = prices[prices.index >= start]
    elif period == "MAX":
        p = prices
    else:
        n_days = PRICE_PERIODS.get(period, 252)
        p = prices.iloc[-n_days:] if len(prices) >= n_days else prices

    if p.empty:
        return empty_fig("No data for period")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=p.index, y=p.values, mode="lines",
        line=dict(color=C["cyan"], width=1.5),
        fill="tozeroy", fillcolor="rgba(0,188,212,0.08)",
        hovertemplate="%{x|%b %d, %Y}<br>$%{y:.2f}<extra></extra>",
    ))

    fig.update_layout(
        **make_chart_layout(
            title=dict(text=f"{symbol} ({period})", font=dict(size=11, color=C["orange"]), x=0.01),
            xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
            yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"]), tickprefix="$"),
        ),
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
        return empty_fig()
    symbol = pathname.split("/detail/")[-1].upper()

    ticker_obj = startup.universe.get(symbol)
    if ticker_obj is None:
        return empty_fig(f"{symbol} not found")

    window_days = WINDOW_MAP.get(window_name)
    series = ticker_obj.window_series(ratio_name, window_days)
    st = ticker_obj.stats(ratio_name, window_days)

    if st is None or series.empty:
        return empty_fig(f"No {ratio_name} data for {symbol}")

    mean = st["mean"]
    std = st["std"]
    current = st["current"]

    fig = go.Figure()

    # +/- 2 sigma band
    fig.add_hrect(y0=mean - 2 * std, y1=mean + 2 * std,
                  fillcolor="rgba(255,215,0,0.03)", line_width=0)

    # +/- 1 sigma lines
    for y_val, label in [(mean + std, f"+1\u03c3 {mean + std:.1f}"),
                         (mean - std, f"-1\u03c3 {mean - std:.1f}")]:
        fig.add_hline(y=y_val, line_dash="dash", line_color=C["yellow"], line_width=1, opacity=0.5,
                      annotation_text=label, annotation_position="right",
                      annotation_font=dict(size=9, color=C["yellow"]))

    # +/- 2 sigma lines
    for y_val, label in [(mean + 2 * std, "+2\u03c3"),
                         (mean - 2 * std, "-2\u03c3")]:
        fig.add_hline(y=y_val, line_dash="dot", line_color="rgba(255,215,0,0.4)", line_width=0.5,
                      annotation_text=label, annotation_position="right",
                      annotation_font=dict(size=8, color="rgba(255,215,0,0.5)"))

    # Mean line
    fig.add_hline(y=mean, line_dash="dash", line_color=C["orange"], line_width=1.5, opacity=0.7,
                  annotation_text=f"\u03bc {mean:.2f}", annotation_position="right",
                  annotation_font=dict(size=10, color=C["orange"]))

    # Main ratio line
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values, mode="lines",
        line=dict(color=C["white"], width=1.8), name=ratio_name,
        hovertemplate="%{x|%b %d, %Y}<br>" + ratio_name + ": %{y:.2f}x<extra></extra>",
    ))

    # Current value dot
    fig.add_trace(go.Scatter(
        x=[series.index[-1]], y=[current], mode="markers",
        marker=dict(color=C["cyan"], size=9, line=dict(width=2, color="#0a0a0a")),
        name=f"Current: {current:.2f}x", hoverinfo="skip",
    ))

    # Earnings "E" markers
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
        **make_chart_layout(
            title=dict(text=f"{symbol}  {ratio_name}", font=dict(size=14, color=C["white"]), x=0.01, y=0.97),
            xaxis=dict(gridcolor=C["border"], gridwidth=0.5, zeroline=False, showline=False,
                       range=[series.index.min(), series.index.max()],
                       tickfont=dict(size=10, color=C["gray"])),
            yaxis=dict(gridcolor=C["border"], gridwidth=0.5, zeroline=False, showline=False,
                       range=[y_min, y_max], ticksuffix="x",
                       tickfont=dict(size=10, color=C["gray"])),
            margin=dict(l=55, r=80, t=40, b=40),
        ),
    )
    return fig
