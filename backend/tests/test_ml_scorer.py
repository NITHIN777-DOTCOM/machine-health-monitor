"""Training rules, health calibration, and the scorer's status handling."""
import numpy as np
import pytest

from app.ml import training
from app.ml.dataset import Dataset, Segment
from app.ml.features import FeatureWindow
from app.ml.scorer import ANOMALY, NEEDS_RETRAIN, NO_MODEL, OK, WARMING_UP, Scorer, health_from_score
from helpers import sim_rows


@pytest.fixture
def scorer(reg, trained):
    return Scorer(reg, *trained)


def windows(scorer, rows):
    fw = scorer.make_window()
    return [f for f in (fw.push_row(r) for r in rows) if f is not None]


# ---- training ------------------------------------------------------------------------

def test_meta_contents(trained, reg):
    model, meta = trained
    assert meta["sensors"] == ["temp_c", "humidity", "sound_peak", "vib_count"]
    assert len(meta["feature_names"]) == 24 and meta["window_s"] == 10
    assert meta["training"]["rows_normal_by_source"] == {"real": 0, "synthetic": 1200}
    assert meta["provisional"] is True and meta["provisional_reason"]
    assert set(meta["normal_stats"]) == set(meta["feature_names"])
    assert all(s["std"] >= training.STD_FLOOR for s in meta["normal_stats"].values())
    assert meta["params"]["random_state"] == 42


def test_training_uses_only_normal_rows(reg):
    rows = sim_rows(reg, "sudden_fault", 300, 3, source="real")
    data = Dataset(["x"], [Segment("x", rows)])
    X, info = training.build_training_matrix(data, ["temp_c", "humidity", "sound_peak", "vib_count"], 10, 0.3)
    n_normal = sum(r.label == "normal" for r in rows)
    assert info["rows_normal_by_source"] == {"real": n_normal, "synthetic": 0}
    assert info["rows_skipped_not_normal"] == {"fault": 300 - n_normal}
    # No window may contain a fault row: the highest vibration in any window stays normal.
    vib_max = X[:, 5 * 3 + 3]           # vib_count__max (4th sensor, 'max' is stat index 3)
    assert vib_max.max() < 20


def test_real_only_model_is_not_provisional(reg):
    data = Dataset(["r"], [Segment("r", sim_rows(reg, "normal", 200, 4, source="real"))])
    _, meta = training.train(data, reg, n_estimators=20)
    assert meta["provisional"] is False and meta["provisional_reason"] is None


def test_training_refuses_too_little_data(reg):
    data = Dataset(["r"], [Segment("r", sim_rows(reg, "normal", 30, 5))])
    with pytest.raises(training.TrainingError, match="normal windows"):
        training.train(data, reg)


def test_training_refuses_without_ml_sensors(make_registry):
    reg = make_registry(lambda d: [s.update(include_in_ml=False) for s in d["sensors"]])
    with pytest.raises(training.TrainingError, match="No ML sensors"):
        training.train(Dataset([], []), reg)


# ---- health calibration --------------------------------------------------------------

def test_health_calibration_anchor_points():
    cal = training.calibrate(np.array([-0.40, -0.45, -0.50, -0.55, -0.60]), threshold=-0.58)
    m, t, a = cal["median_score"], cal["threshold_score"], cal["abnormal_score"]
    assert (m, t) == (-0.50, -0.58) and a == pytest.approx(-0.66)
    assert health_from_score(m, cal) == pytest.approx(100)
    assert health_from_score(t, cal) == pytest.approx(50)
    assert health_from_score(a, cal) == pytest.approx(0)
    assert health_from_score(0.0, cal) == 100 and health_from_score(-5.0, cal) == 0
    grid = np.linspace(-1, 0, 200)
    hs = [health_from_score(s, cal) for s in grid]
    assert all(0 <= h <= 100 for h in hs) and hs == sorted(hs)


def test_calibration_degenerate_median():
    cal = training.calibrate(np.array([-0.6, -0.6]), threshold=-0.5)
    assert cal["median_score"] > cal["threshold_score"]


def test_training_health_distribution(trained):
    _, meta = trained
    assert meta["training_health"]["median"] > 90
    assert meta["training_health"]["share_below_50"] == pytest.approx(0.01, abs=0.01)


# ---- scoring -------------------------------------------------------------------------

def test_normal_windows_score_healthy(scorer, reg):
    results = [scorer.score(f) for f in windows(scorer, sim_rows(reg, "normal", 300, 77))]
    health = np.array([r["health"] for r in results])
    assert np.median(health) > 80
    assert np.mean([r["ml_status"] == ANOMALY for r in results]) < 0.05
    assert all(r["provisional"] is True for r in results)


def test_vibration_fault_is_anomaly_with_cause(scorer, reg):
    rows = sim_rows(reg, "normal", 15, 9)
    for r in rows:
        r.values["vib_count"] = 80.0 + (r.ms // 1000) % 3
    result = scorer.score(windows(scorer, rows)[-1])
    assert result["ml_status"] == ANOMALY and result["health"] < 50 and result["range_excess"] > 3
    top = result["causes"][0]
    assert top["sensor"] == "vib_count" and top["direction"] == "high" and top["z"] > 3
    assert top["text"] == "Vibration high" and len(result["causes"]) == 2


def test_range_excess_is_zero_inside_training_range(scorer, reg):
    fs = windows(scorer, sim_rows(reg, "normal", 120, 1))     # same seed as training data
    assert max(scorer.range_excess(f) for f in fs) == 0.0


def test_range_excess_lowers_health():
    cal = {"threshold_score": -0.58, "median_score": -0.50}
    assert health_from_score(-0.50, cal, excess=0.0) == pytest.approx(100)
    assert health_from_score(-0.50, cal, excess=1.5) == pytest.approx(75)
    assert health_from_score(-0.50, cal, excess=3.0) == pytest.approx(50)
    assert health_from_score(-0.50, cal, excess=30.0) == 0.0


def test_warming_up(scorer):
    assert scorer.score(None)["ml_status"] == WARMING_UP
    assert scorer.score(None)["health"] is None


def test_no_model(reg, tmp_path):
    s = Scorer.load(reg, tmp_path)
    assert s.status == NO_MODEL and s.make_window() is None
    r = s.score({"x": 1.0})
    assert r["ml_status"] == NO_MODEL and r["health"] is None and "train.py" in r["message"]


def test_broken_model_file(reg, tmp_path):
    (tmp_path / "model.joblib").write_bytes(b"not a model")
    (tmp_path / "model_meta.json").write_text("{}", encoding="utf-8")
    s = Scorer.load(reg, tmp_path)
    assert s.status == NO_MODEL and "could not load" in s.message


def test_sensor_mismatch_needs_retrain_and_does_not_crash(make_registry, trained):
    reg2 = make_registry(lambda d: next(s for s in d["sensors"] if s["key"] == "leak_raw").update(enabled=True))
    s = Scorer(reg2, *trained)
    assert s.status == NEEDS_RETRAIN and "sensors changed" in s.message
    assert s.make_window() is None
    r = s.score({"anything": 1.0})
    assert r["ml_status"] == NEEDS_RETRAIN and r["health"] is None


def test_save_and_load_roundtrip(reg, trained, tmp_path):
    training.save(*trained, tmp_path)
    s = Scorer.load(reg, tmp_path)
    assert s.status == "READY" and s.provisional and s.info()["window_s"] == 10
    f = windows(s, sim_rows(reg, "normal", 20, 5))[-1]
    assert s.score(f)["ml_status"] in (OK, ANOMALY)


def test_window_comes_from_model_meta(scorer):
    fw = scorer.make_window()
    assert isinstance(fw, FeatureWindow) and fw.window_ms == 10_000
