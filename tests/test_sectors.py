import pandas as pd
import numpy as np
from data.sectors import (
    compute_sector_returns,
    compute_return_attribution,
    compute_normalized_performance,
    compute_sector_normalized_series,
    SECTOR_COLORS,
)


def test_sector_returns():
    ticker_returns = {"AAPL": 0.15, "MSFT": 0.20, "GOOG": 0.10, "JPM": 0.05, "BAC": 0.08}
    ticker_sectors = {"AAPL": "Tech", "MSFT": "Tech", "GOOG": "Tech", "JPM": "Fins", "BAC": "Fins"}
    result = compute_sector_returns(ticker_returns, ticker_sectors)
    assert abs(result["Tech"] - 0.15) < 0.001
    assert abs(result["Fins"] - 0.065) < 0.001


def test_return_attribution():
    total, eps_contrib, mult_contrib = compute_return_attribution(
        pe_start=20, pe_end=22, eps_start=5, eps_end=6
    )
    assert eps_contrib > 0
    assert mult_contrib > 0
    assert abs(eps_contrib - 0.20) < 0.001  # 6/5 - 1
    assert abs(mult_contrib - 0.10) < 0.001  # 22/20 - 1


def test_return_attribution_zero_input():
    total, eps, mult = compute_return_attribution(0, 22, 5, 6)
    assert total == 0


def test_normalized_performance():
    prices = pd.Series(
        [100, 105, 110, 108, 115],
        index=pd.date_range("2025-01-01", periods=5),
    )
    norm = compute_normalized_performance(prices)
    assert norm.iloc[0] == 0.0
    assert abs(norm.iloc[-1] - 0.15) < 0.001


def test_sector_normalized_series():
    dates = pd.date_range("2025-01-01", periods=4)
    price_dict = {
        "AAPL": pd.Series([100, 110, 120, 130], index=dates),
        "MSFT": pd.Series([200, 210, 220, 240], index=dates),
        "JPM": pd.Series([50, 48, 46, 44], index=dates),
    }
    sector_tickers = {"Tech": ["AAPL", "MSFT"], "Fins": ["JPM"]}
    result = compute_sector_normalized_series(sector_tickers, price_dict)
    assert "Tech" in result
    assert "Fins" in result
    assert result["Tech"].iloc[0] == 0.0
    assert result["Fins"].iloc[0] == 0.0
    # Fins should be negative (price declined)
    assert result["Fins"].iloc[-1] < 0


def test_sector_colors():
    assert "Technology" in SECTOR_COLORS
    assert SECTOR_COLORS["Technology"] == "#00ff00"
    assert len(SECTOR_COLORS) == 8
