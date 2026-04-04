"""ProjectHighbourne — Bloomberg-style Valuation Dashboard."""

import os
os.environ["DASH_DISABLE_JUPYTER"] = "1"

import dash
from dash import dcc, html, dash_table, callback_context
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.loader import load_tickers, load_market_data, compute_all_ratios, get_filing_dates
from models.ticker import Ticker, Universe

# ---------------------------------------------------------------------------
# Bloomberg color palette
# ---------------------------------------------------------------------------
C = {
    "bg":       "#0b0e11",
    "panel":    "#141820",
    "panel2":   "#1a1f2b",
    "border":   "#2a2f3a",
    "text":     "#d4d4d4",
    "dim":      "#6b7280",
    "orange":   "#ff8c00",
    "yellow":   "#ffd700",
    "green":    "#00c853",
    "red":      "#ff4444",
    "cyan":     "#00bcd4",
    "blue":     "#4a9eff",
    "white":    "#f0f0f0",
    "line":     "#e8e8e8",
}
FONT = "'JetBrains Mono', 'Roboto Mono', 'Consolas', monospace"

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("Loading tickers...")
df_tickers = load_tickers()
ticker_sector = dict(zip(df_tickers["Ticker"], df_tickers["Sector"]))

print("Loading market data (5Y)...")
mktcap, close_prices = load_market_data(years=5)

print("Computing ratios...")
ratio_dfs = compute_all_ratios(mktcap)

print("Building universe...")
universe = Universe()
all_symbols = set()
for df in ratio_dfs.values():
    all_symbols.update(df.columns)

for symbol in sorted(all_symbols):
    t = Ticker(symbol, sector=ticker_sector.get(symbol))
    for ratio_name, df in ratio_dfs.items():
        if symbol in df.columns:
            t.set_ratio(ratio_name, df[symbol])
    universe.add_ticker(t)

RATIO_NAMES = ["P/B", "P/S", "P/E", "EV/EBITDA"]
WINDOW_NAMES = ["5Y", "2Y", "6M"]
WINDOW_DAYS = Universe.WINDOWS

print(f"Ready. {len(universe.symbols)} tickers loaded.")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stat_card(label, value, color=None, small=False):
    color = color or C["text"]
    return html.Div(style={
        "padding": "8px 14px",
        "backgroundColor": C["panel2"],
        "borderRadius": "6px",
        "border": f"1px solid {C['border']}",
        "minWidth": "90px",
    }, children=[
        html.Div(label, style={"fontSize": "10px", "color": C["dim"], "marginBottom": "2px", "letterSpacing": "0.5px"}),
        html.Div(value, style={"fontSize": "15px" if not small else "13px", "fontWeight": "700", "color": color}),
    ])


def metric_row(label, value, color=None):
    return html.Div(style={"display": "flex", "justifyContent": "space-between", "padding": "4px 0",
                           "borderBottom": f"1px solid {C['border']}"}, children=[
        html.Span(label, style={"color": C["dim"], "fontSize": "11px"}),
        html.Span(value, style={"color": color or C["text"], "fontSize": "11px", "fontWeight": "600"}),
    ])


def format_market_cap(val):
    if pd.isna(val) or val == 0:
        return "N/A"
    if abs(val) >= 1e12:
        return f"${val/1e12:.1f}T"
    if abs(val) >= 1e9:
        return f"${val/1e9:.1f}B"
    if abs(val) >= 1e6:
        return f"${val/1e6:.0f}M"
    return f"${val:,.0f}"

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = dash.Dash(
    __name__,
    suppress_callback_exceptions=True,
    title="ProjectHighbourne",
)


def _tab_style():
    return {
        "backgroundColor": "transparent", "border": "none",
        "color": C["dim"], "fontFamily": FONT, "fontSize": "12px",
        "padding": "8px 16px", "fontWeight": "500",
    }

def _tab_selected():
    return {
        "backgroundColor": C["panel2"], "border": "none",
        "borderBottom": f"2px solid {C['orange']}", "color": C["orange"],
        "fontFamily": FONT, "fontSize": "12px", "padding": "8px 16px", "fontWeight": "700",
    }


app.layout = html.Div(style={
    "backgroundColor": C["bg"], "color": C["text"], "fontFamily": FONT,
    "minHeight": "100vh",
}, children=[

    # ---- Top nav bar ----
    html.Div(style={
        "display": "flex", "alignItems": "center", "justifyContent": "space-between",
        "padding": "12px 24px", "backgroundColor": C["panel"],
        "borderBottom": f"2px solid {C['orange']}",
    }, children=[
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "12px"}, children=[
            html.Div("PH", style={
                "backgroundColor": C["orange"], "color": C["bg"], "fontWeight": "900",
                "padding": "4px 8px", "borderRadius": "4px", "fontSize": "14px",
            }),
            html.Span("ProjectHighbourne", style={"fontSize": "16px", "fontWeight": "600", "color": C["white"]}),
            html.Span("Relative Value Monitor", style={"fontSize": "11px", "color": C["dim"], "marginLeft": "8px"}),
        ]),
        html.Div(style={"display": "flex", "gap": "4px"}, children=[
            dcc.Tabs(id="main-tabs", value="rv-tab", style={"height": "36px"}, children=[
                dcc.Tab(label="RV Chart", value="rv-tab", style=_tab_style(), selected_style=_tab_selected()),
                dcc.Tab(label="Screener", value="screener-tab", style=_tab_style(), selected_style=_tab_selected()),
                dcc.Tab(label="Sectors", value="sector-tab", style=_tab_style(), selected_style=_tab_selected()),
            ]),
        ]),
    ]),

    # ---- Tab content ----
    html.Div(id="tab-content", style={"padding": "20px 24px"}),
])


# ---------------------------------------------------------------------------
# Tab routing
# ---------------------------------------------------------------------------

@app.callback(Output("tab-content", "children"), Input("main-tabs", "value"))
def render_tab(tab):
    if tab == "rv-tab":
        return _rv_layout()
    elif tab == "screener-tab":
        return _screener_layout()
    elif tab == "sector-tab":
        return _sector_layout()
    return html.Div("Not found")


# ===========================================================================
# TAB 1: RV CHART
# ===========================================================================

def _rv_layout():
    return html.Div([
        # Controls
        html.Div(style={"display": "flex", "gap": "16px", "marginBottom": "16px", "flexWrap": "wrap", "alignItems": "flex-end"}, children=[
            html.Div([
                html.Label("TICKER", style={"color": C["dim"], "fontSize": "10px", "display": "block", "marginBottom": "4px", "letterSpacing": "1px"}),
                dcc.Dropdown(id="rv-ticker", options=[{"label": s, "value": s} for s in universe.symbols],
                             value="ADBE", searchable=True,
                             style={"width": "160px", "backgroundColor": C["panel"], "fontFamily": FONT}),
            ]),
            html.Div([
                html.Label("RATIO", style={"color": C["dim"], "fontSize": "10px", "display": "block", "marginBottom": "4px", "letterSpacing": "1px"}),
                dcc.Dropdown(id="rv-ratio", options=[{"label": r, "value": r} for r in RATIO_NAMES],
                             value="P/E", style={"width": "140px", "backgroundColor": C["panel"], "fontFamily": FONT}),
            ]),
            html.Div([
                html.Label("WINDOW", style={"color": C["dim"], "fontSize": "10px", "display": "block", "marginBottom": "4px", "letterSpacing": "1px"}),
                dcc.RadioItems(id="rv-window", options=[{"label": w, "value": w} for w in WINDOW_NAMES],
                               value="2Y", inline=True,
                               inputStyle={"marginRight": "4px"},
                               labelStyle={"marginRight": "14px", "color": C["text"], "fontSize": "13px", "fontWeight": "500"}),
            ]),
        ]),

        # Two-column: chart + sidebar
        html.Div(style={"display": "flex", "gap": "20px"}, children=[
            # Chart column
            html.Div(style={"flex": "1"}, children=[
                # Stats cards row
                html.Div(id="rv-stats", style={
                    "display": "flex", "gap": "8px", "marginBottom": "12px", "flexWrap": "wrap",
                }),
                # Chart
                dcc.Graph(id="rv-chart", config={"displayModeBar": False}, style={"height": "460px"}),
            ]),

            # Sidebar: ticker info
            html.Div(id="rv-sidebar", style={
                "width": "260px", "flexShrink": "0",
                "backgroundColor": C["panel"], "borderRadius": "8px",
                "border": f"1px solid {C['border']}", "padding": "16px",
            }),
        ]),
    ])


@app.callback(
    [Output("rv-stats", "children"), Output("rv-chart", "figure"), Output("rv-sidebar", "children")],
    [Input("rv-ticker", "value"), Input("rv-ratio", "value"), Input("rv-window", "value")],
)
def update_rv(symbol, ratio_name, window_name):
    ticker = universe.get(symbol)
    empty_fig = go.Figure()
    empty_fig.update_layout(paper_bgcolor=C["bg"], plot_bgcolor=C["bg"], font=dict(family=FONT, color=C["dim"]),
                            annotations=[dict(text="No data", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font=dict(size=18))])

    if ticker is None:
        return [], empty_fig, html.Div("Select a ticker")

    window_days = WINDOW_DAYS[window_name]
    series = ticker.window_series(ratio_name, window_days)
    st = ticker.stats(ratio_name, window_days)

    if st is None or series.empty:
        return [stat_card("Status", "No data", C["dim"])], empty_fig, _build_sidebar(symbol, ticker)

    mean, std, current, z = st["mean"], st["std"], st["current"], st["z_score"]

    # ---- Stats cards ----
    z_color = C["green"] if z < -0.5 else C["red"] if z > 0.5 else C["text"]
    diff_pct = (current - mean) / mean * 100 if mean else 0
    diff_color = C["green"] if diff_pct < 0 else C["red"]
    stats = [
        stat_card("CURRENT", f"{current:.2f}x", C["white"]),
        stat_card("HIST AVG", f"{mean:.2f}x", C["orange"]),
        stat_card("DIFF", f"{diff_pct:+.1f}%", diff_color),
        stat_card("# SD", f"{z:+.2f}", z_color),
        stat_card("LOW", f"{st['low']:.2f}x"),
        stat_card("HIGH", f"{st['high']:.2f}x"),
    ]

    # ---- Chart ----
    fig = go.Figure()

    # +/- 2σ band (faint)
    fig.add_hrect(y0=mean - 2 * std, y1=mean + 2 * std, fillcolor="rgba(255,215,0,0.03)", line_width=0)

    # +/- 1σ lines (yellow dashed)
    for y_val, label in [(mean + std, f"+1σ {mean+std:.1f}"), (mean - std, f"-1σ {mean-std:.1f}")]:
        fig.add_hline(y=y_val, line_dash="dash", line_color=C["yellow"], line_width=1, opacity=0.5,
                      annotation_text=label, annotation_position="right",
                      annotation_font=dict(size=9, color=C["yellow"]))

    # Mean line (orange dashed)
    fig.add_hline(y=mean, line_dash="dash", line_color=C["orange"], line_width=1.5, opacity=0.7,
                  annotation_text=f"μ {mean:.2f}", annotation_position="right",
                  annotation_font=dict(size=10, color=C["orange"]))

    # Main ratio line (white)
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values, mode="lines",
        line=dict(color=C["line"], width=1.8),
        name=ratio_name,
        hovertemplate="%{x|%b %d, %Y}<br>" + ratio_name + ": %{y:.2f}x<extra></extra>",
    ))

    # Current value dot
    fig.add_trace(go.Scatter(
        x=[series.index[-1]], y=[current], mode="markers",
        marker=dict(color=C["cyan"], size=9, line=dict(width=2, color=C["bg"])),
        name=f"Current: {current:.2f}x", hoverinfo="skip",
    ))

    # ---- Earnings "E" markers ----
    filings = get_filing_dates(symbol)
    window_start = series.index.min()
    for f in filings:
        f_date = pd.Timestamp(f["date"])
        if f_date < window_start or f_date > series.index.max():
            continue
        # Find the ratio value closest to this filing date
        idx = series.index.get_indexer([f_date], method="nearest")[0]
        if idx < 0 or idx >= len(series):
            continue
        y_val = series.iloc[idx]
        if pd.isna(y_val):
            continue

        color = C["green"] if f["form"] == "10-K" else C["green"]
        fig.add_trace(go.Scatter(
            x=[f_date], y=[y_val],
            mode="markers+text",
            marker=dict(color=color, size=14, symbol="square", opacity=0.85,
                        line=dict(width=1, color=C["bg"])),
            text=["E"],
            textposition="middle center",
            textfont=dict(size=8, color=C["bg"], family=FONT),
            hovertemplate=f"{f['form']} filed %{{x|%b %d, %Y}}<extra></extra>",
            showlegend=False,
        ))

    # Auto-scale axes tightly
    y_min = max(0, series.min() * 0.9, mean - 2.5 * std)
    y_max = max(series.max(), mean + 2.5 * std) * 1.05

    fig.update_layout(
        paper_bgcolor=C["bg"], plot_bgcolor=C["bg"],
        font=dict(family=FONT, color=C["text"], size=11),
        title=dict(text=f"{symbol}  {ratio_name}", font=dict(size=16, color=C["white"]), x=0.01, y=0.97),
        xaxis=dict(gridcolor=C["border"], gridwidth=0.5, zeroline=False, showline=False,
                   range=[series.index.min(), series.index.max()],
                   tickfont=dict(size=10, color=C["dim"])),
        yaxis=dict(gridcolor=C["border"], gridwidth=0.5, zeroline=False, showline=False,
                   range=[y_min, y_max], ticksuffix="x",
                   tickfont=dict(size=10, color=C["dim"])),
        margin=dict(l=55, r=80, t=40, b=40),
        showlegend=False,
        hovermode="x unified",
    )

    sidebar = _build_sidebar(symbol, ticker)
    return stats, fig, sidebar


def _build_sidebar(symbol, ticker):
    """Build the right sidebar with ticker info and key metrics."""
    sector = ticker.sector or "Unknown"

    # Current market cap
    mc_val = mktcap[symbol].dropna().iloc[-1] if symbol in mktcap.columns else np.nan
    price_val = close_prices[symbol].dropna().iloc[-1] if symbol in close_prices.columns else np.nan

    # All ratio stats for this ticker (2Y window)
    ratio_cards = []
    for rn in RATIO_NAMES:
        st = ticker.stats(rn, WINDOW_DAYS["2Y"])
        if st:
            z = st["z_score"]
            z_color = C["green"] if z < -0.5 else C["red"] if z > 0.5 else C["dim"]
            ratio_cards.append(
                metric_row(rn, f"{st['current']:.1f}x  (z={z:+.1f})", z_color)
            )

    return html.Div([
        # Ticker header
        html.Div(symbol, style={"fontSize": "22px", "fontWeight": "800", "color": C["cyan"], "marginBottom": "2px"}),
        html.Div(sector, style={"fontSize": "11px", "color": C["dim"], "marginBottom": "16px"}),

        # Key metrics
        metric_row("Price", f"${price_val:.2f}" if not pd.isna(price_val) else "N/A"),
        metric_row("Market Cap", format_market_cap(mc_val)),
        html.Div(style={"height": "12px"}),

        # All ratios summary
        html.Div("VALUATION (2Y)", style={"fontSize": "10px", "color": C["orange"], "letterSpacing": "1px",
                                           "marginBottom": "6px", "fontWeight": "700"}),
        *ratio_cards,
    ])


# ===========================================================================
# TAB 2: SCREENER
# ===========================================================================

def _screener_layout():
    return html.Div([
        html.Div(style={"display": "flex", "gap": "16px", "marginBottom": "16px", "flexWrap": "wrap", "alignItems": "flex-end"}, children=[
            html.Div([
                html.Label("RATIO", style={"color": C["dim"], "fontSize": "10px", "display": "block", "marginBottom": "4px", "letterSpacing": "1px"}),
                dcc.Dropdown(id="scr-ratio", options=[{"label": r, "value": r} for r in RATIO_NAMES],
                             value="P/E", style={"width": "150px", "backgroundColor": C["panel"], "fontFamily": FONT}),
            ]),
            html.Div([
                html.Label("WINDOW", style={"color": C["dim"], "fontSize": "10px", "display": "block", "marginBottom": "4px", "letterSpacing": "1px"}),
                dcc.RadioItems(id="scr-window", options=[{"label": w, "value": w} for w in WINDOW_NAMES],
                               value="2Y", inline=True,
                               inputStyle={"marginRight": "4px"},
                               labelStyle={"marginRight": "14px", "color": C["text"], "fontSize": "13px"}),
            ]),
            html.Div([
                html.Label("SECTOR", style={"color": C["dim"], "fontSize": "10px", "display": "block", "marginBottom": "4px", "letterSpacing": "1px"}),
                dcc.Dropdown(id="scr-sector",
                             options=[{"label": "All Sectors", "value": "ALL"}] + [{"label": s, "value": s} for s in universe.sector_list],
                             value="ALL", style={"width": "220px", "backgroundColor": C["panel"], "fontFamily": FONT}),
            ]),
            html.Div([
                html.Label("VIEW", style={"color": C["dim"], "fontSize": "10px", "display": "block", "marginBottom": "4px", "letterSpacing": "1px"}),
                dcc.RadioItems(id="scr-view",
                               options=[{"label": "Cheapest", "value": "cheap"}, {"label": "Richest", "value": "rich"}],
                               value="cheap", inline=True,
                               inputStyle={"marginRight": "4px"},
                               labelStyle={"marginRight": "14px", "color": C["text"], "fontSize": "13px"}),
            ]),
        ]),

        dash_table.DataTable(
            id="scr-table",
            columns=[
                {"name": "Ticker", "id": "Ticker"},
                {"name": "Sector", "id": "Sector"},
                {"name": "Current", "id": "Current", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "Mean", "id": "Mean", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "Std", "id": "Std", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "Z-Score", "id": "Z-Score", "type": "numeric", "format": {"specifier": "+.2f"}},
                {"name": "Low", "id": "Low", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "High", "id": "High", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "% from Mean", "id": "% from Mean", "type": "numeric", "format": {"specifier": "+.1f"}},
            ],
            page_size=30,
            sort_action="native",
            filter_action="native",
            style_as_list_view=True,
            style_header={
                "backgroundColor": C["panel2"], "color": C["orange"], "fontWeight": "700",
                "fontSize": "11px", "border": f"1px solid {C['border']}", "fontFamily": FONT,
                "letterSpacing": "0.5px",
            },
            style_cell={
                "backgroundColor": C["bg"], "color": C["text"], "border": f"1px solid {C['border']}",
                "fontSize": "12px", "fontFamily": FONT, "padding": "8px 12px", "textAlign": "right",
            },
            style_cell_conditional=[
                {"if": {"column_id": "Ticker"}, "textAlign": "left", "fontWeight": "700", "color": C["cyan"]},
                {"if": {"column_id": "Sector"}, "textAlign": "left", "color": C["dim"]},
            ],
            style_data_conditional=[
                {"if": {"filter_query": "{Z-Score} < -1.5"}, "color": C["green"]},
                {"if": {"filter_query": "{Z-Score} > 1.5"}, "color": C["red"]},
                {"if": {"state": "active"}, "backgroundColor": C["panel2"], "border": f"1px solid {C['cyan']}"},
            ],
            style_filter={
                "backgroundColor": C["panel"], "color": C["text"], "fontFamily": FONT,
            },
        ),
    ])


@app.callback(Output("scr-table", "data"),
              [Input("scr-ratio", "value"), Input("scr-window", "value"),
               Input("scr-sector", "value"), Input("scr-view", "value")])
def update_screener(ratio, window, sector, view):
    df = universe.screener(ratio, window)
    if df.empty:
        return []
    if sector != "ALL":
        df = df[df["Sector"] == sector]
    if view == "rich":
        df = df.sort_values("Z-Score", ascending=False)
    return df.head(50).to_dict("records")


# ===========================================================================
# TAB 3: SECTORS
# ===========================================================================

def _sector_layout():
    return html.Div([
        html.Div(style={"display": "flex", "gap": "16px", "marginBottom": "20px", "alignItems": "flex-end"}, children=[
            html.Div([
                html.Label("RATIO", style={"color": C["dim"], "fontSize": "10px", "display": "block", "marginBottom": "4px", "letterSpacing": "1px"}),
                dcc.Dropdown(id="sec-ratio", options=[{"label": r, "value": r} for r in RATIO_NAMES],
                             value="P/E", style={"width": "150px", "backgroundColor": C["panel"], "fontFamily": FONT}),
            ]),
            html.Div([
                html.Label("WINDOW", style={"color": C["dim"], "fontSize": "10px", "display": "block", "marginBottom": "4px", "letterSpacing": "1px"}),
                dcc.RadioItems(id="sec-window", options=[{"label": w, "value": w} for w in WINDOW_NAMES],
                               value="2Y", inline=True,
                               inputStyle={"marginRight": "4px"},
                               labelStyle={"marginRight": "14px", "color": C["text"], "fontSize": "13px"}),
            ]),
        ]),

        dash_table.DataTable(
            id="sec-table",
            columns=[
                {"name": "Sector", "id": "Sector"},
                {"name": "Median", "id": "Median", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "25th Pctl", "id": "25th", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "75th Pctl", "id": "75th", "type": "numeric", "format": {"specifier": ".2f"}},
                {"name": "# Tickers", "id": "Count", "type": "numeric"},
            ],
            sort_action="native",
            style_as_list_view=True,
            style_header={
                "backgroundColor": C["panel2"], "color": C["orange"], "fontWeight": "700",
                "fontSize": "11px", "border": f"1px solid {C['border']}", "fontFamily": FONT,
            },
            style_cell={
                "backgroundColor": C["bg"], "color": C["text"], "border": f"1px solid {C['border']}",
                "fontSize": "12px", "fontFamily": FONT, "padding": "8px 12px", "textAlign": "right",
            },
            style_cell_conditional=[
                {"if": {"column_id": "Sector"}, "textAlign": "left", "fontWeight": "600", "color": C["cyan"]},
            ],
        ),
    ])


@app.callback(Output("sec-table", "data"),
              [Input("sec-ratio", "value"), Input("sec-window", "value")])
def update_sectors(ratio, window):
    df = universe.sector_medians(ratio, window)
    if df.empty:
        return []
    return df.to_dict("records")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=8050)
