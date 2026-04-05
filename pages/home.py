"""Home page layout for the Highbourne Terminal scanner."""

from datetime import datetime
from dash import html, dcc, callback, Input, Output, State
import plotly.graph_objects as go

import data.startup as startup
from theme import C, FONT_FAMILY, CONTAINER_STYLE, header_bar, function_key_bar
from components.screener_table import build_screener_table
from components.risk_panel import build_risk_dashboard
from utils.formatters import fmt_price

# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------
PANEL_STYLE = {
    "backgroundColor": C["panel"],
    "border": f"1px solid {C['border']}",
    "padding": "10px",
    "marginBottom": "8px",
    "fontFamily": FONT_FAMILY,
}

SECTION_HEADER = {
    "color": C["orange"],
    "fontSize": "11px",
    "fontWeight": "bold",
    "fontFamily": FONT_FAMILY,
    "textTransform": "uppercase",
    "marginBottom": "6px",
    "letterSpacing": "1px",
}

LABEL_STYLE = {
    "color": C["gray"],
    "fontSize": "9px",
    "fontFamily": FONT_FAMILY,
    "textTransform": "uppercase",
}


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_headline_bar():
    """Bloomberg-style combined headline bar: movers tape + news wire in one panel."""
    df = startup.screener_df

    # --- Row 1: Movers ticker tape ---
    mover_items = []
    if not df.empty:
        top = df.reindex(df["ret_1d"].abs().sort_values(ascending=False).index).head(20)
        for _, row in top.iterrows():
            color = C["green"] if row["ret_1d"] > 0 else C["red"]
            arrow = "\u25b2" if row["ret_1d"] > 0 else "\u25bc"
            mover_items.append(
                html.Span([
                    html.Span(row["symbol"], style={"color": C["white"], "fontWeight": "bold", "marginRight": "2px"}),
                    html.Span(f"{arrow}{row['ret_1d']:+.1f}%", style={"color": color}),
                ], style={"marginRight": "16px", "whiteSpace": "nowrap", "fontSize": "10px"})
            )

    # Duplicate items for seamless loop (marquee scrolls -50%, second copy fills the gap)
    movers_row = html.Div([
        html.Div(
            html.Div(mover_items + mover_items, style={
                "display": "flex", "animation": "marquee 25s linear infinite", "whiteSpace": "nowrap",
            }),
            style={"overflow": "hidden", "flex": "1"},
        ),
    ], style={
        "display": "flex", "alignItems": "center",
        "padding": "4px 0", "borderBottom": f"1px solid {C['border']}",
    })

    # --- Row 2: Combined news (stock-specific + market) ---
    def _shorten(headline, max_len=80):
        """Truncate headline to max_len chars, cut at last word boundary."""
        if not headline or len(headline) <= max_len:
            return headline
        cut = headline[:max_len].rsplit(" ", 1)[0]
        return cut + "..."

    all_news = []

    # Stock-specific news
    for article in getattr(startup, "news_cache", []):
        age = article.get("age", "")
        title = _shorten(article.get("title", ""))
        all_news.append(
            html.Span([
                html.Span(article["symbol"], style={"color": C["yellow"], "fontWeight": "bold", "marginRight": "4px"}),
                html.A(title, href=article["link"], target="_blank",
                       style={"color": "#6699cc", "textDecoration": "none"}),
                html.Span(f"  {age}", style={"color": "#444"}) if age else None,
            ], style={"marginRight": "30px", "whiteSpace": "nowrap", "fontSize": "10px"})
        )

    # General market news (Finnhub)
    for article in getattr(startup, "market_news_cache", []):
        headline = _shorten(article.get("headline", article.get("title", "")))
        source = article.get("source", article.get("publisher", ""))
        url = article.get("url", article.get("link", "#"))
        age = article.get("age", "")
        if headline:
            all_news.append(
                html.Span([
                    html.Span("\u25cf ", style={"color": C["cyan"], "fontSize": "6px"}),
                    html.A(headline, href=url, target="_blank",
                           style={"color": "#88aacc", "textDecoration": "none"}),
                    html.Span(f"  {age}", style={"color": "#444"}) if age else None,
                ], style={"marginRight": "30px", "whiteSpace": "nowrap", "fontSize": "10px"})
            )

    news_row = html.Div([
        html.Div(
            html.Div(all_news + all_news, style={
                "display": "flex", "animation": "marquee 40s linear infinite", "whiteSpace": "nowrap",
            }),
            style={"overflow": "hidden", "flex": "1"},
        ),
    ], style={
        "display": "flex", "alignItems": "center", "padding": "4px 0",
    }) if all_news else html.Div()

    return html.Div([
        movers_row,
        news_row,
    ], style={
        "backgroundColor": C["panel"], "border": f"1px solid {C['border']}",
        "borderLeft": f"3px solid {C['orange']}",
        "padding": "2px 10px", "marginBottom": "8px", "fontFamily": FONT_FAMILY,
    })


def _build_convergence_screen():
    """Signal Convergence Screen — ranks stocks by aligned bullish/bearish signals."""
    df = startup.screener_df
    if df.empty:
        return html.Div()

    # ---- Compute bullish & bearish scores for every row ----
    rows = []
    for _, r in df.iterrows():
        bull_score = 0
        bull_count = 0
        bull_total = 7  # number of possible bullish signals

        bear_score = 0
        bear_count = 0
        bear_total = 7

        z = r.get("z_score", 0) or 0
        rsi = r.get("rsi", 50) or 50
        macd = r.get("macd", "") or ""
        ma = r.get("ma_trend", "") or ""
        pct52 = r.get("pct_52w", 0.5) or 0.5
        si = r.get("short_interest", 0) or 0
        ret3 = r.get("ret_3d", 0) or 0

        # --- Bullish signals ---
        if z < -1.0:
            bull_score += 20; bull_count += 1
            if z < -2.0:
                bull_score += 10
        if rsi < 30:
            bull_score += 15; bull_count += 1
            if rsi < 20:
                bull_score += 5
        if macd == "Bull":
            bull_score += 10; bull_count += 1
        if ma == "Above":
            bull_score += 10; bull_count += 1
        if pct52 < 0.25:
            bull_score += 10; bull_count += 1
        if si > 10:
            bull_score += 5; bull_count += 1
        if ret3 < -5:
            bull_score += 5; bull_count += 1

        # --- Bearish signals ---
        if z > 1.0:
            bear_score += 20; bear_count += 1
            if z > 2.0:
                bear_score += 10
        if rsi > 70:
            bear_score += 15; bear_count += 1
        if macd == "Bear":
            bear_score += 10; bear_count += 1
        if ma == "Below":
            bear_score += 10; bear_count += 1
        if pct52 > 0.75:
            bear_score += 10; bear_count += 1
        if ret3 > 5:
            bear_score += 5; bear_count += 1

        # Normalize to 0-100 (max raw = 90)
        bull_norm = min(100, round(bull_score / 90 * 100))
        bear_norm = min(100, round(bear_score / 90 * 100))

        rows.append({
            "symbol": r.get("symbol", ""),
            "name": r.get("name", ""),
            "sector": r.get("sector", ""),
            "bull_score": bull_norm,
            "bull_count": bull_count,
            "bull_total": bull_total,
            "bear_score": bear_norm,
            "bear_count": bear_count,
            "bear_total": bear_total,
            "z_score": z,
            "rsi": rsi,
            "price": r.get("price", 0) or 0,
            "ret_1d": r.get("ret_1d", 0) or 0,
        })

    # Sort for top buys (highest bullish) and top sells (highest bearish)
    top_buys = sorted(rows, key=lambda x: x["bull_score"], reverse=True)[:15]
    top_sells = sorted(rows, key=lambda x: x["bear_score"], reverse=True)[:15]

    # ---- Helper to build a score bar ----
    def _score_bar(score, color):
        return html.Div(
            html.Div(style={
                "width": f"{score}%", "height": "100%",
                "backgroundColor": color, "borderRadius": "2px",
            }),
            style={
                "width": "60px", "height": "10px",
                "backgroundColor": "#1a1a1a", "borderRadius": "2px",
                "display": "inline-block", "verticalAlign": "middle",
            },
        )

    # ---- Helper to build a table ----
    def _convergence_table(items, color, label):
        header = html.Tr([
            html.Th("#", style={**_TH, "width": "20px"}),
            html.Th("SYMBOL", style={**_TH, "width": "90px", "textAlign": "left"}),
            html.Th("SECTOR", style={**_TH, "width": "80px", "textAlign": "left"}),
            html.Th("SCORE", style={**_TH, "width": "80px"}),
            html.Th("SIGNALS", style={**_TH, "width": "55px"}),
            html.Th("Z", style={**_TH, "width": "40px"}),
            html.Th("RSI", style={**_TH, "width": "35px"}),
            html.Th("PRICE", style={**_TH, "width": "55px", "textAlign": "right"}),
            html.Th("1D%", style={**_TH, "width": "45px", "textAlign": "right"}),
        ])

        body_rows = []
        score_key = "bull_score" if color == C["green"] else "bear_score"
        count_key = "bull_count" if color == C["green"] else "bear_count"
        total_key = "bull_total" if color == C["green"] else "bear_total"

        for i, item in enumerate(items, 1):
            sc = item[score_key]
            if sc == 0:
                continue
            ret_color = C["green"] if item["ret_1d"] > 0 else C["red"] if item["ret_1d"] < 0 else C["gray"]
            body_rows.append(html.Tr([
                html.Td(str(i), style={**_TD, "color": C["gray"]}),
                html.Td([
                    html.Div(item["symbol"], style={"color": C["white"], "fontWeight": "bold", "fontSize": "10px"}),
                    html.Div(item["name"][:20], style={"color": C["gray"], "fontSize": "8px"}),
                ], style={**_TD, "padding": "2px 4px"}),
                html.Td(item["sector"][:12], style={**_TD, "color": C["gray"]}),
                html.Td([
                    _score_bar(sc, color),
                    html.Span(f" {sc}", style={"color": color, "fontSize": "9px", "marginLeft": "4px"}),
                ], style={**_TD}),
                html.Td(f"{item[count_key]}/{item[total_key]}", style={**_TD, "color": C["yellow"]}),
                html.Td(f"{item['z_score']:.1f}", style={**_TD, "color": C["cyan"]}),
                html.Td(f"{item['rsi']:.0f}", style={**_TD}),
                html.Td(fmt_price(item["price"]), style={**_TD, "textAlign": "right"}),
                html.Td(f"{item['ret_1d']:+.1f}%", style={**_TD, "textAlign": "right", "color": ret_color}),
            ]))

        if not body_rows:
            body_rows.append(html.Tr(html.Td(
                "No signals", colSpan=9,
                style={**_TD, "color": C["gray"], "textAlign": "center"},
            )))

        return html.Table([
            html.Thead(header),
            html.Tbody(body_rows),
        ], style={"width": "100%", "borderCollapse": "collapse"})

    # ---- Assemble the panel ----
    return html.Div([
        # Header
        html.Div([
            html.Div("SIGNAL CONVERGENCE", style={
                "color": C["orange"], "fontSize": "12px", "fontWeight": "bold",
                "fontFamily": FONT_FAMILY, "letterSpacing": "1px",
            }),
            html.Div('\u2014 "What to trade today"', style={
                "color": C["yellow"], "fontSize": "10px", "fontFamily": FONT_FAMILY,
                "marginLeft": "8px",
            }),
            html.Div("Stocks ranked by number of aligned bullish / bearish signals", style={
                "color": C["gray"], "fontSize": "9px", "fontFamily": FONT_FAMILY,
                "marginLeft": "auto",
            }),
        ], style={"display": "flex", "alignItems": "baseline", "marginBottom": "6px"}),
        # Two side-by-side tables
        html.Div([
            html.Div([
                html.Div("TOP BUYS", style={**SECTION_HEADER, "color": C["green"]}),
                _convergence_table(top_buys, C["green"], "BUY"),
            ], style={**PANEL_STYLE, "flex": "1", "marginRight": "4px", "overflowX": "auto"}),
            html.Div([
                html.Div("TOP SELLS", style={**SECTION_HEADER, "color": C["red"]}),
                _convergence_table(top_sells, C["red"], "SELL"),
            ], style={**PANEL_STYLE, "flex": "1", "marginLeft": "4px", "overflowX": "auto"}),
        ], style={"display": "flex"}),
    ], style={
        "backgroundColor": C["panel"], "border": f"1px solid {C['border']}",
        "borderLeft": f"3px solid {C['orange']}",
        "padding": "8px 10px", "marginBottom": "8px", "fontFamily": FONT_FAMILY,
    })


# Table cell styles for convergence screen
_TH = {
    "color": C["orange"], "fontSize": "8px", "fontFamily": FONT_FAMILY,
    "padding": "3px 4px", "textAlign": "center",
    "borderBottom": f"2px solid {C['border']}", "textTransform": "uppercase",
}

_TD = {
    "color": C["white"], "fontSize": "10px", "fontFamily": FONT_FAMILY,
    "padding": "2px 4px", "textAlign": "center",
    "borderBottom": f"1px solid {C['border']}",
}


def _build_filter_bar():
    """Sector dropdown, view toggle, and ticker count."""
    sector_options = [{"label": "All", "value": "All"}]
    if startup.universe is not None:
        sector_options += [
            {"label": s, "value": s} for s in startup.universe.sector_list
        ]

    dropdown_style = {
        "backgroundColor": "#1a1a1a",
        "color": C["white"],
        "fontFamily": FONT_FAMILY,
        "fontSize": "11px",
        "width": "200px",
    }

    return html.Div([
        html.Div([
            html.Span("SECTOR ", style={**LABEL_STYLE, "marginRight": "6px"}),
            dcc.Dropdown(
                id="sector-filter",
                options=sector_options,
                value="All",
                clearable=False,
                className="dark-dropdown",
                style=dropdown_style,
            ),
        ], style={"display": "flex", "alignItems": "center", "marginRight": "20px"}),
        html.Div([
            html.Span("VIEW ", style={**LABEL_STYLE, "marginRight": "6px"}),
            dcc.RadioItems(
                id="view-filter",
                options=[
                    {"label": "Cheap", "value": "Cheap"},
                    {"label": "Rich", "value": "Rich"},
                    {"label": "All", "value": "All"},
                ],
                value="All",
                inline=True,
                inputStyle={"marginRight": "4px"},
                labelStyle={
                    "color": C["white"], "fontSize": "10px",
                    "fontFamily": FONT_FAMILY, "marginRight": "12px", "cursor": "pointer",
                },
            ),
        ], style={"display": "flex", "alignItems": "center", "marginRight": "20px"}),
        html.Span(
            id="ticker-count",
            style={"color": C["gray"], "fontSize": "10px", "fontFamily": FONT_FAMILY, "marginLeft": "auto"},
        ),
    ], style={
        **PANEL_STYLE,
        "display": "flex",
        "alignItems": "center",
    })




def _build_gainers_losers_bar():
    """Horizontal bar showing advancers / decliners / unchanged counts."""
    adv = startup.risk_stats.get("advancers", 0)
    dec = startup.risk_stats.get("decliners", 0)
    unch = startup.risk_stats.get("unchanged", 0)
    total = adv + dec + unch or 1

    def _segment(label, count, bg, fg):
        return html.Div(
            f"{label} {count}",
            style={
                "width": f"{count / total * 100:.0f}%",
                "backgroundColor": bg, "color": fg,
                "textAlign": "center", "fontSize": "10px",
                "fontFamily": FONT_FAMILY, "padding": "3px 0",
            },
        )

    return html.Div([
        _segment("ADV", adv, "#003300", C["green"]),
        _segment("UNCH", unch, "#1a1a1a", C["gray"]),
        _segment("DEC", dec, "#330000", C["red"]),
    ], style={"display": "flex", "marginBottom": "8px", "border": f"1px solid {C['border']}"})


def _build_movers_panel():
    """Two side-by-side panels for top gainers and losers with rotation interval."""
    df = startup.screener_df
    if df.empty:
        gainers_data, losers_data = [], []
    else:
        gainers = df.nlargest(10, "ret_1d")
        losers = df.nsmallest(10, "ret_1d")
        gainers_data = [
            {"symbol": r["symbol"], "ret_1d": r["ret_1d"], "price": r["price"]}
            for _, r in gainers.iterrows()
        ]
        losers_data = [
            {"symbol": r["symbol"], "ret_1d": r["ret_1d"], "price": r["price"]}
            for _, r in losers.iterrows()
        ]

    return html.Div([
        dcc.Interval(id="mover-interval", interval=5000, n_intervals=0),
        html.Div([
            html.Div([
                html.Div("TOP GAINERS", style=SECTION_HEADER),
                html.Div(
                    id="gainers-list",
                    children=_mover_list(gainers_data[:5], C["green"], is_gainer=True),
                ),
            ], style={**PANEL_STYLE, "flex": "1", "marginRight": "4px"}),
            html.Div([
                html.Div("TOP LOSERS", style=SECTION_HEADER),
                html.Div(
                    id="losers-list",
                    children=_mover_list(losers_data[:5], C["red"], is_gainer=False),
                ),
            ], style={**PANEL_STYLE, "flex": "1", "marginLeft": "4px"}),
        ], style={"display": "flex"}),
        dcc.Store(id="gainers-store", data=gainers_data),
        dcc.Store(id="losers-store", data=losers_data),
    ])


def _mover_list(items, color, is_gainer=True):
    """Render a list of mover rows."""
    arrow = "\u25b2" if is_gainer else "\u25bc"
    return [
        html.Div([
            html.Span(arrow, style={"color": color, "marginRight": "4px", "fontSize": "8px"}),
            html.Span(it["symbol"], style={
                "color": C["white"], "fontWeight": "bold", "width": "50px", "display": "inline-block",
            }),
            html.Span(fmt_price(it["price"]), style={
                "color": C["gray"], "marginRight": "8px", "width": "65px",
                "display": "inline-block", "textAlign": "right",
            }),
            html.Span(f"{it['ret_1d']:+.1f}%", style={"color": color, "fontWeight": "bold"}),
        ], style={"fontSize": "10px", "fontFamily": FONT_FAMILY, "padding": "2px 0"})
        for it in items
    ]


def _build_scatter_plot():
    """Market movers scatter: top 30 movers by |ret_1d|."""
    df = startup.screener_df
    fig = go.Figure()

    if not df.empty:
        df_sorted = df.reindex(df["ret_1d"].abs().sort_values(ascending=False).index)
        movers = df_sorted.head(30).copy()

        # ret_1d is already in percentage points; convert to decimal for tickformat
        ret_decimal = movers["ret_1d"] / 100
        colors = [C["green"] if r > 0 else C["red"] for r in movers["ret_1d"]]
        sizes = [max(6, min(16, abs(r))) for r in movers["ret_1d"]]

        fig.add_trace(go.Scatter(
            x=list(range(len(movers))),
            y=ret_decimal.tolist(),
            mode="markers+text",
            marker=dict(color=colors, size=sizes, opacity=0.8),
            text=movers["symbol"].tolist(),
            textposition="top center",
            textfont=dict(size=8, color=C["white"], family=FONT_FAMILY),
            hovertemplate="%{text}<br>Ret: %{y:.2%}<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="solid", line_color=C["border"], line_width=1)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=C["panel"],
        plot_bgcolor=C["bg"],
        font=dict(family=FONT_FAMILY, size=10, color=C["white"]),
        margin=dict(l=40, r=20, t=30, b=20),
        height=300,
        title=dict(text="TOP MOVERS \u2014 1D RETURN", font=dict(color=C["orange"], size=11)),
        xaxis=dict(showticklabels=False, gridcolor=C["border"], zeroline=False, title=""),
        yaxis=dict(title="1D Return", tickformat=".1%", gridcolor=C["border"],
                   zeroline=True, zerolinecolor=C["border"]),
        showlegend=False,
    )

    return dcc.Graph(figure=fig, config={"displayModeBar": False})


def _build_regime_panel():
    """Market Regime Detection panel — equity + fixed income composite."""
    rd = getattr(startup, "regime_data", None) or {}
    regime = rd.get("regime", "N/A")
    color = rd.get("color", C["gray"])
    score = rd.get("score", 50)
    guidance = rd.get("guidance", "")
    indicators = rd.get("indicators", [])

    # --- Score gauge bar ---
    gauge_pct = max(0, min(100, score))
    gauge_bar = html.Div([
        html.Div([
            html.Span("RISK-ON", style={"color": "#00ff00", "fontSize": "9px", "fontFamily": FONT_FAMILY}),
            html.Div(style={
                "flex": "1", "height": "8px", "margin": "0 10px",
                "background": "linear-gradient(to right, #ff4444, #ff8c00, #ffff00, #00ff00)",
                "borderRadius": "4px", "position": "relative",
            }, children=[
                html.Div(style={
                    "position": "absolute", "top": "-4px",
                    "left": f"{gauge_pct}%", "transform": "translateX(-50%)",
                    "width": "4px", "height": "16px",
                    "backgroundColor": C["white"], "borderRadius": "2px",
                    "boxShadow": "0 0 4px rgba(255,255,255,0.5)",
                }),
            ]),
            html.Span("RISK-OFF", style={"color": "#ff4444", "fontSize": "9px", "fontFamily": FONT_FAMILY}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "2px"}),
        html.Div(f"{score:.0f}", style={
            "textAlign": "center", "color": color, "fontSize": "14px",
            "fontWeight": "bold", "fontFamily": FONT_FAMILY,
        }),
    ], style={"marginBottom": "10px"})

    # --- Indicator rows ---
    def _indicator_row(ind):
        s = ind.get("score", 50)
        filled = int(s / 10)
        bar_chars = "\u2588" * filled + "\u2591" * (10 - filled)
        return html.Div([
            html.Span(ind["name"], style={
                "color": C["gray"], "fontSize": "10px", "fontFamily": FONT_FAMILY,
                "width": "110px", "display": "inline-block",
            }),
            html.Span(ind.get("value", "N/A"), style={
                "color": C["white"], "fontSize": "10px", "fontFamily": FONT_FAMILY,
                "width": "75px", "display": "inline-block", "textAlign": "right",
                "marginRight": "8px",
            }),
            html.Span(bar_chars, style={
                "color": ind.get("color", C["gray"]), "fontSize": "10px",
                "fontFamily": FONT_FAMILY, "letterSpacing": "1px",
                "width": "110px", "display": "inline-block",
            }),
            html.Span(f"{s:.0f}", style={
                "color": C["white"], "fontSize": "10px", "fontFamily": FONT_FAMILY,
                "width": "30px", "display": "inline-block", "textAlign": "right",
                "marginRight": "8px",
            }),
            html.Span(ind.get("signal", ""), style={
                "color": ind.get("color", C["gray"]), "fontSize": "9px",
                "fontFamily": FONT_FAMILY, "fontWeight": "bold",
            }),
        ], style={"padding": "2px 0"})

    equity_indicators = [i for i in indicators if i.get("group") == "EQUITY"]
    fi_indicators = [i for i in indicators if i.get("group") == "FIXED INCOME"]

    equity_section = html.Div([
        html.Div("EQUITY SIGNALS", style={
            "color": C["cyan"], "fontSize": "9px", "fontWeight": "bold",
            "fontFamily": FONT_FAMILY, "letterSpacing": "1px",
            "marginBottom": "4px", "marginTop": "6px",
        }),
        *[_indicator_row(ind) for ind in equity_indicators],
    ])

    fi_section = html.Div([
        html.Div("FIXED INCOME SIGNALS", style={
            "color": C["cyan"], "fontSize": "9px", "fontWeight": "bold",
            "fontFamily": FONT_FAMILY, "letterSpacing": "1px",
            "marginBottom": "4px", "marginTop": "8px",
        }),
        *[_indicator_row(ind) for ind in fi_indicators],
    ])

    # --- Guidance ---
    guidance_section = html.Div([
        html.Div("GUIDANCE", style={
            "color": C["orange"], "fontSize": "9px", "fontWeight": "bold",
            "fontFamily": FONT_FAMILY, "letterSpacing": "1px",
            "marginTop": "10px", "marginBottom": "4px",
        }),
        html.Div(guidance, style={
            "color": C["white"], "fontSize": "10px", "fontFamily": FONT_FAMILY,
            "lineHeight": "1.4",
        }),
    ])

    # --- Assemble ---
    return html.Div([
        # Header row
        html.Div([
            html.Span("MARKET REGIME", style={
                "color": C["orange"], "fontSize": "12px", "fontWeight": "bold",
                "fontFamily": FONT_FAMILY, "letterSpacing": "1px",
            }),
            html.Span(regime, style={
                "color": color, "fontSize": "14px", "fontWeight": "bold",
                "fontFamily": FONT_FAMILY, "marginLeft": "auto",
            }),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "6px"}),
        html.Hr(style={"border": "none", "borderTop": f"2px solid {C['border']}", "margin": "0 0 8px 0"}),
        gauge_bar,
        equity_section,
        fi_section,
        guidance_section,
    ], style={
        **PANEL_STYLE,
        "borderLeft": f"3px solid {color}",
    })


def _build_sector_performance():
    """Two-panel layout: sector returns table + normalized sector chart."""
    sd = startup.sector_data
    sector_returns = sd.get("returns", {})
    sector_norm = sd.get("normalized", {})
    sector_colors = sd.get("colors", {})

    # Sector returns table
    table_rows = []
    for sector, ret in sorted(sector_returns.items(), key=lambda x: x[1], reverse=True):
        color = C["green"] if ret > 0 else C["red"]
        table_rows.append(
            html.Tr([
                html.Td(sector, style={
                    "color": C["white"], "fontSize": "10px", "fontFamily": FONT_FAMILY,
                    "padding": "3px 8px", "borderBottom": f"1px solid {C['border']}",
                }),
                html.Td(f"{ret:+.2%}", style={
                    "color": color, "fontSize": "10px", "fontFamily": FONT_FAMILY,
                    "padding": "3px 8px", "borderBottom": f"1px solid {C['border']}",
                    "textAlign": "right",
                }),
            ])
        )

    sector_table = html.Table([
        html.Thead(html.Tr([
            html.Th("SECTOR", style={
                "color": C["orange"], "fontSize": "9px", "fontFamily": FONT_FAMILY,
                "padding": "3px 8px", "textAlign": "left", "borderBottom": f"2px solid {C['border']}",
            }),
            html.Th("MEDIAN RET", style={
                "color": C["orange"], "fontSize": "9px", "fontFamily": FONT_FAMILY,
                "padding": "3px 8px", "textAlign": "right", "borderBottom": f"2px solid {C['border']}",
            }),
        ])),
        html.Tbody(table_rows),
    ], style={"width": "100%", "borderCollapse": "collapse"})

    # Normalized sector chart
    fig = go.Figure()
    if isinstance(sector_norm, dict):
        for sector_name, series in sector_norm.items():
            if hasattr(series, "index"):
                clr = sector_colors.get(sector_name, C["white"])
                fig.add_trace(go.Scatter(
                    x=series.index.tolist(), y=series.tolist(),
                    mode="lines", name=sector_name, line=dict(color=clr, width=1),
                ))

    # Zero line + bullish/bearish zone tints
    fig.add_hline(y=0, line_dash="solid", line_color=C["gray"], line_width=0.8, opacity=0.5,
                  annotation_text="FLAT", annotation_position="right",
                  annotation_font=dict(size=8, color=C["gray"]))
    fig.add_hrect(y0=0, y1=1e6, fillcolor="rgba(0,255,0,0.03)", line_width=0)
    fig.add_hrect(y0=-1e6, y1=0, fillcolor="rgba(255,68,68,0.03)", line_width=0)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=C["panel"],
        plot_bgcolor=C["bg"],
        font=dict(family=FONT_FAMILY, size=9, color=C["white"]),
        margin=dict(l=40, r=10, t=30, b=40),
        height=280,
        title=dict(text="SECTOR PERFORMANCE (NORMALIZED)", font=dict(color=C["orange"], size=11)),
        xaxis=dict(gridcolor=C["border"]),
        yaxis=dict(gridcolor=C["border"]),
        legend=dict(font=dict(size=8), bgcolor="rgba(0,0,0,0)",
                    orientation="h", yanchor="top", y=-0.15),
        showlegend=True,
    )

    return html.Div([
        html.Div("SECTOR PERFORMANCE", style=SECTION_HEADER),
        html.Div([
            html.Div(sector_table, style={
                **PANEL_STYLE, "flex": "1", "marginRight": "4px",
                "overflowY": "auto", "maxHeight": "300px",
            }),
            html.Div(
                dcc.Graph(figure=fig, config={"displayModeBar": False}),
                style={**PANEL_STYLE, "flex": "2", "marginLeft": "4px"},
            ),
        ], style={"display": "flex"}),
    ])


# ---------------------------------------------------------------------------
# Main layout function
# ---------------------------------------------------------------------------

def layout():
    """Build and return the full home page layout."""
    ts = datetime.now().strftime("%H:%M:%S")

    return html.Div([
        header_bar("HIGHBOURNE TERMINAL", "EQUITY SCANNER", ts),

        html.Div([
            _build_headline_bar(),
            _build_filter_bar(),
            _build_convergence_screen(),
            build_screener_table(),
            _build_gainers_losers_bar(),
            _build_movers_panel(),

            # Market movers scatter + risk dashboard + regime panel
            html.Div([
                html.Div(_build_scatter_plot(), style={"flex": "1", "marginRight": "4px"}),
                html.Div(build_risk_dashboard(), style={"flex": "1", "marginLeft": "4px", "marginRight": "4px"}),
                html.Div(_build_regime_panel(), style={"flex": "1", "marginLeft": "4px"}),
            ], style={"display": "flex", "marginBottom": "8px"}),

            _build_sector_performance(),
            function_key_bar("F1"),
        ], style={"padding": "0 12px"}),

        # Refresh infrastructure
        dcc.Interval(id="refresh-interval", interval=60 * 1000, n_intervals=0),
        dcc.Store(id="prev-prices", storage_type="memory"),
    ], style=CONTAINER_STYLE)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("screener-table-container", "children"),
    Output("ticker-count", "children"),
    Input("sector-filter", "value"),
    Input("view-filter", "value"),
)
def update_screener(sector, view):
    """Rebuild the screener table filtered by sector and valuation view."""
    df = startup.screener_df.copy()
    if sector and sector != "All":
        df = df[df["sector"] == sector]
    if view == "Cheap":
        df = df[df["z_score"] < -0.5].sort_values("z_score", ascending=True)
    elif view == "Rich":
        df = df[df["z_score"] > 0.5].sort_values("z_score", ascending=False)

    table = build_screener_table(df)
    return table.children, f"Showing {len(df)} tickers"


@callback(
    Output("gainers-list", "children"),
    Output("losers-list", "children"),
    Input("mover-interval", "n_intervals"),
    State("gainers-store", "data"),
    State("losers-store", "data"),
)
def rotate_movers(n, gainers_data, losers_data):
    """Rotate through top 10 movers, showing 5 at a time."""
    if not gainers_data:
        return [], []

    page = n % 2
    start = page * 5

    def _slice(items):
        return items[start:start + 5] if start < len(items) else items[:5]

    return (
        _mover_list(_slice(gainers_data), C["green"], is_gainer=True),
        _mover_list(_slice(losers_data), C["red"], is_gainer=False),
    )
