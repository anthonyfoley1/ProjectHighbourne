"""Screener table component -- custom HTML table with sparklines, range bars, and signal badges."""

from dash import html
import dash

import data.startup as startup
from theme import C, FONT_FAMILY
from utils.formatters import fmt_price


# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------
_CELL = {
    "padding": "4px 6px",
    "fontSize": "10px",
    "fontFamily": FONT_FAMILY,
    "borderBottom": "1px solid #111",
    "whiteSpace": "nowrap",
}

_HEADER = {
    **_CELL,
    "color": C["orange"],
    "fontSize": "8px",
    "fontWeight": "bold",
    "textTransform": "uppercase",
    "backgroundColor": "#1a2030",
    "borderBottom": f"1px solid {C['orange']}",
}


# ---------------------------------------------------------------------------
# Sub-components
# ---------------------------------------------------------------------------

def range_bar_52w(low, high, current):
    """Inline 52-week range bar with cyan position indicator."""
    if low is None or high is None or current is None or high == low:
        return html.Span("\u2014", style={"color": C["dim"]})
    pct = max(0, min(100, (current - low) / (high - low) * 100))
    return html.Div([
        html.Span(f"${low:.0f}", style={"fontSize": "7px", "color": C["dim"], "marginRight": "3px"}),
        html.Div(
            html.Div(style={
                "position": "absolute", "left": f"{pct}%", "top": "-2px",
                "width": "6px", "height": "10px", "backgroundColor": C["cyan"],
                "borderRadius": "1px", "transform": "translateX(-50%)",
            }),
            style={
                "position": "relative", "flex": "1", "height": "4px",
                "backgroundColor": "#333", "borderRadius": "2px",
            },
        ),
        html.Span(f"${high:.0f}", style={"fontSize": "7px", "color": C["dim"], "marginLeft": "3px"}),
    ], style={"display": "flex", "alignItems": "center", "width": "80px"})


def sparkline_svg(prices, color, width=60, height=16):
    """Generate an inline SVG sparkline as a raw html.Div (no iframe)."""
    if prices is None or len(prices) < 5:
        return ""
    p = prices.iloc[-90:].values
    if len(p) < 2:
        return ""
    mn, mx = p.min(), p.max()
    rng = mx - mn if mx != mn else 1
    points = []
    for i, v in enumerate(p):
        x = i / (len(p) - 1) * width
        y = height - (v - mn) / rng * (height - 2) - 1
        points.append(f"{x:.1f},{y:.1f}")
    pts = " ".join(points)
    svg = (
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1"/></svg>'
    )
    return html.Div(
        dash.html.Iframe(
            srcDoc=svg,
            style={"width": f"{width}px", "height": f"{height}px",
                   "border": "none", "overflow": "hidden"},
        )
    )


def signal_badge(signal):
    """Colored signal badge (BUY / SELL / CHEAP / RICH / FAIR)."""
    styles = {
        "BUY": {"backgroundColor": C["green"], "color": "#000",
                "padding": "1px 4px", "fontSize": "8px", "fontWeight": "bold", "borderRadius": "2px"},
        "SELL": {"backgroundColor": C["red"], "color": "#fff",
                 "padding": "1px 4px", "fontSize": "8px", "fontWeight": "bold", "borderRadius": "2px"},
        "CHEAP": {"border": f"1px solid {C['green']}", "color": C["green"],
                  "padding": "1px 4px", "fontSize": "8px", "fontWeight": "bold", "borderRadius": "2px"},
        "RICH": {"color": C["orange"], "fontSize": "8px", "fontWeight": "bold"},
    }
    style = styles.get(signal, {"color": C["dim"], "fontSize": "8px"})
    label = signal if signal in styles else "FAIR"
    return html.Span(label, style=style)


# ---------------------------------------------------------------------------
# Main table builder
# ---------------------------------------------------------------------------

def build_screener_table(df=None):
    """Build the full screener HTML table from *df* (defaults to startup.screener_df).

    Returns an ``html.Div`` whose ``id="screener-table-container"``.
    """
    if df is None:
        df = startup.screener_df
    if df.empty:
        return html.Div("No data", style={"color": C["dim"]}, id="screener-table-container")

    header = html.Tr([
        html.Th("", style={**_HEADER, "width": "20px"}),
        html.Th("TICKER", style=_HEADER),
        html.Th("NAME", style=_HEADER),
        html.Th("SECTOR", style=_HEADER),
        html.Th("RV", style=_HEADER),
        html.Th("Z-SCR", style=_HEADER),
        html.Th("RSI", style=_HEADER),
        html.Th("MACD", style=_HEADER),
        html.Th("1D %", style={**_HEADER, "textAlign": "right"}),
        html.Th("3D %", style={**_HEADER, "textAlign": "right"}),
        html.Th("SIGNAL", style={**_HEADER, "textAlign": "center"}),
        html.Th("PRICE", style={**_HEADER, "textAlign": "right"}),
        html.Th("MA", style=_HEADER),
        html.Th("52W RANGE", style={**_HEADER, "textAlign": "center"}),
        html.Th("90D", style={**_HEADER, "textAlign": "right"}),
    ])

    rows = []
    for _, r in df.head(50).iterrows():
        sym = r["symbol"]
        alert = r.get("alert_type")
        z = r["z_score"]
        ret1 = r["ret_1d"]
        ret3 = r["ret_3d"]

        # Row highlight for alerts
        row_style = {"cursor": "pointer"}
        if alert == "BUY":
            row_style["backgroundColor"] = "rgba(0,255,0,0.04)"
            row_style["borderLeft"] = f"3px solid {C['green']}"
        elif alert == "SELL":
            row_style["backgroundColor"] = "rgba(255,68,68,0.04)"
            row_style["borderLeft"] = f"3px solid {C['red']}"

        # Alert arrow icon
        icon = ""
        if alert in ("BUY", "SELL"):
            icon = html.Span("\u25ba", style={
                "color": C["green"] if alert == "BUY" else C["red"],
                "fontWeight": "bold",
            })

        # Conditional colors
        z_color = C["green"] if z < 0 else C["red"] if z > 0 else C["white"]
        rsi_val = r["rsi"]
        rsi_color = C["green"] if rsi_val <= 30 else C["red"] if rsi_val >= 70 else C["white"]
        macd = r["macd"]
        macd_color = C["green"] if macd == "Bull" else C["red"] if macd == "Bear" else C["dim"]
        r1_color = C["green"] if ret1 > 0 else C["red"] if ret1 < 0 else C["dim"]
        r3_color = C["green"] if ret3 > 0 else C["red"] if ret3 < 0 else C["dim"]
        ma = r["ma_trend"]
        ma_color = C["green"] if ma == "Above" else C["red"]

        # Sparkline
        prices = startup.price_cache.get(sym)
        # Sparkline color based on 90-day trend, not 1-day return
        if prices is not None and len(prices) >= 90:
            trend_90d = float(prices.iloc[-1]) - float(prices.iloc[-90])
        elif prices is not None and len(prices) >= 2:
            trend_90d = float(prices.iloc[-1]) - float(prices.iloc[0])
        else:
            trend_90d = 0
        spark_color = C["green"] if trend_90d >= 0 else C["red"]
        spark = sparkline_svg(prices, spark_color)

        row = html.Tr([
            html.Td(icon, style=_CELL),
            html.Td(
                html.A(sym, href=f"/detail/{sym}",
                       style={"color": "#fff", "fontWeight": "bold", "textDecoration": "none"}),
                style=_CELL,
            ),
            html.Td(r.get("name", ""), style={
                **_CELL, "color": C["gray"], "fontSize": "9px",
                "maxWidth": "120px", "overflow": "hidden", "textOverflow": "ellipsis",
            }),
            html.Td(r["sector"], style={**_CELL, "color": C["dim"], "fontSize": "9px"}),
            html.Td(r["rv_sig"], style={**_CELL, "color": C["green"] if z < 0 else C["orange"]}),
            html.Td(f"{z:.1f}", style={**_CELL, "color": z_color, "fontWeight": "bold"}),
            html.Td(f"{rsi_val:.0f}", style={
                **_CELL, "color": rsi_color,
                "fontWeight": "bold" if rsi_val <= 30 or rsi_val >= 70 else "normal",
            }),
            html.Td(macd, style={**_CELL, "color": macd_color}),
            html.Td(f"{ret1:+.1f}%", style={**_CELL, "color": r1_color, "textAlign": "right"}),
            html.Td(f"{ret3:+.1f}%", style={**_CELL, "color": r3_color, "textAlign": "right"}),
            html.Td(signal_badge(r["signal"]), style={**_CELL, "textAlign": "center"}),
            html.Td(fmt_price(r["price"]), style={**_CELL, "textAlign": "right"}),
            html.Td(ma, style={**_CELL, "color": ma_color}),
            html.Td(range_bar_52w(r.get("low_52w"), r.get("high_52w"), r["price"]),
                     style={**_CELL, "textAlign": "center"}),
            html.Td(spark, style={**_CELL, "textAlign": "right"}),
        ], style=row_style, id={"type": "screener-row", "index": sym})

        rows.append(row)

    return html.Div(
        html.Table(
            [html.Thead(header), html.Tbody(rows)],
            style={"width": "100%", "borderCollapse": "collapse"},
        ),
        id="screener-table-container",
        style={
            "backgroundColor": C["panel"],
            "border": f"1px solid {C['border']}",
            "borderRadius": "4px",
            "overflowX": "auto",
            "marginBottom": "4px",
        },
    )
