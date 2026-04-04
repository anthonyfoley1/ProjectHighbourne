"""ProjectHighbourne -- Bloomberg-style multi-page Dash shell."""

import dash
from dash import html, dcc, Input, Output, State
import pages.home as home
import pages.detail as detail

# Dash auto-loads assets/style.css — no manual CSS injection needed
app = dash.Dash(__name__, suppress_callback_exceptions=True)
app.title = "Highbourne Terminal"

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    html.Div(id="page-content"),
], style={"backgroundColor": "#000", "minHeight": "100vh"})

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

@app.callback(Output("page-content", "children"), Input("url", "pathname"))
def display_page(pathname):
    if pathname and pathname.startswith("/detail/"):
        symbol = pathname.split("/detail/")[-1].upper()
        return detail.layout(symbol)
    return home.layout()


@app.callback(
    Output("url", "pathname", allow_duplicate=True),
    Input("search-bar", "n_submit"),
    State("search-bar", "value"),
    prevent_initial_call=True,
)
def search_navigate(n_submit, value):
    if value and value.strip():
        return f"/detail/{value.upper().strip()}"
    return dash.no_update


# ---------------------------------------------------------------------------
# Company-name search suggestions
# ---------------------------------------------------------------------------

@app.callback(
    Output("search-suggestions", "children"),
    Output("search-suggestions", "style"),
    Input("search-bar", "value"),
    prevent_initial_call=True,
)
def update_search_suggestions(query):
    if not query or len(query) < 2:
        return [], {"display": "none"}

    query_lower = query.lower()
    matches = []

    for ticker, name in startup.ticker_name.items():
        if query_lower in ticker.lower() or query_lower in (name or "").lower():
            matches.append((ticker, name or ""))
        if len(matches) >= 8:
            break

    if not matches:
        return [], {"display": "none"}

    suggestions = []
    for ticker, name in matches:
        suggestions.append(
            html.A(
                f"{ticker} — {name}",
                href=f"/detail/{ticker}",
                style={
                    "display": "block", "padding": "6px 10px", "color": "#e0e0e0",
                    "textDecoration": "none", "fontSize": "10px",
                    "borderBottom": "1px solid #222",
                },
            )
        )

    return suggestions, {
        "display": "block", "position": "absolute", "top": "100%",
        "left": 0, "right": 0, "zIndex": 1000,
        "backgroundColor": "#1a1a1a", "border": "1px solid #444",
        "maxHeight": "250px", "overflowY": "auto",
    }


# ---------------------------------------------------------------------------
# Live Clock
# ---------------------------------------------------------------------------
from datetime import datetime

@app.callback(Output("live-clock", "children"), Input("clock-interval", "n_intervals"))
def update_clock(n):
    return datetime.now().strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
import data.startup as startup
startup.init()

if __name__ == "__main__":
    app.run(debug=False, port=8050)
