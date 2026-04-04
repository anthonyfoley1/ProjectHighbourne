"""ProjectHighbourne -- Bloomberg-style multi-page Dash shell."""

import dash
from dash import html, dcc, Input, Output, State
from theme import C, FONT_FAMILY, STYLESHEET, CONTAINER_STYLE, FLASH_CSS
import pages.home as home
import pages.detail as detail

app = dash.Dash(__name__, suppress_callback_exceptions=True)

# ---------------------------------------------------------------------------
# Dark-theme CSS (injected into index_string)
# ---------------------------------------------------------------------------
_DARK_DROPDOWN_CSS = """
/* Dash dropdown -- dark theme overrides */
.Select-control { background-color: #1a1a1a !important; border-color: #444 !important; }
.Select-menu-outer { background-color: #1a1a1a !important; border-color: #444 !important; }
.Select-option { background-color: #1a1a1a !important; color: #e0e0e0 !important; }
.Select-option.is-focused { background-color: #333 !important; }
.Select-value-label { color: #e0e0e0 !important; }
.Select-placeholder { color: #777 !important; }
.Select-input input { color: #e0e0e0 !important; }
.dash-dropdown .Select-control { background-color: #1a1a1a !important; }
.dash-dropdown .Select-menu-outer { background-color: #1a1a1a !important; }
.dash-dropdown .Select-option:hover { background-color: #333 !important; }
.VirtualizedSelectFocusedOption { background-color: #333 !important; }
.VirtualizedSelectOption { background-color: #1a1a1a !important; color: #e0e0e0 !important; }
"""

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Highbourne Terminal</title>
        {%css%}
        <style>
            body { margin: 0; padding: 0; background: #000;
                   font-family: ''' + FONT_FAMILY + '''; }
            @keyframes marquee {
                0% { transform: translateX(100%); }
                100% { transform: translateX(-100%); }
            }
            ''' + _DARK_DROPDOWN_CSS + '''
            ''' + FLASH_CSS + '''
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

app.layout = html.Div([
    dcc.Location(id="url", refresh=False),
    html.Div(id="page-content", style=STYLESHEET),
], style={"backgroundColor": C["bg"], "minHeight": "100vh"})

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
# Startup
# ---------------------------------------------------------------------------
import data.startup as startup
startup.init()

if __name__ == "__main__":
    app.run(debug=False, port=8050)
