"""Risk dashboard panel component for the Highbourne Terminal home page."""

from dash import html

import data.startup as startup
from theme import C, FONT_FAMILY


# ---------------------------------------------------------------------------
# Style constants
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stat_row(label, value, color=C["white"]):
    return html.Div([
        html.Span(label, style={**LABEL_STYLE, "width": "120px", "display": "inline-block"}),
        html.Span(str(value), style={**VALUE_STYLE, "color": color}),
    ], style={"padding": "2px 0"})


def gauge_bar(value, min_val, max_val, color=C["orange"], label=""):
    """Horizontal gauge bar with fill proportional to value."""
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
# Public builder
# ---------------------------------------------------------------------------

def build_risk_dashboard():
    """Build the risk dashboard panel (VIX, F&G, breadth, verdict)."""
    rs = startup.risk_stats
    vix_val = rs.get("vix", {}).get("value") or 0
    vix_chg = rs.get("vix", {}).get("change") or 0
    fg = rs.get("fear_greed", {})
    fg_val = fg.get("value") or 50
    fg_label = fg.get("label", "N/A")
    breadth = rs.get("breadth", {})
    verdict = rs.get("verdict", {})
    verdict_label = verdict.get("level", verdict.get("label", "N/A")) if isinstance(verdict, dict) else str(verdict)
    verdict_color = verdict.get("color", C["gray"]) if isinstance(verdict, dict) else C["gray"]

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
        html.Div([
            html.Span("VERDICT ", style=LABEL_STYLE),
            html.Span(
                verdict_label,
                style={
                    "backgroundColor": verdict_color,
                    "color": "#fff" if verdict_color in ("#880000", "#ff4444") else "#000",
                    "padding": "2px 10px",
                    "fontSize": "11px",
                    "fontWeight": "bold",
                    "fontFamily": FONT_FAMILY,
                    "borderRadius": "2px",
                },
            ),
        ], style={"marginTop": "4px"}),
    ], style=PANEL_STYLE)
