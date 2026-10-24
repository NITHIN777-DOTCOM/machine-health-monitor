"""Phase 6: paths (frozen vs repo), the dashboard served by FastAPI, demo recordings,
version info and the launcher's port handling. No hardware, no real exe."""
import shutil
import socket

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import launcher, paths
from app.config import MODELS_DIR, Settings
from app.recorder import Recorder, list_recordings
from app.sources import serial_source
from app.sources.replay import resolve_recording
from app.version import APP_ID, VERSION


@pytest.fixture
def portable(monkeypatch, tmp_path):
    """paths.* pointed at a fake bundle and a fake exe folder (with a space in its name)."""
    bundle = tmp_path / "_internal"
    shutil.copytree(paths.DEFAULT_CONFIG_DIR, bundle / "backend" / "config")
    (bundle / "models").mkdir()
    for name in paths.MODEL_FILES:
        shutil.copy(MODELS_DIR / name, bundle / "models" / name)
    app_dir = tmp_path / "Portable Test Folder"
    for name, value in {
        "DEFAULT_CONFIG_DIR": bundle / "backend" / "config", "DEFAULT_MODELS_DIR": bundle / "models",
        "CONFIG_DIR": app_dir / "config", "MODELS_DIR": app_dir / "models",
        "RECORDINGS_DIR": app_dir / "data" / "recordings", "LOGS_DIR": app_dir / "logs",
    }.items():
        monkeypatch.setattr(paths, name, value)
    return app_dir


def test_first_run_copies_defaults_next_to_the_exe(portable):
    copied = paths.ensure_app_dirs()
    names = sorted(p.name for p in copied)
    assert names == sorted(paths.CONFIG_FILES + paths.MODEL_FILES)
    for d in ("config", "models", "data/recordings", "logs"):
        assert (portable / d).is_dir()


def test_user_edits_and_retrained_models_are_never_overwritten(portable):
    paths.ensure_app_dirs()
    (portable / "config" / "settings.json").write_text('{"hold_seconds": 7}', encoding="utf-8")
    (portable / "models" / "model_meta.json").unlink()       # e.g. a half-copied retrain
    assert paths.ensure_app_dirs() == []                     # model.joblib exists: the pair is left alone
    assert (portable / "config" / "settings.json").read_text(encoding="utf-8") == '{"hold_seconds": 7}'


def test_development_paths_are_the_repo():
    assert not paths.FROZEN
    assert paths.CONFIG_DIR == paths.REPO_DIR / "backend" / "config"
    assert paths.DASHBOARD_DIR == paths.REPO_DIR / "dashboard" / "dist"
    assert paths.RECORDINGS_DIR == paths.REPO_DIR / "data" / "recordings"


# ---- dashboard served by FastAPI ----------------------------------------------------------

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("MHM_PORT", raising=False)
    monkeypatch.setattr(main.paths, "ensure_app_dirs", lambda: [])
    rec, demo = tmp_path / "recordings", tmp_path / "demo"
    rec.mkdir()
    demo.mkdir()
    monkeypatch.setattr(main, "load_settings",
                        lambda: Settings(recordings_dir=rec, demo_dir=demo, models_dir=MODELS_DIR, link_grace_s=0.3))
    monkeypatch.setattr(serial_source.list_ports, "comports", lambda: [])
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    monkeypatch.setattr(main.paths, "DASHBOARD_DIR", dist)
    with TestClient(main.app) as c:
        c.dirs = (rec, demo, dist)
        yield c


def test_dashboard_at_root_with_spa_fallback(client):
    r = client.get("/")
    assert r.status_code == 200 and "dashboard" in r.text and r.headers["cache-control"] == "no-cache"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert "dashboard" in client.get("/some/page").text           # unknown page -> index.html
    assert client.get("/assets/old-name.js").status_code == 404     # missing file -> 404, not the page
    assert client.get("/..%2Fsecret.txt").status_code == 404


def test_api_and_ws_paths_are_not_swallowed(client):
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/no-such-endpoint").status_code == 404
    assert client.get("/ws/nothing").status_code == 404
    with client.websocket_connect("/ws/stream") as ws:
        assert ws.receive_json()["type"] == "status"


def test_dashboard_not_built_says_how_to_build_it(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main.paths, "DASHBOARD_DIR", tmp_path / "nothing")
    r = client.get("/")
    assert r.status_code == 503 and "npm run build" in r.text


def test_version_in_status(client):
    v = client.get("/api/status").json()["version"]
    assert v["app"] == APP_ID and v["version"] == VERSION and v["frozen"] is False


# ---- demo recordings (data/demo) ---------------------------------------------------------------

def test_demo_recordings_are_listed_and_replayable(client, run_sim, registry):
    rec, demo, _ = client.dirs
    rows, _ = run_sim("normal", 30)
    r = Recorder(registry, demo)
    path = r.start()
    for row in rows:
        r.write(row)
    r.stop()
    demo_name = "demo_SIMULATED_test.csv"
    path.rename(demo / demo_name)
    listed = client.get("/api/recordings").json()["recordings"]
    assert [(x["file"], x["folder"]) for x in listed] == [(demo_name, "demo")]
    s = client.post("/api/source", json={"type": "replay", "file": demo_name, "speed": 20}).json()
    assert s["source"] == "replay" and s["file"] == demo_name
    assert client.post("/api/warmstart", json={"file": demo_name}).status_code == 200


def test_recordings_folder_wins_over_demo_for_the_same_name(tmp_path):
    a, b = tmp_path / "recordings", tmp_path / "demo"
    a.mkdir()
    b.mkdir()
    for d in (a, b):
        (d / "x.csv").write_text("# ms\nms\n1\n", encoding="utf-8")
    (b / "y.csv").write_text("# ms\nms\n1\n", encoding="utf-8")
    (tmp_path / "outside.csv").write_text("# ms\nms\n1\n", encoding="utf-8")
    assert resolve_recording([a, b], "x.csv").parent == a
    assert resolve_recording([a, b], "y.csv").parent == b
    assert [(r["file"], r["folder"]) for r in list_recordings([a, b])] == [("x.csv", "recordings"), ("y.csv", "demo")]
    with pytest.raises(FileNotFoundError):
        resolve_recording([a, b], "../outside.csv")          # outside every recordings folder


# ---- launcher ----------------------------------------------------------------------------------

def test_candidate_ports():
    assert launcher.candidate_ports(8000) == list(range(8000, 8011))
    assert launcher.candidate_ports(8005)[-1] == 8015
    assert launcher.candidate_ports(9000) == list(range(9000, 9011))


def test_busy_port_is_skipped():
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        busy_port = blocker.getsockname()[1]
        sock, port, busy = launcher.bind_free_port([busy_port, busy_port + 1, busy_port + 2])
        try:
            assert busy == [busy_port] and port != busy_port
        finally:
            sock.close()


def test_no_instance_on_a_foreign_or_empty_port():
    with socket.socket() as other:
        other.bind(("127.0.0.1", 0))
        other.listen(1)
        port = other.getsockname()[1]
        assert launcher.probe(port, timeout=0.3) is None        # listening, but not this app


def test_source_text():
    assert launcher.source_text({"source": "serial", "serial_port": "COM5"}) == "Arduino on COM5"
    assert launcher.source_text({"source": "simulator",
                                 "startup_reason": "no Arduino found; using simulator (normal)"}) == \
        "Simulator (no Arduino found)"
    assert "serial disabled" in launcher.source_text(
        {"source": "simulator", "startup_reason": "MHM_SOURCE=simulator; serial disabled, using simulator (normal)"})


def test_args():
    a = launcher.parse_args(["--simulator", "--port", "8050", "--no-browser"])
    assert a.simulator and a.port == 8050 and a.no_browser
    assert launcher.parse_args([]).port == 8000
