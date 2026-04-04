"""Centralized formatting utilities for the Highbourne Terminal.

All display-formatting logic lives here so that pages and components
never duplicate conversion/rounding code.
"""

import numpy as np


def fmt_pct(val, decimals=1, fallback="N/A"):
    """Format a decimal as a signed percentage string.

    >>> fmt_pct(0.05)
    '+5.0%'
    >>> fmt_pct(-0.0491)
    '-4.9%'
    """
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return fallback
    return f"{val * 100:+.{decimals}f}%"


def fmt_price(val, fallback="N/A"):
    """Format as dollar price.

    >>> fmt_price(24.12)
    '$24.12'
    """
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return fallback
    return f"${val:.2f}"


def fmt_large(val, fallback="N/A"):
    """Format large numbers with SI suffix.

    >>> fmt_large(103_420_000_000)
    '$103.42B'
    """
    if val is None:
        return fallback
    if val >= 1e12:
        return f"${val / 1e12:.2f}T"
    if val >= 1e9:
        return f"${val / 1e9:.2f}B"
    if val >= 1e6:
        return f"${val / 1e6:.1f}M"
    return f"${val:,.0f}"


def fmt_val(val, fmt_str=".2f", prefix="", suffix="", fallback="N/A"):
    """Generic value formatter with optional prefix/suffix."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return fallback
    return f"{prefix}{val:{fmt_str}}{suffix}"


def fmt_date_friendly(date_str):
    """Format a date string as 'Wed May 23rd 2026'.

    Accepts anything that pandas.Timestamp can parse.
    Returns the original string on failure.
    """
    import pandas as pd

    try:
        dt = pd.Timestamp(date_str)
        day = dt.day
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return dt.strftime(f"%a %b {day}{suffix} %Y")
    except Exception:
        return str(date_str)


def fmt_volume(val, fallback="N/A"):
    """Format a volume number with commas."""
    if val is None:
        return fallback
    return f"{val:,.0f}"
