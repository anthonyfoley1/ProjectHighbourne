import pandas as pd
import tempfile, os
from data.cache import CacheManager


def test_cache_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        cm = CacheManager(d)
        df = pd.DataFrame({"A": [1, 2, 3]}, index=pd.date_range("2025-01-01", periods=3))
        cm.save("test_prices", df)
        loaded = cm.load("test_prices")
        pd.testing.assert_frame_equal(df, loaded, check_freq=False)


def test_cache_staleness():
    with tempfile.TemporaryDirectory() as d:
        cm = CacheManager(d, max_age_hours=0)
        df = pd.DataFrame({"A": [1]})
        cm.save("test", df)
        assert cm.is_stale("test") is True


def test_cache_missing_returns_none():
    with tempfile.TemporaryDirectory() as d:
        cm = CacheManager(d)
        assert cm.load("nonexistent") is None


def test_json_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        cm = CacheManager(d)
        data = {"ticker": "AAPL", "values": [1, 2, 3]}
        cm.save_json("test_json", data)
        loaded = cm.load_json("test_json")
        assert loaded == data


def test_json_missing_returns_none():
    with tempfile.TemporaryDirectory() as d:
        cm = CacheManager(d)
        assert cm.load_json("nonexistent") is None


def test_is_stale_missing_key():
    with tempfile.TemporaryDirectory() as d:
        cm = CacheManager(d)
        assert cm.is_stale("no_such_key") is True


def test_creates_cache_dir():
    with tempfile.TemporaryDirectory() as d:
        subdir = os.path.join(d, "nested", "cache")
        cm = CacheManager(subdir)
        assert os.path.isdir(subdir)
