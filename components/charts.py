"""Reusable chart builders and layout helpers for Plotly figures.

Provides a single source of truth for the Bloomberg-dark chart theme
so individual pages never duplicate layout dictionaries.
"""

import plotly.graph_objects as go
from theme import C, FONT_FAMILY


def make_chart_layout(**overrides):
    """Return a Plotly layout dict with the Highbourne dark theme.

    Any keyword arguments override the base defaults, avoiding the
    duplicate-keyword errors that ``**CHART_LAYOUT`` spreading caused.
    """
    base = dict(
        paper_bgcolor="#0a0a0a",
        plot_bgcolor="#0a0a0a",
        font=dict(family=FONT_FAMILY, color=C["gray"], size=10),
        hovermode="x unified",
    )
    base.update(overrides)
    return base


def empty_fig(msg="No data"):
    """Return a blank figure with a centered message annotation."""
    fig = go.Figure()
    fig.update_layout(
        **make_chart_layout(),
        annotations=[
            dict(
                text=msg, x=0.5, y=0.5,
                xref="paper", yref="paper",
                showarrow=False,
                font=dict(size=14, color=C["gray"]),
            )
        ],
    )
    return fig
