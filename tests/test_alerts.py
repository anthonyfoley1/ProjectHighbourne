"""Tests for alert, composite score, and signal label functions."""

from models.ticker import compute_alert, compute_composite_score, compute_signal_label


def test_buy_alert():
    alert = compute_alert(z_score=-2.0, rsi=25, macd_signal="Bull", ma_trend="Below")
    assert alert["type"] == "BUY"


def test_sell_alert():
    alert = compute_alert(z_score=2.0, rsi=75, macd_signal="Bear", ma_trend="Above")
    assert alert["type"] == "SELL"


def test_no_alert():
    alert = compute_alert(z_score=-0.5, rsi=50, macd_signal="Flat", ma_trend="Above")
    assert alert["type"] is None


def test_composite_overweight():
    score = compute_composite_score(
        z_score=-2.0, rsi=25, macd_signal="Bull", peer_return=-0.15, pt_upside=0.50
    )
    assert score["label"] == "OVERWEIGHT"


def test_composite_underweight():
    score = compute_composite_score(
        z_score=2.5, rsi=78, macd_signal="Bear", peer_return=0.20, pt_upside=-0.25
    )
    assert score["label"] == "UNDERWEIGHT"


def test_signal_buy():
    assert compute_signal_label(-2.0, "BUY") == "BUY"


def test_signal_cheap():
    assert compute_signal_label(-1.2, None) == "CHEAP"


def test_signal_fair():
    assert compute_signal_label(0.3, None) == "FAIR"


def test_signal_rich():
    assert compute_signal_label(1.2, None) == "RICH"
