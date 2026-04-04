from datetime import datetime
from dash import html, dcc
from theme import C, CONTAINER_STYLE, header_bar, function_key_bar

def layout():
    ts = datetime.now().strftime("%H:%M:%S")
    return html.Div([
        header_bar("HIGHBOURNE TERMINAL", "EQUITY SCANNER", ts),
        html.Div("Scanner loading...", style={"color": C["gray"], "padding": "20px"}),
        function_key_bar("F1"),
    ], style=CONTAINER_STYLE)
