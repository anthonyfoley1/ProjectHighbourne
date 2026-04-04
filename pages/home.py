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
    all_news = []

    # Stock-specific news
    for article in getattr(startup, "news_cache", []):
        age = article.get("age", "")
        all_news.append(
            html.Span([
                html.Span(article["symbol"], style={"color": C["yellow"], "fontWeight": "bold", "marginRight": "4px"}),
                html.A(article["title"], href=article["link"], target="_blank",
                       style={"color": "#6699cc", "textDecoration": "none"}),
                html.Span(f"  {article['publisher']}", style={"color": "#555"}),
                html.Span(f"  {age}", style={"color": "#444"}) if age else None,
            ], style={"marginRight": "40px", "whiteSpace": "nowrap", "fontSize": "10px"})
        )

    # General market news (Finnhub)
    for article in getattr(startup, "market_news_cache", []):
        headline = article.get("headline", article.get("title", ""))
        source = article.get("source", article.get("publisher", ""))
        url = article.get("url", article.get("link", "#"))
        age = article.get("age", "")
        if headline:
            all_news.append(
                html.Span([
                    html.Span("\u25cf ", style={"color": C["cyan"], "fontSize": "6px"}),
                    html.A(headline, href=url, target="_blank",
                           style={"color": "#88aacc", "textDecoration": "none"}),
                    html.Span(f"  {source}", style={"color": "#555"}),
                    html.Span(f"  {age}", style={"color": "#444"}) if age else None,
                ], style={"marginRight": "40px", "whiteSpace": "nowrap", "fontSize": "10px"})
            )

    news_row = html.Div([
        html.Div(
            html.Div(all_news + all_news, style={
                "display": "flex", "animation": "marquee 80s linear infinite", "whiteSpace": "nowrap",
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
            build_screener_table(),
            _build_gainers_losers_bar(),
            _build_movers_panel(),

            # Market movers scatter + risk dashboard side by side
            html.Div([
                html.Div(_build_scatter_plot(), style={"flex": "1", "marginRight": "4px"}),
                html.Div(build_risk_dashboard(), style={"flex": "1", "marginLeft": "4px"}),
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
        df = df[df["z_score"] < 0]
    elif view == "Rich":
        df = df[df["z_score"] > 0]

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
