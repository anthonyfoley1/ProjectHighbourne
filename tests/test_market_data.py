import pandas as pd
from data.market_data import compute_returns, compute_52w_range, compute_relative_volume


def test_compute_returns():
    prices = pd.Series([100, 102, 101, 105, 103],
                       index=pd.date_range("2025-01-01", periods=5))
    ret_1d, ret_3d = compute_returns(prices)
    assert abs(ret_1d - ((103 - 105) / 105)) < 0.001
    assert abs(ret_3d - ((103 - 101) / 101)) < 0.001


def test_compute_returns_insufficient_data():
    prices = pd.Series([100, 102])
    ret_1d, ret_3d = compute_returns(prices)
    assert ret_1d == 0.0
    assert ret_3d == 0.0


def test_compute_52w_range():
    prices = pd.Series(range(10, 110), index=pd.date_range("2024-01-01", periods=100), dtype=float)
    low, high, pct = compute_52w_range(prices)
    assert low == 10.0
    assert high == 109.0
    assert 0 <= pct <= 1


def test_compute_relative_volume():
    vol = pd.Series([100] * 10 + [250], index=pd.date_range("2025-01-01", periods=11))
    rv = compute_relative_volume(vol, lookback=10)
    assert rv == 2.5
