"""Training rules, health calibration, and the scorer's status handling."""
import copy

import numpy as np
import pytest

from app.ml import training
from app.ml.dataset import Dataset, Segment
from app.ml.features import FeatureWindow
from app.ml.scorer import (ANOMALY, NEEDS_RETRAIN, NO_MODEL, OK, WARMING_UP, Scorer, health_from_score, plain_words,
                           short_name, z_band)
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
    # 16 features: temperature and humidity use only std and slope (sensors.json ml_stats, Phase 8.2)
    assert len(meta["feature_names"]) == 16 and meta["window_s"] == 10
    assert not any(n.endswith(("__mean", "__last")) for n in meta["feature_names"] if n.startswith(("temp_c", "humidity")))
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
    # Below the threshold the IF part decays softly (IF scores saturate outside the training
    # data, so on its own it never claims 0): 25 one normal spread below, 12.5 at three.
    assert health_from_score(a, cal) == pytest.approx(25)
    assert health_from_score(t - 3 * (m - t), cal) == pytest.approx(12.5)
    assert health_from_score(0.0, cal) == 100 and 0 < health_from_score(-5.0, cal) < 2
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
    assert top["text"] == "Vibration: far above normal" and top["band"] == "far" and len(result["causes"]) == 2


def test_range_excess_is_zero_inside_training_range(scorer, reg):
    fs = windows(scorer, sim_rows(reg, "normal", 120, 1))     # same seed as training data
    assert max(scorer.range_excess(f) for f in fs) == 0.0


def test_range_excess_lowers_health_gradually():
    cal = {"threshold_score": -0.58, "median_score": -0.50}
    h = lambda e: health_from_score(-0.50, cal, excess=e)     # noqa: E731 - a healthy IF score
    assert h(0.0) == pytest.approx(100)
    # Moderately out of range -> a mid score, not 0 (vibration 13 vs a normal 0-6 is ~14 stds).
    assert 60 < h(1.5) < 75 and 45 < h(6.0) < 50 and 30 <= h(13.8) <= 40
    assert 0 < h(89) < 10 and h(200) == 0.0                     # extreme values still reach 0
    es = np.linspace(0, 300, 301)
    hs = [h(e) for e in es]
    assert hs == sorted(hs, reverse=True)


def test_health_is_the_worse_of_both_parts():
    cal = {"threshold_score": -0.58, "median_score": -0.50}
    assert health_from_score(-0.58, cal, excess=0.0) == pytest.approx(50)     # IF part decides
    assert health_from_score(-0.58, cal, excess=13.8) < 40                     # range part decides
    assert health_from_score(-0.66, cal, excess=1.0) == pytest.approx(25)     # IF part decides


def test_vibration_13_is_a_mid_score(reg, profile):
    """Range term: a value moderately outside a normal vibration of 0-6 gives a mid score.
    Since Phase 8.2 the simulator's normal vibration is real-like (almost always 0), so this
    test trains its own model on the 0-6 spread it was calibrated for."""
    prof = copy.deepcopy(profile)
    prof["sensors"]["vib_count"].update(mean=2.0, wander=1.0, noise=1.2, min=0, max=5)
    data = Dataset(["a", "b"], [Segment("a", sim_rows(reg, "normal", 600, 1, profile=prof)),
                                Segment("b", sim_rows(reg, "normal", 600, 2, profile=prof))])
    sc = Scorer(reg, *training.train(data, reg, window_s=10, n_estimators=60))
    rows = sim_rows(reg, "normal", 15, 9, profile=prof)
    for r in rows:
        r.values["vib_count"] = 13.0 + (r.ms // 1000) % 3 - 1
    result = sc.score(windows(sc, rows)[-1])
    assert result["ml_status"] == ANOMALY and 20 <= result["health"] <= 45


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
    reg2 = make_registry(lambda d: next(s for s in d["sensors"] if s["key"] == "leak_raw").update(include_in_ml=True))
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


# ---- plain-language causes ------------------------------------------------------------

def test_z_bands():
    assert [z_band(z) for z in (0, 1.99, 2, -2.5, 3, 5.9, 6, -99)] == [
        "normal", "normal", "slight", "slight", "clear", "clear", "far", "far"]


def test_plain_words_by_statistic():
    assert plain_words("mean", 1.0) == "normal"
    assert plain_words("mean", 2.4) == "slightly high"
    assert plain_words("last", 4.0) == "above normal"
    assert plain_words("max", 64.5) == "far above normal"
    assert plain_words("min", -7) == "far below normal"
    assert plain_words("std", 3.5) == "unstable"
    assert plain_words("slope", -6.5) == "falling fast"


def test_short_name_drops_the_explanation():
    assert short_name("Sound level (peak deviation)") == "Sound level"
    assert short_name("Vibration") == "Vibration"


def _features_at(scorer, z_by_feature):
    """A feature dict at the normal mean, except the given features at the given z."""
    stats = scorer.meta["normal_stats"]
    return {name: st["mean"] + z_by_feature.get(name, 0.0) * st["std"] for name, st in stats.items()}


def test_level_wording_wins_over_spread_for_the_same_sensor(scorer):
    # Vibration's spread is further from normal than its level, but both are unusual:
    # the cause (and so the headline detail) says "far above normal", not "very unstable".
    feats = _features_at(scorer, {"vib_count__std": 40.0, "vib_count__mean": 8.0, "temp_c__mean": 2.5})
    causes = scorer.causes(feats)
    assert causes[0]["feature"] == "vib_count__mean" and causes[0]["text"] == "Vibration: far above normal"
    assert causes[1]["sensor"] == "temp_c"


def test_spread_wording_kept_when_the_level_is_normal(scorer):
    feats = _features_at(scorer, {"vib_count__std": 7.0, "vib_count__mean": 1.0})
    top = scorer.causes(feats)[0]
    assert top["feature"] == "vib_count__std" and top["text"] == "Vibration: very unstable"


def test_ml_stats_change_needs_retrain(trained, make_registry):
    """A model trained with one ml_stats set is refused when sensors.json asks for another."""
    model, meta = trained

    def all_stats(d):
        for s in d["sensors"]:
            s.pop("ml_stats", None)
    sc = Scorer(make_registry(all_stats), model, meta)
    assert sc.status == NEEDS_RETRAIN and "ML statistics changed" in sc.message
