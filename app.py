"""ProjectHighbourne — Bloomberg-style multi-page Dash shell."""

import dash
from dash import html, dcc, Input, Output, State
from theme import C, FONT_FAMILY, STYLESHEET, CONTAINER_STYLE, FLASH_CSS
import pages.home as home
import pages.detail as detail

app = dash.Dash(__name__, suppress_callback_exceptions=True)

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

@app.callback(Output("page-content", "children"), Input("url", "pathname"))
def display_page(pathname):
    if pathname and pathname.startswith("/detail/"):
        symbol = pathname.split("/detail/")[-1].upper()
        return detail.layout(symbol)
    return home.layout()

if __name__ == "__main__":
    app.run(debug=True, port=8050)
