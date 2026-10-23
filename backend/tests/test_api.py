"""REST + WebSocket API with FastAPI's TestClient. The serial port is never touched."""
import shutil
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import MODELS_DIR, Settings
from app.models import stored_columns
from app.sources import serial_source


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("MHM_PORT", raising=False)
    models = tmp_path / "models"                     # a copy: tests may retrain or delete it
    models.mkdir()
    for name in ("model.joblib", "model_meta.json"):
        shutil.copy(MODELS_DIR / name, models / name)
    monkeypatch.setattr(main, "load_settings",
                        lambda: Settings(recordings_dir=tmp_path, models_dir=models, link_grace_s=0.3))
    # No real hardware: startup and any switch to serial see no ports at all.
    monkeypatch.setattr(serial_source.list_ports, "comports", lambda: [])
    with TestClient(main.app) as c:
        yield c


def wait_for(fn, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def fast_sim(client, scenario="normal"):
    r = client.post("/api/source", json={"type": "simulator", "scenario": scenario, "speed": 20})
    assert r.status_code == 200
    return r.json()


def test_status_on_startup(client):
    s = client.get("/api/status").json()
    assert s["source"] == "simulator" and s["scenario"] == "normal" and s["connected"] is True
    assert s["startup_reason"] == "no Arduino found; using simulator (normal)"
    assert s["recording"]["on"] is False
    for key in ("speed", "serial_port", "last_error", "rows_received", "rows_rejected", "device", "scenarios"):
        assert key in s
    assert "recovery" in s["scenarios"]


def test_sensors_is_the_registry(client, registry):
    d = client.get("/api/sensors").json()
    assert d["csv_columns"] == registry.csv_columns
    assert [s["key"] for s in d["sensors"]] == registry.sensor_keys
    assert {"hysteresis", "in_ml", "enabled", "limits_note"} <= set(d["sensors"][0])


def test_history(client):
    fast_sim(client)
    rows = wait_for(lambda: (h := client.get("/api/history?seconds=600").json())["count"] >= 12 and h["rows"])
    assert list(rows[0]) == stored_columns(main.app.state.mhm.registry) + ["analysis"]
    compact = rows[-1]["analysis"]
    assert set(compact) == {"overall", "alert_source", "ml_status", "health", "forecast"}
    assert compact["ml_status"] == "OK" and compact["health"] is not None      # trend-chart data
    assert set(compact["forecast"]) == {"temp_c", "humidity"}
    full = client.get("/api/history?seconds=600&detail=full").json()["rows"][-1]["analysis"]
    assert {"headline", "device", "ml", "forecast"} <= set(full)
    plain = client.get("/api/history?seconds=600&detail=none").json()["rows"][-1]
    assert "analysis" not in plain
    assert client.get("/api/history?seconds=0").status_code == 422


def test_record_label_and_replay_round_trip(client, tmp_path):
    assert client.get("/api/recordings").json() == {"recordings": []}
    fast_sim(client)
    start = client.post("/api/record/start").json()
    assert start["on"] is True and (tmp_path / start["file"]).exists()
    assert client.post("/api/label", json={"label": "fault"}).json() == {"label": "fault"}
    assert client.get("/api/status").json()["recording"]["label"] == "fault"
    wait_for(lambda: client.get("/api/status").json()["recording"]["rows"] >= 10)
    stop = client.post("/api/record/stop").json()
    assert stop["on"] is False and stop["rows"] >= 10
    header = (tmp_path / start["file"]).read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == stored_columns(main.app.state.mhm.registry)   # raw rows only, no analysis
    assert client.post("/api/label", json={"label": None}).json() == {"label": None}

    recs = client.get("/api/recordings").json()["recordings"]
    assert recs[0]["file"] == start["file"] and recs[0]["rows"] == stop["rows"]

    # simulator -> replay -> simulator
    r = client.post("/api/source", json={"type": "replay", "file": start["file"], "speed": 20})
    assert r.status_code == 200 and r.json()["source"] == "replay"
    # 20x = 50 ms per row, but each row also runs ML (slower under coverage): allow for both.
    wait_for(lambda: client.get("/api/status").json()["source_detail"]["finished"],
             timeout=3 + 0.15 * stop["rows"])
    detail = client.get("/api/status").json()["source_detail"]
    assert detail["rows_played"] == stop["rows"]
    s = fast_sim(client, "recovery")
    assert (s["source"], s["scenario"]) == ("simulator", "recovery")


def test_switch_to_serial_without_arduino(client):
    client.post("/api/source", json={"type": "serial"})
    s = client.get("/api/status").json()
    assert s["connected"] is True and s["link"] == "starting"        # grace period, no flash
    s = wait_for(lambda: (s := client.get("/api/status").json())["link"] == "down" and s)
    assert s["source"] == "serial" and s["connected"] is False
    assert "No Arduino found" in s["last_error"]


def test_source_switch_never_reports_disconnected(client):
    with client.websocket_connect("/ws/stream") as ws:
        ws.receive_json()
        for scenario in ("sudden_fault", "recovery", "normal"):
            fast_sim(client, scenario)
        statuses = [m["status"] for m in (ws.receive_json() for _ in range(60)) if m["type"] == "status"]
    assert len(statuses) >= 3
    assert all(s["connected"] for s in statuses), [(s["scenario"], s["link"]) for s in statuses]


def test_finished_replay_reports_link_finished(client):
    fast_sim(client)
    f = client.post("/api/record/start").json()["file"]
    wait_for(lambda: client.get("/api/status").json()["recording"]["rows"] >= 3)
    client.post("/api/record/stop")
    client.post("/api/source", json={"type": "replay", "file": f, "speed": 20})
    s = wait_for(lambda: (s := client.get("/api/status").json())["link"] == "finished" and s)
    assert s["connected"] is False and s["data_age_s"] is not None


@pytest.mark.parametrize("body, code, message", [
    ({"type": "foo"}, 422, "simulator"),
    ({"type": "simulator", "scenario": "nope"}, 400, "unknown scenario"),
    ({"type": "simulator", "speed": 0}, 400, "speed"),
    ({"type": "simulator", "speed": 100}, 400, "speed"),
    ({"type": "replay"}, 400, "needs 'file'"),
    ({"type": "replay", "file": "missing.csv"}, 404, "No recording named"),
    ({"type": "replay", "file": "../secrets.csv"}, 404, "No recording named"),
])
def test_bad_source_requests(client, body, code, message):
    r = client.post("/api/source", json=body)
    assert r.status_code == code
    assert message in str(r.json()["detail"])
    assert client.get("/api/status").json()["source"] == "simulator"   # unchanged


def test_bad_label(client):
    r = client.post("/api/label", json={"label": "broken"})
    assert r.status_code == 422 and "label" in str(r.json()["detail"])


def test_websocket_streams_rows_with_device_block(client):
    fast_sim(client, "sudden_fault")
    with client.websocket_connect("/ws/stream") as ws:
        first = ws.receive_json()
        assert first["type"] == "status" and first["status"]["source"] == "simulator"
        msg = next(m for m in (ws.receive_json() for _ in range(50)) if m["type"] == "row")
    assert msg["mode"] == "simulated"
    assert list(msg["row"]) == stored_columns(main.app.state.mhm.registry)
    dev = msg["analysis"]["device"]
    assert set(dev) == {"state", "reported", "reason", "hold_remaining_s", "agrees"}
    assert dev["agrees"] is True and dev["state"] == msg["row"]["dev_state"]
    assert {"overall", "alert_source", "headline", "ml", "forecast"} <= set(msg["analysis"])


def test_websocket_gets_status_on_source_change(client):
    with client.websocket_connect("/ws/stream") as ws:
        ws.receive_json()
        fast_sim(client, "slow_drift")
        msg = next(m for m in (ws.receive_json() for _ in range(100))
                   if m["type"] == "status" and m["status"]["scenario"] == "slow_drift")
    assert msg["status"]["speed"] == 20


def test_mhm_source_simulator_never_touches_serial(monkeypatch, tmp_path):
    """MHM_SOURCE=simulator: startup uses the simulator without listing ports, and a switch
    to serial is refused (for running the software while another program holds the COM port)."""
    monkeypatch.setenv("MHM_SOURCE", "simulator")
    monkeypatch.setenv("MHM_PORT", "COM5")             # would normally pick serial
    def no_ports():
        raise AssertionError("serial ports must not be listed")
    monkeypatch.setattr(serial_source.list_ports, "comports", no_ports)
    real_load = main.load_settings
    monkeypatch.setattr(main, "load_settings", lambda: _with_dirs(real_load(), tmp_path))
    with TestClient(main.app) as c:
        status = c.get("/api/status").json()
        assert status["source"] == "simulator"
        assert "MHM_SOURCE" in status["startup_reason"]
        r = c.post("/api/source", json={"type": "serial"})
        assert r.status_code == 400 and "MHM_SOURCE" in r.json()["detail"]
        assert c.get("/api/status").json()["source"] == "simulator"


def _with_dirs(settings: Settings, tmp_path) -> Settings:
    settings.recordings_dir = tmp_path
    settings.models_dir = MODELS_DIR
    return settings


def test_ml_thresholds_in_status_and_model(client):
    expected = {"anomaly_health": 50, "anomaly_rows": 3, "clear_health": 60, "clear_rows": 5}
    assert client.get("/api/status").json()["ml_thresholds"] == expected
    assert client.get("/api/model").json()["ml_thresholds"] == expected


def test_serial_availability_is_reported(client):
    serial = client.get("/api/status").json()["serial"]
    assert serial["available"] is False and "No Arduino found" in serial["note"]


def test_serial_unavailable_when_forced_to_simulator(client):
    main.app.state.mhm.settings.force_source = "simulator"
    serial = client.get("/api/status").json()["serial"]
    assert serial == {"available": False, "port": None,
                      "note": "Serial disabled (MHM_SOURCE=simulator). Unset it and restart to use the Arduino."}
