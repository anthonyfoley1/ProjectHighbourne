"""Home page layout for the Highbourne Terminal scanner."""

from datetime import datetime
from dash import html, dcc, dash_table, callback, Input, Output, State, no_update
import dash
import plotly.graph_objects as go
import numpy as np

import data.startup as startup
from theme import C, FONT_FAMILY, CONTAINER_STYLE, header_bar, function_key_bar, stat_card

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

VALUE_STYLE = {
    "color": C["white"],
    "fontSize": "12px",
    "fontWeight": "bold",
    "fontFamily": FONT_FAMILY,
}


# ---------------------------------------------------------------------------
# Helper: gauge bar (inline since theme.py doesn't have it yet)
# ---------------------------------------------------------------------------
def gauge_bar(value, min_val, max_val, color=C["orange"], label=""):
    """Horizontal gauge bar with a fill proportional to value."""
    pct = max(0, min(100, (value - min_val) / (max_val - min_val) * 100)) if max_val > min_val else 0
    return html.Div([
        html.Div(label, style=LABEL_STYLE) if label else None,
        html.Div(
            html.Div(style={
                "width": f"{pct:.0f}%",
                "height": "100%",
                "backgroundColor": color,
                "borderRadius": "2px",
            }),
            style={
                "width": "100%",
                "height": "8px",
                "backgroundColor": "#222",
                "borderRadius": "2px",
                "marginTop": "2px",
            },
        ),
    ], style={"marginBottom": "4px"})


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_alert_banner():
    """Orange-bordered alert strip showing up to 5 alerts."""
    df = startup.screener_df
    alerts_df = df[df["alert_type"].notna()].head(5) if not df.empty else df.head(0)
    n_alerts = len(alerts_df)

    alert_items = []
    for _, row in alerts_df.iterrows():
        color = C["green"] if row["alert_type"] == "BUY" else C["red"]
        alert_items.append(
            html.Span(
                f"{row['symbol']} {row['rv_sig']} z={row['z_score']} {row['alert_reason']}",
                style={
                    "color": color,
                    "fontSize": "10px",
                    "fontFamily": FONT_FAMILY,
                    "marginRight": "16px",
                    "whiteSpace": "nowrap",
                },
            )
        )

    return html.Div([
        html.Span(
            f"ALERTS {n_alerts}",
            style={
                "backgroundColor": C["orange"],
                "color": "#000",
                "padding": "2px 8px",
                "fontSize": "10px",
                "fontWeight": "bold",
                "fontFamily": FONT_FAMILY,
                "marginRight": "12px",
                "borderRadius": "2px",
                "whiteSpace": "nowrap",
            },
        ),
        html.Div(
            alert_items,
            style={
                "display": "flex",
                "flexWrap": "nowrap",
                "overflow": "hidden",
                "flex": "1",
            },
        ),
    ], style={
        "background": "#1a0a00",
        "border": f"1px solid {C['orange']}",
        "padding": "6px 10px",
        "display": "flex",
        "alignItems": "center",
        "marginBottom": "8px",
    })


def _build_filter_bar():
    """Sector dropdown, view toggle, and ticker count."""
    sector_options = [{"label": "All", "value": "All"}]
    if startup.universe is not None:
        sector_options += [
            {"label": s, "value": s} for s in startup.universe.sector_list
        ]

    dropdown_style = {
        "backgroundColor": C["bg"],
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
                    "color": C["white"],
                    "fontSize": "10px",
                    "fontFamily": FONT_FAMILY,
                    "marginRight": "12px",
                    "cursor": "pointer",
                },
            ),
        ], style={"display": "flex", "alignItems": "center", "marginRight": "20px"}),
        html.Span(
            id="ticker-count",
            style={
                "color": C["gray"],
                "fontSize": "10px",
                "fontFamily": FONT_FAMILY,
                "marginLeft": "auto",
            },
        ),
    ], style={
        **PANEL_STYLE,
        "display": "flex",
        "alignItems": "center",
    })


def _build_screener_table():
    """DataTable styled in Bloomberg colors."""
    cols = [
        {"name": "Symbol", "id": "symbol"},
        {"name": "Sector", "id": "sector"},
        {"name": "Price", "id": "price", "type": "numeric", "format": dash_table.FormatTemplate.money(2)},
        {"name": "Ratio", "id": "rv_sig"},
        {"name": "Z-Score", "id": "z_score", "type": "numeric"},
        {"name": "RSI", "id": "rsi", "type": "numeric"},
        {"name": "MACD", "id": "macd", "type": "numeric"},
        {"name": "1D Ret", "id": "ret_1d", "type": "numeric",
         "format": dash_table.FormatTemplate.percentage(2)},
        {"name": "3D Ret", "id": "ret_3d", "type": "numeric",
         "format": dash_table.FormatTemplate.percentage(2)},
        {"name": "Signal", "id": "signal"},
        {"name": "MA Trend", "id": "ma_trend"},
        {"name": "52W %", "id": "pct_52w", "type": "numeric",
         "format": dash_table.FormatTemplate.percentage(1)},
    ]

    return dash_table.DataTable(
        id="screener-table",
        columns=cols,
        data=startup.screener_df.to_dict("records") if not startup.screener_df.empty else [],
        sort_action="native",
        filter_action="none",
        page_size=25,
        style_table={
            "overflowX": "auto",
            "border": f"1px solid {C['border']}",
        },
        style_header={
            "backgroundColor": "#1a2030",
            "color": C["orange"],
            "fontWeight": "bold",
            "fontSize": "10px",
            "fontFamily": FONT_FAMILY,
            "textTransform": "uppercase",
            "border": f"1px solid {C['border']}",
        },
        style_cell={
            "backgroundColor": C["bg"],
            "color": C["white"],
            "fontSize": "10px",
            "fontFamily": FONT_FAMILY,
            "border": f"1px solid {C['border']}",
            "padding": "4px 8px",
            "textAlign": "left",
            "cursor": "pointer",
        },
        style_data_conditional=[
            # Green for negative z-scores (cheap)
            {
                "if": {
                    "filter_query": "{z_score} < 0",
                    "column_id": "z_score",
                },
                "color": C["green"],
            },
            # Red for positive z-scores (rich)
            {
                "if": {
                    "filter_query": "{z_score} > 0",
                    "column_id": "z_score",
                },
                "color": C["red"],
            },
            # Green for positive returns
            {
                "if": {
                    "filter_query": "{ret_1d} > 0",
                    "column_id": "ret_1d",
                },
                "color": C["green"],
            },
            {
                "if": {
                    "filter_query": "{ret_1d} < 0",
                    "column_id": "ret_1d",
                },
                "color": C["red"],
            },
            {
                "if": {
                    "filter_query": "{ret_3d} > 0",
                    "column_id": "ret_3d",
                },
                "color": C["green"],
            },
            {
                "if": {
                    "filter_query": "{ret_3d} < 0",
                    "column_id": "ret_3d",
                },
                "color": C["red"],
            },
        ],
        style_as_list_view=True,
    )


def _build_gainers_losers_bar():
    """Horizontal bar showing advancers / decliners / unchanged counts."""
    adv = startup.risk_stats.get("advancers", 0)
    dec = startup.risk_stats.get("decliners", 0)
    unch = startup.risk_stats.get("unchanged", 0)
    total = adv + dec + unch or 1

    return html.Div([
        html.Div(
            f"ADV {adv}",
            style={
                "width": f"{adv / total * 100:.0f}%",
                "backgroundColor": "#003300",
                "color": C["green"],
                "textAlign": "center",
                "fontSize": "10px",
                "fontFamily": FONT_FAMILY,
                "padding": "3px 0",
            },
        ),
        html.Div(
            f"UNCH {unch}",
            style={
                "width": f"{unch / total * 100:.0f}%",
                "backgroundColor": "#1a1a1a",
                "color": C["gray"],
                "textAlign": "center",
                "fontSize": "10px",
                "fontFamily": FONT_FAMILY,
                "padding": "3px 0",
            },
        ),
        html.Div(
            f"DEC {dec}",
            style={
                "width": f"{dec / total * 100:.0f}%",
                "backgroundColor": "#330000",
                "color": C["red"],
                "textAlign": "center",
                "fontSize": "10px",
                "fontFamily": FONT_FAMILY,
                "padding": "3px 0",
            },
        ),
    ], style={
        "display": "flex",
        "marginBottom": "8px",
        "border": f"1px solid {C['border']}",
    })


def _build_movers_panel():
    """Two side-by-side panels for top gainers and losers with rotation interval."""
    df = startup.screener_df
    if df.empty:
        gainers_data = []
        losers_data = []
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

    def _mover_list(items, color):
        return [
            html.Div(
                f"{it['symbol']:6s}  {it['ret_1d']:+.2%}  ${it['price']:.2f}",
                style={
                    "color": color,
                    "fontSize": "10px",
                    "fontFamily": FONT_FAMILY,
                    "padding": "1px 0",
                },
            )
            for it in items
        ]

    return html.Div([
        dcc.Interval(id="mover-interval", interval=5000, n_intervals=0),
        html.Div([
            # Gainers panel
            html.Div([
                html.Div("TOP GAINERS", style=SECTION_HEADER),
                html.Div(
                    id="gainers-list",
                    children=_mover_list(gainers_data[:5], C["green"]),
                ),
            ], style={**PANEL_STYLE, "flex": "1", "marginRight": "4px"}),
            # Losers panel
            html.Div([
                html.Div("TOP LOSERS", style=SECTION_HEADER),
                html.Div(
                    id="losers-list",
                    children=_mover_list(losers_data[:5], C["red"]),
                ),
            ], style={**PANEL_STYLE, "flex": "1", "marginLeft": "4px"}),
        ], style={"display": "flex"}),
        # Store full data for rotation callback
        dcc.Store(id="gainers-store", data=gainers_data),
        dcc.Store(id="losers-store", data=losers_data),
    ])


def _build_scatter_plot():
    """Market movers scatter: x=relative_volume (placeholder), y=ret_1d."""
    df = startup.screener_df
    fig = go.Figure()

    if not df.empty:
        # Compute a relative volume proxy from price_cache
        rel_vol = []
        for sym in df["symbol"]:
            prices = startup.price_cache.get(sym)
            if prices is not None and len(prices) > 20:
                recent_vol = float(np.std(prices.iloc[-5:]))
                avg_vol = float(np.std(prices.iloc[-60:]))
                rv = recent_vol / avg_vol if avg_vol > 0 else 1.0
            else:
                rv = 1.0
            rel_vol.append(rv)

        colors = [C["green"] if r > 0 else C["red"] for r in df["ret_1d"]]

        fig.add_trace(go.Scatter(
            x=rel_vol,
            y=df["ret_1d"].tolist(),
            mode="markers+text",
            marker=dict(color=colors, size=6, opacity=0.7),
            text=[
                sym if (abs(ret) > 0.03 or rv > 2) else ""
                for sym, ret, rv in zip(df["symbol"], df["ret_1d"], rel_vol)
            ],
            textposition="top center",
            textfont=dict(size=8, color=C["white"], family=FONT_FAMILY),
            hovertemplate="%{text}<br>RelVol: %{x:.2f}<br>Ret: %{y:.2%}<extra></extra>",
        ))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=C["panel"],
        plot_bgcolor=C["bg"],
        font=dict(family=FONT_FAMILY, size=10, color=C["white"]),
        margin=dict(l=40, r=20, t=30, b=40),
        height=300,
        title=dict(text="MARKET MOVERS", font=dict(color=C["orange"], size=11)),
        xaxis=dict(
            title="Relative Volatility",
            gridcolor=C["border"],
            zeroline=False,
        ),
        yaxis=dict(
            title="1D Return",
            tickformat=".1%",
            gridcolor=C["border"],
            zeroline=True,
            zerolinecolor=C["border"],
        ),
    )

    return dcc.Graph(figure=fig, config={"displayModeBar": False})


def _build_risk_dashboard():
    """Risk stats panel with VIX, F&G, breadth, and verdict badge."""
    rs = startup.risk_stats
    vix_val = rs.get("vix", {}).get("value") or 0
    vix_chg = rs.get("vix", {}).get("change") or 0
    fg = rs.get("fear_greed", {})
    fg_val = fg.get("value") or 50
    fg_label = fg.get("label", "N/A")
    breadth = rs.get("breadth", {})
    verdict = rs.get("verdict", {})
    verdict_label = verdict.get("label", "N/A") if isinstance(verdict, dict) else str(verdict)
    verdict_color = verdict.get("color", C["gray"]) if isinstance(verdict, dict) else C["gray"]

    def _stat_row(label, value, color=C["white"]):
        return html.Div([
            html.Span(label, style={**LABEL_STYLE, "width": "120px", "display": "inline-block"}),
            html.Span(str(value), style={**VALUE_STYLE, "color": color}),
        ], style={"padding": "2px 0"})

    # VIX color
    vix_color = C["green"] if vix_val < 20 else (C["yellow"] if vix_val < 30 else C["red"])

    return html.Div([
        html.Div("RISK DASHBOARD", style=SECTION_HEADER),
        _stat_row("VIX", f"{vix_val:.1f}  ({vix_chg:+.1f})" if vix_val else "N/A", vix_color),
        gauge_bar(vix_val, 0, 80, vix_color, "VIX LEVEL"),
        html.Hr(style={"borderColor": C["border"], "margin": "6px 0"}),
        _stat_row("FEAR & GREED", f"{fg_val} ({fg_label})",
                  C["green"] if fg_val > 50 else C["red"]),
        _stat_row("% > 200 SMA", f"{breadth.get('pct_above_200sma', 0):.0f}%"),
        _stat_row("% > 50 SMA", f"{breadth.get('pct_above_50sma', 0):.0f}%"),
        _stat_row("AVG RSI", f"{breadth.get('avg_rsi', 50):.1f}"),
        _stat_row("NEW HIGHS", str(rs.get("new_highs", 0)), C["green"]),
        _stat_row("NEW LOWS", str(rs.get("new_lows", 0)), C["red"]),
        html.Hr(style={"borderColor": C["border"], "margin": "6px 0"}),
        # Verdict badge
        html.Div([
            html.Span("VERDICT ", style=LABEL_STYLE),
            html.Span(
                verdict_label,
                style={
                    "backgroundColor": verdict_color,
                    "color": "#000",
                    "padding": "2px 10px",
                    "fontSize": "11px",
                    "fontWeight": "bold",
                    "fontFamily": FONT_FAMILY,
                    "borderRadius": "2px",
                },
            ),
        ], style={"marginTop": "4px"}),
    ], style=PANEL_STYLE)


def _build_sector_performance():
    """Two-panel layout: sector returns table + normalized sector chart."""
    sd = startup.sector_data
    sector_returns = sd.get("returns", {})
    sector_norm = sd.get("normalized", {})
    sector_colors = sd.get("colors", {})

    # -- Left: sector table --
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
                "padding": "3px 8px", "textAlign": "left",
                "borderBottom": f"2px solid {C['border']}",
            }),
            html.Th("MEDIAN RET", style={
                "color": C["orange"], "fontSize": "9px", "fontFamily": FONT_FAMILY,
                "padding": "3px 8px", "textAlign": "right",
                "borderBottom": f"2px solid {C['border']}",
            }),
        ])),
        html.Tbody(table_rows),
    ], style={"width": "100%", "borderCollapse": "collapse"})

    # -- Right: normalized sector performance chart --
    fig = go.Figure()
    if isinstance(sector_norm, dict):
        for sector_name, series in sector_norm.items():
            if hasattr(series, "index"):
                clr = sector_colors.get(sector_name, C["white"])
                fig.add_trace(go.Scatter(
                    x=series.index.tolist(),
                    y=series.tolist(),
                    mode="lines",
                    name=sector_name,
                    line=dict(color=clr, width=1),
                ))

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
        legend=dict(
            font=dict(size=8),
            bgcolor="rgba(0,0,0,0)",
            orientation="h",
            yanchor="top",
            y=-0.15,
        ),
        showlegend=True,
    )

    return html.Div([
        html.Div("SECTOR PERFORMANCE", style=SECTION_HEADER),
        html.Div([
            html.Div(sector_table, style={
                **PANEL_STYLE, "flex": "1", "marginRight": "4px", "overflowY": "auto",
                "maxHeight": "300px",
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
        # 1. Header
        header_bar("HIGHBOURNE TERMINAL", "EQUITY SCANNER", ts),

        html.Div([
            # 2. Alert Banner
            _build_alert_banner(),

            # 3. Filter Bar
            _build_filter_bar(),

            # 4. Screener Table
            _build_screener_table(),

            # 5. Gainers/Losers Bar
            _build_gainers_losers_bar(),

            # 6. Today's Movers
            _build_movers_panel(),

            # 7 & 8. Market Movers Scatter + Risk Dashboard (side by side)
            html.Div([
                html.Div(
                    _build_scatter_plot(),
                    style={"flex": "1", "marginRight": "4px"},
                ),
                html.Div(
                    _build_risk_dashboard(),
                    style={"flex": "1", "marginLeft": "4px"},
                ),
            ], style={"display": "flex", "marginBottom": "8px"}),

            # 9. Sector Performance
            _build_sector_performance(),

            # 10. Function Key Bar
            function_key_bar("F1"),
        ], style={"padding": "0 12px"}),

        # --- Cell flash animation infrastructure (Task 12) ---
        dcc.Interval(id="refresh-interval", interval=60 * 1000, n_intervals=0),
        dcc.Store(id="prev-prices", storage_type="memory"),
    ], style=CONTAINER_STYLE)


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

@callback(
    Output("screener-table", "data"),
    Output("ticker-count", "children"),
    Input("sector-filter", "value"),
    Input("view-filter", "value"),
)
def update_screener(sector, view):
    """Filter the screener table by sector and valuation view."""
    df = startup.screener_df.copy()
    if sector and sector != "All":
        df = df[df["sector"] == sector]
    if view == "Cheap":
        df = df[df["z_score"] < 0]
    elif view == "Rich":
        df = df[df["z_score"] > 0]
    return df.to_dict("records"), f"Showing {len(df)} tickers"


@callback(
    Output("url", "pathname"),
    Input("screener-table", "active_cell"),
    State("screener-table", "data"),
    prevent_initial_call=True,
)
def navigate_to_detail(active_cell, data):
    """Navigate to detail page when a row is clicked."""
    if active_cell:
        row = data[active_cell["row"]]
        return f"/detail/{row['symbol']}"
    return no_update


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

    # Alternate between first 5 and last 5
    page = n % 2
    start = page * 5

    def _make_items(items, color):
        sliced = items[start:start + 5] if start < len(items) else items[:5]
        return [
            html.Div(
                f"{it['symbol']:6s}  {it['ret_1d']:+.2%}  ${it['price']:.2f}",
                style={
                    "color": color,
                    "fontSize": "10px",
                    "fontFamily": FONT_FAMILY,
                    "padding": "1px 0",
                },
            )
            for it in sliced
        ]

    return _make_items(gainers_data, C["green"]), _make_items(losers_data, C["red"])


# TODO: implement price comparison callback for cell flash
# This callback should:
#   - fire on Input("refresh-interval", "n_intervals")
#   - compare current prices against State("prev-prices", "data")
#   - apply flash-green / flash-red CSS classes to changed cells
#   - update prev-prices store with the new snapshot
