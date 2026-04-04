"""Sector analysis utilities — pure functions, no I/O."""

from statistics import median
import pandas as pd

SECTOR_COLORS = {
    "Technology": "#00ff00",
    "Industrials": "#ff8c00",
    "Health Care": "#ffff00",
    "Materials": "#bb86fc",
    "Financials": "#00bcd4",
    "Consumer Staples": "#e91e63",
    "Communication": "#ff4444",
    "Consumer Discretionary": "#999999",
}


def compute_sector_returns(ticker_returns: dict, ticker_sectors: dict) -> dict:
    """Compute median return per sector.

    Args:
        ticker_returns: {ticker: float} — return for each ticker.
        ticker_sectors: {ticker: str}  — sector label for each ticker.

    Returns:
        {sector: median_return}
    """
    sector_groups: dict[str, list[float]] = {}
    for ticker, ret in ticker_returns.items():
        sector = ticker_sectors.get(ticker)
        if sector is None:
            continue
        sector_groups.setdefault(sector, []).append(ret)
    return {sector: median(rets) for sector, rets in sector_groups.items()}


def compute_return_attribution(pe_start, pe_end, eps_start, eps_end) -> tuple:
    """Decompose return into EPS growth + multiple expansion.

    Total ~= EPS Growth + Multiple Expansion  (ignoring the cross-term).

    Returns:
        (total_return, eps_contribution, multiple_contribution)
        Returns (0, 0, 0) if any input is 0.
    """
    if pe_start == 0 or pe_end == 0 or eps_start == 0 or eps_end == 0:
        return (0, 0, 0)

    eps_contribution = eps_end / eps_start - 1
    multiple_contribution = pe_end / pe_start - 1
    total_return = eps_contribution + multiple_contribution
    return (total_return, eps_contribution, multiple_contribution)


def compute_normalized_performance(prices: pd.Series) -> pd.Series:
    """Normalize price series to start at 0% return.

    Formula: prices / prices.iloc[0] - 1
    """
    return prices / prices.iloc[0] - 1


def compute_sector_normalized_series(sector_tickers: dict, price_dict: dict) -> dict:
    """Compute normalized median performance per sector.

    Args:
        sector_tickers: {sector: [tickers]}
        price_dict:     {ticker: pd.Series}

    Returns:
        {sector: pd.Series of normalized median performance}
    """
    result = {}
    for sector, tickers in sector_tickers.items():
        normed = []
        for t in tickers:
            if t in price_dict:
                normed.append(compute_normalized_performance(price_dict[t]))
        if normed:
            combined = pd.concat(normed, axis=1)
            result[sector] = combined.median(axis=1)
    return result
