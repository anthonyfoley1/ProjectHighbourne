"""Bloomberg-terminal-inspired theme constants and Dash component factories.

All visual styling lives in assets/style.css. This module provides:
- Color constants (for Python-side conditional coloring)
- Component factories that use CSS className instead of inline styles
"""

from dash import html, dcc

# ---------------------------------------------------------------------------
# Color palette (used in Python for conditional logic, not for styling)
# ---------------------------------------------------------------------------
C = {
    "bg": "#000000",
    "panel": "#0a0a0a",
    "header": "#1a1a1a",
    "border": "#333333",
    "orange": "#ff8c00",
    "green": "#00ff00",
    "red": "#ff4444",
    "yellow": "#ffff00",
    "white": "#e0e0e0",
    "gray": "#999999",
    "dim": "#777777",
    "cyan": "#00bcd4",
    "purple": "#bb86fc",
    "pink": "#e91e63",
}

FONT_FAMILY = "'Lucida Console', 'Monaco', 'Courier New', monospace"

# Keep these for backward compat during migration — components can use className instead
STYLESHEET = {"fontFamily": FONT_FAMILY, "backgroundColor": C["bg"], "color": C["white"], "fontSize": "11px", "padding": "8px"}
CONTAINER_STYLE = {"maxWidth": "1100px", "margin": "0 auto"}
FLASH_CSS = ""  # Now in assets/style.css


# ---------------------------------------------------------------------------
# Component factories
# ---------------------------------------------------------------------------

def header_bar(title, subtitle="", timestamp=""):
    """Top header bar with title, subtitle, search input, and live clock."""
    return html.Div(className="bbg-top-header", children=[
        html.Span(title, className="title"),
        html.Span(subtitle, className="subtitle"),
        dcc.Input(id="search-bar", placeholder="Search ticker...",
                  style={"backgroundColor": "#000", "color": C["yellow"],
                         "border": f"1px solid {C['border']}", "padding": "3px 8px",
                         "fontSize": "11px", "fontFamily": FONT_FAMILY,
                         "marginRight": "12px", "outline": "none", "width": "140px"}),
        html.Span(id="live-clock", children=timestamp, style={"color": C["gray"], "fontSize": "10px"}),
        dcc.Interval(id="clock-interval", interval=1000, n_intervals=0),
    ])


def function_key_bar(active_key="F1"):
    """Bottom function-key bar (F1-F4)."""
    keys = [("F1", "HOME"), ("F2", "SCREENER"), ("F3", "SECTORS"), ("F4", "DETAIL")]
    children = []
    for fk, label in keys:
        cls = "bbg-fn-key active" if fk == active_key else "bbg-fn-key"
        children.append(html.Span(f"{fk} {label}", className=cls))
    children.append(html.Span("HIGHBOURNE v2.0", style={"marginLeft": "auto", "color": C["orange"], "fontSize": "10px"}))
    return html.Div(className="bbg-fn-bar", children=children)


def stat_card(label, value, color=None):
    """Small stat card with uppercase label and bold value."""
    return html.Div(className="bbg-stat-card", children=[
        html.Div(label, className="label"),
        html.Div(value, className="value", style={"color": color} if color else {}),
    ])
