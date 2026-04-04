from datetime import datetime
from dash import html, dcc
from theme import C, CONTAINER_STYLE, header_bar, function_key_bar

def layout(symbol="AAPL"):
    ts = datetime.now().strftime("%H:%M:%S")
    return html.Div([
        header_bar("HIGHBOURNE TERMINAL", "DETAIL VIEW", ts),
        html.Div([
            html.A("◄ BACK TO SCANNER", href="/",
                   style={"color": C["yellow"], "textDecoration": "none",
                          "border": "1px solid #444", "padding": "2px 6px",
                          "background": "#111", "fontSize": "10px"}),
        ], style={"marginBottom": "6px"}),
        html.Div(f"Detail view for {symbol} — coming soon...",
                 style={"color": C["gray"], "padding": "20px"}),
        function_key_bar("F4"),
    ], style=CONTAINER_STYLE)
