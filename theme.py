"""Bloomberg-terminal-inspired theme constants and Dash component factories."""

from dash import html

# ---------------------------------------------------------------------------
# Color palette
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

# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
FONT_FAMILY = "'Lucida Console', 'Monaco', 'Courier New', monospace"

# ---------------------------------------------------------------------------
# Base styles
# ---------------------------------------------------------------------------
STYLESHEET = {
    "fontFamily": FONT_FAMILY,
    "backgroundColor": C["bg"],
    "color": C["white"],
    "fontSize": "11px",
    "padding": "8px",
}

CONTAINER_STYLE = {
    "maxWidth": "1100px",
    "margin": "0 auto",
}

# ---------------------------------------------------------------------------
# Flash animation CSS (inject via html.Style)
# ---------------------------------------------------------------------------
FLASH_CSS = """
@keyframes cellFlash {
    0%  { background-color: transparent; }
    15% { background-color: rgba(255, 255, 0, 0.3); }
    30% { background-color: transparent; }
    45% { background-color: rgba(255, 255, 0, 0.3); }
    60% { background-color: transparent; }
}
.cell-flash {
    animation: cellFlash 1s ease-out;
}
"""

# ---------------------------------------------------------------------------
# Component factories
# ---------------------------------------------------------------------------

def header_bar(title: str, subtitle: str, timestamp: str) -> html.Div:
    """Top header bar with title, subtitle, search input, and timestamp."""
    return html.Div(
        style={
            "backgroundColor": C["header"],
            "borderBottom": f"2px solid {C['orange']}",
            "display": "flex",
            "alignItems": "center",
            "padding": "6px 12px",
        },
        children=[
            html.Span(
                title,
                style={
                    "color": C["orange"],
                    "fontWeight": "bold",
                    "fontSize": "14px",
                    "marginRight": "10px",
                    "fontFamily": FONT_FAMILY,
                },
            ),
            html.Span(
                subtitle,
                style={
                    "color": C["gray"],
                    "fontSize": "11px",
                    "marginRight": "auto",
                    "fontFamily": FONT_FAMILY,
                },
            ),
            html.Input(
                id="search-bar",
                placeholder="Search...",
                style={
                    "backgroundColor": C["bg"],
                    "color": C["yellow"],
                    "border": f"1px solid {C['border']}",
                    "padding": "3px 8px",
                    "fontSize": "11px",
                    "fontFamily": FONT_FAMILY,
                    "marginRight": "12px",
                    "outline": "none",
                },
            ),
            html.Span(
                timestamp,
                style={
                    "color": C["gray"],
                    "fontSize": "10px",
                    "fontFamily": FONT_FAMILY,
                },
            ),
        ],
    )


_FKEYS = [
    ("F1", "HOME"),
    ("F2", "SCREENER"),
    ("F3", "SECTORS"),
    ("F4", "DETAIL"),
]


def function_key_bar(active_key: str) -> html.Div:
    """Bottom function-key bar (F1-F4) with version label on the right."""
    keys = []
    for fk, label in _FKEYS:
        keys.append(
            html.Span(
                f"{fk} {label}",
                style={
                    "backgroundColor": C["gray"] if fk == active_key else C["header"],
                    "color": C["yellow"],
                    "padding": "3px 10px",
                    "fontSize": "10px",
                    "fontFamily": FONT_FAMILY,
                    "marginRight": "4px",
                    "cursor": "pointer",
                },
            )
        )
    return html.Div(
        style={
            "backgroundColor": C["header"],
            "borderTop": f"1px solid {C['border']}",
            "display": "flex",
            "alignItems": "center",
            "padding": "4px 12px",
        },
        children=[
            *keys,
            html.Span(
                "HIGHBOURNE v2.0",
                style={
                    "marginLeft": "auto",
                    "color": C["orange"],
                    "fontSize": "10px",
                    "fontFamily": FONT_FAMILY,
                },
            ),
        ],
    )


def stat_card(label: str, value: str, color: str = C["white"]) -> html.Div:
    """Small stat card with uppercase label and bold value."""
    return html.Div(
        style={
            "flex": "1",
            "backgroundColor": "#111111",
            "border": f"1px solid {C['border']}",
            "padding": "8px 10px",
            "fontFamily": FONT_FAMILY,
        },
        children=[
            html.Div(
                label,
                style={
                    "color": C["orange"],
                    "fontSize": "8px",
                    "textTransform": "uppercase",
                    "marginBottom": "4px",
                },
            ),
            html.Div(
                value,
                style={
                    "color": color,
                    "fontSize": "14px",
                    "fontWeight": "bold",
                },
            ),
        ],
    )
