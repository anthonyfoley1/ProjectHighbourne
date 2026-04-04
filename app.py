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
/* Global dark dropdown — targets all react-select elements regardless of class hash */
div[class*="-control"] { background-color: #1a1a1a !important; border-color: #444 !important; }
div[class*="-menu"] { background-color: #1a1a1a !important; border-color: #444 !important; z-index: 1000 !important; }
div[class*="-menuList"] { background-color: #1a1a1a !important; }
div[class*="-option"] { background-color: #1a1a1a !important; color: #e0e0e0 !important; }
div[class*="-option"]:hover { background-color: #333 !important; }
div[class*="-singleValue"] { color: #e0e0e0 !important; }
div[class*="-placeholder"] { color: #777 !important; }
div[class*="-indicatorSeparator"] { background-color: #444 !important; }
div[class*="-indicatorContainer"] svg { fill: #999 !important; color: #999 !important; }
div[class*="-input"] input { color: #e0e0e0 !important; }
/* Plotly hover labels — dark theme */
.hoverlabel { background-color: #1a1a1a !important; }
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
                0% { transform: translateX(0%); }
                100% { transform: translateX(-50%); }
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
