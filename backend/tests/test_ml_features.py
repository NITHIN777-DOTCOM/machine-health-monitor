"""Window features: device-clock window, warming up, missing values, slope, registry-driven list."""
import math

import pytest

from app.ml.dataset import Dataset, Segment
from app.ml.features import STATS, FeatureWindow, feature_names, ml_sensor_keys
from app.ml.training import build_training_matrix
from helpers import rows_from


def push_all(fw, rows):
    return [fw.push_row(r) for r in rows]


def test_warming_up_until_window_full():
    fw = FeatureWindow(["a"], window_s=10)
    out = push_all(fw, rows_from([{"a": float(i)} for i in range(12)]))
    assert out[:9] == [None] * 9            # 9 rows cover only 8 s
    assert out[9] is not None and out[11] is not None


def test_window_uses_device_clock_not_row_count():
    # Rows 2 s apart: 5 rows cover 8 s but a 10 s window expects 10 samples -> too sparse.
    fw = FeatureWindow(["a"], window_s=10)
    assert all(f is None for f in push_all(fw, rows_from([{"a": 1.0}] * 8, step_ms=2000)))
    # Rows 0.5 s apart: 18 rows cover only 8.5 s of device time -> still warming up.
    fw = FeatureWindow(["a"], window_s=10)
    assert all(f is None for f in push_all(fw, rows_from([{"a": 1.0}] * 18, step_ms=500)))


def test_stats_and_slope_units_per_second():
    fw = FeatureWindow(["a"], window_s=10)
    vals = [{"a": 20.0 + 0.5 * i} for i in range(10)]     # +0.5 per second
    f = push_all(fw, rows_from(vals))[-1]
    assert f["a__slope"] == pytest.approx(0.5)
    assert f["a__mean"] == pytest.approx(22.25)
    assert (f["a__min"], f["a__max"], f["a__last"]) == (20.0, 24.5, 24.5)
    assert f["a__std"] == pytest.approx(math.sqrt(sum((0.5 * i - 2.25) ** 2 for i in range(10)) / 10))
    assert list(f) == feature_names(["a"])


def test_window_slides():
    fw = FeatureWindow(["a"], window_s=10)
    f = push_all(fw, rows_from([{"a": 0.0}] * 10 + [{"a": 100.0}] * 10))[-1]
    assert f["a__min"] == 100.0 and f["a__slope"] == 0.0


@pytest.mark.parametrize("n_missing, ok", [(3, True), (4, False)])
def test_missing_values_threshold(n_missing, ok):
    vals = [{"a": 1.0, "b": float(i)} for i in range(10)]
    for i in range(n_missing):
        vals[i * 2]["b"] = None
    f = push_all(FeatureWindow(["a", "b"], window_s=10, max_missing_frac=0.3), rows_from(vals))[-1]
    assert (f is not None) == ok
    if ok:
        assert f["b__mean"] == pytest.approx(sum(v["b"] for v in vals if v["b"] is not None) / (10 - n_missing))


def test_gaps_in_device_clock_count_as_missing():
    ms = [0, 1000, 2000, 3000, 4000, 5000, 9000]           # 6000-8000 missing: 3 of 10
    fw = FeatureWindow(["a"], window_s=10)
    out = [fw.push(m, {"a": 1.0}) for m in ms]
    assert out[-1] is not None
    fw = FeatureWindow(["a"], window_s=10)
    out = [fw.push(m, {"a": 1.0}) for m in [0, 1000, 2000, 3000, 4000, 9000]]   # 4 missing
    assert out[-1] is None


def test_values_are_never_filled_with_zero():
    vals = [{"a": 50.0}] * 10
    vals[3] = {"a": None}
    f = push_all(FeatureWindow(["a"], window_s=10), rows_from(vals))[-1]
    assert f["a__min"] == 50.0 and f["a__mean"] == 50.0


def test_device_reset_restarts_window():
    fw = FeatureWindow(["a"], window_s=10)
    push_all(fw, rows_from([{"a": 1.0}] * 12))
    assert fw.push(0, {"a": 1.0}) is None and not fw.full


def test_feature_list_is_registry_driven(make_registry, registry):
    assert ml_sensor_keys(registry) == ["temp_c", "humidity", "sound_peak", "vib_count"]
    assert len(feature_names(ml_sensor_keys(registry))) == 4 * len(STATS)

    def enable_all(d):
        for s in d["sensors"]:
            s["enabled"] = True
    keys = ml_sensor_keys(make_registry(enable_all))
    assert keys == ["temp_c", "humidity", "sound_peak", "vib_count"]   # the others are include_in_ml: false

    def leak_into_ml(d):
        next(s for s in d["sensors"] if s["key"] == "leak_raw")["include_in_ml"] = True
    assert "leak_raw" in ml_sensor_keys(make_registry(leak_into_ml))

    def drop_humidity(d):
        next(s for s in d["sensors"] if s["key"] == "humidity")["include_in_ml"] = False
    assert "humidity" not in ml_sensor_keys(make_registry(drop_humidity))


def test_training_and_live_use_identical_features(registry, run_sim):
    rows, _ = run_sim("sudden_fault", 60)
    for r in rows:
        r.label = "normal"
    sensors = ml_sensor_keys(registry)
    X, _ = build_training_matrix(Dataset(["x"], [Segment("x", rows)]), sensors, 10, 0.3)
    fw = FeatureWindow(sensors, 10, 0.3)
    live = [f for f in (fw.push_row(r) for r in rows) if f is not None]
    names = feature_names(sensors)
    assert X.tolist() == [[f[n] for n in names] for f in live]


def test_window_too_short_is_rejected():
    with pytest.raises(ValueError):
        FeatureWindow(["a"], window_s=1)
