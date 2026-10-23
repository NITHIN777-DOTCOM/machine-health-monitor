"""Trend forecast: direction above/below, stable, fit quality, cap, reached, data coverage."""
import random

import pytest

from app.ml.forecast import forecast, predicts_critical
from helpers import make_reg, rows_from, sensor

ABOVE = make_reg(sensor("t", 32, 35))
BELOW = make_reg(sensor("d", warn=10, critical=5, direction="below"))


def series(key, start, slope, n=60, noise=0.0, step_ms=1000, seed=0):
    rng = random.Random(seed)
    return rows_from([{key: start + slope * i * step_ms / 1000 + rng.gauss(0, noise)} for i in range(n)],
                     step_ms=step_ms)


def test_rising_towards_above_limit():
    f = forecast(series("t", 28.0, 0.02), ABOVE)["t"]
    level = 28.0 + 0.02 * 59
    assert f["status"] == "approaching" and f["trend"] == "rising"
    assert f["to_warn_s"] == pytest.approx((32 - level) / 0.02, rel=1e-3)
    assert f["to_critical_s"] == pytest.approx((35 - level) / 0.02, rel=1e-3)
    assert f["r2"] == pytest.approx(1.0) and f["slope_per_s"] == pytest.approx(0.02)
    assert f["text"].startswith("T: WARN in ~")


def test_falling_towards_below_limit():
    f = forecast(series("d", 20.0, -0.1), BELOW)["d"]
    level = 20.0 - 0.1 * 59
    assert f["status"] == "approaching" and f["trend"] == "falling"
    assert f["to_warn_s"] == pytest.approx((10 - level) / -0.1, rel=1e-3)
    assert f["to_critical_s"] == pytest.approx((5 - level) / -0.1, rel=1e-3)


@pytest.mark.parametrize("reg, key, slope", [(ABOVE, "t", -0.02), (BELOW, "d", 0.1)])
def test_moving_away_from_limit_is_stable(reg, key, slope):
    f = forecast(series(key, 20.0, slope), reg)[key]
    assert f["status"] == "stable" and f["to_warn_s"] is None and f["to_critical_s"] is None


def test_flat_noise_is_stable():
    f = forecast(series("t", 29.0, 0.0, noise=0.2), ABOVE)["t"]
    assert f["status"] == "stable" and f["text"] == "T: stable"


def test_poor_fit_is_not_trusted():
    f = forecast(series("t", 29.0, 0.003, noise=0.5, seed=3), ABOVE, min_r2=0.6)["t"]
    assert f["r2"] < 0.6 and f["status"] == "stable" and f["to_warn_s"] is None


def test_far_future_is_capped():
    f = forecast(series("t", 29.0, 0.0005), ABOVE, cap_s=1800)["t"]
    assert f["to_warn_s"] is None and f["to_warn"] == "> 30 min"
    assert f["status"] == "stable" and "> 30 min" in f["text"]
    assert not predicts_critical({"t": f})


def test_reached_limits():
    f = forecast(series("t", 35.5, 0.0, noise=0.05), ABOVE)["t"]
    assert f["status"] == "reached" and f["to_warn"] == "reached" and f["to_critical_s"] == 0.0
    assert predicts_critical({"t": f})


def test_warn_reached_critical_approaching():
    f = forecast(series("t", 31.0, 0.05), ABOVE)["t"]
    assert f["to_warn"] == "reached" and f["to_critical_s"] > 0 and f["status"] == "reached"


def test_uses_device_clock():
    # Rows every 2 s: the slope must still be per second.
    f = forecast(series("t", 28.0, 0.02, n=30, step_ms=2000), ABOVE)["t"]
    assert f["slope_per_s"] == pytest.approx(0.02)


def test_insufficient_data():
    assert forecast(series("t", 28.0, 0.1, n=4), ABOVE)["t"]["status"] == "insufficient_data"
    rows = series("t", 28.0, 0.1)
    for r in rows[:40]:
        r.values["t"] = None                       # only 20 of 60 s have values
    assert forecast(rows, ABOVE)["t"]["status"] == "insufficient_data"
    assert forecast([], ABOVE)["t"]["status"] == "insufficient_data"


def test_only_enabled_sensors_with_limits():
    reg = make_reg(sensor("t", 32, 35), sensor("h", None, None), sensor("x", 1, 2, enabled=False))
    assert set(forecast(series("t", 28, 0.02), reg)) == {"t"}


def test_window_limits_history():
    rows = series("t", 20.0, 0.0, n=200)
    for r in rows[-60:]:
        r.values["t"] = 28.0 + 0.02 * (r.ms / 1000 - 140)
    f = forecast(rows, ABOVE, window_s=60)["t"]          # only the ramp is in the last 60 s
    assert f["slope_per_s"] == pytest.approx(0.02) and f["status"] == "approaching"
