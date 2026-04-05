"""Detail page -- per-ticker deep-dive view for the Highbourne Terminal."""

from datetime import datetime
import dash
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
    compute_bollinger_bands, OVERLAY_PARAMS,
)
from data.loader import get_filing_dates
from models.ticker import compute_alert, compute_composite_score, compute_signal_label
from components.barometer import compute_barometer, build_barometer
from theme import C, FONT_FAMILY, CONTAINER_STYLE, header_bar, function_key_bar, stat_card
from components.charts import make_chart_layout, empty_fig
from utils.formatters import fmt_val, fmt_large, fmt_pct, fmt_price, fmt_date_friendly, fmt_volume
from data.defeatbeta import (
    get_earnings_transcripts, get_sec_filings, get_defeatbeta_news,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
RATIO_NAMES = ["P/E", "P/S", "P/B", "EV/EBITDA"]
WINDOW_MAP = {"5Y": 5 * 365, "2Y": 2 * 365, "6M": 182}
WINDOW_OPTIONS = [{"label": w, "value": w} for w in WINDOW_MAP]

PRICE_PERIODS = {
    "1D": 1, "5D": 5, "1M": 21, "3M": 63, "6M": 126,
    "YTD": None, "1Y": 252, "2Y": 504, "5Y": 1260, "MAX": None,
}

OVERLAY_OPTIONS = [
    {"label": "Bollinger Bands", "value": "Bollinger Bands"},
    {"label": "Moving Averages", "value": "Moving Averages"},
    {"label": "MA Crossovers", "value": "MA Crossovers"},
    {"label": "Volume", "value": "Volume"},
]

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
    prices = startup.get_prices(symbol, full=True)

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

    composite_old = compute_composite_score(best_z, current_rsi, macd_sig, 0.0, pt_upside)
    barometer_data = compute_barometer(symbol, info=info)
    composite = {"label": barometer_data["label"], "color": barometer_data["color"], "score": barometer_data["composite"]}
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

    sec_desc = _build_description(info, symbol, barometer_data)
    sec_news = _build_news(info, symbol=symbol)
    sec_price = _build_price_section(info, prices)
    sec_earnings = _build_earnings_section(symbol)
    sec_financials = None

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

    sec_rv = _build_rv_controls(symbol)
    sec_technicals = _build_technicals_section(prices, symbol)

    return html.Div([
        sec_header,
        sec_ticker_header,
        sec_desc,
        sec_news,
        sec_price,
        sec_earnings,
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
        ytd_ts = pd.Timestamp(datetime(datetime.now().year, 1, 1))
        if prices.index.tz is not None:
            ytd_ts = ytd_ts.tz_localize(prices.index.tz)
        ytd_start = prices.index[prices.index >= ytd_ts]
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
        items.append(html.Span(f"Mkt Cap: {fmt_large(mkt_cap)}", style={
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


def _build_description(info, symbol, barometer_data=None):
    """Description text with company details + peers ratio comparison panel + barometer."""
    # Break long description into paragraphs (split on ". " after ~200 chars)
    raw_desc = info.get("description", "No description available.") or "No description available."
    sentences = raw_desc.replace(". ", ".|").split("|")
    paragraphs = []
    current = ""
    for s in sentences:
        current += s
        if len(current) > 200:
            paragraphs.append(current.strip())
            current = ""
    if current.strip():
        paragraphs.append(current.strip())
    description_text = paragraphs

    # Company details from yfinance info
    details = []
    website = info.get("website")
    if website:
        details.append(html.Div([
            html.Span("Website: ", style={"color": C["dim"], "fontSize": "9px"}),
            html.A(website, href=website, target="_blank", style={"color": C["cyan"], "fontSize": "9px"}),
        ]))

    hq_city = info.get("city", "")
    hq_state = info.get("state", "")
    hq_country = info.get("country", "")
    hq_parts = [p for p in [hq_city, hq_state, hq_country] if p]
    if hq_parts:
        details.append(html.Div([
            html.Span("HQ: ", style={"color": C["dim"], "fontSize": "9px"}),
            html.Span(", ".join(hq_parts), style={"color": C["gray"], "fontSize": "9px"}),
        ]))

    employees = info.get("fullTimeEmployees")
    if employees:
        details.append(html.Div([
            html.Span("Employees: ", style={"color": C["dim"], "fontSize": "9px"}),
            html.Span(f"{employees:,}", style={"color": C["gray"], "fontSize": "9px"}),
        ]))

    # C-suite officers from yfinance
    officers = info.get("companyOfficers", [])
    if officers:
        exec_items = []
        for off in officers[:5]:
            name = off.get("name", "")
            title = off.get("title", "")
            if name and title:
                exec_items.append(html.Div([
                    html.Span(name, style={"color": C["white"], "fontSize": "9px", "fontWeight": "bold"}),
                    html.Span(f" — {title}", style={"color": C["dim"], "fontSize": "9px"}),
                ]))
        if exec_items:
            details.append(html.Div([
                html.Span("Leadership: ", style={"color": C["dim"], "fontSize": "9px"}),
            ], style={"marginTop": "4px"}))
            details.extend(exec_items)

    try:
        competitors = fetch_competitors(symbol, startup.universe.symbols, startup.ticker_sector, info=info)
    except Exception:
        competitors = []

    peers_content = _build_peers_ratios(symbol, competitors)

    # Build barometer visual if data available
    barometer_el = build_barometer(barometer_data) if barometer_data else None

    return html.Div(
        style={"display": "flex", "gap": "10px", "marginBottom": "8px"},
        children=[
            html.Div([
                *[html.P(p, style={"color": C["gray"], "fontSize": "10px", "lineHeight": "1.5", "margin": "0 0 6px 0"}) for p in description_text],
                html.Div(details, style={"marginTop": "6px", "borderTop": f"1px solid {C['border']}", "paddingTop": "6px"}) if details else None,
            ], style={**PANEL_STYLE, "flex": "1", "marginBottom": 0}),
            html.Div(
                (peers_content if isinstance(peers_content, list) else [peers_content])
                + ([html.Div(barometer_el, style={"marginTop": "10px", "borderTop": f"1px solid {C['border']}", "paddingTop": "10px"})] if barometer_el else []),
                style={**PANEL_STYLE, "width": "340px", "flexShrink": "0", "marginBottom": 0, "overflowX": "auto"},
            ),
        ],
    )


def _build_peers_ratios(symbol, competitors):
    """Build peer comparison table showing ratios with premium/discount %."""
    ratio_names = ["P/E", "P/S", "P/B", "EV/EBITDA"]

    # Get current ratios for this ticker
    ticker_obj = startup.universe.get(symbol)
    my_ratios = {}
    for r in ratio_names:
        if ticker_obj:
            s = ticker_obj.get_ratio(r)
            my_ratios[r] = float(s.iloc[-1]) if len(s) > 0 else None
        else:
            my_ratios[r] = None

    # Get ratios for peers
    peer_data = {}
    for comp in competitors[:5]:
        comp_obj = startup.universe.get(comp)
        if comp_obj:
            peer_data[comp] = {}
            for r in ratio_names:
                s = comp_obj.get_ratio(r)
                peer_data[comp][r] = float(s.iloc[-1]) if len(s) > 0 else None

    # Compute peer average
    peer_avg = {}
    for r in ratio_names:
        vals = [peer_data[c][r] for c in peer_data if peer_data[c].get(r) is not None]
        peer_avg[r] = sum(vals) / len(vals) if vals else None

    # Header row
    hdr_style = {"color": C["orange"], "fontSize": "8px", "fontWeight": "bold", "padding": "3px 5px",
                 "textAlign": "right", "borderBottom": f"1px solid {C['orange']}"}
    header = html.Tr([
        html.Th("", style={**hdr_style, "textAlign": "left"}),
        *[html.Th(r, style=hdr_style) for r in ratio_names],
    ])

    cell = {"padding": "3px 5px", "fontSize": "9px", "borderBottom": "1px solid #111", "textAlign": "right"}
    rows = []

    # Company row (highlighted)
    my_cells = [html.Td(symbol, style={**cell, "color": C["white"], "fontWeight": "bold", "textAlign": "left"})]
    for r in ratio_names:
        v = my_ratios.get(r)
        my_cells.append(html.Td(f"{v:.1f}x" if v else "—", style={**cell, "color": C["cyan"], "fontWeight": "bold"}))
    rows.append(html.Tr(my_cells, style={"background": "rgba(0,188,212,0.06)"}))

    # Peer rows
    for comp in competitors[:5]:
        if comp not in peer_data:
            continue
        peer_cells = [html.Td(
            html.A(comp, href=f"/detail/{comp}", style={"color": C["white"], "textDecoration": "none"}),
            style={**cell, "textAlign": "left"},
        )]
        for r in ratio_names:
            v = peer_data[comp].get(r)
            peer_cells.append(html.Td(f"{v:.1f}x" if v else "—", style={**cell, "color": C["gray"]}))
        rows.append(html.Tr(peer_cells))

    # Peer average row
    avg_cells = [html.Td("Peer Avg", style={**cell, "color": C["orange"], "fontWeight": "bold", "textAlign": "left",
                                             "borderTop": f"1px solid {C['border']}"})]
    for r in ratio_names:
        v = peer_avg.get(r)
        avg_cells.append(html.Td(f"{v:.1f}x" if v else "—",
                                 style={**cell, "color": C["orange"], "fontWeight": "bold",
                                        "borderTop": f"1px solid {C['border']}"}))
    rows.append(html.Tr(avg_cells))

    # Premium/Discount row
    disc_cells = [html.Td("vs Peers", style={**cell, "color": C["dim"], "textAlign": "left", "fontSize": "8px"})]
    for r in ratio_names:
        my_v = my_ratios.get(r)
        avg_v = peer_avg.get(r)
        if my_v and avg_v and avg_v != 0:
            pct = (my_v - avg_v) / avg_v * 100
            color = C["red"] if pct > 0 else C["green"]  # premium = red (expensive), discount = green (cheap)
            label = f"+{pct:.0f}%" if pct > 0 else f"{pct:.0f}%"
            disc_cells.append(html.Td(label, style={**cell, "color": color, "fontWeight": "bold", "fontSize": "9px"}))
        else:
            disc_cells.append(html.Td("—", style={**cell, "color": C["dim"]}))
    rows.append(html.Tr(disc_cells))

    return [
        html.Div("PEER COMPARISON", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                            "letterSpacing": "1px", "marginBottom": "6px"}),
        html.Table([html.Thead(header), html.Tbody(rows)],
                   style={"width": "100%", "borderCollapse": "collapse"}),
    ]


def _build_news(info, symbol=None):
    """Recent news, SEC filings, and earnings transcripts section."""
    from data.news import fetch_company_news

    sub_label = {
        "color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
        "letterSpacing": "1px", "marginBottom": "4px", "marginTop": "10px",
    }
    section_children = [
        html.Div("RECENT NEWS & FILINGS", style={
            "color": C["orange"], "fontSize": "10px", "fontWeight": "bold",
            "letterSpacing": "1px", "marginBottom": "6px",
            "borderBottom": f"2px solid {C['orange']}", "paddingBottom": "4px",
        }),
    ]

    has_content = False

    # ------------------------------------------------------------------
    # 1) NEWS  (Finnhub -> DefeatBeta -> yfinance fallback)
    # ------------------------------------------------------------------
    news_items = []
    if symbol:
        # Finnhub first
        try:
            articles = fetch_company_news(symbol, days_back=5, limit=5)
            for a in articles:
                news_items.append({
                    "title": a["headline"], "link": a["url"],
                    "publisher": a["source"], "age": a["age"],
                })
        except Exception:
            pass

        # DefeatBeta news if Finnhub returned nothing
        if not news_items:
            try:
                db_news = get_defeatbeta_news(symbol, limit=5)
                for n in db_news:
                    news_items.append({
                        "title": n.get("title", ""),
                        "link": n.get("link", "#"),
                        "publisher": n.get("publisher", ""),
                        "age": n.get("report_date", ""),
                    })
            except Exception:
                pass

    # yfinance fallback
    if not news_items:
        for n in (info.get("news") or [])[:3]:
            news_items.append({
                "title": n.get("title", ""), "link": n.get("link", "#"),
                "publisher": n.get("publisher", ""), "age": "",
            })

    if news_items:
        has_content = True
        section_children.append(html.Div("NEWS", style=sub_label))
        for n in news_items:
            age = n.get("age", "")
            section_children.append(html.Div([
                html.A(n["title"], href=n["link"], target="_blank",
                       style={"color": "#6699cc", "textDecoration": "none", "fontSize": "10px"}),
                html.Span(f"  {n['publisher']}", style={"color": C["gray"], "fontSize": "9px"}),
                html.Span(f"  {age}", style={"color": "#555", "fontSize": "9px"}) if age else None,
            ], style={"marginBottom": "3px", "borderBottom": f"1px solid {C['border']}", "paddingBottom": "3px"}))

    # ------------------------------------------------------------------
    # 2) SEC FILINGS
    # ------------------------------------------------------------------
    if symbol:
        try:
            filings = get_sec_filings(symbol, limit=8)
        except Exception:
            filings = []

        if filings:
            has_content = True
            section_children.append(html.Div("SEC FILINGS", style=sub_label))

            filing_hdr_style = {
                "display": "grid", "gridTemplateColumns": "60px 1fr 120px",
                "padding": "3px 0", "borderBottom": f"1px solid {C['orange']}",
                "fontSize": "8px", "fontWeight": "bold", "color": C["orange"],
                "fontFamily": FONT_FAMILY,
            }
            section_children.append(html.Div([
                html.Span("Type"), html.Span("Description"), html.Span("Filed", style={"textAlign": "right"}),
            ], style=filing_hdr_style))

            for f in filings:
                filed = f.get("filing_date", "")
                url = f.get("filing_url", "#")
                section_children.append(html.Div([
                    html.Span(f.get("form_type", ""), style={"color": C["white"], "fontWeight": "bold"}),
                    html.A(f.get("form_type_description", ""), href=url, target="_blank",
                           style={"color": "#6699cc", "textDecoration": "none"}),
                    html.Span(filed, style={"textAlign": "right", "color": C["gray"]}),
                ], style={
                    "display": "grid", "gridTemplateColumns": "60px 1fr 120px",
                    "padding": "3px 0", "borderBottom": f"1px solid {C['border']}",
                    "fontSize": "10px", "fontFamily": FONT_FAMILY,
                }))

    # ------------------------------------------------------------------
    # 3) EARNINGS TRANSCRIPTS
    # ------------------------------------------------------------------
    if symbol:
        try:
            transcripts = get_earnings_transcripts(symbol)[:8]
        except Exception:
            transcripts = []

        if transcripts:
            has_content = True
            section_children.append(html.Div("EARNINGS TRANSCRIPTS", style=sub_label))

            for tc in transcripts:
                fy = tc.get("fiscal_year", "")
                fq = tc.get("fiscal_quarter", "")
                rd = tc.get("report_date", "")
                label = f"Q{fq} FY{fy} Earnings Call"
                section_children.append(html.Div([
                    html.Span(label, style={"color": C["white"], "fontSize": "10px"}),
                    html.Span(rd, style={"color": C["gray"], "fontSize": "10px", "marginLeft": "auto"}),
                ], style={
                    "display": "flex", "justifyContent": "space-between",
                    "padding": "3px 0", "borderBottom": f"1px solid {C['border']}",
                    "fontFamily": FONT_FAMILY,
                }))

    if not has_content:
        return html.Div()

    return html.Div(section_children, style={**PANEL_STYLE, "marginBottom": "8px"})


def _build_price_section(info, prices):
    """Price chart + market data table side by side."""

    # Time period buttons (rectangular, not radio circles)
    period_buttons = []
    for p in PRICE_PERIODS:
        btn_style = {
            "padding": "3px 8px", "fontSize": "9px", "cursor": "pointer",
            "fontFamily": FONT_FAMILY, "border": f"1px solid {C['border']}",
            "background": C["orange"] if p == "1Y" else "#000",
            "color": "#000" if p == "1Y" else C["gray"],
            "fontWeight": "bold" if p == "1Y" else "normal",
        }
        period_buttons.append(html.Span(p, id={"type": "period-btn", "index": p}, style=btn_style))

    # Studies dropdown
    studies_dropdown = html.Div([
        html.Details([
            html.Summary("fx Studies \u25be", style={
                "color": C["orange"], "fontSize": "10px", "cursor": "pointer",
                "padding": "3px 8px", "border": f"1px solid {C['border']}",
                "background": "#1a1a1a", "fontFamily": FONT_FAMILY,
                "listStyle": "none",
            }),
            html.Div([
                dcc.Checklist(
                    id="overlay-toggles",
                    options=OVERLAY_OPTIONS,
                    value=["Moving Averages"],
                    inputStyle={"marginRight": "6px", "accentColor": C["orange"]},
                    labelStyle={
                        "display": "block", "padding": "5px 12px", "fontSize": "10px",
                        "color": C["white"], "cursor": "pointer", "fontFamily": FONT_FAMILY,
                    },
                    style={"padding": "4px 0"},
                ),
            ], style={
                "position": "absolute", "top": "100%", "right": "0", "zIndex": "100",
                "background": "#1a1a1a", "border": f"1px solid {C['border']}",
                "minWidth": "180px", "borderRadius": "2px",
                "boxShadow": "0 4px 12px rgba(0,0,0,0.5)",
            }),
        ], style={"position": "relative"}),
    ])

    return html.Div(
        style={"display": "flex", "gap": "10px", "marginBottom": "8px"},
        children=[
            html.Div([
                html.Div(
                    style={"display": "flex", "justifyContent": "space-between", "alignItems": "center",
                           "marginBottom": "4px"},
                    children=[
                        # Period buttons
                        html.Div([
                            dcc.RadioItems(
                                id="price-period",
                                options=[{"label": p, "value": p} for p in PRICE_PERIODS],
                                value="1Y",
                                inline=True,
                                inputStyle={"display": "none"},
                                labelStyle={
                                    "padding": "3px 8px", "fontSize": "9px", "cursor": "pointer",
                                    "fontFamily": FONT_FAMILY, "border": f"1px solid {C['border']}",
                                    "marginRight": "2px", "color": C["gray"], "background": "#000",
                                },
                                className="bbg-period-selector",
                            ),
                        ]),
                        # Studies dropdown
                        studies_dropdown,
                    ],
                ),
                dcc.Graph(id="price-chart", config={"displayModeBar": False}, style={"height": "350px"}),
            ], style={**PANEL_STYLE, "flex": "1", "marginBottom": 0}),
            html.Div(
                _build_market_data_table(info, prices),
                style={**PANEL_STYLE, "width": "260px", "flexShrink": "0", "marginBottom": 0,
                       "overflowY": "auto", "maxHeight": "400px"},
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
    """Earnings surprise chart section with expandable data table."""
    earnings_table = _build_earnings_data_table(symbol)

    return html.Div([
        html.Div("EARNINGS SURPRISE", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                              "letterSpacing": "1px", "marginBottom": "4px"}),
        dcc.Graph(id="earnings-chart", figure=_build_earnings_chart(symbol),
                  config={"displayModeBar": False}, style={"height": "300px"}),
        earnings_table,
    ], style=PANEL_STYLE)


def _build_earnings_data_table(symbol):
    """Build an expandable HTML table with full earnings history."""
    try:
        earnings = fetch_earnings_history(symbol)
    except Exception:
        earnings = []
    if not earnings:
        return html.Div()

    prices = startup.get_prices(symbol)

    hdr_style = {
        "color": C["orange"], "fontSize": "8px", "fontWeight": "bold",
        "padding": "4px 6px", "textAlign": "right",
        "borderBottom": f"1px solid {C['orange']}",
        "fontFamily": FONT_FAMILY,
    }

    header = html.Tr([
        html.Th("Quarter", style={**hdr_style, "textAlign": "left"}),
        html.Th("Date", style=hdr_style),
        html.Th("EPS Actual", style=hdr_style),
        html.Th("EPS Est", style=hdr_style),
        html.Th("Surprise %", style=hdr_style),
        html.Th("Beat/Miss", style=hdr_style),
        html.Th("Px Surp (3D)", style=hdr_style),
    ])

    rows = []
    for e in reversed(earnings):  # most recent first
        act = e.get("actual")
        est = e.get("estimate")
        surp = e.get("surprise_pct")
        q_label = e.get("quarter", "")

        beat = act is not None and est is not None and act >= est
        beat_label = "BEAT" if beat else "MISS" if (act is not None and est is not None) else "--"
        beat_color = C["green"] if beat else C["red"] if beat_label == "MISS" else C["gray"]
        row_bg = "rgba(0,255,0,0.04)" if beat else "rgba(255,68,68,0.04)" if beat_label == "MISS" else "transparent"

        # 3-day price reaction
        px_3d = None
        if q_label and prices is not None and len(prices) > 5:
            try:
                er_date = pd.Timestamp(q_label)
                if prices.index.tz is not None:
                    er_date = er_date.tz_localize(prices.index.tz)
                mask = prices.index >= er_date
                if mask.any():
                    idx_start = prices.index[mask][0]
                    pos = prices.index.get_loc(idx_start)
                    if pos + 3 < len(prices):
                        p_start = float(prices.iloc[pos])
                        p_end = float(prices.iloc[pos + 3])
                        px_3d = (p_end - p_start) / p_start * 100
            except Exception:
                pass

        cell = {
            "padding": "3px 6px", "fontSize": "9px",
            "borderBottom": f"1px solid {C['border']}",
            "textAlign": "right", "fontFamily": FONT_FAMILY,
        }

        # Strip timestamps from dates — show just YYYY-MM-DD
        q_date_str = str(q_label).split(" ")[0] if q_label else ""

        rows.append(html.Tr([
            html.Td(q_date_str, style={**cell, "color": C["white"], "textAlign": "left"}),
            html.Td(q_date_str, style={**cell, "color": C["gray"]}),
            html.Td(f"${act:.2f}" if act is not None else "--", style={**cell, "color": C["white"]}),
            html.Td(f"${est:.2f}" if est is not None else "--", style={**cell, "color": C["gray"]}),
            html.Td(f"{surp:+.1f}%" if surp is not None else "--",
                     style={**cell, "color": C["green"] if surp and surp >= 0 else C["red"] if surp else C["gray"]}),
            html.Td(beat_label, style={**cell, "color": beat_color, "fontWeight": "bold"}),
            html.Td(f"{px_3d:+.1f}%" if px_3d is not None else "--",
                     style={**cell, "color": C["green"] if px_3d and px_3d >= 0 else C["red"] if px_3d else C["gray"]}),
        ], style={"backgroundColor": row_bg}))

    table = html.Table(
        [html.Thead(header), html.Tbody(rows)],
        style={"width": "100%", "borderCollapse": "collapse"},
    )

    return html.Details([
        html.Summary("View Data Table", style={
            "color": C["orange"], "fontSize": "10px", "cursor": "pointer",
            "fontFamily": FONT_FAMILY, "padding": "6px 0", "fontWeight": "bold",
        }),
        html.Div(table, style={
            "maxHeight": "300px", "overflowY": "auto", "marginTop": "6px",
        }),
    ], style={"marginTop": "6px"})


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


def _build_rv_summary_table(symbol, window_days=None):
    """Bloomberg-style RV summary: all ratios at a glance with current, hist avg, range, implied price."""
    ticker_obj = startup.universe.get(symbol)
    prices = startup.get_prices(symbol)
    current_price = float(prices.iloc[-1]) if prices is not None and len(prices) > 0 else None

    cell = {"padding": "3px 6px", "fontSize": "10px", "fontFamily": FONT_FAMILY,
            "borderBottom": "1px solid #111", "whiteSpace": "nowrap"}
    hdr = {**cell, "color": C["orange"], "fontSize": "8px", "fontWeight": "bold",
           "textTransform": "uppercase", "borderBottom": f"1px solid {C['orange']}"}

    header = html.Tr([
        html.Th("Metric", style={**hdr, "textAlign": "left"}),
        html.Th("Current", style={**hdr, "textAlign": "right"}),
        html.Th("Hist Avg", style={**hdr, "textAlign": "right"}),
        html.Th("Diff", style={**hdr, "textAlign": "right"}),
        html.Th("# SD", style={**hdr, "textAlign": "right"}),
        html.Th("Range", style={**hdr, "width": "120px", "textAlign": "center"}),
        html.Th("Low", style={**hdr, "textAlign": "right"}),
        html.Th("High", style={**hdr, "textAlign": "right"}),
        html.Th("Implied Px", style={**hdr, "textAlign": "right"}),
    ])

    rows = []
    for ratio_name in RATIO_NAMES:
        if ticker_obj is None:
            continue
        try:
            st = ticker_obj.stats(ratio_name, window_days)
        except Exception:
            st = None
        if st is None:
            rows.append(html.Tr([
                html.Td(
                    html.Span(ratio_name, id=f"rv-select-{ratio_name.replace('/', '-')}",
                              style={"color": C["dim"]}),
                    style=cell,
                ),
                *[html.Td("—", style={**cell, "color": C["dim"], "textAlign": "right"}) for _ in range(7)],
                html.Td("—", style={**cell, "color": C["dim"], "textAlign": "right"}),
            ]))
            continue

        current = st["current"]
        mean = st["mean"]
        std = st["std"]
        z = st["z_score"]
        low = st["low"]
        high = st["high"]
        diff_pct = ((current - mean) / mean * 100) if mean != 0 else 0

        # Color: green if cheap (below mean), red if rich (above mean)
        val_color = C["green"] if current < mean else C["red"]
        z_color = C["green"] if z < 0 else C["red"]

        # Implied price at historical average: if ratio returns to mean, what's the stock price?
        implied_px = None
        if current_price and current != 0:
            implied_px = current_price * (mean / current)

        # Range bar: position of current between low and high
        pct_in_range = max(0, min(100, (current - low) / (high - low) * 100)) if high != low else 50
        range_bar = html.Div([
            html.Div(style={
                "position": "relative", "height": "6px", "background": "#222",
                "borderRadius": "3px", "width": "100%",
            }, children=[
                # Current dot (cyan)
                html.Div(style={
                    "position": "absolute", "left": f"{pct_in_range}%", "top": "-2px",
                    "width": "8px", "height": "10px", "background": C["cyan"],
                    "borderRadius": "2px", "transform": "translateX(-50%)",
                }),
                # Mean marker (orange diamond)
                html.Div(style={
                    "position": "absolute",
                    "left": f"{max(0, min(100, (mean - low) / (high - low) * 100)) if high != low else 50}%",
                    "top": "-1px", "width": "6px", "height": "8px", "background": C["orange"],
                    "borderRadius": "1px", "transform": "translateX(-50%) rotate(45deg)",
                }),
            ]),
        ], style={"width": "100px", "display": "inline-block"})

        rows.append(html.Tr([
            html.Td(
                html.Span(ratio_name, id=f"rv-select-{ratio_name.replace('/', '-')}",
                           style={"cursor": "pointer", "color": C["cyan"], "fontWeight": "bold",
                                  "textDecoration": "underline", "textDecorationColor": C["border"]}),
                style=cell,
            ),
            html.Td(f"{current:.1f}x", style={**cell, "color": val_color, "fontWeight": "bold", "textAlign": "right"}),
            html.Td(f"{mean:.1f}x", style={**cell, "color": C["orange"], "textAlign": "right"}),
            html.Td(f"{diff_pct:+.0f}%", style={**cell, "color": val_color, "textAlign": "right"}),
            html.Td(f"{z:+.1f}", style={**cell, "color": z_color, "fontWeight": "bold", "textAlign": "right"}),
            html.Td(range_bar, style={**cell, "textAlign": "center"}),
            html.Td(f"{low:.1f}x", style={**cell, "color": C["dim"], "textAlign": "right"}),
            html.Td(f"{high:.1f}x", style={**cell, "color": C["dim"], "textAlign": "right"}),
            html.Td(
                f"${implied_px:.2f}" if implied_px else "—",
                style={**cell, "color": C["cyan"], "fontWeight": "bold", "textAlign": "right"},
            ),
        ]))

    # Current price label
    price_label = html.Tr([
        html.Td("Current Price", style={**cell, "color": C["orange"], "fontWeight": "bold"}),
        *[html.Td("", style=cell) for _ in range(7)],
        html.Td(
            f"${current_price:.2f}" if current_price else "—",
            style={**cell, "color": C["orange"], "fontWeight": "bold", "textAlign": "right"},
        ),
    ])

    return html.Div([
        html.Div(
            style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "4px"},
            children=[
                html.Span("RELATIVE VALUATION", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold", "letterSpacing": "1px"}),
                html.Span("● Current  ◆ Hist Avg", style={"color": C["gray"], "fontSize": "8px"}),
            ],
        ),
        html.Table(
            [html.Thead(header), html.Tbody([price_label] + rows)],
            style={"width": "100%", "borderCollapse": "collapse"},
        ),
    ], style={"marginBottom": "14px"})


def _build_rv_controls(symbol):
    """RV summary table + window selector + RV chart. Ratio selected via table rows."""
    # Hidden ratio RadioItems — updated by JavaScript when table rows are clicked
    hidden_ratio = dcc.RadioItems(
        id="ratio-dropdown",
        options=[{"label": r, "value": r} for r in RATIO_NAMES],
        value="P/E",
        style={"display": "none"},
    )

    # Window toggle only
    window_row = html.Div(
        style={"display": "flex", "gap": "12px", "alignItems": "center", "marginBottom": "6px"},
        children=[
            html.Label("WINDOW", style={"color": C["orange"], "fontSize": "8px", "marginRight": "4px",
                                        "fontFamily": FONT_FAMILY, "fontWeight": "bold"}),
            dcc.RadioItems(
                id="window-toggle",
                options=WINDOW_OPTIONS,
                value="2Y",
                inline=True,
                inputStyle={"display": "none"},
                labelStyle={
                    "padding": "3px 8px", "fontSize": "9px", "cursor": "pointer",
                    "fontFamily": FONT_FAMILY, "border": f"1px solid {C['border']}",
                    "marginRight": "2px", "color": C["gray"], "background": "#000",
                },
                className="bbg-period-selector",
            ),
        ],
    )

    return html.Div([
        html.Div(id="rv-summary-container", children=_build_rv_summary_table(symbol)),
        hidden_ratio,
        window_row,
        html.Div(id="rv-chart-container"),
    ], style=PANEL_STYLE)


def _build_technicals_section(prices, symbol):
    """Technical analysis charts: RSI, MACD (price+MA is now in the enhanced price chart)."""

    rsi_tooltip = ("RSI (Relative Strength Index) measures momentum on a 0-100 scale. "
                   "Above 70 = overbought (may pull back). Below 30 = oversold (may bounce). "
                   "Uses 14-period lookback.")
    macd_tooltip = ("MACD tracks trend momentum using two moving averages. "
                    "When MACD crosses above Signal = bullish. Below = bearish. "
                    "Green histogram = bullish momentum. Red = bearish.")

    return html.Div([
        html.Div("TECHNICAL ANALYSIS", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                                               "letterSpacing": "1px", "marginBottom": "4px"}),
        html.Div([
            html.Span("RSI ", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold"}),
            html.Span(["i", html.Span(rsi_tooltip, className="info-text")], className="info-tip"),
        ], style={"marginBottom": "2px"}),
        dcc.Graph(id="ta-rsi-chart", figure=_build_ta_rsi_chart(prices, symbol),
                  config={"displayModeBar": False}, style={"height": "300px", "marginBottom": "4px"}),
        html.Div([
            html.Span("MACD ", style={"color": C["orange"], "fontSize": "9px", "fontWeight": "bold"}),
            html.Span(["i", html.Span(macd_tooltip, className="info-text")], className="info-tip"),
        ], style={"marginBottom": "2px"}),
        dcc.Graph(id="ta-macd-chart", figure=_build_ta_macd_chart(prices, symbol),
                  config={"displayModeBar": False}, style={"height": "300px"}),
    ], style=PANEL_STYLE)


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def _build_earnings_chart(symbol):
    """Earnings surprise scatter chart with beat/miss coloring and 3-day price reaction."""
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
    prices = startup.get_prices(symbol)

    # Estimate markers (hollow circles) — hover disabled, shown via Actual hover
    fig.add_trace(go.Scatter(
        x=quarters, y=estimates, mode="markers",
        marker=dict(color="rgba(0,0,0,0)", size=14,
                    line=dict(color=C["gray"], width=2.5)),
        name="Estimate",
        hoverinfo="skip",
    ))

    # Actual markers (filled, green=beat, red=miss)
    colors = []
    sizes = []
    hover_texts = []
    for i, e in enumerate(earnings):
        act = e.get("actual")
        est = e.get("estimate")
        surp = e.get("surprise_pct")
        beat = act is not None and est is not None and act >= est
        color = C["green"] if beat else C["red"] if act is not None else C["gray"]
        colors.append(color)
        # Most recent quarter gets a bigger dot
        sizes.append(18 if i == len(earnings) - 1 else 14)

        # Build hover text
        lines = []
        if act is not None:
            lines.append(f"Actual: ${act:.2f}")
        if est is not None:
            lines.append(f"Estimate: ${est:.2f}")
        if surp is not None:
            arrow = "▲" if surp >= 0 else "▼"
            lines.append(f"EPS Surprise: {arrow} {surp:+.1f}%")

        # 3-day price reaction
        q_date = e.get("quarter")
        if q_date and prices is not None and len(prices) > 5:
            try:
                er_date = pd.Timestamp(q_date)
                if prices.index.tz is not None:
                    er_date = er_date.tz_localize(prices.index.tz)
                mask = prices.index >= er_date
                if mask.any():
                    idx_start = prices.index[mask][0]
                    pos = prices.index.get_loc(idx_start)
                    if pos + 3 < len(prices):
                        p_start = float(prices.iloc[pos])
                        p_end = float(prices.iloc[pos + 3])
                        ret_3d = (p_end - p_start) / p_start * 100
                        lines.append(f"Px Move (3D): {ret_3d:+.1f}%")
            except Exception:
                pass

        hover_texts.append("<br>".join(lines))


    fig.add_trace(go.Scatter(
        x=quarters, y=actuals, mode="markers",
        marker=dict(color=colors, size=sizes, line=dict(color="#0a0a0a", width=1)),
        name="Actual",
        text=hover_texts,
        hoverinfo="text",
    ))

    # Connect estimates to actuals with thin lines
    for i, e in enumerate(earnings):
        act = e.get("actual")
        est = e.get("estimate")
        if act is not None and est is not None:
            color = C["green"] if act >= est else C["red"]
            fig.add_trace(go.Scatter(
                x=[quarters[i], quarters[i]], y=[est, act],
                mode="lines", line=dict(color=color, width=1, dash="dot"),
                showlegend=False, hoverinfo="skip",
            ))

    fig.update_layout(
        **make_chart_layout(
            title=dict(text=f"{symbol} EARNINGS SURPRISE", font=dict(size=11, color=C["orange"]), x=0.01),
            xaxis=dict(gridcolor=C["border"], tickfont=dict(size=10, color=C["gray"])),
            yaxis=dict(gridcolor=C["border"], tickfont=dict(size=10, color=C["gray"]),
                       title=dict(text="EPS ($)", font=dict(size=10, color=C["gray"]))),
            height=280,
            margin=dict(l=60, r=20, t=40, b=60),
            hovermode="closest",
            hoverlabel=dict(bgcolor="#1a1a1a", bordercolor=C["border"],
                            font=dict(color=C["white"], family=FONT_FAMILY, size=11)),
            showlegend=True,
            legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0,
                        font=dict(size=9, color=C["gray"])),
        ),
    )
    return fig


def _build_ta_rsi_chart(prices, symbol):
    """RSI chart with overbought/oversold zones (6M)."""
    if prices is None or len(prices) < 30:
        return empty_fig("Insufficient data for RSI")

    rsi = compute_rsi(prices, 14).dropna()
    rsi_6m = rsi.iloc[-126:] if len(rsi) >= 126 else rsi
    if rsi_6m.empty:
        return empty_fig("Insufficient RSI data")
    current_val = float(rsi_6m.iloc[-1])

    # Color based on current level
    rsi_color = C["green"] if current_val <= 30 else C["red"] if current_val >= 70 else C["purple"]
    label = " OVERSOLD" if current_val <= 30 else " OVERBOUGHT" if current_val >= 70 else ""

    fig = go.Figure()
    fig.add_hrect(y0=70, y1=100, fillcolor="rgba(255,68,68,0.08)", line_width=0)
    fig.add_hrect(y0=0, y1=30, fillcolor="rgba(0,255,0,0.06)", line_width=0)
    fig.add_hline(y=70, line_dash="dash", line_color=C["red"], line_width=0.8, opacity=0.5,
                  annotation_text="OVERBOUGHT 70", annotation_position="top left",
                  annotation_font=dict(size=8, color=C["red"]))
    fig.add_hline(y=30, line_dash="dash", line_color=C["green"], line_width=0.8, opacity=0.5,
                  annotation_text="OVERSOLD 30", annotation_position="bottom left",
                  annotation_font=dict(size=8, color=C["green"]))
    fig.add_hline(y=50, line_dash="dot", line_color=C["dim"], line_width=0.5, opacity=0.3)

    fig.add_trace(go.Scatter(x=rsi_6m.index, y=rsi_6m.values, mode="lines",
                             line=dict(color=C["purple"], width=2), name="RSI",
                             fill="tozeroy", fillcolor="rgba(187,134,252,0.05)"))

    # Current value annotation
    fig.add_annotation(x=rsi_6m.index[-1], y=current_val,
                       text=f"RSI: {current_val:.0f}{label}", showarrow=True, arrowhead=2,
                       font=dict(size=10, color=rsi_color, family=FONT_FAMILY),
                       arrowcolor=rsi_color, bgcolor="#0a0a0a", bordercolor=rsi_color, borderwidth=1)

    fig.update_layout(
        **make_chart_layout(
            title=dict(text=f"{symbol} RSI (6M)", font=dict(size=11, color=C["orange"]), x=0.01),
            xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
            yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"]),
                       range=[0, 100], dtick=10),
            height=300,
            margin=dict(l=50, r=80, t=35, b=30),
        ),
    )
    return fig


def _build_ta_macd_chart(prices, symbol):
    """MACD chart with histogram (6M)."""
    if prices is None or len(prices) < 35:
        return empty_fig("Insufficient data for MACD")

    macd_l, sig_l, hist = compute_macd(prices)
    # Drop NaN values from the start
    valid = macd_l.dropna().index
    if len(valid) < 10:
        return empty_fig("Insufficient MACD data")

    n = min(126, len(valid))
    macd_6m = macd_l.loc[valid[-n:]]
    sig_6m = sig_l.loc[valid[-n:]]
    hist_6m = hist.loc[valid[-n:]]

    # Determine current signal
    current_macd = float(macd_6m.iloc[-1])
    current_sig = float(sig_6m.iloc[-1])
    is_bullish = current_macd > current_sig
    signal_text = "BULLISH" if is_bullish else "BEARISH"
    signal_color = C["green"] if is_bullish else C["red"]

    fig = go.Figure()

    # Bullish/bearish zone tints around zero line
    y_abs_max = max(abs(macd_6m.max()), abs(macd_6m.min()), abs(hist_6m.max()), abs(hist_6m.min())) * 1.5
    fig.add_hrect(y0=0, y1=y_abs_max, fillcolor="rgba(0,255,0,0.04)", line_width=0)
    fig.add_hrect(y0=-y_abs_max, y1=0, fillcolor="rgba(255,68,68,0.04)", line_width=0)

    hist_colors = [C["green"] if v >= 0 else C["red"] for v in hist_6m.values]
    fig.add_trace(go.Bar(x=hist_6m.index, y=hist_6m.values,
                         marker_color=hist_colors, name="Histogram", opacity=0.6))
    fig.add_trace(go.Scatter(x=macd_6m.index, y=macd_6m.values, mode="lines",
                             line=dict(color=C["cyan"], width=2), name="MACD"))
    fig.add_trace(go.Scatter(x=sig_6m.index, y=sig_6m.values, mode="lines",
                             line=dict(color=C["orange"], width=1.5, dash="dash"), name="Signal"))
    fig.add_hline(y=0, line_dash="solid", line_color=C["dim"], line_width=0.8)

    # Current signal annotation
    fig.add_annotation(x=macd_6m.index[-1], y=current_macd,
                       text=signal_text, showarrow=True, arrowhead=2,
                       font=dict(size=9, color=signal_color, family=FONT_FAMILY),
                       arrowcolor=signal_color, bgcolor="#0a0a0a",
                       bordercolor=signal_color, borderwidth=1)

    fig.update_layout(
        **make_chart_layout(
            title=dict(text=f"{symbol} MACD (6M)", font=dict(size=11, color=C["orange"]), x=0.01),
            xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
            yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
            height=300,
            margin=dict(l=50, r=80, t=35, b=50),
            showlegend=True,
            legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0,
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
    Input("overlay-toggles", "value"),
    State("url", "pathname"),
)
def update_price_chart(period, overlays, pathname):
    """Update enhanced price chart with toggleable overlays and adaptive parameters."""
    if not pathname or "/detail/" not in pathname:
        return empty_fig()
    symbol = pathname.split("/detail/")[-1].upper()
    prices = startup.get_prices(symbol, full=True)
    if prices is None or prices.empty:
        return empty_fig("No price data")

    overlays = overlays or []

    # Slice prices to selected period
    if period == "YTD":
        start = pd.Timestamp(f"{datetime.now().year}-01-01")
        if prices.index.tz is not None:
            start = start.tz_localize(prices.index.tz)
        p = prices[prices.index >= start]
        if p.empty:
            p = prices.iloc[-60:] if len(prices) >= 60 else prices
    elif period == "MAX":
        p = prices
    else:
        n_days = PRICE_PERIODS.get(period, 252)
        p = prices.iloc[-n_days:] if len(prices) >= n_days else prices

    if p.empty:
        return empty_fig("No data for period")

    # Get adaptive parameters
    params = OVERLAY_PARAMS.get(period, OVERLAY_PARAMS["1Y"])

    from plotly.subplots import make_subplots

    has_volume = "Volume" in overlays
    if has_volume:
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03,
            row_heights=[0.8, 0.2],
        )
    else:
        fig = go.Figure()

    row = 1 if has_volume else None

    # --- Bollinger Bands (behind the price line) ---
    if "Bollinger Bands" in overlays:
        bb_upper, bb_mid, bb_lower = compute_bollinger_bands(
            prices, period=params["bb_period"], std_dev=params["bb_std"],
        )
        bb_upper = bb_upper.reindex(p.index)
        bb_lower = bb_lower.reindex(p.index)

        # Upper band
        upper_kwargs = dict(
            x=p.index, y=bb_upper.values, mode="lines",
            line=dict(color="rgba(0,188,212,0.3)", width=1, dash="dash"),
            name=f"BB Upper ({params['bb_period']},{params['bb_std']})",
            hoverinfo="skip",
        )
        # Lower band with fill to upper
        lower_kwargs = dict(
            x=p.index, y=bb_lower.values, mode="lines",
            line=dict(color="rgba(0,188,212,0.3)", width=1, dash="dash"),
            fill="tonexty", fillcolor="rgba(0,188,212,0.06)",
            name="BB Lower",
            hoverinfo="skip",
        )
        if has_volume:
            fig.add_trace(go.Scatter(**upper_kwargs), row=1, col=1)
            fig.add_trace(go.Scatter(**lower_kwargs), row=1, col=1)
        else:
            fig.add_trace(go.Scatter(**upper_kwargs))
            fig.add_trace(go.Scatter(**lower_kwargs))

    # --- Price line with area fill ---
    price_kwargs = dict(
        x=p.index, y=p.values, mode="lines",
        line=dict(color="#00bcd4", width=2),
        fill="tozeroy", fillcolor="rgba(0,188,212,0.12)",
        name="Close",
        hovertemplate="%{x|%b %d, %Y}<br>$%{y:.2f}<extra></extra>",
    )
    if has_volume:
        fig.add_trace(go.Scatter(**price_kwargs), row=1, col=1)
    else:
        fig.add_trace(go.Scatter(**price_kwargs))

    # --- Moving Averages ---
    if "Moving Averages" in overlays:
        short_sma = compute_sma(prices, params["short_sma"]).reindex(p.index)
        long_sma = compute_sma(prices, params["long_sma"]).reindex(p.index)

        short_kwargs = dict(
            x=p.index, y=short_sma.values, mode="lines",
            line=dict(color="#ff8c00", width=1.5, dash="dash"),
            name=f"SMA {params['short_sma']}",
        )
        long_kwargs = dict(
            x=p.index, y=long_sma.values, mode="lines",
            line=dict(color="#ff4444", width=1.5, dash="dash"),
            name=f"SMA {params['long_sma']}",
        )
        if has_volume:
            fig.add_trace(go.Scatter(**short_kwargs), row=1, col=1)
            fig.add_trace(go.Scatter(**long_kwargs), row=1, col=1)
        else:
            fig.add_trace(go.Scatter(**short_kwargs))
            fig.add_trace(go.Scatter(**long_kwargs))

    # --- MA Crossovers ---
    if "MA Crossovers" in overlays:
        full_short = compute_sma(prices, params["short_sma"])
        full_long = compute_sma(prices, params["long_sma"])
        if not full_short.dropna().empty and not full_long.dropna().empty:
            golden, death = detect_crossovers(full_short, full_long)
            window_start = p.index[0]
            window_end = p.index[-1]
            for d in golden:
                if d >= window_start and d <= window_end:
                    y_val = float(prices.loc[d]) if d in prices.index else None
                    if y_val is not None:
                        fig.add_annotation(
                            x=d, y=y_val, text="GC", showarrow=True, arrowhead=2,
                            arrowcolor=C["green"], font=dict(size=8, color=C["green"]),
                        )
            for d in death:
                if d >= window_start and d <= window_end:
                    y_val = float(prices.loc[d]) if d in prices.index else None
                    if y_val is not None:
                        fig.add_annotation(
                            x=d, y=y_val, text="DC", showarrow=True, arrowhead=2,
                            arrowcolor=C["red"], font=dict(size=8, color=C["red"]),
                        )

    # --- Volume bars (secondary y-axis) ---
    if has_volume:
        try:
            import yfinance as yf
            tk = yf.Ticker(symbol)
            hist = tk.history(period="max")
            if "Volume" in hist.columns:
                vol = hist["Volume"].reindex(p.index, method="nearest")
                vol = vol.fillna(0)
                vol_colors = ["#555"] * len(vol)
                fig.add_trace(go.Bar(
                    x=p.index, y=vol.values,
                    marker_color=vol_colors, name="Volume", opacity=0.4,
                    hovertemplate="%{x|%b %d, %Y}<br>Vol: %{y:,.0f}<extra></extra>",
                ), row=2, col=1)
        except Exception:
            pass

    # --- Current price badge (always shown) ---
    last_price = float(p.iloc[-1])
    fig.add_annotation(
        x=p.index[-1], y=last_price,
        text=f"${last_price:.2f}",
        showarrow=True, arrowhead=2, arrowcolor="#00bcd4",
        font=dict(size=9, color="#000", family=FONT_FAMILY),
        bgcolor="#00bcd4", bordercolor="#00bcd4", borderwidth=1,
    )

    # --- Layout ---
    layout_kwargs = dict(
        paper_bgcolor="#0a0a0a",
        plot_bgcolor="#0a0a0a",
        title=dict(text=f"{symbol} ({period})", font=dict(size=11, color=C["orange"]), x=0.01),
        xaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"])),
        yaxis=dict(gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"]), tickprefix="$"),
        height=350,
        margin=dict(l=50, r=80, t=35, b=55),
        hovermode="x unified",
        showlegend=True,
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0,
                    font=dict(size=8, color=C["gray"])),
        font=dict(family=FONT_FAMILY),
    )
    if has_volume:
        layout_kwargs["yaxis2"] = dict(
            gridcolor=C["border"], tickfont=dict(size=8, color=C["gray"]),
        )
        layout_kwargs["xaxis2"] = dict(
            gridcolor=C["border"], tickfont=dict(size=9, color=C["gray"]),
        )

    fig.update_layout(**layout_kwargs)
    return fig




@callback(
    Output("rv-summary-container", "children"),
    Input("window-toggle", "value"),
    State("url", "pathname"),
)
def update_rv_summary(window_name, pathname):
    """Update RV summary table when window changes."""
    if not pathname or "/detail/" not in pathname:
        return html.Div()
    symbol = pathname.split("/detail/")[-1].upper()
    window_days = WINDOW_MAP.get(window_name)
    return _build_rv_summary_table(symbol, window_days)


@callback(
    Output("rv-chart-container", "children"),
    Input("ratio-dropdown", "value"),
    Input("window-toggle", "value"),
    State("url", "pathname"),
)
def update_rv_chart(ratio_name, window_name, pathname):
    """Update the RV chart based on ratio and window selection."""
    if not pathname or "/detail/" not in pathname:
        return html.Div(dcc.Graph(figure=empty_fig(), config={"displayModeBar": False}, style={"height": "320px"}))
    symbol = pathname.split("/detail/")[-1].upper()

    ticker_obj = startup.universe.get(symbol)
    if ticker_obj is None:
        return html.Div(dcc.Graph(figure=empty_fig(f"{symbol} not found"), config={"displayModeBar": False}, style={"height": "320px"}))

    window_days = WINDOW_MAP.get(window_name)
    try:
        series = ticker_obj.window_series(ratio_name, window_days)
    except Exception:
        series = pd.Series(dtype=float)

    if series is None or len(series) < 10:
        return html.Div(dcc.Graph(figure=empty_fig(f"Insufficient {ratio_name} data for {symbol}"), config={"displayModeBar": False}, style={"height": "320px"}))

    # Filter out negative and extreme values (e.g., EV/EBITDA when EBITDA near zero)
    # Only keep positive values and cap at a reasonable ceiling
    series = series[series > 0]
    if len(series) < 10:
        return html.Div(dcc.Graph(figure=empty_fig(f"Insufficient positive {ratio_name} data for {symbol}"), config={"displayModeBar": False}, style={"height": "320px"}))

    # Remove extreme outliers: cap at 99th percentile to avoid chart distortion
    p99 = series.quantile(0.99)
    p01 = series.quantile(0.01)
    series = series[(series <= p99 * 1.5) & (series >= p01 * 0.5)]
    if len(series) < 10:
        return html.Div(dcc.Graph(figure=empty_fig(f"Insufficient {ratio_name} data for {symbol}"), config={"displayModeBar": False}, style={"height": "320px"}))

    # Recompute stats on the cleaned series
    current = float(series.iloc[-1])
    mean = float(series.mean())
    std = float(series.std())
    if std == 0:
        return html.Div(dcc.Graph(figure=empty_fig(f"No variation in {ratio_name} for {symbol}"), config={"displayModeBar": False}, style={"height": "320px"}))

    fig = go.Figure()

    # Zone fills between sigma bands (like RSI colored zones)
    # Extreme zones: beyond +/-2 sigma
    fig.add_hrect(y0=mean + 2 * std, y1=mean + 4 * std,
                  fillcolor="rgba(255,68,68,0.07)", line_width=0)
    fig.add_hrect(y0=mean - 4 * std, y1=mean - 2 * std,
                  fillcolor="rgba(0,255,0,0.07)", line_width=0)
    # Rich/Cheap zones: between +/-1 and +/-2 sigma
    fig.add_hrect(y0=mean + std, y1=mean + 2 * std,
                  fillcolor="rgba(255,68,68,0.04)", line_width=0)
    fig.add_hrect(y0=mean - 2 * std, y1=mean - std,
                  fillcolor="rgba(0,255,0,0.04)", line_width=0)

    # Zone labels on the right margin
    fig.add_annotation(x=1.01, y=mean + 1.5 * std, text="RICH",
                       xref="paper", yref="y", showarrow=False,
                       font=dict(size=8, color="rgba(255,68,68,0.6)", family=FONT_FAMILY))
    fig.add_annotation(x=1.01, y=mean - 1.5 * std, text="CHEAP",
                       xref="paper", yref="y", showarrow=False,
                       font=dict(size=8, color="rgba(0,255,0,0.6)", family=FONT_FAMILY))
    fig.add_annotation(x=1.01, y=mean + 2.5 * std, text="EXTREME",
                       xref="paper", yref="y", showarrow=False,
                       font=dict(size=7, color="rgba(255,68,68,0.7)", family=FONT_FAMILY))
    fig.add_annotation(x=1.01, y=mean - 2.5 * std, text="EXTREME",
                       xref="paper", yref="y", showarrow=False,
                       font=dict(size=7, color="rgba(0,255,0,0.7)", family=FONT_FAMILY))
    fig.add_annotation(x=1.01, y=mean, text="FAIR",
                       xref="paper", yref="y", showarrow=False,
                       font=dict(size=8, color="rgba(255,165,0,0.6)", family=FONT_FAMILY))

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

    # Y-axis range — use the cleaned series range, padded slightly
    y_min = max(0, series.min() * 0.9)
    y_max = series.max() * 1.1

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

    # --- Sector attribution ---
    sector_attr = html.Div()
    try:
        sector = startup.ticker_sector.get(symbol, "Unknown")
        sector_medians_df = startup.universe.sector_medians(ratio_name, window_name)
        if not sector_medians_df.empty and sector in sector_medians_df["Sector"].values:
            sector_row = sector_medians_df[sector_medians_df["Sector"] == sector].iloc[0]
            sector_median = float(sector_row["Median"])

            premium_discount = (current - sector_median) / sector_median * 100 if sector_median != 0 else 0
            pd_label = "premium" if premium_discount > 0 else "discount"
            pd_color = C["red"] if premium_discount > 0 else C["green"]

            # Attribution: how much of the stock's deviation from its own mean is
            # sector-wide vs stock-specific
            stock_dev = current - mean
            sector_dev = sector_median - mean
            if abs(stock_dev) > 0.001:
                sector_pct = min(100, max(0, abs(sector_dev / stock_dev) * 100))
                stock_pct = 100 - sector_pct
            else:
                sector_pct = 0
                stock_pct = 0

            attr_style = {
                "display": "flex", "gap": "16px", "alignItems": "center",
                "marginTop": "6px", "padding": "4px 8px",
                "borderTop": f"1px solid {C['border']}",
            }
            label_s = {"color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
                       "fontFamily": FONT_FAMILY, "textTransform": "uppercase"}
            value_s = {"color": C["white"], "fontSize": "10px", "fontFamily": FONT_FAMILY,
                       "marginLeft": "4px"}

            sector_attr = html.Div([
                html.Span([
                    html.Span(f"Sector {ratio_name}: ", style=label_s),
                    html.Span(f"{sector_median:.1f}x", style=value_s),
                ]),
                html.Span([
                    html.Span("vs Sector: ", style=label_s),
                    html.Span(f"{premium_discount:+.1f}% {pd_label}", style={**value_s, "color": pd_color}),
                ]),
                html.Span([
                    html.Span("Attribution: ", style=label_s),
                    html.Span(f"Sector {sector_pct:.0f}% / Stock {stock_pct:.0f}%", style=value_s),
                ]),
            ], style=attr_style)
    except Exception:
        pass

    return html.Div([
        dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"height": "320px"}),
        sector_attr,
    ])
