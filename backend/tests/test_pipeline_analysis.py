"""Live analysis: analysis block, overall status / alert source, ML smoothing, warm start,
NEEDS_RETRAIN, model reload and the training job endpoint."""
import csv
import shutil
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.analysis import ML_UNAVAILABLE, Analyzer, compact
from app.config import MODELS_DIR, Settings
from app.device_rules import DeviceStateMachine
from app.ml.features import FeatureWindow
from app.ml.scorer import ANOMALY, NEEDS_RETRAIN, NO_MODEL, OK, WARMING_UP, Scorer
from app.models import csv_header
from app.sources import serial_source
from helpers import collapse, rows_from, sim_rows

ML_KEYS = {"status", "health", "causes", "provisional", "warmup_remaining_s", "instant", "message"}
FC_KEYS = {"trend", "status", "seconds_to_warn", "seconds_to_critical", "to_warn", "to_critical", "text", "r2"}


def check_block(a, registry):
    """Every analysis block has the same well-formed shape, whatever the ML status."""
    assert set(a) == {"overall", "alert_source", "headline", "headline_detail", "device", "ml", "forecast", "warm_start"}
    assert a["overall"] in ("NORMAL", "WARNING", "CRITICAL")
    assert a["alert_source"] in ("rules", "ml", "both", "none")
    assert isinstance(a["headline"], str) and a["headline"]
    assert set(a["device"]) == {"state", "reported", "reason", "hold_remaining_s", "agrees"}
    assert ML_KEYS <= set(a["ml"])
    assert a["ml"]["status"] in (OK, ANOMALY, WARMING_UP, ML_UNAVAILABLE, NO_MODEL, NEEDS_RETRAIN)
    h = a["ml"]["health"]
    assert h is None or 0 <= h <= 100
    assert set(a["forecast"]) == {s.key for s in registry.enabled if s.forecast}
    for f in a["forecast"].values():
        assert set(f) == FC_KEYS


class Rig:
    """Analyzer + device mirror, fed like the pipeline does."""

    def __init__(self, registry, scorer, **settings):
        self.registry = registry
        self.analyzer = Analyzer(registry, Settings(**settings), scorer)
        self.device = DeviceStateMachine(registry, 5)

    def feed(self, rows):
        out = []
        for r in rows:
            self.device.update(r.values)
            snap = {**self.device.snapshot(), "agrees": None}
            out.append(self.analyzer.update(r, snap))
        return out


@pytest.fixture
def scorer(reg, trained):
    return Scorer(reg, *trained)


def vib_rows(registry, n, vib, seed=5, start_ms=0, dev_state="NORMAL"):
    rows = sim_rows(registry, "normal", n, seed)
    for i, r in enumerate(rows):
        r.ms = start_ms + i * 1000
        r.values["vib_count"] = vib + i % 3
        r.dev_state = dev_state
    return rows


# ---- analysis block for every ML status ----------------------------------------------

def test_warming_up_then_ok(reg, scorer):
    out = Rig(reg, scorer).feed(sim_rows(reg, "normal", 30, 11))
    for a in out:
        check_block(a, reg)
    assert [a["ml"]["warmup_remaining_s"] for a in out[:9]] == [9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
    assert all(a["ml"]["status"] == WARMING_UP for a in out[:9])
    assert (out[0]["headline"], out[0]["headline_detail"]) == ("All systems normal", "ML warming up: 9 s left")
    assert all(a["ml"]["status"] == OK for a in out[9:])
    assert out[-1]["overall"] == "NORMAL" and out[-1]["alert_source"] == "none"


def test_ml_unavailable_on_sensor_fault(reg, scorer):
    rows = sim_rows(reg, "sensor_fault", 120, 3)
    out = Rig(reg, scorer).feed(rows)
    for a in out:
        check_block(a, reg)
    start = next(i for i, r in enumerate(rows) if r.values["temp_c"] is None)
    late = out[start + 5:]
    assert all(a["ml"]["status"] == ML_UNAVAILABLE for a in late)
    assert "Temperature" in late[-1]["ml"]["message"] and "Humidity" in late[-1]["ml"]["message"]
    assert late[-1]["overall"] == "WARNING" and late[-1]["alert_source"] == "rules"
    assert late[-1]["headline"] == "Sensor fault: DHT11" and late[-1]["headline_detail"] == "DHT11: no reading"
    # The forecast says "no data" from the first missing row, not "stable" from old readings.
    assert out[start]["forecast"]["temp_c"]["status"] == "no_data"
    assert all(a["forecast"][k]["status"] == "no_data" for a in late for k in ("temp_c", "humidity"))


def test_no_model(reg):
    out = Rig(reg, Scorer(reg)).feed(sim_rows(reg, "normal", 15, 1))
    for a in out:
        check_block(a, reg)
    assert out[-1]["ml"]["status"] == NO_MODEL and out[-1]["ml"]["health"] is None
    assert out[-1]["headline"] == "All systems normal (rules only)"


def test_needs_retrain_keeps_rules_working(make_registry, trained):
    reg2 = make_registry(lambda d: next(s for s in d["sensors"] if s["key"] == "leak_raw").update(include_in_ml=True))
    rig = Rig(reg2, Scorer(reg2, *trained))
    rows = sim_rows(reg2, "normal", 15, 2)
    rows[-1].values["temp_c"] = 36.0
    rows[-1].dev_state = "CRITICAL"
    out = rig.feed(rows)
    for a in out:
        check_block(a, reg2)
    assert out[-1]["ml"]["status"] == NEEDS_RETRAIN and "sensors changed" in out[-1]["ml"]["message"]
    assert out[-1]["overall"] == "CRITICAL" and out[-1]["alert_source"] == "rules"
    assert out[-1]["device"]["state"] == "CRITICAL"


# ---- overall status and alert source -------------------------------------------------

def test_ml_anomaly_alone_is_only_warning(reg, scorer):
    out = Rig(reg, scorer).feed(sim_rows(reg, "normal", 20, 4) + vib_rows(reg, 15, 999, start_ms=20_000))
    a = out[-1]
    check_block(a, reg)
    assert a["ml"]["status"] == ANOMALY and a["ml"]["health"] == 0
    assert a["overall"] == "WARNING"            # never CRITICAL from ML, even at health 0
    assert a["alert_source"] == "ml"
    assert a["headline"] == "Unusual vibration pattern (health 0)"
    assert a["headline_detail"].startswith("Vibration: far above normal")
    assert a["ml"]["causes"][0]["sensor"] == "vib_count" and a["ml"]["causes"][0]["direction"] == "high"


def test_rules_and_ml_together(reg, scorer):
    rows = sim_rows(reg, "normal", 20, 4) + vib_rows(reg, 15, 90, start_ms=20_000, dev_state="CRITICAL")
    a = Rig(reg, scorer).feed(rows)[-1]
    assert a["overall"] == "CRITICAL" and a["alert_source"] == "both"
    assert a["headline"] == "Vibration above critical limit"
    assert "crit limit 60" in a["headline_detail"] and "ML anomaly (health" in a["headline_detail"]


def test_overall_never_critical_from_ml_in_any_scenario(reg, scorer):
    for scenario in ("sudden_fault", "slow_drift", "recovery", "drift_and_recover", "sensor_fault"):
        rows = sim_rows(reg, scenario, 300, 8)
        for r, a in zip(rows, Rig(reg, scorer).feed(rows)):
            if a["overall"] == "CRITICAL":
                assert r.dev_state == "CRITICAL", scenario
            assert a["overall"] in (r.dev_state, "WARNING")


def test_safety_zone_headline_says_below_and_mixed_says_past(reg, scorer):
    rows = sim_rows(reg, "normal", 20, 4)
    rows[-1].values.update(distance_cm=8.0)
    rows[-1].dev_state = "CRITICAL"
    a = Rig(reg, scorer).feed(rows)[-1]
    assert a["device"]["state"] == "CRITICAL" and a["headline"] == "Safety zone below critical limit"
    assert "Safety zone 8, crit limit 10" in a["headline_detail"]
    rows[-1].values.update(vib_count=70.0)
    a = Rig(reg, scorer).feed(rows)[-1]
    assert a["headline"] == "Vibration and safety zone past critical limits"


def test_safety_zone_clear_reading_is_normal(reg, scorer):
    rows = sim_rows(reg, "normal", 20, 4)
    for r in rows:
        r.values["distance_cm"] = 400.0              # no echo = nothing in range
    a = Rig(reg, scorer).feed(rows)[-1]
    assert a["device"]["state"] == "NORMAL" and a["overall"] == "NORMAL"


def test_forecast_headline(reg, scorer):
    rows = sim_rows(reg, "normal", 90, 9)                # a seed whose ML health stays above the clear level
    for i, r in enumerate(rows):
        r.values["temp_c"] = 29.0 + 0.02 * i                # steady climb, still below 32
    a = Rig(reg, scorer).feed(rows)[-1]
    assert a["forecast"]["temp_c"]["trend"] == "rising"
    assert a["forecast"]["temp_c"]["seconds_to_warn"] > 0
    assert a["headline"].startswith("Temperature may reach warning in ")
    assert a["headline_detail"].startswith("Temperature rising: warning in ")


# ---- smoothing ---------------------------------------------------------------------------

class FakeScorer:
    """Returns scripted health values, so the smoothing logic can be tested exactly."""

    status, message, provisional, ready = "READY", None, False, True
    meta = {"window_s": 10}

    def __init__(self, healths):
        self.healths = list(healths)

    def make_window(self):
        return FeatureWindow(["a"], 2)          # full from the 2nd row

    def score(self, feats):
        h = self.healths.pop(0)
        return {"ml_status": ANOMALY if h < 50 else OK, "health": h, "causes": [], "range_excess": 0}


def smoothed(healths, **settings):
    reg = Scorer.__init__.__globals__["Registry"].from_dict({"csv_columns": ["ms", "a", "dev_state"], "sensors": [
        {"key": "a", "enabled": True, "include_in_ml": True, "tier": "core"}]})
    rig = Rig(reg, FakeScorer(healths), **settings)
    rows = rows_from([{"a": 1.0}] * (len(healths) + 1))
    return [a["ml"]["status"] for a in rig.feed(rows)][1:]


def test_anomaly_needs_three_low_rows():
    assert smoothed([40, 40, 70, 40, 40, 40]) == [OK, OK, OK, OK, OK, ANOMALY]


def test_anomaly_clears_after_five_high_rows():
    s = smoothed([40, 40, 40] + [70, 70, 70, 70, 55] + [70] * 5)
    assert s[2] == ANOMALY
    assert s[3:8] == [ANOMALY] * 5           # 55 is not > 60: resets the clear counter
    assert s[8:12] == [ANOMALY] * 4 and s[12] == OK


def test_hovering_around_threshold_does_not_flicker():
    s = smoothed([45, 55] * 20 + [45, 45, 45] + [58, 45] * 10)
    assert collapse(s) == [OK, ANOMALY]       # never flips back while it hovers


def test_clearing_anomaly_has_honest_headline():
    reg = Scorer.__init__.__globals__["Registry"].from_dict({"csv_columns": ["ms", "a", "dev_state"], "sensors": [
        {"key": "a", "enabled": True, "include_in_ml": True, "tier": "core"}]})
    rig = Rig(reg, FakeScorer([30, 30, 30, 90, 90, 90, 90, 90]))
    out = rig.feed(rows_from([{"a": 1.0}] * 9))[1:]
    assert out[2]["headline"] == "Unusual pattern (health 30)"
    assert [a["ml"]["clear_remaining_s"] for a in out[3:]] == [4, 3, 2, 1, None]
    assert out[3]["headline"] == "Back to normal; ML anomaly clearing in 4 s"
    assert out[3]["headline_detail"] == "Health 90"
    assert out[-1]["ml"]["status"] == OK and out[-1]["overall"] == "NORMAL"


def test_smoothing_thresholds_come_from_settings():
    assert smoothed([40, 40], ml_anomaly_rows=2) == [OK, ANOMALY]


# ---- warm start --------------------------------------------------------------------------

def test_warm_start_removes_warming_up(reg, scorer):
    rig = Rig(reg, scorer)
    n = rig.analyzer.warm_start(sim_rows(reg, "normal", 70, 12), "warm.csv")
    assert n == 70
    # Live data from a different session: its level doesn't match the recording exactly.
    live = sim_rows(reg, "normal", 20, 13)              # live device starts again at ms 0
    out = rig.feed(live)
    # No warming up at all. The windows of rows 0-9 span the joint and do score as anomalous
    # (the guard is doing real work), yet the status stays OK through them and the next 3 rows
    # (the earliest an escalation on fully-live windows could happen).
    assert any(a["ml"]["instant"] == ANOMALY for a in out[:10])
    assert [a["ml"]["status"] for a in out[:13]] == [OK] * 13
    # While settling, a health number would be meaningless: none is shown.
    assert [a["ml"]["settling_remaining_s"] for a in out[:11]] == [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, None]
    assert all(a["ml"]["health"] is None for a in out[:10])
    assert all(a["ml"]["health"] is not None for a in out[10:])
    assert out[0]["headline_detail"] == "ML settling after warm start: 10 s left"
    assert out[10]["ml"]["message"] is None                     # window is all live data now
    assert out[0]["forecast"]["temp_c"]["status"] != "insufficient_data"
    assert out[0]["warm_start"] == "warm-started from warm.csv"


def test_splice_guard_does_not_hide_a_real_fault(reg, scorer):
    rig = Rig(reg, scorer)
    rig.analyzer.warm_start(sim_rows(reg, "normal", 70, 12), "warm.csv")
    out = rig.feed(vib_rows(reg, 25, 999))
    statuses = [a["ml"]["status"] for a in out]
    assert statuses[:10] == [OK] * 10                     # guard period
    assert statuses[12] == ANOMALY                        # 3 low rows after the guard


def test_reset_drops_pending_warm_start(reg, scorer):
    rig = Rig(reg, scorer)
    rig.analyzer.warm_start(sim_rows(reg, "normal", 70, 12), "warm.csv")
    rig.analyzer.reset()
    assert rig.feed(sim_rows(reg, "normal", 1, 13))[0]["ml"]["status"] == WARMING_UP


def test_compact_summary(reg, scorer):
    a = Rig(reg, scorer).feed(sim_rows(reg, "normal", 12, 1))[-1]
    c = compact(a)
    assert c["ml_status"] == OK and c["health"] == a["ml"]["health"]
    assert set(c["forecast"]["temp_c"]) == {"seconds_to_warn", "seconds_to_critical"}
    assert compact(None) is None


def test_timing_stats(reg, scorer):
    rig = Rig(reg, scorer)
    rig.feed(sim_rows(reg, "normal", 30, 1))
    t = rig.analyzer.timing()
    assert t["rows"] == 30 and 0 < t["avg_ms"] < 50 and t["p95_ms"] < 50


# ---- API: warm start, model reload, training job, NEEDS_RETRAIN ---------------------------

def write_recording(path, registry, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(csv_header(registry))
        for r in rows:
            w.writerow(r.to_csv_row(registry))


@pytest.fixture
def api(monkeypatch, tmp_path):
    def make(registry_mutate=None):
        models = tmp_path / "models"
        models.mkdir(exist_ok=True)
        for name in ("model.joblib", "model_meta.json"):
            shutil.copy(MODELS_DIR / name, models / name)
        monkeypatch.delenv("MHM_PORT", raising=False)
        monkeypatch.setattr(serial_source.list_ports, "comports", lambda: [])
        monkeypatch.setattr(main, "load_settings",
                            lambda: Settings(recordings_dir=tmp_path, models_dir=models, link_grace_s=0.3))
        if registry_mutate:
            real_load = main.Registry.load
            def load(*a, **k):
                r = real_load(*a, **k)
                return main.Registry.from_dict(registry_mutate(r))
            monkeypatch.setattr(main.Registry, "load", staticmethod(load))
        return TestClient(main.app)
    return make


def wait_for(fn, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def first_rows(client, n=3):
    with client.websocket_connect("/ws/stream") as ws:
        return [m for m in (ws.receive_json() for _ in range(n + 5)) if m["type"] == "row"][:n]


def test_api_warm_start_with_source_switch(api, tmp_path, reg):
    write_recording(tmp_path / "warm.csv", reg, sim_rows(reg, "normal", 120, 21, source="real"))
    with api() as client:
        with client.websocket_connect("/ws/stream") as ws:
            r = client.post("/api/source", json={"type": "simulator", "speed": 20, "warmstart": "warm.csv"})
            assert r.status_code == 200
            rows = [m for m in (ws.receive_json() for _ in range(60))
                    if m["type"] == "row" and m["mode"] == "simulated" and m["row"]["ms"] < 5000]
        # The new source's very first row is already past warming up and has a forecast.
        assert rows[0]["row"]["ms"] == 0
        assert rows[0]["analysis"]["ml"]["status"] == OK
        assert rows[0]["analysis"]["forecast"]["temp_c"]["status"] != "insufficient_data"
        assert rows[0]["analysis"]["warm_start"] == "warm-started from warm.csv"
        status = client.get("/api/status").json()
        assert status["warm_start"]["applied"] is True and status["warm_start"]["rows"] == 70   # last 10 + 60 s
        assert client.post("/api/source", json={"type": "simulator", "warmstart": "nope.csv"}).status_code == 404


def test_api_warm_start_endpoint(api, tmp_path, reg):
    write_recording(tmp_path / "warm.csv", reg, sim_rows(reg, "normal", 120, 21, source="real"))
    with api() as client:
        r = client.post("/api/warmstart", json={"file": "warm.csv"})
        assert r.status_code == 200 and r.json()["rows"] == 70
        wait_for(lambda: client.get("/api/status").json()["warm_start"]["applied"])
        assert client.post("/api/warmstart", json={"file": "nope.csv"}).status_code == 404


def test_warmstart_file_setting_on_startup(monkeypatch, tmp_path, reg):
    write_recording(tmp_path / "warm.csv", reg, sim_rows(reg, "normal", 120, 21, source="real"))
    monkeypatch.delenv("MHM_PORT", raising=False)
    monkeypatch.setattr(serial_source.list_ports, "comports", lambda: [])
    monkeypatch.setattr(main, "load_settings", lambda: Settings(
        recordings_dir=tmp_path, models_dir=MODELS_DIR, warmstart_file="warm.csv"))
    with TestClient(main.app) as client:
        rows = first_rows(client)
        assert all(m["analysis"]["ml"]["status"] == OK for m in rows)
        assert client.get("/api/status").json()["warm_start"]["file"] == "warm.csv"


def test_api_model_info_and_reload(api, tmp_path):
    with api() as client:
        info = client.get("/api/model").json()
        assert info["status"] == "READY" and info["provisional"] is True
        assert info["trained_on"]["synthetic"] > 0 and info["trained_on"]["real"] == 0
        assert info["sensors"] == ["temp_c", "humidity", "sound_peak", "vib_count"]
        assert {"median_score", "threshold_score", "abnormal_score"} <= set(info["calibration"])
        (tmp_path / "models" / "model.joblib").unlink()
        assert client.post("/api/model/reload").json()["status"] == NO_MODEL
        client.post("/api/source", json={"type": "simulator", "speed": 20})
        a = wait_for(lambda: (s := client.get("/api/status").json())["analysis"] and s["analysis"])
        assert a["ml"]["status"] == NO_MODEL
        shutil.copy(MODELS_DIR / "model.joblib", tmp_path / "models" / "model.joblib")
        assert client.post("/api/model/reload").json()["status"] == "READY"


def test_api_train_job(api, tmp_path, reg):
    for i in (1, 2):
        write_recording(tmp_path / f"n{i}.csv", reg, sim_rows(reg, "normal", 150, 30 + i, source="real"))
    with api() as client:
        before = client.get("/api/model").json()["created"]
        r = client.post("/api/model/train", json={"files": ["n1.csv", "n2.csv"]})
        assert r.status_code == 202
        job_id = r.json()["id"]
        job = wait_for(lambda: (j := client.get(f"/api/model/train/{job_id}").json())["status"] in ("done", "failed") and j,
                       timeout=60)
        assert job["status"] == "done", job["message"]
        assert job["result"]["rows_normal_by_source"] == {"real": 300, "synthetic": 0}
        info = client.get("/api/model").json()
        assert info["provisional"] is False and info["trained_on"]["real"] == 300 and info["created"] != before
        assert client.post("/api/model/train", json={"files": []}).status_code == 400
        assert client.post("/api/model/train", json={"files": ["missing.csv"]}).status_code == 404
        assert client.get("/api/model/train/nope").status_code == 404


def test_api_needs_retrain_when_sensor_added(api):
    def enable_leak(r):            # leak is enabled but not an ML feature; adding it to ML needs a retrain
        d = r.to_dict()
        sensors = [{**s, "include_in_ml": s["include_in_ml"] or s["key"] == "leak_raw"} for s in d["sensors"]]
        return {"schema_version": 2, "csv_columns": d["csv_columns"], "sensors": sensors}

    with api(enable_leak) as client:
        assert client.get("/api/model").json()["status"] == NEEDS_RETRAIN
        client.post("/api/source", json={"type": "simulator", "scenario": "sudden_fault", "speed": 20})
        a = wait_for(lambda: (s := client.get("/api/status").json())["analysis"] and s["analysis"])
        assert a["ml"]["status"] == NEEDS_RETRAIN and a["device"]["state"] in ("NORMAL", "WARNING", "CRITICAL")
        rows = wait_for(lambda: (h := client.get("/api/history").json())["count"] > 5 and h["rows"])
        assert rows[-1]["leak_raw"] is not None           # the new sensor is simulated, rules still run
